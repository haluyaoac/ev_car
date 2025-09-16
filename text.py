from baidu_api import geocode
from config import AK, CAR, USE_BAIDU_ROUTE
import graph_builder




# 示例百度地图 API Key
ak = AK
# 起点和终点
origin = '天津城建大学'
destination = '天津滨海国际机场'
# 地理编码（地址转坐标）
start_coord = geocode(origin, ak)
end_coord = geocode(destination, ak)
if not start_coord or not end_coord:
    print("地址解析失败，无法继续")
    exit()
#print(f"起点坐标: {start_coord}, 终点坐标: {end_coord}")

car_used = CAR
max_range_km = car_used["battery_kwh"] / car_used["consumption_kwh_per_km"]         #最大续航

# # #测试search_stations_by_circle--------------------------------------------------------------------
# # midpoint = midpoint(start_coord[0], start_coord[1], end_coord[0], end_coord[1])
# # radius = geodesic_distance(start_coord[0], start_coord[1], end_coord[0], end_coord[1]) / 2
# # stations_circle = search_stations_by_circle("充电站", midpoint, radius, ak)
# # print(f"圆形搜索找到 {len(stations_circle)} 个充电站")
# # #保存到本地text文件
# # with open("stations_circle.txt", "w", encoding="utf-8") as f:
# #     for station in stations_circle:
# #         f.write(f"{station['name']}, {station['lat']}, {station['lng']}, {station['address']}\n")
# # #画在地图上
# # map_circle = folium.Map(location=midpoint, zoom_start=12)
# # marker_cluster_circle = MarkerCluster().add_to(map_circle)
# # #-------------------------------------------------------------------------------------------------

# #测试search_stations_along_route-----------------------------------------------------------------
# """ route, route_start, route_end, route_name = get_route_polyline(start_coord, end_coord, ak)
# if not route:
#     print("获取路线失败，无法继续")
#     exit()
#     #保存到本地text文件
# with open("route.txt", "w", encoding="utf-8") as f:
#     #路段名
#     for i in range(len(route_start)):
#         for j in range(route_start[i], route_end[i]+1):
#             f.write(f"{route[j][0]}, {route[j][1]};")
#         f.write("\n") """

# # #从txet文件读取路线
# # route = []
# # with open("route.txt", "r", encoding="utf-8") as f:
# #     for line in f:
# #         points = line.strip().split(";")
# #         for point in points:
# #             if point:
# #                 lat, lng = map(float, point.split(","))
# #                 route.append((lat, lng))

# # print(f"路线点数: {len(route)}")
# # endurance_km =   CAR["max_range_km"] * 0.9  # 续航里程的90%作为搜索半径
# # stations_route = search_stations_along_route(route, endurance_km, "充电站", ak)
# # print(f"沿路线搜索找到 {len(stations_route)} 个充电站")
# # #保存到本地text文件
# # with open("stations_route.txt", "w", encoding="utf-8") as f:
# #     for station in stations_route:
# #         f.write(f"{station['name']}, {station['lat']}, {station['lng']}, {station['address']}\n")


#测试建图
#从txet文件读取充电站
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
stations.insert(0, {"name": "起点", "lat": start_coord[0], "lng": start_coord[1], "address": origin})
stations.append({"name": "终点", "lat": end_coord[0], "lng": end_coord[1], "address": destination})
print(f"充电站点数: {len(stations)}")


nodes, adj, idx_origin, idx_destination = graph_builder.build_graph_with_endpoints(
            stations,
            origin=start_coord,
            destination=end_coord,
            max_range_km=max_range_km,
            use_baidu_route=USE_BAIDU_ROUTE,
            ak=AK,
            prefilter_factor=1.2,
            sleep_between_calls=1,
            verbose=True
        )

#把边权保存到文件中
with open("graph_edges.txt", "w", encoding="utf-8") as f:
    for u in adj:
        for v, dist in adj[u]:
            f.write(f"{nodes[u]['name']} -> {nodes[v]['name']}: {dist:.2f} km\n")
            print(f"{nodes[u]['name']} -> {nodes[v]['name']}: {dist:.2f} km")
    

# # 建图
# max_range_km = CAR["battery_kwh"] / CAR["consumption_kwh_per_km"]         #最大续航

# nodes, adj, idx_origin, idx_destination = graph_builder.build_graph_with_endpoints2(
#                 stations,
#                 origin=start_coord,
#                 destination=end_coord,
#                 max_range_km=max_range_km,
#                 ak=AK,
#                 prefilter_factor=1.2,
#                 verbose=False
#             )
# #保存到本地text文件
# with open("graph_nodes.txt", "w", encoding="utf-8") as f:
#     for node in nodes:
#         f.write(f"{node['name']}, {node['lat']}, {node['lng']}, {node.get('address', '')}\n")
#         for adj_node, dist in adj.get(nodes.index(node), []):
#             f.write(f"  -> {nodes[adj_node]['name']} ({dist:.2f} km)\n")

# print(f"图节点数: {len(nodes)}")
# print(f"起点索引: {idx_origin}, 终点索引: {idx_destination}")
# #绘制简单的点和边的图


# # #以直线距离建图
# # # 2. 构造邻接表（直线距离）
# # car = {
# #     "battery_kwh": 60,  # 电池容量
# #     "consumption_kwh_per_km": 3,  # 每公里耗电
# #     "avg_speed_kmph": 40  # 平均速度
# # }
# # max_range_km = 20  # 设定续航阈值（公里），测试时可以设大一点保证连通
# # n = len(stations)
# # adj = {i: [] for i in range(n)}
# # for i in range(n):
# #     for j in range(i+1, n):
# #         d = haversine_km((stations[i]["lat"], stations[i]["lng"]),
# #                          (stations[j]["lat"], stations[j]["lng"]))
# #         if d <= max_range_km:
# #             adj[i].append((j, d))
# #             adj[j].append((i, d))


# # points = [(s["lat"], s["lng"]) for s in stations]
# # start_idx = 0
# # end_idx = n - 1
# # start_soc = 100

# # # 4. 跑 A* 路径规划
# # res = path_planner.dijkstra_ev(points, adj, car, start_idx, end_idx, start_soc=start_soc)

# # # 5. 输出结果
# # if res:
# #     print(f"总耗时: {res['total_time_min']:.2f} 分钟")
# #     print("路径节点:")
# #     for (state, action) in res["path"]:
# #         idx, soc = state
# #         print(f"  {stations[idx]['name']} (SOC={soc}%) -> {action}")
# # else:
# #     print("未找到可行路径")



