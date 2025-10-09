import asyncio
import aiohttp
import time
import random
import atexit
from typing import Dict, Any, List, Optional
from config import QPS_MATRIX, MAX_RETRIES


# ---------------------------
# 单个 AK 的 QPS 控制器
# ---------------------------
class AKWorker:
    def __init__(self, ak: str, qps_limit: Dict[str, int]):
        """
        ak: 百度地图 AK
        qps_limit: {api_type: qps}
        """
        self.ak = ak
        self.qps_limit = qps_limit
        self._last_requests: Dict[str, List[float]] = {api: [] for api in qps_limit}
        self._lock = asyncio.Lock()

    async def throttle(self, api_type: str):
        """限制单个 AK 在某种 API 类型下的请求频率"""
        if api_type not in self.qps_limit:
            self.qps_limit[api_type] = 3
            self._last_requests[api_type] = []

        max_qps = self.qps_limit[api_type]
        async with self._lock:
            now = time.time()
            records = self._last_requests[api_type]
            # 清理超过 1 秒的旧请求
            self._last_requests[api_type] = [t for t in records if now - t < 1]
            if len(self._last_requests[api_type]) >= max_qps:
                sleep_time = 1 - (now - self._last_requests[api_type][0])
                await asyncio.sleep(max(sleep_time, 0))
            self._last_requests[api_type].append(time.time())

    async def fetch(
        self,
        session: aiohttp.ClientSession,
        api_type: str,
        url: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        异步发送请求，带自动重试
        - max_retries: 最大重试次数
        """
        await self.throttle(api_type)
        params["ak"] = self.ak

        last_err = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with session.get(url, params=params, timeout=10) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    # 百度 API 的业务错误码处理
                    if isinstance(data, dict) and data.get("status", 0) != 0:
                        raise ValueError(f"Baidu API Error {data.get('status')}: {data.get('message')}")
                    return data
            except Exception as e:
                last_err = e
                # 指数退避 + 随机抖动
                delay = (2 ** (attempt - 1)) * 0.5 + random.uniform(0, 0.3)
                print(f"[WARN] {self.ak} 第 {attempt}/{MAX_RETRIES} 次请求失败 ({e})，{delay:.2f}s 后重试...")
                await asyncio.sleep(delay)

        # 所有重试都失败
        return {
            "status": -1,
            "error": str(last_err),
            "ak": self.ak,
            "url": url,
            "params": params,
            "retries": MAX_RETRIES,
        }


# ---------------------------
# 多 AK 调度器
# ---------------------------
class MultiAKDispatcher:
    def __init__(self, qps_matrix: Dict[str, Dict[str, int]]):
        """
        qps_matrix: {ak1: {api_type: qps, ...}, ak2: {...}}
        """
        self.workers = [AKWorker(ak, qps) for ak, qps in qps_matrix.items()]
        self._session: Optional[aiohttp.ClientSession] = None

    async def start(self):
        """初始化 aiohttp 连接池"""
        if self._session is None:
            connector = aiohttp.TCPConnector(limit=100)
            self._session = aiohttp.ClientSession(connector=connector)

    async def close(self):
        """关闭 aiohttp 会话"""
        if self._session:
            await self._session.close()
            self._session = None

    def _pick_worker(self, api_type: str) -> AKWorker:
        """选择当前最空闲的 AK"""
        now = time.time()
        candidates = []
        for w in self.workers:
            records = w._last_requests.get(api_type, [])
            active = len([t for t in records if now - t < 1])
            candidates.append((w, active))
        random.shuffle(candidates)
        return min(candidates, key=lambda x: x[1])[0]

    async def fetch_json_async(
        self,
        api_type: str,
        url: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        worker = self._pick_worker(api_type)
        return await worker.fetch(self._session, api_type, url, params)

    async def gather_json_async(
        self,
        api_type: str,
        tasks: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """批量并发请求"""
        results = await asyncio.gather(
            *(self.fetch_json_async(api_type, t["url"], t["params"]) for t in tasks),
            return_exceptions=True,
        )
        clean_results = []
        for r in results:
            if isinstance(r, Exception):
                clean_results.append({"status": -1, "error": str(r)})
            else:
                clean_results.append(r)
        return clean_results


# ---------------------------
# 单例 Dispatcher + 对外接口
# ---------------------------
DISPATCHER: Optional[MultiAKDispatcher] = None


async def _ensure_dispatcher() -> MultiAKDispatcher:
    """懒加载 dispatcher 实例"""
    global DISPATCHER
    if DISPATCHER is None:
        DISPATCHER = MultiAKDispatcher(QPS_MATRIX)
        await DISPATCHER.start()
    return DISPATCHER


async def fetch_json_async(
    api_type: str, url: str, params: Dict[str, Any], max_retries: int = 3
) -> Dict[str, Any]:
    """异步接口"""
    dispatcher = await _ensure_dispatcher()
    return await dispatcher.fetch_json_async(api_type, url, params, max_retries=max_retries)


def fetch_json(api_type: str, url: str, params: Dict[str, Any], max_retries: int = 3) -> Dict[str, Any]:
    """
    同步封装（兼容 Flask / CLI 调用）
    自动判断是否存在事件循环
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        return loop.run_until_complete(fetch_json_async(api_type, url, params, max_retries))
    else:
        return asyncio.run(fetch_json_async(api_type, url, params, max_retries))


# ---------------------------
# 程序退出时清理资源
# ---------------------------
@atexit.register
def _cleanup_dispatcher():
    if DISPATCHER:
        try:
            asyncio.run(DISPATCHER.close())
        except Exception:
            pass
