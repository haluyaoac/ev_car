from flask import Flask, request, render_template
import logging
from config import USE_BAIDU_POI, USE_BAIDU_DIS, AK, CAR, USE_SPARSIFICATION, SPANNER_EPSILON
import baidu_api
import graph_builder
import path_planner
from utils import geodesic_distance, haversine_km, midpoint, polyline_sample
from db import session as db_session
from db import crud as db_crud

app = Flask(__name__, static_folder="static", template_folder="templates")
logging.basicConfig(level=logging.INFO)

# Ensure DB tables exist
db_session.init_db(create_sample=False)

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/plan", methods=["POST"])
def plan():
    brand = request.form.get("brand", "").strip()
    start_soc = int(request.form.get("start_soc", "70"))
    origin = request.form.get("origin", "").strip() or "天津城建大学"
    destination = request.form.get("destination", "").strip() or "天津滨海国际机场"

    # 读取车辆配置（优先品牌/名称）
    with db_session.SessionLocal() as db:
        car_obj = None
        if brand:
            car_obj = db_crud.get_car_by_brand(db, brand) or db_crud.get_car_by_name(db, brand)
        if not car_obj:
            car_obj = db_crud.get_car_by_name(db, CAR.get("name")) or db_crud.get_default_car(db)

    if car_obj:
        car_used = {
            "name": car_obj.name,
            "battery_kwh": car_obj.battery_kwh,
            "consumption_kwh_per_km": car_obj.consumption_kwh_per_km,
            "initial_soc_percent": car_obj.initial_soc_percent,
            "avg_speed_kmph": car_obj.avg_speed_kmph,
        }
    else:
        car_used = CAR

    logging.info("使用车辆: %s", car_used)

    # geocode为起点和终点进行地理编码
    start_coord = None
    end_coord = None
    try:
        start_coord = baidu_api.geocode(origin, AK)
        end_coord = baidu_api.geocode(destination, AK)
    except Exception as e:
        logging.warning("百度 geocode 失败: %s", e)

    
    if USE_BAIDU_POI:
    # 搜索充电站（优先百度 POI）
        stations = []
        endurance_km = car_used["battery_kwh"] / car_used["consumption_kwh_per_km"]
        try:
            mid = midpoint(start_coord[0], start_coord[1], end_coord[0], end_coord[1])
            dist = geodesic_distance(start_coord[0], start_coord[1], end_coord[0], end_coord[1])
            radius = dist / 2
            stations = baidu_api.search_stations_by_circle("充电站", mid, radius, AK)
        except Exception as e:
            logging.warning("百度 POI 搜索失败: %s", e)
    else:
    #从text文件读取充电站
        stations = []
        with open("stations_circle.txt", "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split(",")
                if len(parts) >= 4:
                    name = parts[0].strip()
                    lat = float(parts[1].strip())
                    lng = float(parts[2].strip())
                    address = parts[3].strip()
                    stations.append({"name": name, "lat": lat, "lng": lng, "address": address})
                    print(f"读取充电站: {name} at ({lat}, {lng})")
        stations.insert(0, {"name": "起点", "lat": start_coord[0], "lng": start_coord[1], "address": origin})
        stations.append({"name": "终点", "lat": end_coord[0], "lng": end_coord[1], "address": destination})


    # 构建图/稀疏化
    max_range_km = car_used["battery_kwh"] / car_used["consumption_kwh_per_km"]         #最大续航

    #稀疏化处理
    if USE_SPARSIFICATION == 1:
    #采用Greedy-Spanner稀疏化
        points = [(n["lat"], n["lng"]) for n in nodes]
        keep_pairs = graph_builder.greedy_spanner(points, SPANNER_EPSILON)
        adj_final = {i: [] for i in range(len(points))}
        for u, v, _ in keep_pairs:
            nav_km = baidu_api.get_route_distance(points[u], points[v])
            if nav_km is None:
                nav_km = haversine_km(points[u], points[v])
            if nav_km <= max_range_km:
                adj_final[u].append((v, nav_km))
                adj_final[v].append((u, nav_km))
    else : 
        if USE_BAIDU_DIS:
            nodes, adj, idx_origin, idx_destination = graph_builder.build_graph_with_endpoints(
                stations,
                origin=start_coord,
                destination=end_coord,
                max_range_km=max_range_km,
                use_baidu_route=USE_BAIDU_DIS,
                ak=AK,
                prefilter_factor=1.2,
                sleep_between_calls=1,
                verbose=True
            )
        else :
            #从文件读取边权
            nodes = []
            with open("stations_circle.txt", "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split(",")
                    if len(parts) >= 4:
                        name = parts[0].strip()
                        lat = float(parts[1].strip())
                        lng = float(parts[2].strip())
                        address = parts[3].strip()
                        nodes.append({"name": name, "lat": lat, "lng": lng, "address": address})
                        print(f"读取充电站: {name} at ({lat}, {lng})")
            nodes.insert(0, {"name": "起点", "lat": start_coord[0], "lng": start_coord[1], "address": origin})
            nodes.append({"name": "终点", "lat": end_coord[0], "lng": end_coord[1], "address": destination})
            adj = {i: [] for i in range(len(nodes))}
            with open("graph_edges.txt", "r", encoding="utf-8") as f:
                for line in f:
                    if "->" in line:
                        parts = line.split("->")
                        u_name = parts[0].strip()
                        rest = parts[1].strip().split(":")
                        v_name = rest[0].strip()
                        dist_km = float(rest[1].strip().split()[0])
                        u_idx = next((i for i, n in enumerate(nodes) if n["name"] == u_name), None)
                        v_idx = next((i for i, n in enumerate(nodes) if n["name"] == v_name), None)
                        if u_idx is not None and v_idx is not None:
                            adj[u_idx].append((v_idx, dist_km))
                            adj[v_idx].append((u_idx, dist_km))
            idx_origin = 0
            idx_destination = len(nodes) - 1
        if USE_SPARSIFICATION == -1:
            #采用KNN稀疏化
            final_adj = adj
            preserve = set()
            if idx_origin is not None: preserve.add(idx_origin)
            if idx_destination is not None: preserve.add(idx_destination)
            final_adj = graph_builder.sparsify_by_knn(nodes, adj, original_adj=adj or adj, k=8, preserve=preserve, verbose=False)

    

    # 路径规划
    points = [(n["lat"], n["lng"]) for n in nodes]
    res = path_planner.dijkstra_ev(points, adj, car_used, idx_origin, idx_destination, start_soc=start_soc,)

    # 提取路径节点信息（坐标 + SOC + 名称）
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
            print(f"  {nodes[idx]['name']} (SOC={soc}%) -> {action} {points[idx]}")
            #坐标点
    print(f"总耗时: {res['total_time_min']:.2f} 分钟")

    routes = []
    #调用api,获取具体路径信息
    coords = [(p["lat"], p["lng"]) for p in route_points]
    for i in range(len(coords)-1):
        segment = baidu_api.get_route_polyline(coords[i], coords[i+1], AK)
        if segment:
            routes.extend(segment)


    from baidu_api import get_route_polyline  # 你自己封装的API调用函数

    full_polyline = []

    for i in range(len(route_points) - 1):
        start = (route_points[i]["lat"], route_points[i]["lng"])
        end = (route_points[i+1]["lat"], route_points[i+1]["lng"])
        seg_polyline = get_route_polyline(start, end, ak=AK)
        if seg_polyline:
            # 避免重复首点
            if full_polyline and full_polyline[-1] == seg_polyline[0]:
                seg_polyline = seg_polyline[1:]
            full_polyline.extend(seg_polyline)

    # 把 full_polyline 传给模板
    return render_template("result.html", polyline=full_polyline, ak=AK)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)