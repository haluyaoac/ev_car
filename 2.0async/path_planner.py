# -*- coding: utf-8 -*-
from typing import Dict, List, Tuple, Optional
import heapq
from utils import Coord, haversine_km
from config import CHARGE_PERCENT_STEP, A_STAR_EPS_HEURISTIC, STATION_POWER_KW

State = Tuple[int, int]  # (node_idx, soc_percent_discrete)


def energy_needed_percent(dist_km: float, battery_kwh: float, consumption_kwh_per_km: float) -> float:
    """计算行驶 dist_km 所需的电量百分比（相对于电池容量）。
    consumption_kwh_per_km: 能耗 kWh/km
    """
    need_kwh = dist_km * consumption_kwh_per_km
    return need_kwh / battery_kwh * 100.0


def energy_needed_kwh(dist_km: float, consumption_kwh_per_km: float) -> float:
    """返回行驶 dist_km 所需能量，单位 kWh"""
    return dist_km * consumption_kwh_per_km


def charge_time_hours(delta_pct: float, battery_kwh: float, station_power_kw: float = STATION_POWER_KW) -> float:
    """
    计算充电 delta_pct 所需的时间（h）。
    station_power_kw: 充电桩功率（kW）
    """
    if delta_pct <= 0:
        return 0.0
    need_kwh = (delta_pct / 100.0) * battery_kwh
    base = (need_kwh / max(10.0, station_power_kw)) * 60.0
    penalty = 0.04 * delta_pct  # 简单高SOC惩罚
    return base * (1.0 + penalty / 100.0)

