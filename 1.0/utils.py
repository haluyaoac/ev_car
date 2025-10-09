import math
import random
from typing import List, Tuple
from config import RANDOM_SEED
import time
from typing import List, Tuple
from threading import Lock

random.seed(RANDOM_SEED)

Coord = Tuple[float, float]  # (lat, lng)

EARTH_R_KM = 6371.0088

EARTH_RADIUS = 6371000  # 地球半径（米）


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


def offset_point(lat, lng, dx, dy):
    """
    根据经纬度和东西/南北方向的偏移量（米）计算新坐标
    dx: 东西方向偏移（米），向东为正
    dy: 南北方向偏移（米），向北为正
    """
    new_lat = lat + (dy / EARTH_RADIUS) * (180 / math.pi)
    new_lng = lng + (dx / (EARTH_RADIUS * math.cos(math.radians(lat)))) * (180 / math.pi)
    return new_lat, new_lng

def corridor_polygon(lat1, lng1, lat2, lng2, half_width_m):
    """
    根据两点和走廊半宽生成矩形多边形（首尾闭合）
    返回 [(lat, lng), ...]
    """
    # 计算连线的方位角（弧度）
    dx = (lng2 - lng1) * math.pi / 180 * EARTH_RADIUS * math.cos(math.radians((lat1 + lat2) / 2))
    dy = (lat2 - lat1) * math.pi / 180 * EARTH_RADIUS
    angle = math.atan2(dx, dy)  # 注意这里dx, dy顺序

    # 垂直方向的偏移角
    perp_angle = angle + math.pi / 2

    # 起点左右偏移
    lat1_left, lng1_left = offset_point(lat1, lng1,
                                        half_width_m * math.cos(perp_angle),
                                        half_width_m * math.sin(perp_angle))
    lat1_right, lng1_right = offset_point(lat1, lng1,
                                          -half_width_m * math.cos(perp_angle),
                                          -half_width_m * math.sin(perp_angle))
    # 终点左右偏移
    lat2_left, lng2_left = offset_point(lat2, lng2,
                                        half_width_m * math.cos(perp_angle),
                                        half_width_m * math.sin(perp_angle))
    lat2_right, lng2_right = offset_point(lat2, lng2,
                                          -half_width_m * math.cos(perp_angle),
                                          -half_width_m * math.sin(perp_angle))

    # 顺时针闭合
    polygon = [
        (lat1_left, lng1_left),
        (lat2_left, lng2_left),
        (lat2_right, lng2_right),
        (lat1_right, lng1_right),
        (lat1_left, lng1_left)  # 闭合
    ]
    return polygon

def polygon_to_bounds_str(polygon):
    """
    将多边形点列表转成百度API bounds参数字符串
    """
    return ",".join([f"{lat:.6f},{lng:.6f}" for lat, lng in polygon])



