import asyncio
from baidu_api import geocode
from config import AK, CAR, USE_BAIDU_ROUTE
from baidu_api_impl import search_stations_along_route, search_stations_in_area



#展示到百度地图
import webbrowser
import urllib.parse
def open_in_baidu_map(origin, destination, stations):
    base_url = "https://api.map.baidu.com/direction"
    params = {
        "origin": origin,
        "destination": destination,
        "mode": "driving",
        "region": "天津",
        "output": "html",
        "src": "yourCompanyName|yourAppName"
    }
    url = f"{base_url}?{urllib.parse.urlencode(params)}"
    # 添加充电站标记
    for station in stations:
        lat = station.get("lat")
        lng = station.get("lng")
        if lat is None or lng is None:
            loc = station.get("location", {})
            lat = loc.get("lat")
            lng = loc.get("lng")
        if lat and lng:
            url += f"&markers={lat},{lng}"
    webbrowser.open(url)


async def main():
    origin = '天津城建大学'
    destination = '天津滨海国际机场'
    # 地理编码（地址转坐标）
    start_coord = await geocode(origin, AK)
    end_coord = await geocode(destination, AK)


    car_used = CAR
    max_range_km = car_used["battery_kwh"] / car_used["consumption_kwh_per_km"]         #最大续航

    stations = await search_stations_along_route(start_coord, end_coord, AK, 100)  # 充电站列表
    print(f"起点附近搜索到 {len(stations)} 个充电站")
    #保存到文件
    with open("text\\stations_area.txt", "w", encoding="utf-8") as f:
        for station in stations:
            lat = station.get("lat")
            lng = station.get("lng")
            if lat is None or lng is None:
                loc = station.get("location", {})
                lat = loc.get("lat")
                lng = loc.get("lng")
            f.write(f"{station.get('name','')},{lat},{lng},{station.get('address','')}\n")


    open_in_baidu_map(origin, destination, stations)


    from baidu_api import d
    await d.close()



if __name__ == "__main__":
    asyncio.run(main())



