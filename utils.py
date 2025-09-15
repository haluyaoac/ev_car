import math
import random
from typing import List, Tuple
from config import RANDOM_SEED
import time
import requests
from typing import List, Optional, Tuple
from random import uniform
from threading import Lock

random.seed(RANDOM_SEED)

Coord = Tuple[float, float]  # (lat, lng)

EARTH_R_KM = 6371.0088

EARTH_RADIUS = 6371000  # 地球半径（米）


# =========================
# QPS控制器
# =========================

class QPSLimiter:
    def __init__(self, max_qps: int):
        self.interval = 1.0 / max_qps
        self.last_time = 0
        self.lock = Lock()

    def wait(self):
        with self.lock:
            now = time.time()
            elapsed = now - self.last_time
            if elapsed < self.interval:
                wait_time = self.interval - elapsed
                print(f"[QPS] 等待 {wait_time:.2f} 秒")
                time.sleep(wait_time)
            self.last_time = time.time()


def offset_coordinate(lat, lng, distance_m, bearing_deg):
    δ = distance_m / EARTH_RADIUS
    θ = math.radians(bearing_deg)
    φ1 = math.radians(lat)
    λ1 = math.radians(lng)
    φ2 = math.asin(math.sin(φ1) * math.cos(δ) +
                   math.cos(φ1) * math.sin(δ) * math.cos(θ))
    λ2 = λ1 + math.atan2(math.sin(θ) * math.sin(δ) * math.cos(φ1),
                         math.cos(δ) - math.sin(φ1) * math.sin(φ2))
    return math.degrees(φ2), math.degrees(λ2)


def build_buffer_polygon(polyline, buffer_km):
    """绘制多边形"""
    left_offsets = []
    right_offsets = []
    for i in range(len(polyline) - 1):
        lat1, lng1 = polyline[i]
        lat2, lng2 = polyline[i+1]
        dx = math.radians(lng2 - lng1)
        dy = math.radians(lat2 - lat1)
        y = math.sin(dx) * math.cos(math.radians(lat2))
        x = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - \
            math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(dx)
        bearing = (math.degrees(math.atan2(y, x)) + 360) % 360
        left_offsets.append(offset_coordinate(lat1, lng1, buffer_km*1000, bearing - 90))
        right_offsets.append(offset_coordinate(lat1, lng1, buffer_km*1000, bearing + 90))
    lat_last, lng_last = polyline[-1]
    left_offsets.append(offset_coordinate(lat_last, lng_last, buffer_km*1000, bearing - 90))
    right_offsets.append(offset_coordinate(lat_last, lng_last, buffer_km*1000, bearing + 90))
    polygon = left_offsets + right_offsets[::-1]
    return polygon

def geodesic_distance(lat1, lng1, lat2, lng2):
    """计算两点球面距离（米）"""
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = φ2 - φ1
    dλ = math.radians(lng2 - lng1)
    a = math.sin(dφ/2)**2 + math.cos(φ1)*math.cos(φ2)*math.sin(dλ/2)**2
    return EARTH_RADIUS * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def midpoint(lat1, lng1, lat2, lng2):
    """计算两点的大地中点"""
    φ1, λ1 = math.radians(lat1), math.radians(lng1)
    φ2, λ2 = math.radians(lat2), math.radians(lng2)
    bx = math.cos(φ2) * math.cos(λ2 - λ1)
    by = math.cos(φ2) * math.sin(λ2 - λ1)
    φ3 = math.atan2(math.sin(φ1) + math.sin(φ2),
                    math.sqrt((math.cos(φ1) + bx)**2 + by**2))
    λ3 = λ1 + math.atan2(by, math.cos(φ1) + bx)
    return math.degrees(φ3), math.degrees(λ3)


def haversine_km(a: Coord, b: Coord) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 2 * EARTH_R_KM * math.asin(math.sqrt(h))


def polyline_sample(points: List[Coord], step: int) -> List[Coord]:
    if step <= 1:
        return points[:]
    return [p for i, p in enumerate(points) if i % step == 0] + ([points[-1]] if points else [])


def point_segment_distance_km(p: Coord, a: Coord, b: Coord) -> float:
    # 投影到弧度平面近似为平面向量计算，短段近似足够
    (x, y) = (math.radians(p[1]), math.radians(p[0]))
    (x1, y1) = (math.radians(a[1]), math.radians(a[0]))
    (x2, y2) = (math.radians(b[1]), math.radians(b[0]))
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return haversine_km(p, a)
    t = ((x - x1) * dx + (y - y1) * dy) / (dx*dx + dy*dy)
    t = max(0.0, min(1.0, t))
    proj = (y1 + t * dy, x1 + t * dx)
    # 反转回 (lat,lng)
    proj_ll = (math.degrees(proj[0]), math.degrees(proj[1]))
    return haversine_km(p, proj_ll)


def distance_point_to_polyline_km(p: Coord, poly: List[Coord]) -> float:
    best = float('inf')
    for i in range(len(poly) - 1):
        best = min(best, point_segment_distance_km(p, poly[i], poly[i+1]))
    return best if best < float('inf') else 0.0


def rnd(a: float, b: float) -> float:
    return random.uniform(a, b)



