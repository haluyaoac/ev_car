import asyncio, time, json, traceback, atexit
import aiohttp
from typing import Optional, Dict, Any, List

class AsyncRequestDispatcher:
    def __init__(self, max_qps: int = 3, max_concurrent: int = 3, user_agent: str = "EV-Planner/1.0"):
        self.max_qps = max_qps                                   # 每秒最大请求数
        self.max_concurrent = max_concurrent                     # 最大并发请求数   
        self._last_req_ts = 0.0                                  # 上次请求时间戳
        self._sem = asyncio.Semaphore(max_concurrent)            # 并发控制信号量
        self._queue: asyncio.Queue = asyncio.Queue()             # 请求队列
        self._workers: List[asyncio.Task] = []                   # 工作协程列表
        self._session: Optional[aiohttp.ClientSession] = None    # aiohttp session
        self._running = False                                    # 是否已启动
        self._ua = user_agent                                    # User-Agent
    

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
        # 取消 worker
        for t in self._workers:
            t.cancel()
        self._workers.clear()
        if self._session:
            await self._session.close()
            self._session = None

    async def _throttle(self):
        # 简单 QPS 控制：保证两次请求间隔 >= 1/max_qps
        if self.max_qps <= 0:
            return
        now = time.time()
        interval = 1.0 / self.max_qps
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
                async with self._session.get(url, params=params) as resp:
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
        return {"_error": "unreachable"}  # 理论不达

    async def fetch_json_async(self, url: str, params: Dict[str, Any], retries: int = 3, timeout_s: float = 15.0):
        # 异步接口：提交请求并返回 Future
        fut = asyncio.get_event_loop().create_future()
        await self._queue.put((url, params, fut, retries, timeout_s))
        return await fut

# 全局单例
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
            # 若已有 loop（如在 FastAPI/Flask + ai loop），提交启动任务
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
    timeout_s: 每次请求超时，非总超时。
    """
    ensure_dispatcher_started()
    d = get_dispatcher()
    loop = asyncio.get_event_loop()
    if loop.is_running():
        # 已有事件循环（可能在异步 web 框架内部）——应提示用异步接口
        # 简单方案：使用 asyncio.run_coroutine_threadsafe（但需线程）
        # 这里直接抛出警告；若需要可扩展线程安全调用
        coro = d.fetch_json_async(url, params, retries=retries, timeout_s=timeout_s)
        # 临时：创建新任务并等待完成
        return asyncio.run(coro)
    else:
        return loop.run_until_complete(d.fetch_json_async(url, params, retries=retries, timeout_s=timeout_s))