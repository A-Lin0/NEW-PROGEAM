"""
数据库连接与会话管理

支持 SQLite（默认）与 PostgreSQL 双模式
"""

import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import event

from ..config import settings


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类"""
    pass


# 构建引擎参数
_engine_kwargs = {
    "echo": settings.DEBUG,
}

if settings.DB_TYPE == "sqlite":
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    _engine_kwargs.update({
        "pool_size": 10,
        "max_overflow": 20,
        "pool_pre_ping": True,
    })

# 异步引擎
engine = create_async_engine(
    settings.DATABASE_URL,
    **_engine_kwargs,
)

# SQLite 外键约束：连接时启用
if settings.DB_TYPE == "sqlite":
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

# 异步会话工厂
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    """获取数据库会话（依赖注入）"""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """初始化数据库表"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """关闭数据库连接"""
    await engine.dispose()
