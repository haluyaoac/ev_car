# ...existing code...
import logging
from typing import List, Dict, Tuple, Optional
import time
from utils import Coord, haversine_km
from collections import deque
from typing import Set
from baidu_api_impl import get_distance_matrix_batched_async_start
from ak_manner import AK

Edge = Tuple[int, int, float]  # (u,v,dist_km)

def _try_import_baidu_api():
    try:
        import baidu_api as _ba
        return _ba
    except Exception:
        logging.warning("无法导入 baidu_api，百度导航功能不可用")
        return None
    


def build_graph_with_endpoints2(stations, 
                                origin=None, 
                                destination=None,
                                max_range_km=200.0, 
                                aks: List[AK] = None,
                                prefilter_factor=1.0, 
                                verbose=False):
    """
    将 charging stations + origin + destination 作为节点，按导航距离构建邻接表。
    重要：先用直线距离预筛（fast），只有在直线距离未超过预筛阈值时才调用导航 API 获取实际路径距离（昂贵）。
    返回: (nodes, adj, idx_origin, idx_destination)
    stations: List[dict],                     充电站列表，每个充电站为 dict 或 (lat,lng) tuple          
    origin: Optional[Coord] = None,           起点坐标 (lat, lng)，可选
    destination: Optional[Coord] = None,      终点坐标 (lat, lng)，可选
    max_range_km: float = 200.0,              续航里程阈值（单位 km）
    ak: Optional[str] = None,                 百度地图 API Key，若 use_baidu_route 则必需
    prefilter_factor: float = 1,              预筛倍数，控制直线距离预筛阈值（详见说明）
    verbose: bool = False                     是否打印调试信息
    """
    # 构造节点
    nodes = []
    for s in stations:
        nodes.append({
            "name": s.get("name", ""),
            "lat": s.get("lat", s.get("location", {}).get("lat")),
            "lng": s.get("lng", s.get("location", {}).get("lng")),
            "address": s.get("address", ""),
            "uid": s.get("uid", "")
        })

    idx_origin = None
    idx_destination = None
    if origin:
        nodes.insert(0, {"lat": origin[0], "lng": origin[1], "name": "origin", "uid": "origin"})
        idx_origin = 0
    if destination:
        nodes.append({"lat": destination[0], "lng": destination[1], "name": "destination", "uid": "destination"})
        idx_destination = len(nodes) - 1

    n = len(nodes)
    coords = [(n["lat"], n["lng"]) for n in nodes]

    # 直线预筛
    to_lists = [[] for _ in range(n)]
    straight_map = {}
    for i in range(n):
        for j in range(i+1, n):
            d_geo = haversine_km(coords[i], coords[j])
            if d_geo <= max_range_km * prefilter_factor:
                to_lists[i].append(j)
                straight_map[(i, j)] = d_geo

    # 调试输出
    total_candidates = sum(len(lst) for lst in to_lists)
    print(f"[DEBUG] 节点总数: {n}, 候选边总数: {total_candidates}")
    for i, lst in enumerate(to_lists):
        print(f"[DEBUG] 起点 {i} ({coords[i]}), 候选终点数: {len(lst)}")

    # 批量导航距离
    nav_matrix = get_distance_matrix_batched_async_start(coords, coords, to_lists, aks)

    # 构建邻接表
    adj = {i: [] for i in range(n)}
    for i in range(n):
        for idx, j in enumerate(to_lists[i]):
            nav_km = None
            if nav_matrix and idx < len(nav_matrix[i]):
                nav_km = nav_matrix[i][idx]
            if nav_km is None:
                nav_km = straight_map[(i, j)]
            if nav_km <= max_range_km:
                adj[i].append((j, nav_km))
                adj[j].append((i, nav_km))

    return nodes, adj, idx_origin, idx_destination






