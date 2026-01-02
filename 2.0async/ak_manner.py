import asyncio
import time
from typing import Dict, Optional
from aiohttp import ClientSession, ClientTimeout, ClientConnectionError, ClientError
import aiohttp
from flask import json
import requests
from config import MAX_RETRIES

class BaiduAPIError(Exception):
    """百度 API 返回的业务错误"""
    def __init__(self, status: int, message: str, response: dict):
        self.status = status
        self.message = message
        self.response = response
        super().__init__(f"[BaiduAPIError] status={status}, message={message}")

class AK:
    def __init__(self, ak: str, qps_limit: Dict[str, int]):
        self.ak = ak
        self.qps_limit = qps_limit                                                            
        self.session: aiohttp.ClientSession | None = None
        self.lock: Optional[asyncio.Lock] = None     # 同上，延迟初始化
        self.rate = qps_limit
        self.capacity = qps_limit
        self.tokens = {k: float(v) for k, v in self.capacity.items()}
        self.timestamp = time.monotonic()
        self.lock = asyncio.Lock()    # 防止并发竞争

    def get_ak(self) -> str:
        return self.ak
    
    def get_qps_limit(self, api_type: str) -> int:
        return self.qps_limit.get(api_type, 3)

    async def start(self):
        """启动时创建会话"""
        self.tokens = {k: float(v) for k, v in self.capacity.items()}
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
            print(f"✅ AK {self.ak} session 已创建")
        if getattr(self, "lock", None) is None:
            self.lock = asyncio.Lock()

    async def close(self):
        """关闭会话"""
        if self.session:
            await self.session.close()
            print(f"🧹 AK {self.ak} session 已关闭")
        if self.lock:
            self.lock = None

    # ------------------------
    # 令牌桶算法限流
    # ------------------------
    async def acquire(self, api_type: str):
        now = time.monotonic()
        # 计算距离上次放入令牌的时间差
        delta = now - self.timestamp

        # 当前类型的速率与容量（默认3）
        print(f"AK {self.ak} acquire for api_type={api_type}: rate={self.rate.get(api_type, 3)}, capacity={self.capacity.get(api_type, 3)}")
        rate = self.rate.get(api_type, 3)
        capacity = self.capacity.get(api_type, 3)

        # 当前令牌数量（保底）
        current = self.tokens.get(api_type, capacity)

        # 增加令牌（但不超过容量上限）
        new_tokens = min(capacity, current + delta * rate)
        # 保证 self.tokens 是字典并写回当前 api_type
        if not isinstance(self.tokens, dict):
            self.tokens = {}
        self.tokens[api_type] = new_tokens
        self.timestamp = now

        # 如果没有足够令牌，等待补充
        if self.tokens.get(api_type, 0) < 1:
            sleep_time = (1 - self.tokens.get(api_type, 0)) / rate
            await asyncio.sleep(sleep_time)
            self.tokens[api_type] = 0  # 等待后再扣除
            self.timestamp = time.monotonic()
        else:
            self.tokens[api_type] -= 1

    # ------------------------
    # 初始化 aiohttp 会话
    # ------------------------
    async def _ensure_session(self):
        # 如果 session 不存在或已关闭，则重新创建
        if self.session is None or self.session.closed:
            await self.start()
        if self.lock is None:
            self.lock = asyncio.Lock()

    # ------------------------
    # 异步请求
    # ------------------------
    async def fetch_async(self, url: str, params: Dict, api_type: str):
        await self._ensure_session()
        async with self.lock:
            await self.acquire(api_type=api_type)

            params["ak"] = self.ak

            for i in range(MAX_RETRIES):
                try:
                    async with self.session.get(url, params=params) as resp:
                        text = await resp.text()
                        data = json.loads(text)
                        if isinstance(data, dict) and data.get("status") != 0:
                            raise BaiduAPIError(status=data.get("status"), message=data.get("message", ""), response=data)
                        return data

                except BaiduAPIError as e:
                    print(f"[BaiduAPI] 业务错误: status={e.status}, message={e.message}")
                    # 百度的部分状态码不适合重试
                    if e.status in (302, 301, 4, 5):
                        raise
                    if i == MAX_RETRIES - 1:
                        print("重试失败，放弃该请求")
                        return None
                    print(params)
                    await asyncio.sleep(0.5 * (2 ** i))  # 指数退避
                    print("重试中第 {} 次...".format(i + 1))
                    continue

                except (asyncio.TimeoutError, ClientConnectionError, ClientError) as e:
                    print(f"[BaiduAPI] 请求异常: {type(e).__name__}, message={e}")
                    if i == MAX_RETRIES - 1:
                        print("重试失败，放弃该请求")
                        return None
                    await asyncio.sleep(0.5 * (2 ** i))  # 指数退避

                except Exception as e:
                    print(f"[BaiduAPI] 未知异常: {type(e).__name__}, message={e}")
                    if i == MAX_RETRIES - 1:
                        print("重试失败，放弃该请求")
                        return None
                    await asyncio.sleep(0.5 * (2 ** i))  # 指数退避

    # ------------------------
    # 同步请求版本（备用）
    # ------------------------
    def fetch(self, url: str, params: Dict):
        params["ak"] = self.ak
        for i in range(MAX_RETRIES):
            try:
                resp = requests.get(url, params=params, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict) and data.get("status") != 0:
                    raise BaiduAPIError(status=data.get("status"), message=data.get("message", ""), response=data)
                return data
            except (requests.RequestException, ValueError, BaiduAPIError) as e:
                print(f"[BaiduAPI] 同步请求错误: {e}")
                if i == MAX_RETRIES - 1:
                    print("重试失败，放弃该请求")
                    return None
                time.sleep(0.5 * (2 ** i))
