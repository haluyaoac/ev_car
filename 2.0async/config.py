# -*- coding: utf-8 -*-
"""全局配置：百度 AK、车辆参数、算法参数"""
USE_BAIDU_DIS = True            # True 用百度获取距离；False 用文件
USE_BAIDU_ROUTE = True          # True 用百度路线规划距离；False 用直线距离
USE_BAIDU_POI = True           # True 用百度周边 POI 搜索充电站；False 用文件
USE_CAR = True                  # True 从数据库获取车辆参数；False 用默认汽车

# ===== 车辆参数 =====
CAR = {
    "name": "EV-Demo",
    "battery_kwh": 60.0,              # 电池容量 kWh
    "consumption_kwh_per_km": 0.18,   # 能耗 kWh/km（越小越省）
    "initial_soc_percent": 70,        # 起始电量 %
    "avg_speed_kmph": 80.0,           # 平均时速 km/h（用于时间估计）
}
CAR["max_range_km"] = CAR["battery_kwh"] / CAR["consumption_kwh_per_km"]

# ===== 充电桩参数 =====
STATION_POWER_KW = 120.0          # 充电桩功率 kW（用于充电时间估计）

# ===== 筛选与图参数 =====


# ===== A* / 状态空间 =====
CHARGE_PERCENT_STEP = 5      # 电量离散步长（%）。减小更精细，状态更多
A_STAR_EPS_HEURISTIC = 1.0   # 启发式放大系数（>1 更激进，剪枝更多）

# ===== Spanner 稀疏化 =====
USE_SPARSIFICATION = 0       # 1:启用 Greedy-Spanner 稀疏化, -1: 启用 KNN 稀疏化, 0:不稀疏化
SPANNER_EPSILON = 0.2        # (1+ε) 近似阈值；越小越保边

# ===== 其他 =====
RANDOM_SEED = 42   # 随机种子

# ===== 数据库配置 =====
DB_URL = "mysql+pymysql://root:123456@localhost:3306/ev_car?charset=utf8mb4"

# ===== search_way参数 =====
search_way = "行政"     # "圆形" 或 "行政"

# ===== qps_manner =====
AK2 = "fYcVa9810AKiixV8SR9MCGhvgXbkoBpU" #用于wbj地图
OPEN = False               # True 启用限频；False 不限频
MAX_RETRIES = 30
QPS_MATRIX = [
    {
    "ak": "UIAbWq8rLfKdrUx5I76YJLX6aRsXGUE3",
    "id": 1,
    "limits": {
        "place_search": 3,    # 充电站搜索
        "geocoding": 3,       # 地理编码
        "driving_plan": 3,    # 路线规划
        "distance_matrix": 1, # 批量算路
        "distance_get": 3,    # 批量算路（一个一个版本）
        "regeo": 3            # 逆地理编码
    }},
    {
    "ak": "AboK834ycbPJMxlXUly2IPylEJsMRUO7",
    "id": 2,
    "limits": {
        "place_search": 3,    # 充电站搜索
        "geocoding": 3,       # 地理编码
        "driving_plan": 3,    # 路线规划
        "distance_matrix": 1, # 批量算路
        "distance_get": 3,    # 批量算路（一个一个版本）
        "regeo": 3            # 逆地理编码
    }},
    {
    "ak": "tX0XhprsWsWrbJddiZvsIRhoK6d0MwHH",
    "id": 3,
    "limits": {
        "place_search": 3,    # 充电站搜索
        "geocoding": 3,       # 地理编码
        "driving_plan": 3,    # 路线规划
        "distance_matrix": 1, # 批量算路
        "distance_get": 3,    # 批量算路（一个一个版本）
        "regeo": 3            # 逆地理编码
    }},
    {
    "ak": "1hFaU1KDTi6Fckv5IaRpeX1tOL73dU0p",
    "id": 5,
    "limits": {
        "place_search": 3,    # 充电站搜索
        "geocoding": 3,       # 地理编码
        "driving_plan": 3,    # 路线规划
        "distance_matrix": 1, # 批量算路
        "distance_get": 3,    # 批量算路（一个一个版本）
        "regeo": 3            # 逆地理编码
    }},
    {
    "ak": "MRf84TKnZIbuXG8Y4rA6VqMBnsVlKvsw",
    "id": 6,
    "limits": {
        "place_search": 3,    # 充电站搜索
        "geocoding": 3,       # 地理编码
        "driving_plan": 3,    # 路线规划
        "distance_matrix": 1, # 批量算路
        "distance_get": 3,    # 批量算路（一个一个版本）
        "regeo": 3            # 逆地理编码
    }},
    {
    "ak": "peKmsd7clAoMUU5k0dkYqFK6JxPKE7cA",
    "id": 7,
    "limits": {
        "place_search": 3,    # 充电站搜索
        "geocoding": 3,       # 地理编码
        "driving_plan": 3,    # 路线规划
        "distance_matrix": 1, # 批量算路
        "distance_get": 3,    # 批量算路（一个一个版本）
        "regeo": 3            # 逆地理编码
    }},
    {
    "ak": "Syzgvy929Dbw1lRdzwMzFiKcMN6P6ELz",
    "id": 7,
    "limits": {
        "place_search": 3,    # 充电站搜索
        "geocoding": 3,       # 地理编码
        "driving_plan": 3,    # 路线规划
        "distance_matrix": 1, # 批量算路
        "distance_get": 3,    # 批量算路（一个一个版本）
        "regeo": 3            # 逆地理编码
    }}
]


