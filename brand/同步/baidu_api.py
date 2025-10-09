# -*- coding: utf-8 -*-
"""
baidu_api.py

主要函数：
- geocode(address, ak) → (lat, lng) 或 None
- get_route_polyline(start, end, ak) → 路径信息字典
- get_route_distance(start, end, ak) → float → 两点间驾车距离 (km)
- get_distance_matrix(origins, destinations, ak) → List[float] → 距离矩阵
- search_charging_stations_near(coord, radius) → 附近充电桩
- search_stations_in_area(lat, lng, ak, ...) → 行政区域内充电站
"""
import asyncio
from typing import List, Optional, Tuple, Dict, Any
from time import sleep

from qps_manner import fetch_json
from config import AK
from utils import Coord, corridor_polygon, polygon_to_bounds_str


# -------------------- API 封装 --------------------
DRIVE_URL = "https://api.map.baidu.com/directionlite/v1/driving"
PLACE_URL = "https://api.map.baidu.com/place/v2/search"
DISTANCE_URL = "https://api.map.baidu.com/routematrix/v2/driving"
GEOCODE_URL = "https://api.map.baidu.com/geocoding/v3/"
REVERSE_GEOCODE_URL = "https://api.map.baidu.com/reverse_geocoding/v3/"


# ---------- helpers ----------
def _fmt_coord_bd09(lat: float, lng: float) -> str:
    # 百度 Web 服务中某些接口要求经度,纬度；不过 place API expects "lat,lng" for location.
    return f"{lat},{lng}"


def geocode(address, ak) -> Optional[Coord]:
    params = {
        "address": address,
        "output": "json",
        "ak": ak
    }
    data = fetch_json(GEOCODE_URL, params)
    if isinstance(data, dict) and data.get("status") == 0:
        loc = data["result"]["location"]
        return (loc["lat"], loc["lng"])
    return None


def get_area(lat: float, lng: float, ak: str) -> str:
    """逆地理编码：坐标 → 行政区/城市"""
    params = {
        "ak": ak,
        "output": "json",
        "coordtype": "wgs84ll",
        "location": f"{lat},{lng}"
    }
    resp = fetch_json(REVERSE_GEOCODE_URL, params)
    if isinstance(resp, dict) and resp.get("status") == 0:
        comp = resp["result"]["addressComponent"]
        return comp.get("district") or comp.get("city")
    return None


def get_distance(start: Coord, end: Coord, ak: str) -> Optional[float]:
    """获取两点间驾车距离（公里）"""
    params = {
        "origins": _fmt_coord_bd09(*start),
        "destinations": _fmt_coord_bd09(*end),
        "ak": ak,
    }
    try:
        data = fetch_json(DISTANCE_URL, params)
    except Exception as e:
        print(f"[ERROR] 获取距离失败: {e}")
        return None

    results = data.get("result", [])
    if results and "distance" in results[0]:
        return results[0]["distance"]["value"] / 1000.0


def get_route_polyline(start: Coord, end: Coord, ak: str) -> Optional[Dict[str, Any]]:
    """
    获取驾车路线，返回：
    {
        "polyline": [(lat,lng), ...],
        "poly_start": [],
        "poly_end": [],
        "poly_name": [],
        "poly_distance": [],
        "raw": 原始返回
    }
    """
    params = {
        "origin": _fmt_coord_bd09(*start),
        "destination": _fmt_coord_bd09(*end),
        "ak": ak,
    }
    data = fetch_json(DRIVE_URL, params)
    routes = data.get("result", {}).get("routes", [])
    if not routes:
        return None

    route = routes[0]
    steps = route.get("steps", [])
    poly, poly_start, poly_end, poly_name, poly_distance = [], [], [], [], []
    for seg in steps:
        poly_name.append(seg.get("road_name", ""))
        poly_distance.append(seg.get("distance", 0))
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
        "poly_distance": poly_distance,
        "raw": data
    }


