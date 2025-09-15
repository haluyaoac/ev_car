# -*- coding: utf-8 -*-
"""
baidu_api.py
- get_route_polyline(start, end, ak): 获取驾车路线 polyline ([(lat,lng), ...])
- poi_charging_near_paginated(...): 在单点附近分页获取充电站（返回字典列表）
- search_stations_along_route(route_poly, ak, ...): 按段分配配额、分页请求、扩半径、去重与下采样
"""
from baidu_api import get_distance_matrix
from typing import List, Optional
from typing import List, Optional, Tuple
from utils import QPSLimiter



DRIVE_URL = "https://api.map.baidu.com/directionlite/v1/driving"
PLACE_URL = "https://api.map.baidu.com/place/v2/search"
DISTANCE_URL = "https://api.map.baidu.com/routematrix/v2/driving"
# ---------- helpers ----------
def _fmt_coord_bd09(lat: float, lng: float) -> str:
    # 百度 Web 服务中某些接口要求经度,纬度；不过 place API expects "lat,lng" for location.
    return f"{lat},{lng}"

Coord = Tuple[float, float]


# =========================
# 工具函数
# =========================

def _fmt_coord_bd09(lat: float, lng: float) -> str:
    return f"{lat:.6f},{lng:.6f}"


# =========================
# 批量请求函数
# =========================

def get_distance_matrix_batched(origins: List[Coord], destinations: List[Coord], to_lists: List[List[int]], ak: str, qps: int = 3) -> List[List[Optional[float]]]:
    qps_limiter = QPSLimiter(max_qps=qps)
    result_matrix = []

    for i, to_idx_list in enumerate(to_lists):
        row_distances = []
        if not to_idx_list:
            result_matrix.append(row_distances)
            continue

        for j in range(0, len(to_idx_list), 100):
            chunk_idx = to_idx_list[j:j+100]
            chunk_dests = [destinations[k] for k in chunk_idx]

            print(f"[DEBUG] 起点 {i} {origins[i]} -> 终点索引 {chunk_idx} (批次大小 {len(chunk_idx)})")

            sub_matrix = get_distance_matrix([origins[i]], chunk_dests, ak, qps_limiter)

            if sub_matrix is None:
                print(f"[WARN] 起点 {i} 批次 {j//100} 返回 None")
                row_distances.extend([None] * len(chunk_idx))
            else:
                print(f"[DEBUG] 返回行数: {len(sub_matrix)}, 列数: {len(sub_matrix[0]) if sub_matrix else 0}")
                row_distances.extend(sub_matrix[0])

        result_matrix.append(row_distances)

    return result_matrix


