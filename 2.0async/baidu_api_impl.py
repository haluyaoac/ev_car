# -*- coding: utf-8 -*-
"""
baidu_api.py
- get_route_polyline(start, end, ak): 获取驾车路线 polyline ([(lat,lng), ...])
- poi_charging_near_paginated(...): 在单点附近分页获取充电站（返回字典列表）
- search_stations_along_route(route_poly, ak, ...): 按段分配配额、分页请求、扩半径、去重与下采样
"""
import math
from baidu_api import get_route_polyline, search_stations_in_area, get_distances_async
from typing import Dict, List, Optional, Tuple
import asyncio
from utils import haversine_km
from ak_manner import AK

Coord = Tuple[float, float]


def close_ak_sessions(aks: List[AK]):
    """关闭所有 AK 的会话"""
    async def _close_all():
        tasks = []
        for ak in aks:
            tasks.append(asyncio.create_task(ak.close()))
        await asyncio.gather(*tasks)

    asyncio.run(_close_all())

# =========================
# 批量请求函数
# =========================

async def get_distance_matrix_batched_async(
    origins: List[Coord],
    destinations: List[Coord],
    to_lists: List[List[int]],
    aks: List[AK]
) -> List[List[Optional[float]]]:
    """异步批量计算多个起点到多个终点的距离矩阵"""
    tasks = []
    task_meta = []  # [(origin_idx, dest_start_idx_in_to_lists, batch_size)]

    ak_len = len(aks)
    j = 0
    ak = aks[j]

    # 构建任务
    for i, dest_idx_list in enumerate(to_lists):
        dest_subset = [destinations[k] for k in dest_idx_list]
        batch_size = ak.qps_limit["distance_get"]
        for start in range(0, len(dest_subset), batch_size):
            batch = dest_subset[start:start + batch_size]
            tasks.append(get_distances_async(origins[i], batch, ak))
            task_meta.append((i, start, len(batch)))
            j = (j + 1) % ak_len
            ak = aks[j]

    # 等待所有任务完成
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 初始化完整矩阵（None 填充）
    distance_matrix = [
        [None] * len(destinations) for _ in range(len(origins))
    ]

    # 组装返回结果
    for (i, start, batch_len), batch_result in zip(task_meta, results):
        # 若任务异常或返回 None，则对应距离全设为 None
        if isinstance(batch_result, Exception) or batch_result is None:
            batch_result = [None] * batch_len

        dest_idx_list = to_lists[i]
        for offset, dist in enumerate(batch_result):
            # 在完整 destinations 中的实际索引
            dest_global_idx = dest_idx_list[start + offset]
            distance_matrix[i][dest_global_idx] = dist

    return distance_matrix



def get_distance_matrix_batched_async_start(
    origins: List[Coord],
    destinations: List[Coord],
    to_lists: List[List[int]],
    aks: List[AK]
) -> List[List[Optional[float]]]:
    """同步接口，启动异步距离矩阵计算"""

    result = asyncio.run(get_distance_matrix_batched_async(
        origins,
        destinations,
        to_lists,
        aks
    ))
    close_ak_sessions(aks)
    return result

async def search_stations_along_route(
        origin, 
        destination, 
        aks: List[AK], 
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
    print("2.1获取路线折线点")
    route_dict = await get_route_polyline(origin, destination, aks[0])
    #await aks[0].close()
    poly = route_dict.get("polyline", [])
    #按照点的数量划分为若干段，每段搜索一次，总数在query_limit以内
    query_points = []
    n = int(max(1, len(poly) / query_limit))
    for i in range(0, len(poly), n):
        query_points.append(poly[i])
    
    stations = []
    unique = {}
    tasks = []
    j = 0
    ak_cnt = len(aks)
    print(f"沿路线共划分为 {len(query_points)} 个搜索点")
    print("2.2开始沿路线搜索充电站")
    for pt in query_points:
        lat, lng = pt

        tasks.append(asyncio.create_task(search_stations_in_area(lat, lng, aks[j])))
        j = (j + 1) % ak_cnt

    area_stations = await asyncio.gather(*tasks)

    for area in area_stations:
        for st in area:
            uid = st.get("uid")
            if uid and uid not in unique:
                unique[uid] = st
                print(f"[DEBUG] 新增充电站: {st}")
        stations = list(unique.values())


    print(f"沿路搜索到 {len(stations)} 个充电站")
    return stations

def search_stations_along_route_start(
        origin, 
        destination, 
        aks: List[AK], 
        query_limit):
    """同步接口，启动异步沿路线搜索充电站"""
    result = asyncio.run(search_stations_along_route(
        origin, 
        destination, 
        aks, 
        query_limit
    ))
    close_ak_sessions(aks)
    return result

# =========================
# 拼接导航
# =========================
async def get_route_polyline_async(
    route_points: List[Dict],
    aks: List[AK]
) -> Dict:
    """异步获取驾车路线折线"""
    tasks = []
    for i in range(len(route_points) - 1):
        start = (route_points[i]["lat"], route_points[i]["lng"])
        end = (route_points[i + 1]["lat"], route_points[i + 1]["lng"])
        tasks.append(asyncio.create_task(get_route_polyline(start, end, aks[i % len(aks)])))
    result = await asyncio.gather(*tasks)
    return result


def get_route_polyline_start(
    route_points: List[Dict],
    aks: List[AK]
) -> Dict:
    """同步接口，启动异步获取驾车路线折线"""
    result = asyncio.run(get_route_polyline_async(
        route_points,
        aks
    ))
    close_ak_sessions(aks)
    return result



