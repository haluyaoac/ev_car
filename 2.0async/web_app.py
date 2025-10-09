from flask import Flask, request, render_template
import logging
from typing import List
from config import USE_BAIDU_POI, USE_BAIDU_DIS, AK, CAR, USE_SPARSIFICATION, SPANNER_EPSILON, USE_CAR, search_way
from baidu_api import get_route_polyline, geocode, search_stations_by_circle, get_distance
from baidu_api_impl import search_stations_along_route
from graph_builder import build_graph_with_endpoints2, sparsify_by_knn, greedy_spanner
import path_planner
from utils import geodesic_distance, haversine_km, midpoint, Coord
from db import session as db_session, crud as db_crud

app = Flask(__name__, static_folder="static", template_folder="templates")
logging.basicConfig(level=logging.INFO)
db_session.init_db(create_sample=False)

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/plan", methods=["POST"])
def plan():
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
    start_coord = geocode(origin, AK)
    end_coord = geocode(destination, AK)

    if not start_coord or not end_coord:
        return render_template("result.html", polyline=[], nodes=[], stations=[], ak=AK)

    # --- 4. 充电站搜索（串行） ---
    stations = []
    if USE_BAIDU_POI:
        if search_way == "圆形":
            mid = midpoint(start_coord[0], start_coord[1], end_coord[0], end_coord[1])
            dist = geodesic_distance(start_coord[0], start_coord[1], end_coord[0], end_coord[1])
            radius = dist / 2
            stations = search_stations_by_circle("充电站", mid, radius, AK)
        elif search_way == "行政":
            stations = search_stations_along_route(start_coord, end_coord, AK, query_limit=100)
    else:
        with open("text\\stations_area.txt", "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split(",")
                if len(parts) >= 4:
                    name, lat_s, lng_s, address = parts[:4]
                    lat, lng = float(lat_s), float(lng_s)
                    stations.append({"name": name, "lat": lat, "lng": lng, "address": address})
        stations.insert(0, {"name": "起点", "lat": start_coord[0], "lng": start_coord[1], "address": origin})
        stations.append({"name": "终点", "lat": end_coord[0], "lng": end_coord[1], "address": destination})

    # 构图 / 稀疏化
    max_range_km = car_used["battery_kwh"] / car_used["consumption_kwh_per_km"]
    nodes = []
    adj = {}
    idx_origin = None
    idx_destination = None
    if USE_SPARSIFICATION == 1:
        points = [(n["lat"], n["lng"]) for n in stations]
        keep_pairs = greedy_spanner(points, SPANNER_EPSILON)
        adj_final = {i: [] for i in range(len(points))}
        for u, v, _ in keep_pairs:
            nav_km = get_distance(points[u], points[v], AK)
            if nav_km is None:
                nav_km = haversine_km(points[u], points[v])
            if nav_km <= max_range_km:
                adj_final[u].append((v, nav_km))
                adj_final[v].append((u, nav_km))
        nodes = stations
        adj = adj_final
        idx_origin = 0
        idx_destination = len(nodes) - 1
    else:
        if USE_BAIDU_DIS:
            nodes, adj, idx_origin, idx_destination = build_graph_with_endpoints2(
                stations, origin=start_coord, destination=end_coord, max_range_km=max_range_km, ak=AK, prefilter_factor=1, verbose=True
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

    route_points = []
    if res:
        for (state, action) in res["path"]:
            idx, soc = state
            route_points.append({
                "lat": points[idx][0],
                "lng": points[idx][1],
                "soc": soc,
                "name": nodes[idx].get("name", f"Node {idx}")
            })

    # --- 7. 拼接导航 polyline ---
    full_polyline: List[Coord] = []
    for i in range(len(route_points) - 1):
        start = (route_points[i]["lat"], route_points[i]["lng"])
        end = (route_points[i + 1]["lat"], route_points[i + 1]["lng"])
        route_data = get_route_polyline(start, end, ak=AK)
        if not route_data:
            continue
        seg_polyline = route_data["polyline"]
        if full_polyline and seg_polyline and full_polyline[-1] == seg_polyline[0]:
            seg_polyline = seg_polyline[1:]
        full_polyline.extend(seg_polyline)

    return render_template("result.html", polyline=full_polyline, nodes=nodes, stations=stations, ak=AK)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
