# -*- coding: utf-8 -*-
from typing import Dict, List, Tuple, Optional
import heapq
from utils import Coord, haversine_km
from config import CHARGE_PERCENT_STEP, A_STAR_EPS_HEURISTIC

State = Tuple[int, int]  # (node_idx, soc_percent_discrete)


def energy_needed_percent(dist_km: float, battery_kwh: float, consumption_kwh_per_km: float) -> float:
    """计算行驶 dist_km 所需的电量百分比（相对于电池容量）。"""
    need_kwh = dist_km * consumption_kwh_per_km
    return need_kwh / battery_kwh * 100.0


def charge_time_minutes(delta_pct: float, battery_kwh: float, station_power_kw: float = 120.0) -> float:
    """计算充电 delta_pct 所需的时间（分钟）。"""
    if delta_pct <= 0:
        return 0.0
    need_kwh = (delta_pct / 100.0) * battery_kwh
    base = (need_kwh / max(10.0, station_power_kw)) * 60.0
    penalty = 0.04 * delta_pct  # 简单高SOC惩罚
    return base * (1.0 + penalty / 100.0)


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
    best: Dict[State, float] = {start: 0.0}
    prev: Dict[State, Tuple[State, str]] = {}

    while pq:
        g, (u, soc) = heapq.heappop(pq)
        if g > best.get((u, soc), float("inf")) + 1e-9:
            continue
        if u == end_idx:
            # 回溯路径
            path = []
            cur = (u, soc)
            while cur in prev:
                path.append((cur, prev[cur][1]))
                cur = prev[cur][0]
            path.append((cur, "start"))
            path.reverse()
            return {"total_time_min": g, "path": path}

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

