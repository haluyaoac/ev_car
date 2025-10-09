# -*- coding: utf-8 -*-
"""
baidu_api_impl.py
百度地图API的高级封装与批量请求实现
主要函数：
- get_distance_one_one(origins, destinations, to_lists, ak, qps=3) → List[List[Optional[float]]]
参数说明：
    origins: 起点列表 [(lat, lng), ...]
    destinations: 终点列表 [(lat, lng), ...]
    to_lists: 每个起点对应的目的地索引列表 [[idx1, idx2, ...], ...]
    ak: 百度地图API密钥
- get_distance_matrix_batched(origins, destinations, to_lists, ak, num) → List[List[Optional[float]]]
参数说明：
    origins: 起点列表 [(lat, lng), ...]
    destinations: 目的地列表 [(lat, lng), ...]
    to_lists: 每个起点对应的目的地索引列表 [[idx1, idx2, ...], ...]
    ak: 百度地图API密钥
    num: 每次请求的最大目的地数量
- search_stations_along_route(origin, destination, ak, query_limit) → List[Dict[str, Any]]
参数说明：
    origin: 起点坐标 (lat, lng)
    destination: 终点坐标 (lat, lng)
    ak: 百度地图API密钥
    query_limit: 搜索的最大请求数量
"""
import math
from baidu_api import get_distance, get_route_polyline, search_charging_stations_near, search_stations_in_area, get_distance_matrix
from typing import Dict, List, Optional
from typing import List, Optional, Tuple
import asyncio


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
#通过一个点对一个点的方式请求
def get_distance_one_one(origins: List[Coord], destinations: List[Coord], to_lists: List[List[int]], ak: str) -> List[List[Optional[float]]]:
    result_matrix = []

    for i, to_idx_list in enumerate(to_lists):
        row_distances = []
        if not to_idx_list:
            #没有目的地，直接跳过
            result_matrix.append(row_distances)
            continue

        for j in range(0, len(to_idx_list)):

            print(f"[DEBUG] 起点 {i} {origins[i]} -> 终点索引 {to_idx_list[j]}{destinations[to_idx_list[j]]}")
            try:
                sub_matrix = get_distance(origins[i], destinations[to_idx_list[j]], ak)
            except Exception as e:
                print(f"[ERROR] 起点 {i} {origins[i]} -> 终点索引 {to_idx_list[j]}{destinations[to_idx_list[j]]} 请求失败: {e}")
                sub_matrix = None

            if sub_matrix is None:
                print(f"[WARN] 起点 {i} {origins[i]} -> 终点索引 {to_idx_list[j]}{destinations[to_idx_list[j]]} 返回直线距离")
                lat1, lng1 = origins[i]
                lat2, lng2 = destinations[to_idx_list[j]]
                # 计算两点间的直线距离（近似）
                R = 6371.0  # 地球半径，单位：公里
                dlat = math.radians(lat2 - lat1)
                dlon = math.radians(lng2 - lng1)
                a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
                c = 2 * math.asin(math.sqrt(a))
                distance_km = R * c
                row_distances.append(distance_km)
            else:
                print(f"[DEBUG] 返回距离: {sub_matrix}")
                row_distances.append(sub_matrix)

        result_matrix.append(row_distances)

    return result_matrix


#用于一次性计算多个点与多个点间的驾车距离
def get_distance_matrix_batched(origins: List[Coord], destinations: List[Coord], to_lists: List[List[int]], ak: str, num: int) -> List[List[Optional[float]]]:
    result_matrix = []

    for i, to_idx_list in enumerate(to_lists):
        row_distances = []
        if not to_idx_list:
            result_matrix.append(row_distances)
            continue

        for j in range(0, len(to_idx_list), num):
            chunk_idx = to_idx_list[j:j+num]
            chunk_dests = [destinations[k] for k in chunk_idx]

            print(f"[DEBUG] 起点 {i} {origins[i]} -> 终点索引 {chunk_idx} (批次大小 {len(chunk_idx)})")
            try:
                sub_matrix = get_distance_matrix([origins[i]], chunk_dests, ak)
            except Exception as e:
                print(f"[ERROR] 起点 {i} 批次 {j//num} 请求失败: {e}")
                sub_matrix = None

            if sub_matrix is None:
                print(f"[WARN] 起点 {i} 批次 {j//num} 返回直线距离")
                for dest in chunk_dests:
                    lat1, lng1 = origins[i]
                    lat2, lng2 = dest
                    # 计算两点间的直线距离（近似）
                    R = 6371.0  # 地球半径，单位：公里
                    dlat = math.radians(lat2 - lat1)
                    dlon = math.radians(lng2 - lng1)
                    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
                    c = 2 * math.asin(math.sqrt(a))
                    distance_km = R * c
                    row_distances.append(distance_km)
            else:
                print(f"[DEBUG] 返回行数: {len(sub_matrix)}, 列数: {len(sub_matrix[0]) if sub_matrix else 0}")
                row_distances.extend(sub_matrix[0])

        result_matrix.append(row_distances)

    return result_matrix



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



    



