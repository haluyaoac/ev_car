import asyncio, time, json, traceback, atexit
import aiohttp
from typing import Optional, Dict, Any, List


class AsyncRequestDispatcher:
    def __init__(self, max_qps: int = 3, max_concurrent: int = 3, user_agent: str = "EV-Planner/1.0"):
        self.max_qps = max_qps
        self.max_concurrent = max_concurrent
        self._last_req_ts = 0.0
        self._sem = asyncio.Semaphore(max_concurrent)
        self._queue: asyncio.Queue = asyncio.Queue()
        self._workers: List[asyncio.Task] = []
        self._session: Optional[aiohttp.ClientSession] = None
        self._running = False
        self._ua = user_agent
        self._lock = asyncio.Lock()  # 🔑 用于 QPS 控制加锁

    async def start(self, worker_count: int = 3):
        if self._running:
            return
        timeout = aiohttp.ClientTimeout(total=25)
        self._session = aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": self._ua})
        self._running = True
        for _ in range(worker_count):
            self._workers.append(asyncio.create_task(self._worker()))

    async def shutdown(self):
        self._running = False
        for t in self._workers:
            t.cancel()
        self._workers.clear()
        if self._session:
            await self._session.close()
            self._session = None

    async def _throttle(self):
        """QPS 限制，保证全局请求间隔 >= 1/max_qps"""
        if self.max_qps <= 0:
            return
        interval = 1.0 / self.max_qps
        async with self._lock:  # 🔑 全局锁，避免多个 worker 并发突破限制
            now = time.time()
            delta = now - self._last_req_ts
            if delta < interval:
                await asyncio.sleep(interval - delta)
            self._last_req_ts = time.time()

    async def _worker(self):
        while True:
            try:
                item = await self._queue.get()
            except asyncio.CancelledError:
                break
            if item is None:
                self._queue.task_done()
                continue
            url, params, fut, retries, timeout_s = item
            async with self._sem:
                result = await self._do_request(url, params, retries, timeout_s)
                if not fut.done():
                    fut.set_result(result)
            self._queue.task_done()

    async def _do_request(self, url: str, params: Dict[str, Any], retries: int, timeout_s: float):
        if not self._session:
            return {"_error": "session_not_started"}
        backoff = 0.6
        for attempt in range(1, retries + 1):
            try:
                await self._throttle()
                async with self._session.get(url, params=params, timeout=timeout_s) as resp:
                    text = await resp.text()
                    if resp.status != 200:
                        raise RuntimeError(f"http {resp.status} body={text[:180]}")
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        raise RuntimeError(f"json_decode_error: {text[:180]}")
            except Exception as e:
                if attempt == retries:
                    return {"_error": str(e), "_trace": traceback.format_exc(), "_attempts": attempt}
                await asyncio.sleep(backoff)
                backoff *= 1.6
        return {"_error": "unreachable"}

    async def fetch_json_async(self, url: str, params: Dict[str, Any], retries: int = 3, timeout_s: float = 15.0):
        fut = asyncio.get_event_loop().create_future()
        await self._queue.put((url, params, fut, retries, timeout_s))
        return await fut


# ---------- 全局单例封装 ----------
_dispatcher: Optional[AsyncRequestDispatcher] = None


def get_dispatcher() -> AsyncRequestDispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = AsyncRequestDispatcher(max_qps=3, max_concurrent=3)
    return _dispatcher


def set_limits(max_qps: int = 3, max_concurrent: int = 3):
    d = get_dispatcher()
    d.max_qps = max_qps
    d.max_concurrent = max_concurrent


def ensure_dispatcher_started():
    d = get_dispatcher()
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if not d._running:
        if loop.is_running():
            loop.create_task(d.start())
        else:
            loop.run_until_complete(d.start())


def shutdown_dispatcher():
    d = get_dispatcher()
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        return
    if d._running:
        if loop.is_running():
            loop.create_task(d.shutdown())
        else:
            loop.run_until_complete(d.shutdown())


atexit.register(shutdown_dispatcher)


def fetch_json(url: str, params: Dict[str, Any], retries: int = 3, timeout_s: float = 15.0):
    """
    同步封装：阻塞直到得到结果（适配现有同步 baidu_api 代码）。
    """
    ensure_dispatcher_started()
    d = get_dispatcher()
    loop = asyncio.get_event_loop()
    coro = d.fetch_json_async(url, params, retries=retries, timeout_s=timeout_s)

    if loop.is_running():
        # 🔑 在已有 loop 中执行
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        return fut.result()
    else:
        return loop.run_until_complete(coro)
