# -*- coding: utf-8 -*-
"""
baidu_api.py
- get_route_polyline(start, end, ak): 获取驾车路线 polyline ([(lat,lng), ...])
- poi_charging_near_paginated(...): 在单点附近分页获取充电站（返回字典列表）
- search_stations_along_route(route_poly, ak, ...): 按段分配配额、分页请求、扩半径、去重与下采样

"""
from time import sleep
from typing import List, Optional, Tuple
from utils import Coord
from qps_manner import fetch_json, ensure_dispatcher_started
from config import AK


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

from typing import Optional, List, Tuple, Dict, Any

Coord = Tuple[float, float]  # (lat, lng)

def get_route_polyline(
    start: Coord,
    end: Coord,
    ak: str
) -> Optional[Dict[str, Any]]:
    """
    调用百度驾车路线 API，返回包含路线 polyline 及附加信息的字典。
    """
    ensure_dispatcher_started()
    params = {
        "origin": _fmt_coord_bd09(*start),
        "destination": _fmt_coord_bd09(*end),
        "ak": ak,
    }
    data = fetch_json(DRIVE_URL, params, retries=3, timeout_s=18)

    # 顶层状态检查
    if data.get("status") != 0:
        print(f"[Baidu] 路线请求失败: {data.get('message', data)}")
        return None

    result = data.get("result", {})
    routes = result.get("routes", [])
    if not routes:
        print("[Baidu] 未返回 routes")
        return None

    # 取第一条方案
    route = routes[0]


    # polyline 解析
    steps = route.get("steps", [])
    poly: List[Coord] = []
    poly_start: List[int] = []
    poly_end: List[int] = []
    poly_name: List[str] = []

    for seg in steps:
        road_name = seg.get("road_name", "")
        poly_name.append(road_name)
        path_str = seg.get("path")
        if not path_str:
            continue
        poly_start.append(len(poly))
        for pair in path_str.split(';'):
            try:
                lng, lat = map(float, pair.split(','))
                poly.append((lat, lng))
            except ValueError:
                continue
        poly_end.append(len(poly) - 1)

    return {
        "polyline": poly,
        "poly_start": poly_start,
        "poly_end": poly_end,
        "poly_name": poly_name,
        "raw": data  # 保留原始数据，方便调试或扩展
    }



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


def get_distance_matrix(origins: List[Coord], destinations: List[Coord], ak: str, qps_limiter=None, max_retries=3):
    ensure_dispatcher_started()
    if not origins or not destinations:
        return []
    max_points = 100
    n_ori = len(origins)
    n_dst = len(destinations)
    if n_ori * n_dst > max_points:
        print(f"[Baidu] 点数过多 {n_ori}x{n_dst}")
        return None
    params = {
        "origins": "|".join([_fmt_coord_bd09(*pt) for pt in origins]),
        "destinations": "|".join([_fmt_coord_bd09(*pt) for pt in destinations]),
        "ak": ak,
    }

    data = fetch_json(DISTANCE_URL, params, retries=max_retries, timeout_s=15) 
    redo = 0
    while data.get("status") != 0:
        redo += 1
        print("[Baidu] 距离矩阵失败:", data.get("message", data))
        print("重试中第", redo)
        sleep(1000);
        data = fetch_json(DISTANCE_URL, params, retries=max_retries, timeout_s=15)

    results = data.get("result", [])
    if not results or len(results) != n_ori * n_dst:
        print("[Baidu] 距离矩阵结果数量异常")
        return None

    # 组装为二维矩阵
    matrix: List[List[Optional[float]]] = []
    for i in range(n_ori):
        row = []
        for j in range(n_dst):
            idx = i * n_dst + j
            cell = results[idx]
            val = None
            if cell and "distance" in cell and cell["distance"].get("value") is not None:
                val = cell["distance"]["value"] / 1000.0  # 米转公里
            row.append(val)
        matrix.append(row)
    return matrix


def search_charging_stations_near(coord: Coord, radius: int = 2000) -> List[Dict]:
    """
    调用百度POI搜索API，返回附近充电桩列表
    """
    params = {
        "query": "充电桩",
        "location": f"{coord[0]},{coord[1]}",
        "radius": radius,
        "output": "json",
        "ak": AK,
    }
    data = fetch_json(PLACE_URL, params)
    return data.get("results", [])
    


