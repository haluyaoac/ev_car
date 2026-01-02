import json
from typing import Any, Dict, Optional, List

#将充电站信息保存到本地文件
def save_stations_to_file(stations, filename="ev_car/text/stations.json"):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(stations, f, ensure_ascii=False, indent=4)

#将距离信息保存到本地文件
def save_distance_matrix_to_file(distance_matrix, filename="ev_car/text/edges.json"):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(distance_matrix, f, ensure_ascii=False, indent=4)

#保存图的邻接表信息到本地文件
def save_graph_adjacency_to_file(adj, nodes, filename="ev_car/text/adj.txt"):
    with open(filename, "w", encoding="utf-8") as f:
        for u_idx, neighbors in adj.items():
            u_name = nodes[u_idx].get("name", f"Node {u_idx}")
            neighbor_names = [nodes[v_idx].get("name", f"Node {v_idx}") for v_idx, _ in neighbors]
            f.write(f"{u_name}: {', '.join(neighbor_names)}\n")
#把逆地理编码结果保存到本地文件
def save_reverse_geocoding_results_to_file(results, filename="ev_car/text/regeo.json"):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=4)

#起点到终点的路径保存到本地文件
def save_path_to_file(path, filename="ev_car/text/path.json"):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(path, f, ensure_ascii=False, indent=4)

#最后结果路径保存到本地文件
def save_final_path_to_file(final_path, filename="ev_car/text/final_path.json"):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(final_path, f, ensure_ascii=False, indent=4)

def print_ev_plan(res: Optional[Dict[str, object]]):
    """打印电动车路径规划结果（行驶+充电过程可视化）"""
    if not res:
        print("⚠️ 未找到可行路径")
        return

    print("🚗 电动车路径规划结果")
    print("=" * 80)
    print(f"总用时: {res['total_time_min']:.1f} 小时")
    print(f"  ├─ 行驶时间: {res['total_driving_time_min']:.1f} 小时")
    print(f"  ├─ 充电时间: {res['total_charging_time_min']:.1f} 小时")
    print(f"总能耗: {res['total_energy_kwh_driving']:.2f} kWh  "
          f"总充电量: {res['total_energy_kwh_charged']:.2f} kWh")
    print("=" * 80)
    print(f"{'步骤':<4} {'类型':<8} {'节点/段':<18} {'时间(h)':>10} "
          f"{'SOC变化':>12} {'能量(kWh)':>12} {'距离(km)':>10}")
    print("-" * 80)

    for i, step in enumerate(res["path"], start=1):
        if step["type"] == "drive":
            print(f"{i:<4} drive    "
                  f"{step['from']}→{step['to']:<12} "
                  f"{step['time_min']:>10.1f} "
                  f"{step['soc_before_pct']:>3}%→{step['soc_after_pct']:<3}% "
                  f"{-step['energy_kwh']:>10.2f} "
                  f"{step['distance_km']:>10.1f}")
        elif step["type"] == "charge":
            print(f"{i:<4} charge   "
                  f"@{step['at']:<14} "
                  f"{step['time_min']:>10.1f} "
                  f"{step['soc_before_pct']:>3}%→{step['soc_after_pct']:<3}% "
                  f"{'+' + str(round(step['charged_kwh'],2)):>10} "
                  f"{'-':>10}")
    print("=" * 80)
    print("✅ 路径规划流程打印完毕\n")
