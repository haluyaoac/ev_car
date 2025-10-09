import atexit
import asyncio, time
import aiohttp
from typing import Optional, Dict, Any


class BaiduAPIError(Exception):
    """百度 API 返回的业务错误"""
    def __init__(self, status: int, message: str, response: dict):
        self.status = status
        self.message = message
        self.response = response
        super().__init__(f"[BaiduAPIError] status={status}, message={message}")


class AsyncRequestDispatcher:
    def __init__(self, max_qps: int = 2, user_agent: str = "EV-Planner/1.0"):
        self.max_qps = max_qps
        self.user_agent = user_agent
        self._bucket_time = int(time.monotonic())
        self._bucket_count = 0
        self._lock = asyncio.Lock()
        self._session: Optional[aiohttp.ClientSession] = None
        """
        max_qps: 最大 QPS 限制
        user_agent: HTTP 请求头中的 User-Agent 字段
        _bucket_time: 当前时间桶（秒级）
        _bucket_count: 当前时间桶内已发出的请求数
        _lock: 保护桶状态的异步锁
        _session: aiohttp 的长连接 session
        进程退出时会自动关闭 session
        """

    async def start(self):
        """启动长连接 session"""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=15.0)
            self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self):
        """关闭 session"""
        if self._session and not self._session.closed:
            await self._session.close()

    async def _throttle(self):
        """精确分桶 QPS 控制"""
        async with self._lock:
            while True:
                now_sec = int(time.monotonic())
                if now_sec != self._bucket_time:
                    self._bucket_time = now_sec
                    self._bucket_count = 0
                if self._bucket_count < self.max_qps:
                    self._bucket_count += 1
                    return
                sleep_time = self._bucket_time + 1 - time.monotonic()
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

    async def fetch(self, url: str, **kwargs):
        """发起一次 GET 请求，并检查百度 API 返回"""
        if not self._session or self._session.closed:
            raise RuntimeError("Session not started, call await start() first")

        await self._throttle()

        headers = kwargs.pop("headers", {})
        headers["User-Agent"] = self.user_agent

        async with self._session.get(url, headers=headers, **kwargs) as resp:
            resp.raise_for_status()  # HTTP 错误
            # 忽略百度 API 的非标准 content-type
            data = await resp.json(content_type=None)

            # 检查百度 API 状态码
            if isinstance(data, dict) and "status" in data and data["status"] != 0:
                raise BaiduAPIError(
                    status=data["status"],
                    message=data.get("message", "Unknown error"),
                    response=data
                )

            return data

    async def fetch_json_async(self, url: str, params: Dict[str, Any],
                               retries: int = 20, timeout_s: float = 15.0):
        """异步 JSON 请求，带重试"""
        if not self._session or self._session.closed:
            await self.start()

        while True:
            try:
                return await self.fetch(url, params=params)
            except BaiduAPIError as e:
                #如果是额度不足等业务错误，不重试
                if e.status in (302, 301):
                    print(f"[Error] 百度 API 额度不足或请求被拒绝: {e.message}")
                    raise e
                print(f"[Error] {e.status}, {e.message}")
                print("重试中...")
                await asyncio.sleep(1)
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                print(f"[Error] 网络或请求异常: {e}")
                print("重试中...")
                await asyncio.sleep(1)
            retries -= 1
            if retries <= 0:
                raise RuntimeError("请求多次失败，放弃")
            

# 全局唯一实例
dispatcher = AsyncRequestDispatcher(max_qps=2)

_dispatcher_closed = False  # 全局标记，防止重复关闭

async def _async_close_dispatcher():
    global _dispatcher_closed
    if _dispatcher_closed:
        print("[Dispatcher] 已经关闭过，跳过")
        return
    print("[Dispatcher] 正在关闭 aiohttp session ...")
    await dispatcher.close()
    _dispatcher_closed = True
    print("[Dispatcher] 已关闭")

def _close_dispatcher():
    global _dispatcher_closed
    if _dispatcher_closed:
        print("[Dispatcher] 已经关闭过（来自 _close_dispatcher），跳过")
        return
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_async_close_dispatcher())
        loop.close()
    except Exception as e:
        print(f"[Dispatcher] 关闭时出错: {e}")

# 注册退出钩子
atexit.register(_close_dispatcher)