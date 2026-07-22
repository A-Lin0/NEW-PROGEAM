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
    # SQLite/PostgreSQL 兼容的字段增量迁移：检查并补全 interviews.target_company_name 字段
    await _migrate_interview_target_company_name()


async def _migrate_interview_target_company_name():
    """增量迁移：为 interviews 表添加 target_company_name 字段（如果不存在）

    用于持久化用户在前端选择的目标公司名称，避免依赖 company_id 关联丢失。
    兼容 SQLite 与 PostgreSQL。
    """
    from sqlalchemy import text
    async with async_session_factory() as session:
        try:
            if settings.DB_TYPE == "sqlite":
                # SQLite 通过 PRAGMA table_info 检查字段
                result = await session.execute(text("PRAGMA table_info(interviews)"))
                columns = [row[1] for row in result]
                if "target_company_name" not in columns:
                    await session.execute(
                        text("ALTER TABLE interviews ADD COLUMN target_company_name VARCHAR(200)")
                    )
                    await session.commit()
                    print("[migration] 已添加 interviews.target_company_name 字段")
            else:
                # PostgreSQL 通过 information_schema 检查字段
                result = await session.execute(text("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name='interviews' AND column_name='target_company_name'
                """))
                if not result.first():
                    await session.execute(
                        text("ALTER TABLE interviews ADD COLUMN target_company_name VARCHAR(200)")
                    )
                    await session.commit()
                    print("[migration] 已添加 interviews.target_company_name 字段")
        except Exception as e:
            print(f"[migration] target_company_name 检查/添加失败（可忽略）: {e}")


async def close_db():
    """关闭数据库连接"""
    await engine.dispose()
