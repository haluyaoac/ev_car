# -*- coding: utf-8 -*-
"""
baidu_api.py

主要函数：
- geocode(address, ak) → Optional[Coord]
参数说明：
    address: 地址字符串
    ak: 百度地图API密钥
- get_area(lat, lng, ak) → str
参数说明：
    lat: 纬度
    lng: 经度
    ak: 百度地图API密钥
- get_distance(start, end, ak) → Optional[float]
参数说明：
    start: 起点坐标 (lat, lng)
    end: 终点坐标 (lat, lng)
    ak: 百度地图API密钥
- get_route_polyline(start, end, ak) → Optional[Dict[str, Any]]
参数说明：
    start: 起点坐标 (lat, lng)
    end: 终点坐标 (lat, lng)
    ak: 百度地图API密钥
- search_stations_by_circle(query, center, radius_m, ak, ...) → List[Dict[str, Any]]
参数说明：
    query: 搜索关键词
    center: 圆心坐标 (lat, lng)
    radius_m: 搜索半径（米）
    ak: 百度地图API密钥
    radius_limit: 是否限制在圆形区域内
    coord_type: 坐标类型
- search_charging_stations_near(coord, radius, ak) → List[Dict]
参数说明：
    coord: 中心点坐标 (lat, lng)
    radius: 搜索半径（米）
    ak: 百度地图API密钥
- search_stations_in_area(lat, lng, ak, ...) → List[Dict]
参数说明：
    lat: 纬度
    lng: 经度
    ak: 百度地图API密钥
    page_size: 每页数量
    page_num: 页码
    region: 行政区名称（可选）
    limit: 返回结果数量上限
- get_distance_matrix(origins, destinations, ak, ...) → Optional[List[Optional[float]]]
参数说明：
    origins: 起点坐标 (lat, lng)
    destinations: 终点坐标列表 [(lat, lng), ...]
    ak: 百度地图API密钥
    qps_limiter: QPS 限制器（可选）
    max_retries: 最大重试次数
辅助函数：
- _fmt_coord_bd09(lat, lng) → str

"""
import asyncio
from typing import List, Optional, Tuple, Dict, Any
from time import sleep
from utils import Coord, corridor_polygon, polygon_to_bounds_str
from ak_manner import AK

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


def geocode(address, ak: AK) -> Optional[Coord]:
    params = {
        "address": address,
        "output": "json",
        "ak": ak.get_ak(),
    }

    data = ak.fetch(GEOCODE_URL, params)
    if isinstance(data, dict) and data.get("status") == 0:
        loc = data["result"]["location"]
        return (loc["lat"], loc["lng"])
    return None


async def get_area(lat: float, lng: float, ak: AK) -> str:
    """逆地理编码：坐标 → 行政区/城市"""
    params = {
        "ak": ak.get_ak(),
        "output": "json",
        "coordtype": "wgs84ll",
        "location": f"{lat},{lng}"
    }
    resp = await ak.fetch_async(REVERSE_GEOCODE_URL, params, api_type="regeo")
    if isinstance(resp, dict) and resp.get("status") == 0:
        comp = resp["result"]["addressComponent"]
        return comp.get("district") or comp.get("city")
    return None


def get_distance(start: Coord, end: Coord, ak: AK) -> Optional[float]:
    """获取两点间驾车距离（公里）"""
    params = {
        "origins": _fmt_coord_bd09(*start),
        "destinations": _fmt_coord_bd09(*end),
    }
    data = ak.fetch(DISTANCE_URL, params)
    if isinstance(data, dict) and data.get("status") == 0:
        results = data.get("result", [])
        if results and "distance" in results[0]:
            return results[0]["distance"]["value"] / 1000.0
    return None

async def get_route_polyline(start: Coord, end: Coord, ak: AK) -> Optional[Dict[str, Any]]:
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
        "ak": ak.get_ak(),
    }
    data = await ak.fetch_async(DRIVE_URL, params, api_type="driving_plan")
    if isinstance(data, dict) and data.get("status") == 0:
        routes = data.get("result", {}).get("routes", [])       
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
    return None

async def get_distances_async(origin: str, destinations: List[str], ak: AK) -> List[List[float]]:
    """
    计算一个起点到多个终点的距离（自动分批 + 异步并发）
    origin: "lat,lng"
    destinations: ["lat1,lng1", "lat2,lng2", ...]
    """
    tasks = []
    if destinations is None or len(destinations) == 0:
        return []
    params = {
        "origins": _fmt_coord_bd09(origin[0], origin[1]),
        "destinations": "|".join([_fmt_coord_bd09(*pt) for pt in destinations]),
        "tactics": 11   ,  # 最短时间
        "output": "json",
        "ak": ak.get_ak()
    }
    data = await ak.fetch_async(url=DISTANCE_URL, params=params, api_type="distance_matrix")
    if data and data.get("status") == 0:
        results = data.get("result", [])
        distances = []
        for res in results:
            if "distance" in res:
                distances.append(res["distance"]["value"] / 1000.0)
            else:
                distances.append(float('inf'))
        return distances
    return []


async def search_stations_in_area(lat: float, lng: float, ak: AK, page_size: int = 10, page_num : int = 0, region: Optional[str] = None,limit = 5) -> List[Dict]:
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
        region = await get_area(lat, lng, ak)

    # 2. 查询充电站
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
        "ak": ak.get_ak()
    }
    place_resp = await ak.fetch_async(url = PLACE_URL, params=place_params, api_type="place_search")

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