def build_graph_with_endpoints(stations: List[dict],                   
                               origin: Optional[Coord] = None,
                               destination: Optional[Coord] = None,
                               max_range_km: float = 200.0,
                               use_baidu_route: bool = True,
                               ak: Optional[str] = None,
                               prefilter_factor: float = 1,
                               sleep_between_calls: float = 1,
                               verbose: bool = True
                               ) -> Tuple[List[dict], Dict[int, List[Tuple[int, float]]], Optional[int], Optional[int]]:
    """
    将 charging stations + origin + destination 作为节点，按导航距离构建邻接表。
    重要：先用直线距离预筛（fast），只有在直线距离未超过预筛阈值时才调用导航 API 获取实际路径距离（昂贵）。
    返回: (nodes, adj, idx_origin, idx_destination)

    stations: List[dict],                     充电站列表，每个充电站为 dict 或 (lat,lng) tuple          
    origin: Optional[Coord] = None,           起点坐标 (lat, lng)，可选
    destination: Optional[Coord] = None,      终点坐标 (lat, lng)，可选
    max_range_km: float = 200.0,              续航里程阈值（单位 km）
    use_baidu_route: bool = True,             是否使用百度驾车导航距离（否则仅用直线距离）
    ak: Optional[str] = None,                 百度地图 API Key，若 use_baidu_route 则必需
    prefilter_factor: float = 1,              预筛倍数，控制直线距离预筛阈值（详见说明）
    sleep_between_calls: float = 1,        API 调用间隔（秒），避免频率过高被限流
    verbose: bool = False                     是否打印调试信息
    """
    # 构造节点列表（浅拷贝）
    nodes: List[dict] = []
    for s in stations:
        if isinstance(s, dict):
            #判断s类型
            nodes.append({**s})
        else:
            nodes.append({"lat": s[0], "lng": s[1]})

    idx_origin = None
    idx_destination = None
    if origin:
        nodes.insert(0, {"lat": origin[0], "lng": origin[1], "name": "origin"})
        idx_origin = 0
    if destination:
        nodes.append({"lat": destination[0], "lng": destination[1], "name": "destination"})
        idx_destination = len(nodes) - 1

    n = len(nodes)
    adj: Dict[int, List[Tuple[int, float]]] = {i: [] for i in range(n)}
    dist_cache: Dict[Tuple[int, int], float] = {}

    baidu = _try_import_baidu_api() if use_baidu_route and ak else None

    def _coord_of_index(i: int) -> Coord:
        return (nodes[i]["lat"], nodes[i]["lng"])

    for i in range(n):
        ai = _coord_of_index(i)
        for j in range(i + 1, n):
            bj = _coord_of_index(j)

            # 1) 先用直线距离进行快速预筛（避免不必要的导航请求）
            straight_km = haversine_km(ai, bj)
            if straight_km > max_range_km * prefilter_factor:
                # 直线距离就超过阈值，直接跳过
                if verbose:

                    pass
                continue

            # 2) 若通过预筛，尝试使用导航距离（优先百度 driving），失败回退到直线
            nav_km: Optional[float] = None
            if baidu:
                try:
                    nav_km = baidu.get_route_distance(ai, bj, ak)
                except Exception as e:
                    if verbose:
                        print(f"[graph_builder] baidu route failed for {i}-{j}: {e}")
                    nav_km = None
                time.sleep(sleep_between_calls)

            if nav_km is None:
                nav_km = straight_km 

            # 3) 根据导航距离决定是否连边
            if nav_km <= max_range_km:
                adj[i].append((j, nav_km))
                adj[j].append((i, nav_km))
                if verbose:
                    print(f"[graph_builder] edge {i}<->{j} nav={nav_km:.2f}km straight={straight_km:.2f}km")

    return nodes, adj, idx_origin, idx_destination



def _connected_components(adj: Dict[int, List[Tuple[int, float]]]) -> List[Set[int]]:
    """返回邻接表 adj 的连通分量（节点集合列表）。"""
    n = len(adj)
    seen = set()
    comps: List[Set[int]] = []
    for u in adj.keys():
        if u in seen:
            continue
        q = deque([u])
        comp = set([u])
        seen.add(u)
        while q:
            v = q.popleft()
            for w, _ in adj.get(v, []):
                if w not in seen:
                    seen.add(w)
                    comp.add(w)
                    q.append(w)
        comps.append(comp)
    return comps


