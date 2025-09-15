# -*- coding: utf-8 -*-
"""
baidu_api.py
- get_route_polyline(start, end, ak): 获取驾车路线 polyline ([(lat,lng), ...])
- poi_charging_near_paginated(...): 在单点附近分页获取充电站（返回字典列表）
- search_stations_along_route(route_poly, ak, ...): 按段分配配额、分页请求、扩半径、去重与下采样

"""
from typing import List, Optional, Tuple
import requests
from utils import Coord
from qps_manner import fetch_json, ensure_dispatcher_started


DRIVE_URL = "https://api.map.baidu.com/directionlite/v1/driving"
PLACE_URL = "https://api.map.baidu.com/place/v2/search"
DISTANCE_URL = "https://api.map.baidu.com/routematrix/v2/driving"
GEOCODE_URL = "https://api.map.baidu.com/geocoding/v3/"


# ---------- helpers ----------
def _fmt_coord_bd09(lat: float, lng: float) -> str:
    # 百度 Web 服务中某些接口要求经度,纬度；不过 place API expects "lat,lng" for location.
    return f"{lat},{lng}"

def get_route_distance(start: Coord, end: Coord, ak: str) -> Optional[float]:
    """
    获取一个点到一个点的驾车路线距离（公里）。失败返回 None。
    start/end: (lat, lng)
    """
    params = {
        "origins": _fmt_coord_bd09(*start),
        "destinations": _fmt_coord_bd09(*end),
        "ak": ak,
    }
    try:
        data = fetch_json(DISTANCE_URL, params=params, timeout_s=10)
    except Exception as e:
        print("[Baidu] 距离请求异常:", e)
        return None
    if data.get("status") != 0:
        print("[Baidu] 距离请求失败:", data.get("message", data))
        return None
    results = data.get("result", [])
    if not results or "distance" not in results[0]:
        print("[Baidu] 未返回距离")
        return None
    return results[0]["distance"]["value"] / 1000.0  # 米转公里


def geocode(address, ak) -> Optional[Coord]:
    ensure_dispatcher_started()
    params = {
        "address": address,
        "output": "json",
        "ak": ak
    }
    data = fetch_json(GEOCODE_URL, params, retries=3, timeout_s=12)
    if not isinstance(data, dict) or data.get("_error"):
        print(f"[Geocode] 请求异常: {data.get('_error') if isinstance(data, dict) else data}")
        return None
    if data.get("status") == 0:
        loc = data["result"]["location"]
        return (loc["lat"], loc["lng"])
    print(f"[Geocode] 失败: {data.get('msg', data)}")
    return None

def get_route_polyline(start: Coord, end: Coord, ak: str) -> Tuple[Optional[List[Coord]], List[int], List[int], List[str]]:
    ensure_dispatcher_started()
    params = {
        "origin": _fmt_coord_bd09(*start),
        "destination": _fmt_coord_bd09(*end),
        "ak": ak,
    }
    data = fetch_json(DRIVE_URL, params, retries=3, timeout_s=18)
    if not data or data.get("_error"):
        print("[Baidu] 路线请求异常:", data.get("_error") if isinstance(data, dict) else data)
        return None
    if data.get("status") != 0:
        print("[Baidu] 路线请求失败:", data.get("message", data))
        return None
    # ...existing code... (解析 steps 保留原逻辑)
    # 复制你现有的解析段落
    routes = data.get("result", {}).get("routes", [])
    if not routes:
        print("[Baidu] 未返回 routes")
        return None
    steps = routes[0].get("steps", [])
    poly: List[Coord] = []
    poly_start: List[int] = []
    poly_end: List[int] = []
    poly_name: List[str] = []
    for seg in steps:
        poly_name.append(seg.get("road_name",""))
        path_str = seg.get("path")
        if not path_str: continue
        poly_start.append(len(poly))
        for pair in path_str.split(';'):
            try:
                lng, lat = map(float, pair.split(','))
                poly.append((lat, lng))
            except:
                continue
        poly_end.append(len(poly)-1)
    return poly, poly_start, poly_end, poly_name


def search_stations_by_circle(query, center, radius_m, ak) -> List[dict]:
    ensure_dispatcher_started()
    if not ak:
        return []
    url = PLACE_URL
    stations = []
    page = 0
    page_size = 20
    while True:
        params = {
            "query": query,
            "location": f"{center[0]},{center[1]}",
            "radius": int(radius_m),
            "output": "json",
            "ak": ak,
            "page_size": page_size,
            "page_num": page,
            "scope": 2,
        }
        data = fetch_json(url, params, retries=2, timeout_s=10)
        if not data or data.get("_error"):
            print("[Baidu_api] 请求异常:", data.get("_error") if isinstance(data, dict) else data)
            break
        results = data.get("results", [])
        if not results:
            break
        for item in results:
            stations.append({
                "name": item.get("name"),
                "lat": item.get("location", {}).get("lat"),
                "lng": item.get("location", {}).get("lng"),
                "address": item.get("address", "")
            })
        if len(results) < page_size:
            break
        page += 1
    return stations


# get_distance_matrix 改造：内部每次调用 fetch_json
def get_distance_matrix(origins: List[Coord], destinations: List[Coord], ak: str, qps_limiter=None, max_retries=3):
    ensure_dispatcher_started()
    if not origins or not destinations:
        return []
    max_points = 100
    if len(origins) * len(destinations) > max_points:
        print(f"[Baidu] 点数过多 {len(origins)}x{len(destinations)}")
        return None
    params = {
        "origins": "|".join([_fmt_coord_bd09(*pt) for pt in origins]),
        "destinations": "|".join([_fmt_coord_bd09(*pt) for pt in destinations]),
        "ak": ak,
    }
    data = fetch_json(DISTANCE_URL, params, retries=max_retries, timeout_s=15)
    if not data or data.get("_error"):
        print("[Baidu] 距离矩阵异常:", data.get("_error") if isinstance(data, dict) else data)
        return None
    if data.get("status") != 0:
        print("[Baidu] 距离矩阵失败:", data.get("message", data))
        return None
    results = data.get("result", [])
    if not results:
        return None
    matrix: List[List[Optional[float]]] = []
    for row in results:
        row_values = []
        if isinstance(row, list):
            for cell in row:
                val = None
                if cell and "distance" in cell and cell["distance"].get("value") is not None:
                    val = cell["distance"]["value"] / 1000.0
                row_values.append(val)
        elif isinstance(row, dict):
            if "distance" in row and row["distance"].get("value") is not None:
                row_values.append(row["distance"]["value"] / 1000.0)
            else:
                row_values.append(None)
        matrix.append(row_values)
    return matrix



