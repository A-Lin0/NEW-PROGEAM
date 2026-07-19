"""
统一日志器与请求日志中间件

- get_logger: 返回带模块名标记的 loguru logger
- RequestLogMiddleware: 记录每个 HTTP 请求的方法、路径、状态码与耗时

学生易错点：loguru 的 logger 是全局单例，bind(name) 只追加标记，
不会重复初始化；不要在每次 get_logger 时 configure handler，否则日志会重复输出。
"""

import time
import sys

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# 移除 loguru 默认 handler，统一格式（避免与 uvicorn 日志重复）
logger.remove()
logger.add(
    sys.stderr,
    level="INFO",
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{extra[name]}</cyan> | "
    "<level>{message}</level>",
)


def get_logger(name: str = __name__):
    """获取带模块名标记的日志器"""
    return logger.bind(name=name)


class RequestLogMiddleware(BaseHTTPMiddleware):
    """记录请求方法、路径、状态码、耗时"""

    async def dispatch(self, request: Request, call_next):
        start = time.time()
        try:
            response = await call_next(request)
        except Exception:
            cost = (time.time() - start) * 1000
            logger.bind(name="http").error(
                f"{request.method} {request.url.path} -> 500 ({cost:.1f}ms)"
            )
            raise

        cost = (time.time() - start) * 1000
        logger.bind(name="http").info(
            f"{request.method} {request.url.path} -> {response.status_code} ({cost:.1f}ms)"
        )
        return response