def dijkstra_ev(points: List[Coord],
                adj: Dict[int, List[Tuple[int, float]]],
                car: Dict[str, float],
                start_idx: int,
                end_idx: int,
                start_soc: int = 100,
                station_power_kw: float = 120.0) -> Optional[Dict[str, object]]:
    """
    Dijkstra 于 (节点, SOC%) 状态空间，返回包含详细步骤与统计的结果字典：
      {
        "total_time_min": ...,
        "total_driving_time_min": ...,
        "total_charging_time_min": ...,
        "total_energy_kwh_driving": ...,
        "total_energy_kwh_charged": ...,
        "path": [ { step dict }, ... ]   # 顺序从 start 到 goal
      }

    每一步的 step dict 示例（驾驶）:
      {
        "type": "drive",
        "from": u,
        "to": v,
        "distance_km": d_km,
        "time_min": drive_min,
        "energy_kwh": energy_kwh,
        "energy_pct": energy_pct,
        "soc_before_pct": soc_before,
        "soc_after_pct": soc_after
      }

    每一步的 step dict 示例（充电）:
      {
        "type": "charge",
        "at": u,
        "charged_pct": delta_pct,
        "charged_kwh": charged_kwh,
        "time_min": dt,
        "soc_before_pct": soc_before,
        "soc_after_pct": soc_after
      }
    """
    battery_kwh = float(car["battery_kwh"])
    cons = float(car["consumption_kwh_per_km"])
    vmax = max(30.0, float(car.get("avg_speed_kmph", 50.0)))  # 保底速度

    def norm_pct(p: float) -> int:
        """将百分比 p 限制在 [0,100] 并向下取整到 CHARGE_PERCENT_STEP 的步长（离散化）"""
        p = max(0.0, min(100.0, p))
        step = CHARGE_PERCENT_STEP
        # 向下取整到 step 的倍数
        return int((p // step) * step)

    start_soc = norm_pct(start_soc)
    start: State = (start_idx, start_soc)

    # 优先队列 (g, state)
    pq: List[Tuple[float, State]] = [(0.0, start)]
    # 最佳已知 g 值
    best: Dict[State, float] = {start: 0.0}
    # 前驱 state 与触发动作信息： prev[state] = (prev_state, action_dict)
    prev: Dict[State, Tuple[State, Dict]] = {}

    while pq:
        g, (u, soc) = heapq.heappop(pq)
        if g > best.get((u, soc), float("inf")) + 1e-9:
            continue

        # 目标测试：当到达目标节点（任意 SOC）即可回溯
        if u == end_idx:
            # 回溯并构建详细步骤（逆序）
            rev_steps = []
            cur = (u, soc)
            # 将终点本身作为结束状态（没有动作）——回溯直到 start
            while cur in prev:
                prev_state, action = prev[cur]
                # action 已经是字典，表示从 prev_state 到 cur 所做的动作
                rev_steps.append(action)
                cur = prev_state
            rev_steps.reverse()

            # 计算总体统计
            total_time = g
            total_driving_time = sum(s.get("time_min", 0.0) for s in rev_steps if s["type"] == "drive")
            total_charging_time = sum(s.get("time_min", 0.0) for s in rev_steps if s["type"] == "charge")
            total_energy_driving = sum(s.get("energy_kwh", 0.0) for s in rev_steps if s["type"] == "drive")
            total_energy_charged = sum(s.get("charged_kwh", 0.0) for s in rev_steps if s["type"] == "charge")

            return {
                "total_time_min": total_time,
                "total_driving_time_min": total_driving_time,
                "total_charging_time_min": total_charging_time,
                "total_energy_kwh_driving": total_energy_driving,
                "total_energy_kwh_charged": total_energy_charged,
                "path": rev_steps
            }

        # 驾驶扩展：尝试去相邻节点
        for v, d_km in adj.get(u, []):
            # 当前驱动需要的电量（% 和 kWh）
            need_pct = energy_needed_percent(d_km, battery_kwh, cons)
            need_kwh = energy_needed_kwh(d_km, cons)
            # 只有当当前 SOC 足够时才直接驾驶
            if soc + 1e-9 >= need_pct:
                drive_min = (d_km / vmax) * 60.0
                new_soc_f = max(0.0, soc - need_pct)
                new_soc = norm_pct(new_soc_f)
                ng = g + drive_min
                st = (v, new_soc)
                if ng + 1e-9 < best.get(st, float("inf")):
                    best[st] = ng
                    action = {
                        "type": "drive",
                        "from": u,
                        "to": v,
                        "distance_km": float(d_km),
                        "time_min": float(drive_min),
                        "energy_kwh": float(need_kwh),
                        "energy_pct": float(need_pct),
                        "soc_before_pct": int(soc),
                        "soc_after_pct": int(new_soc)
                    }
                    prev[st] = ((u, soc), action)
                    heapq.heappush(pq, (ng, st))

        # 充电扩展：如果 SOC < 100，枚举可充到的离散目标 SOC
        if soc < 100:
            # add 表示增加的百分比（按步长枚举到 100）
            # range 的上限写成 100 - soc + 1 以便包含恰好到 100 的情况
            for add in range(CHARGE_PERCENT_STEP, 100 - soc + 1, CHARGE_PERCENT_STEP):
                target = soc + add
                target_soc = norm_pct(target)
                # 实际增量（离散化后可能小于 add，因为 norm_pct 向下）
                delta_pct = target_soc - soc
                if delta_pct <= 0:
                    # 如果离散化后没有增长（应该很少发生），跳过
                    continue
                dt = charge_time_hours(delta_pct, battery_kwh, station_power_kw)
                ng = g + dt
                st = (u, target_soc)
                if ng + 1e-9 < best.get(st, float("inf")):
                    best[st] = ng
                    charged_kwh = (delta_pct / 100.0) * battery_kwh
                    action = {
                        "type": "charge",
                        "at": u,
                        "charged_pct": int(delta_pct),
                        "charged_kwh": float(charged_kwh),
                        "time_min": float(dt),
                        "soc_before_pct": int(soc),
                        "soc_after_pct": int(target_soc)
                    }
                    prev[st] = ((u, soc), action)
                    heapq.heappush(pq, (ng, st))

    # 未找到路径
    return None


