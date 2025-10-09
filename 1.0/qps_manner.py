# qps_manner.py
import time
import random
import threading
import requests
from typing import Optional, Dict, Any
from config import QPS_MATRIX, MAX_RETRIES


class BaiduAPIError(Exception):
    """百度 API 返回的业务错误"""
    def __init__(self, status: int, message: str, response: dict):
        self.status = status
        self.message = message
        self.response = response
        super().__init__(f"[BaiduAPIError] status={status}, message={message}")


class MultiAKDispatcher:
    """
    多 AK × 多接口类型的限流调度器（线程安全）
    """
    def __init__(self, qps_matrix: Dict[str, Dict[str, int]]):
        """
        qps_matrix 示例：
        {
            "AK_1": {"place_search": 10, "geocoding": 5},
            "AK_2": {"place_search": 5, "geocoding": 2},
        }
        """
        self.qps_matrix = qps_matrix
        self.timestamps: Dict[str, Dict[str, list]] = {
            ak: {api: [] for api in apis} for ak, apis in qps_matrix.items()
        }
        self.locks = {
            ak: {api: threading.Lock() for api in apis} for ak, apis in qps_matrix.items()
        }

    def _can_use(self, ak: str, api: str) -> bool:
        """判断该 ak/api 是否在 QPS 限制内"""
        now = time.time()
        timestamps = [t for t in self.timestamps[ak][api] if now - t < 1]
        self.timestamps[ak][api] = timestamps
        return len(timestamps) < self.qps_matrix[ak][api]

    def acquire_slot(self, api: str) -> str:
        """分配一个可用 ak；若全部超速则等待"""
        while True:
            candidates = [ak for ak in self.qps_matrix if api in self.qps_matrix[ak]]
            random.shuffle(candidates)
            for ak in candidates:
                with self.locks[ak][api]:
                    if self._can_use(ak, api):
                        self.timestamps[ak][api].append(time.time())
                        return ak
            time.sleep(0.1)  # 所有都满速 -> 等待下一窗口


# ------------------- 全局 Dispatcher 实例 -------------------
dispatcher = MultiAKDispatcher(QPS_MATRIX)


# ------------------- fetch 核心逻辑 -------------------
def fetch(url: str, params: Optional[Dict[str, Any]] = None, api_name: str = "default", **kwargs) -> Any:
    ak = dispatcher.acquire_slot(api_name)
    params = params or {}
    params["ak"] = ak

    resp = requests.get(url, params=params, **kwargs)
    resp.raise_for_status()
    data = resp.json()

    # 检查百度 API 状态码
    if isinstance(data, dict) and "status" in data and data["status"] != 0:
        raise BaiduAPIError(
            status=data["status"],
            message=data.get("message", "Unknown error"),
            response=data
        )

    data["_ak_used"] = ak
    data["_api_name"] = api_name
    return data


def fetch_json(url: str, params: Dict[str, Any], api_name: str):
    """带自动重试"""
    retries = 0
    while retries < MAX_RETRIES:
        try:
            return fetch(url, params=params, api_name=api_name, timeout=10)
        except BaiduAPIError as e:
            if e.status in (302, 301, 4, 5):
                print(f"[Error] 百度 API 限额或拒绝: {e.message}")
                raise e
            print(f"[Error] {e.status}, {e.message}，重试中...")
            time.sleep(1)
        except requests.RequestException as e:
            print(f"[HTTP Error] {e}，重试中...")
            time.sleep(1)
        retries += 1
    raise RuntimeError("请求多次失败，放弃")
