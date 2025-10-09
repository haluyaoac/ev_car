import asyncio
import aiohttp
import time
from typing import Dict, Any, List, Optional
from config import QPS_MATRIX

# ---------------------------
# 单个 AK 的限流与重试 Worker
# ---------------------------
class AKWorker:
    def __init__(self, ak: str, qps_limit: Dict[str, int]):
        self.ak = ak
        self.qps_limit = qps_limit
        self._last_requests: Dict[str, List[float]] = {api: [] for api in qps_limit}
        self._lock = asyncio.Lock()

    async def throttle(self, api_type: str):
        """控制单个 AK 的 QPS"""
        if api_type not in self.qps_limit:
            self.qps_limit[api_type] = 3
            self._last_requests[api_type] = []

        max_qps = self.qps_limit[api_type]
        async with self._lock:
            now = time.time()
            records = self._last_requests[api_type]
            self._last_requests[api_type] = [t for t in records if now - t < 1]
            if len(self._last_requests[api_type]) >= max_qps:
                sleep_time = 1 - (now - self._last_requests[api_type][0])
                await asyncio.sleep(max(sleep_time, 0))
            self._last_requests[api_type].append(time.time())

    async def fetch(
        self, session: aiohttp.ClientSession, api_type: str, url: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """带自动重试的请求"""
        await self.throttle(api_type)
        params["ak"] = self.ak

        for attempt in range(3):
            try:
                async with session.get(url, params=params, timeout=10) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    if data.get("status") == 0:
                        return data
                    else:
                        await asyncio.sleep(0.3 * (attempt + 1))
            except Exception as e:
                if attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
                else:
                    return {"status": -1, "error": str(e), "ak": self.ak}
        return {"status": -1, "error": "Max retries exceeded", "ak": self.ak}


# ---------------------------
# 多 AK 调度器
# ---------------------------
class MultiAKDispatcher:
    def __init__(self, qps_matrix: Dict[str, Dict[str, int]]):
        self.workers = [AKWorker(ak, qps) for ak, qps in qps_matrix.items()]
        self._session: Optional[aiohttp.ClientSession] = None

    async def start(self):
        if self._session is None:
            self._session = aiohttp.ClientSession()

    async def close(self):
        if self._session:
            await self._session.close()
            self._session = None

    def _pick_worker(self, api_type: str) -> AKWorker:
        available = [w for w in self.workers if api_type in w.qps_limit] or self.workers
        return min(
            available,
            key=lambda w: len([t for t in w._last_requests.get(api_type, []) if time.time() - t < 1])
        )

    async def fetch_json_async(self, api_type: str, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
        worker = self._pick_worker(api_type)
        return await worker.fetch(self._session, api_type, url, params)


# ---------------------------
# 单例实例
# ---------------------------
DISPATCHER: Optional[MultiAKDispatcher] = None

async def _ensure_dispatcher() -> MultiAKDispatcher:
    global DISPATCHER
    if DISPATCHER is None:
        DISPATCHER = MultiAKDispatcher(QPS_MATRIX)
        await DISPATCHER.start()
    return DISPATCHER

async def fetch_json_async(api_type: str, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    dispatcher = await _ensure_dispatcher()
    return await dispatcher.fetch_json_async(api_type, url, params)
