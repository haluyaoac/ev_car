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




# ---------- POI 检索 ----------
def search_stations_by_circle(
    query: str,
    center: tuple,
    radius_m: int,
    ak: AKClass,
    radius_limit: bool = False,
    coord_type: int = 3
    
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
            "ak": ak.get_ak(),
            "page_size": page_size,
            "page_num": page,
            "scope": 1,  # 返回基本信息
            "coord_type": coord_type
        }

        data = ak.fetch(url, params)
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


def search_charging_stations_near(coord: Coord, ak: AKClass, radius: int = 2000) -> List[Dict]:
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
        "ak": ak.get_ak(),
    }
    data = ak.fetch(PLACE_URL, params)
    return data.get("results", [])



def a_star_ev(points: List[Coord],                                                   # 点列表 (lat,lng)
              adj: Dict[int, List[Tuple[int, float]]],                               # 邻接表
              car: Dict[str, float],                                                 # 车辆参数字典  
              start_idx: int,                                                        # 起点索引
              end_idx: int,                                                          # 终点索引
              start_soc: int = 100,                                                # 起始SOC%
              station_power_kw: float = 120.0) -> Optional[Dict[str, object]]:       # 充电桩功率
    """A* 于 (节点, SOC%) 状态空间：
    - 驾驶消耗SOC；任意节点可按 CHARGE_PERCENT_STEP 充电；
    - 启发式 = 直线距离/均速(分钟) * A_STAR_EPS_HEURISTIC；
    - 动态续航剪枝：SOC 不足先充电。
    返回 { total_time_min, path[(state, action), ...] } 或 None。
    """
    battery_kwh = float(car["battery_kwh"])                              # 电池容量 kWh      
    cons = float(car["consumption_kwh_per_km"])                          # 能耗 kWh/km
    vmax = max(30.0, float(car["avg_speed_kmph"]))                       # 平均速度 km/h

    def h(node_idx: int) -> float:
        """启发式：从 node_idx 到终点的直线距离 / 平均速度 * A_STAR_EPS_HEURISTIC"""
        d = haversine_km(points[node_idx], points[end_idx])
        return (d / vmax) * 60.0 * A_STAR_EPS_HEURISTIC

    def norm_pct(p: float) -> int:
        """将百分比 p 归一化到 [0, 100]，并按 CHARGE_PERCENT_STEP 步长离散化"""
        p = max(0.0, min(100.0, p))
        step = CHARGE_PERCENT_STEP
        return int((p // step) * step)
    
    start_soc = norm_pct(start_soc)                                      # 起始SOC离散化
    start: State = (start_idx, start_soc)                                # 起始状态 (节点索引, SOC%)

    pq: List[Tuple[float, float, State]] = [(h(start_idx), 0.0, start)]  # 优先队列 (f, g, (u, soc))
    best: Dict[State, float] = {start: 0.0}                              # 最佳已知 g 值
    prev: Dict[State, Tuple[State, str]] = {}                            # 前驱状态与动作

    while pq:
        f, g, (u, soc) = heapq.heappop(pq)
        if g > best.get((u, soc), float("inf")) + 1e-9:
            continue
        if u == end_idx:
            path = []
            cur = (u, soc)
            while cur in prev:
                path.append((cur, prev[cur][1]))
                cur = prev[cur][0]
            path.append((cur, "start"))
            path.reverse()
            return {"total_time_min": g, "path": path}

        # 可达邻居（驾驶）
        any_reachable = False
        for v, d_km in adj.get(u, []):
            need_pct = energy_needed_percent(d_km, battery_kwh, cons)
            if soc + 1e-9 >= need_pct:
                any_reachable = True
                drive_min = (d_km / vmax) * 60.0
                new_soc = norm_pct(soc - need_pct)
                ng = g + drive_min
                st = (v, new_soc)
                if ng + 1e-9 < best.get(st, float("inf")):
                    best[st] = ng
                    prev[st] = ((u, soc), f"drive {u}->{v} {d_km:.1f}km {drive_min:.1f}m ΔSOC=-{need_pct:.1f}% -> {new_soc}%")
                    heapq.heappush(pq, (ng + h(v), ng, st))

        # 充电（若无可达邻居则必充；有可达也允许充以寻求更优）
        if soc < 100:
            for add in range(CHARGE_PERCENT_STEP, 101 - soc + 1, CHARGE_PERCENT_STEP):
                target_soc = norm_pct(soc + add)
                dt = charge_time_minutes(target_soc - soc, battery_kwh, station_power_kw)
                ng = g + dt
                st = (u, target_soc)
                if ng + 1e-9 < best.get(st, float("inf")):
                    best[st] = ng
                    prev[st] = ((u, soc), f"charge {u} {soc}%→{target_soc}% {dt:.1f}m")
                    heapq.heappush(pq, (ng + h(u), ng, st))

    return None


def dijkstra_ev(points: List[Coord],
                adj: Dict[int, List[Tuple[int, float]]],
                car: Dict[str, float],
                start_idx: int,
                end_idx: int,
                start_soc: int = 100,
                station_power_kw: float = 120.0) -> Optional[Dict[str, object]]:
    """
    Dijkstra 于 (节点, SOC%) 状态空间：
    - 驾驶消耗SOC；任意节点可按 CHARGE_PERCENT_STEP 充电；
    - 优先队列按累计时间 g 排序；
    - 动态续航剪枝：SOC 不足先充电。
    返回 { total_time_min, path[(state, action), ...] } 或 None。
    """
    battery_kwh = float(car["battery_kwh"])
    cons = float(car["consumption_kwh_per_km"])
    vmax = max(30.0, float(car["avg_speed_kmph"]))

    def norm_pct(p: float) -> int:
        """将百分比 p 归一化到 [0, 100]，并按 CHARGE_PERCENT_STEP 步长离散化"""
        p = max(0.0, min(100.0, p))
        step = CHARGE_PERCENT_STEP
        return int((p // step) * step)

    start_soc = norm_pct(start_soc)
    start: State = (start_idx, start_soc)

    # 优先队列 (g, state)
    pq: List[Tuple[float, State]] = [(0.0, start)]
    # 最佳已知 g 值
    best: Dict[State, float] = {start: 0.0}
    # 前驱状态与动作
    prev: Dict[State, Tuple[State, str]] = {}

    while pq:
        g, (u, soc) = heapq.heappop(pq)
        if g > best.get((u, soc), float("inf")) + 1e-9:
            continue
        if u == end_idx:
            # 回溯路径
            all_way = []
            path = []
            cur = (u, soc)
            while cur in prev:
                path.append((cur, prev[cur][1]))
                all_way.append(cur, prev[cur])
                cur = prev[cur][0]
            path.append((cur, "start"))
            path.reverse()
            return {"total_time_min": g, "path": path, "prev": all_way}

        # 驾驶扩展
        for v, d_km in adj.get(u, []):
            need_pct = energy_needed_percent(d_km, battery_kwh, cons)
            if soc + 1e-9 >= need_pct:
                drive_min = (d_km / vmax) * 60.0
                new_soc = norm_pct(soc - need_pct)
                ng = g + drive_min
                st = (v, new_soc)
                if ng + 1e-9 < best.get(st, float("inf")):
                    best[st] = ng
                    prev[st] = ((u, soc),
                                f"drive {u}->{v} {d_km:.1f}km {drive_min:.1f}m ΔSOC=-{need_pct:.1f}% -> {new_soc}%")
                    heapq.heappush(pq, (ng, st))

        # 充电扩展
        if soc < 100:
            for add in range(CHARGE_PERCENT_STEP, 101 - soc + 1, CHARGE_PERCENT_STEP):
                target_soc = norm_pct(soc + add)
                dt = charge_time_minutes(target_soc - soc, battery_kwh, station_power_kw)
                ng = g + dt
                st = (u, target_soc)
                if ng + 1e-9 < best.get(st, float("inf")):
                    best[st] = ng
                    prev[st] = ((u, soc), f"charge {u} {soc}%→{target_soc}% {dt:.1f}m")
                    heapq.heappush(pq, (ng, st))

    return None

