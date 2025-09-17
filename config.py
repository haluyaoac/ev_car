# -*- coding: utf-8 -*-
"""全局配置：百度 AK、车辆参数、算法参数"""

# ===== 百度地图 =====
AK = "UIAbWq8rLfKdrUx5I76YJLX6aRsXGUE3"
AK2 = "fYcVa9810AKiixV8SR9MCGhvgXbkoBpU" #用于wbj地图
USE_BAIDU_DIS = False            # True 用百度获取距离；False 用文件
USE_BAIDU_ROUTE = True          # True 用百度路线规划距离；False 用直线距离
USE_BAIDU_POI = False             # True 用百度周边 POI 搜索充电站；False 用文件
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
# ...existing code..."   # 相对路径 SQLite 数据库文件



# ===== search_by_search参数 =====
circle_num = 8        # 圆周采样点数
circle_r = 0.05      # 圆半径，单位：度（约5公里）