def sparsify_by_knn(nodes: List[dict],
                    adj: Dict[int, List[Tuple[int, float]]],
                    original_adj: Dict[int, List[Tuple[int, float]]] = None,
                    k: int = 8,
                    preserve: Set[int] = None,
                    verbose: bool = False) -> Dict[int, List[Tuple[int, float]]]:
    """
    基于已有邻接表按每节点保留 k 个最近邻进行稀疏化，并尽量保持连通性。
    参数:
      - nodes: 节点列表（用于长度或索引一致性）
      - adj: 当前邻接表（dict[idx] -> [(neighbor, weight), ...]）
      - original_adj: 原始完整邻接表（用于必要时从中选择跨分量最小边重连）。
                       若为 None，则无法自动重连，只做局部剪枝。
      - k: 每节点保留的最近邻数量
      - preserve: 要优先保持连通的节点集合（例如 {s_idx, t_idx}）
      - verbose: 是否打印调试信息
    返回新的邻接表（对称化）。
    """
    n = len(nodes)
    preserve = set(preserve or [])
    # 1) 对每个节点选取最近 k 条边
    kept: Dict[int, Set[int]] = {i: set() for i in range(n)}
    for u in range(n):
        neigh = adj.get(u, [])
        # 按权重升序取前 k
        top = sorted(neigh, key=lambda x: x[1])[:k]
        for v, _ in top:
            kept[u].add(v)

    # 2) 对称化：若 u 保留 v，则也在 v 的列表中保留 u（保证无向）
    for u in range(n):
        for v in list(kept[u]):
            kept[v].add(u)

    # 3) 构造新的邻接表，使用原 adj 中的权重（找不到则用 haversine 估算）
    new_adj: Dict[int, List[Tuple[int, float]]] = {i: [] for i in range(n)}
    for u in range(n):
        for v in sorted(kept[u]):
            # 找权重
            w = None
            for vv, ww in adj.get(u, []):
                if vv == v:
                    w = ww
                    break
            if w is None and original_adj is not None:
                for vv, ww in original_adj.get(u, []):
                    if vv == v:
                        w = ww
                        break
            if w is None:
                # 兜底用几何距离估算
                w = haversine_km((nodes[u]["lat"], nodes[u]["lng"]), (nodes[v]["lat"], nodes[v]["lng"]))
            new_adj[u].append((v, w))

    # 4) 检查连通性，若存在多个分量，使用 original_adj 中的最短跨分量边进行逐步连接
    comps = _connected_components(new_adj)
    if len(comps) > 1 and original_adj is not None:
        if verbose:
            print(f"[sparsify] 剪枝后有 {len(comps)} 个分量，尝试从 original_adj 中连通它们")
        # map node -> comp_id
        comp_id = {}
        for idx, comp in enumerate(comps):
            for node in comp:
                comp_id[node] = idx

        # 构造所有可能的跨分量边候选 (comp_u, comp_v, u, v, weight)
        candidates = []
        for u in range(n):
            for v, w in original_adj.get(u, []):
                cu, cv = comp_id.get(u), comp_id.get(v)
                if cu is None or cv is None or cu == cv:
                    continue
                # 只考虑将 preserve 节点保持互通：优先保留连接 preserve 所在分量
                candidates.append((w, u, v, cu, cv))
        # 按权重排序，贪心添加最小边，直到所有分量合并或 preserve 连通
        candidates.sort(key=lambda x: x[0])
        # 并查集（简单）
        parent = list(range(len(comps)))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra == rb:
                return False
            parent[rb] = ra
            return True

        # helper 判断 preserve 是否在同一连通集
        def preserve_connected():
            if not preserve:
                return False
            comp_idxs = set(find(comp_id[p]) for p in preserve if p in comp_id)
            return len(comp_idxs) <= 1

        for w, u, v, cu, cv in candidates:
            if union(cu, cv):
                # 在 new_adj 中加入该边（对称）
                new_adj[u].append((v, w))
                new_adj[v].append((u, w))
                if verbose:
                    print(f"[sparsify] addbridge {u}<->{v} w={w:.2f}")
                if preserve and preserve_connected():
                    break
        # 最后若仍有多个分量且未能连通 preserve，继续贪心直到连通所有分量
        roots = set(find(i) for i in range(len(comps)))
        if len(roots) > 1 and verbose:
            print(f"[sparsify] 剪枝后仍有 {len(roots)} 个分量（尝试全部连通）")
        # 若需要可继续添加更多候选（当前候选集已包含 original_adj 中所有边）

    return new_adj





def fully_connected_edges(points: List[Coord]) -> List[Edge]:
    """
    构造完全图的边列表，按距离升序排序。仅在小规模点集（例如 n <= 200）使用。
    points: List[Coord]       点列表 [(lat,lng), ...]
    """
    edges: List[Edge] = []
    n = len(points)
    for i in range(n):
        for j in range(i + 1, n):
            d = haversine_km(points[i], points[j])
            edges.append((i, j, d))
    edges.sort(key=lambda x: x[2])
    return edges


def dijkstra_len(n: int, adj: Dict[int, List[Tuple[int, float]]], s: int, t: int) -> float:
    import heapq
    dist = [float('inf')] * n
    dist[s] = 0.0
    pq = [(0.0, s)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:
            continue
        if u == t:
            return d
        for v, w in adj.get(u, []):
            nd = d + w
            if nd < dist[v]:
                dist[v] = nd
                heapq.heappush(pq, (nd, v))
    return float('inf')


def greedy_spanner(points: List[Coord], epsilon: float = 0.2) -> List[Edge]:
    """Greedy (1+ε)-spanner：按距离从短到长遍历边；
    若当前 spanner 中 u->v 最短路 > (1+ε)*直连距离，则添加该边。
    仅在小规模点集（例如 n <= 200）使用。
    points: List[Coord]       点列表 [(lat,lng), ...]
    epsilon: float = 0.2      伸展因子（越小越接近完全图，但边数越多）
    """
    edges = fully_connected_edges(points)
    n = len(points)
    adj: Dict[int, List[Tuple[int, float]]] = {i: [] for i in range(n)}
    sp: List[Edge] = []
    for u, v, d in edges:
        current = dijkstra_len(n, adj, u, v)
        if current > (1.0 + epsilon) * d:
            adj[u].append((v, d))
            adj[v].append((u, d))
            sp.append((u, v, d))
    return sp