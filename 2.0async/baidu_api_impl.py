# -*- coding: utf-8 -*-
"""
baidu_api.py
- get_route_polyline(start, end, ak): 获取驾车路线 polyline ([(lat,lng), ...])
- poi_charging_near_paginated(...): 在单点附近分页获取充电站（返回字典列表）
- search_stations_along_route(route_poly, ak, ...): 按段分配配额、分页请求、扩半径、去重与下采样
"""
import math
from baidu_api import get_distance_async, get_route_polyline, search_charging_stations_near, search_stations_in_area
from typing import Dict, List, Optional, Tuple
import asyncio
from utils import haversine_km

DRIVE_URL = "https://api.map.baidu.com/directionlite/v1/driving"
PLACE_URL = "https://api.map.baidu.com/place/v2/search"
DISTANCE_URL = "https://api.map.baidu.com/routematrix/v2/driving"

Coord = Tuple[float, float]


# =========================
# 工具函数
# =========================

def _fmt_coord_bd09(lat: float, lng: float) -> str:
    return f"{lat:.6f},{lng:.6f}"

# =========================
# 批量请求函数
# =========================

async def get_distance_matrix_batched_async(
    origins: List[Coord],
    destinations: List[Coord],
    to_lists: List[List[int]],
    num: int
) -> List[List[Optional[float]]]:
    """异步批量计算多个起点到多个终点的距离矩阵"""
    tasks = []

    for i, to_idx_list in enumerate(to_lists):
        if not to_idx_list:
            tasks.append(asyncio.sleep(0, result=[]))
            continue

        # 按 num 分批（每个请求不超过百度100个）
        for j in range(0, len(to_idx_list), num):
            chunk_idx = to_idx_list[j:j + num]
            chunk_dests = [destinations[k] for k in chunk_idx]
            tasks.append(_fetch_distance_chunk(i, origins[i], chunk_dests))

    all_results = await asyncio.gather(*tasks)
    # 将多个起点的结果整理为行矩阵
    result_matrix = [[] for _ in origins]

    task_idx = 0
    for i, to_idx_list in enumerate(to_lists):
        if not to_idx_list:
            continue
        for j in range(0, len(to_idx_list), num):
            chunk_dists = all_results[task_idx]
            if chunk_dists is None:
                # 请求失败 -> 使用直线距离近似
                chunk_dests = [destinations[k] for k in to_idx_list[j:j+num]]
                for dest in chunk_dests:
                    lat1, lng1 = origins[i]
                    lat2, lng2 = dest
                    result_matrix[i].append(haversine_km(lat1, lng1, lat2, lng2))
            else:
                result_matrix[i].extend(chunk_dists)
            task_idx += 1
    return result_matrix


async def _fetch_distance_chunk(origin_idx: int, origin: Coord, chunk_dests: List[Coord]):
    """一个异步子任务：单起点 + 批量终点"""
    try:
        print(f"[ASYNC] 起点 {origin_idx} -> {len(chunk_dests)} 终点")
        return await get_distance_async(origin, chunk_dests)
    except Exception as e:
        print(f"[ERROR] 起点 {origin_idx} 请求失败: {e}")
        return None
    

def get_distance_matrix_batched(origins, destinations, to_lists, num):
    """同步版本包装（方便旧代码直接用）"""
    return asyncio.run(get_distance_matrix_batched_async(origins, destinations, to_lists, num))



def search_stations_along_route(
        origin, 
        destination, 
        ak, 
        query_limit):
    """
    沿路线搜索充电站
    :param origin: 起点坐标 (lat, lng)
    :param destination: 终点坐标 (lat, lng)
    :param ak: 百度地图API密钥
    :param query_limit: 搜索的最大请求数量
    :return: 充电站列表
    """
    # 获取路线的折线点
    route_dict = get_route_polyline(origin, destination, ak)
    poly = route_dict.get("polyline", [])
    #按照点的数量划分为若干段，每段搜索一次，总数在query_limit以内
    query_points = []
    n = int(max(1, len(poly) / query_limit))
    for i in range(0, len(poly), n):
        query_points.append(poly[i])
    
    stations = []
    unique = {}

    for pt in query_points:
        lat, lng = pt
        area_stations = search_stations_in_area(lat, lng, ak)
        print(f"[DEBUG] 在点 {pt} 附近搜索到 {len(area_stations)} 个充电站")
        for st in area_stations:
            uid = st.get("uid")
            if uid and uid not in unique:
                unique[uid] = st
                print(f"[DEBUG] 新增充电站: {st}")
    stations = list(unique.values())


    print(f"沿路搜索到 {len(stations)} 个充电站")
    return stations



    



