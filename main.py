# -*- coding: utf-8 -*-
import os
import logging
import sys
import config
import baidu_api
import mock_baidu_api
import graph_builder
import path_planner
from utils import polyline_sample, midpoint, geodesic_distance
from db import session as db_session
from db import crud as db_crud

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def main():
    db_session.init_db(create_sample=False)

    # 输入汽车品牌或名称搜索
    brand = "Tesla"
    
    # 先尝试从 DB 读取指定品牌 / 名称；回退到 config.CAR
    with db_session.SessionLocal() as db:
        if brand:
            car_obj = db_crud.get_car_by_brand(db, brand) or db_crud.get_car_by_name(db, brand)
        else:
            car_obj = db_crud.get_car_by_name(db, config.CAR.get("name")) or db_crud.get_default_car(db)

    if car_obj:
        car_used = {
            "name": car_obj.name,
            "battery_kwh": car_obj.battery_kwh,
            "consumption_kwh_per_km": car_obj.consumption_kwh_per_km,
            "initial_soc_percent": car_obj.initial_soc_percent,
            "avg_speed_kmph": car_obj.avg_speed_kmph,
        }
        logging.info("从数据库加载车辆: %s (brand=%s model=%s)", car_obj.name, car_obj.brand, car_obj.model)
    else:
        car_used = config.CAR
        logging.info("未从数据库加载到车辆，使用 config.CAR")
    
    #输出车辆参数
    logging.info("车辆参数: %s", car_used)
    endurance_km = car_used["battery_kwh"] / car_used["consumption_kwh_per_km"]

    # 可定制：从命令行读取起终点地址（可选）
    origin_addr = "天津城建大学"
    dest_addr = "天津滨海国际机场"
    if len(sys.argv) >= 3:
        origin_addr = sys.argv[1]
        dest_addr = sys.argv[2]

    logging.info("配置: USE_BAIDU_ROUTE=%s USE_BAIDU_POI=%s AK=%s",
                 config.USE_BAIDU_ROUTE, config.USE_BAIDU_POI, bool(config.AK))

    # 1) 尝试地址解析 -> 坐标
    start_coord = None
    end_coord = None
    if config.USE_BAIDU_ROUTE and config.AK:
        try:
            logging.info("尝试使用百度 geocode 解析地址：%s -> %s", origin_addr, dest_addr)
            start_coord = baidu_api.geocode(origin_addr, config.AK)
            end_coord = baidu_api.geocode(dest_addr, config.AK)
        except Exception as e:
            logging.warning("调用百度 geocode 异常：%s", e)
    if not start_coord or not end_coord:
        # 回退：使用简单默认坐标或通过 mock route 生成
        logging.warning("Geocode 失败或未启用百度，使用示例坐标并将使用 mock 路线")
        start_coord = (39.085933879314, 117.26557056154)
        end_coord = (39.101173180572, 117.10191852136)

    logging.info("起点坐标: %s, 终点坐标: %s", start_coord, end_coord)

    # 2) 获取路线折线（优先百度 route，否则 mock）
    route = None
    if config.USE_BAIDU_ROUTE and config.AK:
        try:
            route = baidu_api.get_route_polyline(start_coord, end_coord, config.AK)
            logging.info("百度路线点数: %s", len(route) if route else "None")
        except Exception as e:
            logging.warning("调用百度路线失败：%s", e)
            route = None

    if not route:
        logging.info("使用 mock 生成路线")
        route = mock_baidu_api.get_route_polyline_mock(start_coord, end_coord, config.AK)
        logging.info("mock 路线点数: %s", len(route) if route else "None")

    # 采样以控制后续搜索量
    sampled = polyline_sample(route, max(1, config.ROUTE_SAMPLE_EVERY))
    logging.info("原始路线点 %d，采样后 %d", len(route), len(sampled))

    # 3) 搜索充电站（若有百度 POI 且启用则走网络，否则用 mock）
    stations = []
    if config.USE_BAIDU_POI and config.AK:
        if config.SEACHER_BY_CIRCLE:
            mid = midpoint(start_coord[0], start_coord[1], end_coord[0], end_coord[1])
            dist = geodesic_distance(start_coord[0], start_coord[1], end_coord[0], end_coord[1])
            radius = dist/2
            logging.info("使用百度按点圆形搜索充电站（buffer_km=%s）", radius)
            stations = baidu_api.search_stations_by_circle("充电站", mid, radius, config.AK)
        else:
            logging.info("使用百度按路段搜索充电站（buffer_km=%s）", endurance_km)
            stations = baidu_api.search_stations_along_route(route, endurance_km, "充电站", config.AK)
    else:
        logging.info("使用 mock 在采样点附近生成充电站")
        seen = set()
        for lat, lng in sampled:
            res = mock_baidu_api.poi_charging_near_paginated(lat, lng, config.AK, radius_m=int(endurance_km*1000),
                                                            max_results=config.RANDOM_STATIONS_PER_SAMPLE, page_size=20)
            for s in res:
                uid = s.get("uid") or f"{s['lat']:.6f},{s['lng']:.6f}"
                if uid in seen:
                    continue
                seen.add(uid)
                stations.append(s)
        logging.info("mock 生成充电站数: %d", len(stations))

    logging.info("共找到 %d 个站点（去重后）", len(stations))

    # 4) 构建图（站点 + 起终点）

    max_range_km = car_used["battery_kwh"] / car_used["consumption_kwh_per_km"]
    logging.info("构建图（max_range_km=%.1f km）", max_range_km)
    # ...existing code...
    nodes, adj, idx_origin, idx_destination = graph_builder.build_graph_with_endpoints(
        stations,
        origin=start_coord,
        destination=end_coord,
        max_range_km=max_range_km,
        use_baidu_route=config.USE_BAIDU_ROUTE,
        ak=config.AK,
        prefilter_factor=1.2,
        sleep_between_calls=0.03,
        verbose=True
    )
    n_nodes = len(nodes)
    edge_count = sum(len(ne) for ne in adj.values()) // 2
    logging.info("图节点数=%d, 边数=%d, 起点索引=%s, 终点索引=%s", n_nodes, edge_count, idx_origin, idx_destination)

    # 5) 可选稀疏化
    final_adj = adj
    if config.USE_SPANNER:
        logging.info("进行稀疏化（knn）")
        preserve = set()
        if idx_origin is not None:
            preserve.add(idx_origin)
        if idx_destination is not None:
            preserve.add(idx_destination)
        final_adj = graph_builder.sparsify_graph(nodes, adj, original_adj=adj, method="knn",
                                                k=8, preserve=preserve, verbose=True)
        edge_count2 = sum(len(ne) for ne in final_adj.values()) // 2
        logging.info("稀疏化后边数=%d", edge_count2)

    # 6) 路径规划 A*
    logging.info("开始 A* 搜索（初始 SOC=%s%%）", config.CAR["initial_soc_percent"])
    points = [(n["lat"], n["lng"]) for n in nodes]
    try:
        res = path_planner.a_star_ev(points, final_adj, config.CAR, idx_origin, idx_destination,
                                     start_soc=config.CAR["initial_soc_percent"])
    except Exception as e:
        logging.exception("调用 A* 失败: %s", e)
        res = None

    if not res:
        logging.warning("未找到可行路径")
    else:
        logging.info("搜索完成：总耗时(分钟)=%.2f", res["total_time_min"])
        logging.info("路径步骤数=%d", len(res["path"]))
        for st, action in res["path"]:
            logging.info(" 状态 %s -> 动作: %s", st, action)

    # 7) 可选：生成 folium 地图（若安装 folium）
    try:
        import folium
        from folium.plugins import MarkerCluster
        mcenter = route[len(route)//2]
        m = folium.Map(location=mcenter, zoom_start=12)
        folium.PolyLine(route, color="blue", weight=4, opacity=0.7).add_to(m)
        mc = MarkerCluster().add_to(m)
        for s in stations:
            folium.Marker(location=(s["lat"], s["lng"]), popup=s.get("name", ""), icon=folium.Icon(color="green", icon="bolt", prefix="fa")).add_to(mc)
        out = "charging_map_test.html"
        m.save(out)
        logging.info("已生成地图文件: %s", out)
    except Exception as e:
        logging.info("未生成地图（缺少 folium 或出错）：%s", e)



if __name__ == "__main__":
    main()
# ...existing code...


