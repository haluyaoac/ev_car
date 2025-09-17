from baidu_api import geocode, get_route_distance, get_route_polyline, search_charging_stations_near
from config import AK, CAR, USE_BAIDU_ROUTE
from graph_builder import build_graph_with_endpoints2
from baidu_api_impl import get_distance_matrix_batched, get_distance_matrix, search_stations_along_route



origin = '天津城建大学'
destination = '天津滨海国际机场'
# 地理编码（地址转坐标）
start_coord = geocode(origin, AK)
end_coord = geocode(destination, AK)


car_used = CAR
max_range_km = car_used["battery_kwh"] / car_used["consumption_kwh_per_km"]         #最大续航

stations = []                                                                       # 充电站列表


# 从文件读取充电站
# stations = []
# with open("text\\stations_circle.txt", "r", encoding="utf-8") as f:
#     for line in f:
#         parts = line.strip().split(",")
#         if len(parts) >= 4:
#             name = parts[0].strip()
#             lat = float(parts[1].strip())
#             lng = float(parts[2].strip())
#             address = parts[3].strip()
#             stations.append({"name": name, "lat": lat, "lng": lng, "address": address})
#             print(f"读取充电站: {name} at ({lat}, {lng})")
# stations.insert(0, {"name": "起点", "lat": start_coord[0], "lng": start_coord[1], "address": origin})
# stations.append({"name": "终点", "lat": end_coord[0], "lng": end_coord[1], "address": destination})
# print(f"总充电站数: {len(stations)}")

# # 测试批量算路（通过批量算路构建图）
# graph = build_graph_with_endpoints2(stations, origin=start_coord, destination=end_coord, max_range_km=max_range_km, ak=AK)
# print(f"图节点数: {len(graph)}, 边数: {sum(len(v) for v in graph.adj.values()) // 2}")            
# stations.append({"name": "终点", "lat": end_coord[0], "lng": end_coord[1], "address": destination})
# print(f"总充电站数: {len(stations)}")

# 测试沿路搜索

route_all = get_route_polyline(start_coord, end_coord, ak=AK)
route_points = route_all["polyline"]

stations = search_stations_along_route(route_points=route_points, ak=AK)
print(f"沿路搜索充电站数: {len(stations)}")
# 保存结果
with open("text\\stations_along_route.txt", "w", encoding="utf-8") as f:
    for station in stations:
        lat = station.get("lat")
        lng = station.get("lng")
        if lat is None or lng is None:
            loc = station.get("location", {})
            lat = loc.get("lat")
            lng = loc.get("lng")
        f.write(f"{station.get('name','')},{lat},{lng},{station.get('address','')}\n")


#展示到地图
import webbrowser
import urllib.parse

map_url = "https://www.google.com/maps/dir/?api=1"
waypoints = []

for station in stations:
    waypoints.append(f"{station['lat']},{station['lng']}")

# 添加起点和终点
waypoints.insert(0, f"{start_coord[0]},{start_coord[1]}")
waypoints.append(f"{end_coord[0]},{end_coord[1]}")

# 构建完整的URL
full_url = f"{map_url}&origin={waypoints[0]}&destination={waypoints[-1]}&waypoints={'|'.join(waypoints[1:-1])}"
webbrowser.open(full_url)
print("打开地图:", full_url)
