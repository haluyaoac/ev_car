from flask import Flask, request, render_template
import logging
from typing import List
from config import USE_BAIDU_POI, USE_BAIDU_DIS, CAR, USE_SPARSIFICATION, SPANNER_EPSILON, USE_CAR, QPS_MATRIX, AK2
from baidu_api import get_route_polyline, geocode
from baidu_api_impl import search_stations_along_route_start, get_distance_matrix_batched_async_start, get_route_polyline_start
from graph_builder import build_graph_with_endpoints2, sparsify_by_knn, greedy_spanner
import path_planner
from utils import geodesic_distance, haversine_km, midpoint, Coord
from db import session as db_session, crud as db_crud
from ak_manner import AK as AKClass
from save import print_ev_plan

app = Flask(__name__, static_folder="static", template_folder="templates")
logging.basicConfig(level=logging.INFO)
db_session.init_db(create_sample=False)
aks = [AKClass(item["ak"], item["limits"]) for item in QPS_MATRIX]

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/plan", methods=["POST"])
def plan():
    try:
        # --- 1. 获取表单数据 ---
        brand = request.form.get("brand", "").strip()
        start_soc = int(request.form.get("start_soc", "70"))
        origin = request.form.get("origin", "").strip() or "天津城建大学"
        destination = request.form.get("destination", "").strip() or "天津滨海国际机场"

        # --- 2. 获取车辆信息 ---
        if USE_CAR:
            with db_session.SessionLocal() as db:
                car_obj = None
                if brand:
                    car_obj = db_crud.get_car_by_brand(db, brand) or db_crud.get_car_by_name(db, brand)
                if not car_obj:
                    car_obj = db_crud.get_car_by_name(db, CAR.get("name")) or db_crud.get_default_car(db)
            car_used = {
                "name": car_obj.name if car_obj else CAR["name"],
                "battery_kwh": car_obj.battery_kwh if car_obj else CAR["battery_kwh"],
                "consumption_kwh_per_km": car_obj.consumption_kwh_per_km if car_obj else CAR["consumption_kwh_per_km"],
                "initial_soc_percent": car_obj.initial_soc_percent if car_obj else CAR["initial_soc_percent"],
                "avg_speed_kmph": car_obj.avg_speed_kmph if car_obj else CAR["avg_speed_kmph"],
            }
        else:
            car_used = CAR
        logging.info("使用车辆: %s", car_used)

        # --- 3. 地理编码（串行调用 dispatcher） ---
        logging.info("1.获取起点和终点坐标")
        start_coord = geocode(origin, aks[0])
        end_coord = geocode(destination, aks[0])
        logging.info("起点坐标: %s 终点坐标: %s", start_coord, end_coord)

        # --- 4. 充电站搜索（串行） ---
        logging.info("2.搜索充电站")
        stations = []
        if USE_BAIDU_POI:
            stations = search_stations_along_route_start(start_coord, end_coord, aks, query_limit = 10)

        else:
            with open("text\\stations_area.txt", "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split(",")
                    if len(parts) >= 4:
                        name, lat_s, lng_s, address = parts[:4]
                        lat, lng = float(lat_s), float(lng_s)
                        stations.append({"name": name, "lat": lat, "lng": lng, "address": address})
            # 确保起终点插入 nodes 列表
            stations.insert(0, {"name": "起点", "lat": start_coord[0], "lng": start_coord[1], "address": origin})
            stations.append({"name": "终点", "lat": end_coord[0], "lng": end_coord[1], "address": destination})

        # --- 5. 构图 / 稀疏化 ---
        logging.info("3.构建图结构")
        max_range_km = car_used["battery_kwh"] / car_used["consumption_kwh_per_km"]
        nodes = []
        adj = {}
        idx_origin = None
        idx_destination = None

        if USE_SPARSIFICATION == 1:
            points = [(n["lat"], n["lng"]) for n in stations]
            keep_pairs = greedy_spanner(points, SPANNER_EPSILON)
            adj_final = {i: [] for i in range(len(points))}
            to_lists = [[] for _ in range(len(points))]
            for (u, v, _) in keep_pairs:
                to_lists[u].append(v)
                to_lists[v].append(u)

            # 注意：get_distance_matrix_batched_async_start 可能是异步或同步，确保其返回值是可用的
            dist_matrix = get_distance_matrix_batched_async_start(stations, stations, to_lists, aks)
            nodes = stations
            adj = adj_final
            idx_origin = 0
            idx_destination = len(nodes) - 1
        else:
            if USE_BAIDU_DIS:
                nodes, adj, idx_origin, idx_destination = build_graph_with_endpoints2(
                    stations, origin=start_coord, destination=end_coord, max_range_km=max_range_km, aks=aks, prefilter_factor=1, verbose=True
                )
            else:
                nodes = []
                with open("text\\stations_circle.txt", "r", encoding="utf-8") as f:
                    for line in f:
                        parts = line.strip().split(",")
                        if len(parts) >= 4:
                            name, lat_s, lng_s, address = parts[:4]
                            lat, lng = float(lat_s), float(lng_s)
                            nodes.append({"name": name, "lat": lat, "lng": lng, "address": address})
                nodes.insert(0, {"name": "起点", "lat": start_coord[0], "lng": start_coord[1], "address": origin})
                nodes.append({"name": "终点", "lat": end_coord[0], "lng": end_coord[1], "address": destination})
                adj = {i: [] for i in range(len(nodes))}
                with open("text\\graph_edges.txt", "r", encoding="utf-8") as f:
                    for line in f:
                        if "->" in line:
                            parts = line.split("->")
                            u_name = parts[0].strip()
                            v_name, dist_part = parts[1].strip().split(":")
                            dist_km = float(dist_part.strip().split()[0])
                            u_idx = next((i for i, n in enumerate(nodes) if n["name"] == u_name), None)
                            v_idx = next((i for i, n in enumerate(nodes) if n["name"] == v_name), None)
                            if u_idx is not None and v_idx is not None:
                                adj[u_idx].append((v_idx, dist_km))
                                adj[v_idx].append((u_idx, dist_km))
                idx_origin = 0
                idx_destination = len(nodes) - 1

        if USE_SPARSIFICATION == -1:
            preserve = {idx_origin, idx_destination}
            adj = sparsify_by_knn(nodes, adj, original_adj=adj, k=8, preserve=preserve, verbose=False)

        # --- 6. 路径规划 ---
        points = [(n["lat"], n["lng"]) for n in nodes]
        res = path_planner.dijkstra_ev(points, adj, car_used, idx_origin, idx_destination, start_soc=start_soc)

        print_ev_plan(res)
        
        route_points = []
        if res:
            route_points = []
            cur_soc = None

            for step in res["path"]:
                if step["type"] == "drive":
                    # 出发节点
                    from_idx = step["from"]
                    to_idx = step["to"]
                    soc_before = step["soc_before_pct"]
                    soc_after = step["soc_after_pct"]

                    # 出发点
                    route_points.append({
                        "lat": float(points[from_idx][0]),
                        "lng": float(points[from_idx][1]),
                        "soc": float(soc_before),
                        "name": nodes[from_idx].get("name", f"Node {from_idx}")
                    })
                    # 到达点
                    route_points.append({
                        "lat": float(points[to_idx][0]),
                        "lng": float(points[to_idx][1]),
                        "soc": float(soc_after),
                        "name": nodes[to_idx].get("name", f"Node {to_idx}")
                    })
                    cur_soc = soc_after

                elif step["type"] == "charge":
                    u = step["at"]
                    soc_before = step["soc_before_pct"]
                    soc_after = step["soc_after_pct"]
                    route_points.append({
                        "lat": float(points[u][0]),
                        "lng": float(points[u][1]),
                        "soc": float(soc_after),
                        "name": f"{nodes[u].get('name', f'Node {u}')} 🔋充电({soc_before}→{soc_after}%)"
                    })
                    cur_soc = soc_after

            # 可选：去重（避免连续相同节点重复出现）
            deduped = []
            for p in route_points:
                if not deduped or (deduped[-1]["lat"], deduped[-1]["lng"]) != (p["lat"], p["lng"]):
                    deduped.append(p)
            route_points = deduped

        # --- 7. 拼接导航 polyline ---
        """
        full_polyline : 路线折线点列表
        
        """
        full_polyline = get_route_polyline_start(route_points, aks)

        return render_template(
            "result.html",
            polyline=full_polyline,
            nodes=route_points,
            stations=stations,

            ak=AK2 if isinstance(AK2, str) else str(AK2)
        )

    except Exception as e:
        logging.exception("处理 /plan 时出错")
        # 如果需要可以返回一个简单错误页面，方便调试
        return render_template("error.html", message=str(e)), 500



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

