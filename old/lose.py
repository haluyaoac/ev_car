#存放有效但应为某些原因被废弃的代码
#例如：某些功能被集成到其他模块中，某些功能被重

#用于一次性计算多个点与多个点间的驾车距离，使用百度地图API
async def get_distance_matrix_batched(origins: List[Coord], destinations: List[Coord], to_lists: List[List[int]], ak: str, qps: int = 3) -> List[List[Optional[float]]]:
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
            try:
                sub_matrix = await get_distance_matrix([origins[i]], chunk_dests, ak)
            except Exception as e:
                print(f"[ERROR] 起点 {i} 批次 {j//100} 请求失败: {e}")
                sub_matrix = None

            if sub_matrix is None:
                print(f"[WARN] 起点 {i} 批次 {j//100} 返回直线距离")
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