# ---------- POI 检索 ----------
def search_stations_by_circle(
    query: str,
    center: tuple,
    radius_m: int,
    ak: str,
    radius_limit: bool = False,
    coord_type: int = 3,
) -> List[Dict[str, Any]]:
    """
    使用百度地图地点检索API进行圆形区域检索
    """
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
            "is_light_version": "true",
            "radius_limit": str(radius_limit).lower(),
            "output": "json",
            "ak": ak,
            "page_size": page_size,
            "page_num": page,
            "scope": 1,  # 返回基本信息
            "coord_type": 3
        }

        data = fetch_json(url, params)
        if not data or data.get("_error"):
            print("[Baidu_api] 请求异常:", data.get("_error") if isinstance(data, dict) else data)
            break

        results = data.get("results", [])
        if not results:
            break

        for item in results:
            stations.append({
                "uid": item.get("uid"),
                "name": item.get("name"),
                "lat": item.get("location", {}).get("lat"),
                "lng": item.get("location", {}).get("lng"),
                "address": item.get("address", ""),
                "distance": item.get("distance"),
            })

        if len(results) < page_size:
            break
        page += 1

    return stations


def get_distance_matrix(origins: Coord, destinations: List[Coord], ak: str, qps_limiter=None, max_retries=3) -> Optional[List[Optional[float]]]:
    if not origins or not destinations:
        return []
    max_points = 100
    n_dst = len(destinations)
    if n_dst > max_points:
        print(f"[Baidu] 点数过多 {n_dst}")
        return None
    params = {
        "origins": _fmt_coord_bd09(origins[0], origins[1]),
        "destinations": "|".join([_fmt_coord_bd09(*pt) for pt in destinations]),
        "ak": ak,
    }

    data = fetch_json(DISTANCE_URL, params)
    results = data.get("result", [])
    # 组装为二维矩阵
    matrix: List[Optional[float]] = []
    for j in range(n_dst):
        cell = results[j]
        val = None
        if cell and "distance" in cell and cell["distance"].get("value") is not None:
            val = cell["distance"]["value"] / 1000.0  # 米转公里
        matrix.append(val)
    return matrix


def search_charging_stations_near(coord: Coord, radius: int = 2000) -> List[Dict]:
    """
    调用百度POI搜索API，返回附近充电桩列表
    """
    params = {
        "query": "充电桩",
        "location": f"{coord[0]},{coord[1]}",
        "radius": radius,
        "is_light_version": "true",
        "output": "json",
        "scope": 2,  # 返回详细信息
        "ak": AK,
    }
    data = fetch_json(PLACE_URL, params)


    return data.get("results", [])


def search_stations_in_area(lat: float, lng: float, ak: str, page_size: int = 10, page_num : int = 0, region: Optional[str] = None,limit = 7) -> List[Dict]:
    """
    查询某个点所在行政区域的充电站列表
    :param lat: 纬度
    :param lng: 经度
    :param ak: 百度地图 API key
    :param page_size: 每页数量 (10-20)
    :param page_num: 页码，从0开始
    :param region: 可选，指定行政区名称，若不提供则自动获取
    :return: 充电站列表
    """

    if(not region):
        region = get_area(lat, lng, ak)

    # 2. 查询充电站
    place_url = "https://api.map.baidu.com/place/v2/search"
    place_params = {
        "query": "充电站",
        "region": region,
        "center": f"{lat},{lng}",
        "region_limit": "true",  # 限制在该区域
        "scope": 2,
        "filter": "sort_name:distance|sort_rule:1",  # 按距离排序，升序
        "page_size": page_size,
        "page_num": page_num,
        "output": "json",
        "ak": ak
    }
    place_resp = fetch_json(place_url, params=place_params)

    results = []
    for poi in place_resp.get("results", []):
        results.append({
            "name": poi.get("name"),
            "address": poi.get("address"),
            "location": poi.get("location"),
            "area": poi.get("area"),
            "telephone": poi.get("telephone"),
            "overall_rating": poi.get("detail_info", {}).get("overall_rating"),
            "uid": poi.get("uid")
        })

    return results[:limit]
