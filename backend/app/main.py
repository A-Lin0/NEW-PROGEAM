"""
应用入口

FastAPI 服务启动、注册路由、初始化中间件和全局资源
"""

import sys
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 将项目根目录加入 sys.path，以便导入 agent 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from .config import settings
from .db.session import init_db, close_db
from .db.redis_client import init_redis, close_redis
from .middleware.log import RequestLogMiddleware, get_logger

from .api.auth import router as auth_router
from .api.companies import router as companies_router
from .api.resume import router as resume_router
from .api.interview import router as interview_router
from .api.review import router as review_router
from .api.retrieve import router as retrieve_router
from .api.retriever import router as retriever_router
from .api.agent import router as agent_router

logger = get_logger(__name__)


async def _sync_companies_to_vectorstore(orchestrator, session_factory):
    """启动时将公司数据同步到向量库，确保 RAG 检索有数据可用"""
    from sqlalchemy import select
    from .models.company import Company
    from agent.knowledge.vector_store import Document

    # 收集公司数据：DB 公司 + companies.json 兜底公司（前端 c001-c015）
    companies_data = []

    # 1. DB 公司
    async with session_factory() as db:
        result = await db.execute(select(Company))
        companies = result.scalars().all()
    for c in companies:
        companies_data.append({
            "company_id": str(c.id),
            "name": c.name or "",
            "industry": c.industry or "",
            "description": c.description or "",
            "culture": c.culture or "",
            "benefits": c.benefits or "",
            "interview_process": c.interview_process or "",
            "location": c.location or "",
            "size": c.size or "",
            "avg_difficulty": str(c.avg_difficulty) if c.avg_difficulty else "",
            "avg_salary": c.avg_salary or "",
        })

    # 2. companies.json 兜底公司（前端短 ID：c001-c015）
    try:
        from agent.core.retriever_agent import _load_companies_json
        json_companies = _load_companies_json()
        existing_ids = {c["company_id"] for c in companies_data if c.get("company_id")}
        for jc in json_companies:
            cid = str(jc.get("id", ""))
            if not cid or cid in existing_ids:
                continue
            positions = jc.get("positions") or []
            pos_text = ""
            if positions:
                pos_parts = []
                for p in positions[:6]:
                    pos_parts.append(
                        f"{p.get('name','')}({p.get('department','')}, {p.get('salary','')})"
                    )
                pos_text = "；招聘岗位：" + "、".join(pos_parts)
            companies_data.append({
                "company_id": cid,
                "name": jc.get("name", ""),
                "industry": jc.get("industry", ""),
                "description": (jc.get("description", "") or "") + pos_text,
                "culture": jc.get("culture", ""),
                "benefits": jc.get("benefits", ""),
                "interview_process": jc.get("interview_process", ""),
                "location": jc.get("location", ""),
                "size": jc.get("size", ""),
                "avg_difficulty": str(jc.get("avg_difficulty", "")),
                "avg_salary": "",
            })
    except Exception as e:
        logger.warning(f"加载 companies.json 失败（不影响启动）: {e}")

    if not companies_data:
        logger.info("公司数据为空（DB + companies.json 均无数据），跳过向量同步")
        return

    # 检查向量库已有数据量
    existing_count = orchestrator.vector_store.count() if orchestrator.vector_store else 0
    if existing_count >= len(companies_data):
        logger.info(f"向量库已有 {existing_count} 条数据，跳过同步")
        return

    retriever = orchestrator.retriever_agent
    if not retriever:
        logger.warning("RetrieverAgent 未初始化，跳过向量同步")
        return

    result = await retriever.sync_all_companies(companies_data)
    logger.info(
        f"公司数据向量同步完成: synced={result.get('synced_count', 0)}, "
        f"total_companies={len(companies_data)}, error={result.get('error', '')}"
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("=" * 50)
    logger.info("面试辅导系统启动中...")
    logger.info("=" * 50)

    # SQLite 模式：自动创建 data 目录
    if settings.DB_TYPE == "sqlite":
        db_path = settings.SQLITE_DB_PATH
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            logger.info(f"自动创建数据库目录: {db_dir}")

    # 初始化数据库
    await init_db()
    logger.info("数据库连接已建立 (SQLite)")

    # 初始化 Redis
    try:
        await init_redis()
        logger.info("Redis 连接已建立")
    except Exception as e:
        logger.warning(f"Redis 连接失败: {e}")

    # 初始化 Agent 调度器（统一注入 vector_store / embedder / redis / db_factory / LLM 配置）
    try:
        from agent.orchestrator import AgentOrchestrator
        from agent.knowledge.embeddings import EmbeddingModel
        from agent.knowledge.vector_store import VectorStore
        from .db.redis_client import get_redis
        from .db.session import async_session_factory

        embedder = EmbeddingModel()
        vector_store = VectorStore(
            store_type=settings.VECTOR_STORE_TYPE,
            persist_dir=settings.CHROMA_PERSIST_DIR,
        )
        await vector_store.initialize()

        redis_client = await get_redis()

        orchestrator = AgentOrchestrator(
            vector_store=vector_store,
            embedder=embedder,
            redis_client=redis_client,
            db_session_factory=async_session_factory,
            llm_api_key=settings.LLM_API_KEY,
            llm_base_url=settings.LLM_BASE_URL,
            llm_model=settings.LLM_MODEL,
        )
        app.state.orchestrator = orchestrator
        app.state.vector_store = vector_store
        app.state.embedder = embedder

        logger.info(
            f"Agent 调度器初始化完成 "
            f"(vector_store=✓, redis={'✓' if redis_client else '✗'}, "
            f"llm={'✓' if settings.LLM_API_KEY else '✗(降级)'})"
        )

        # 自动同步公司数据到向量库（启动时执行一次）
        try:
            await _sync_companies_to_vectorstore(orchestrator, async_session_factory)
        except Exception as e:
            logger.warning(f"公司数据向量同步失败（不影响启动）: {e}")
    except Exception as e:
        logger.warning(f"Agent 初始化失败（将在首次调用时降级）: {e}")
        import traceback
        logger.warning(traceback.format_exc())
        from agent.orchestrator import AgentOrchestrator
        app.state.orchestrator = AgentOrchestrator()

    logger.info("服务启动完成")

    yield

    # 关闭资源
    await close_db()
    await close_redis()
    logger.info("服务已关闭")


# 创建应用
app = FastAPI(
    title="AI 面试辅导系统",
    description="智能面试准备与模拟平台 - Agent + RAG",
    version="1.0.0",
    lifespan=lifespan,
)

# ---- 中间件 ----
app.add_middleware(RequestLogMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境请限制为前端域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- 注册路由 ----
app.include_router(auth_router)
app.include_router(companies_router)
app.include_router(resume_router)
app.include_router(interview_router)
app.include_router(review_router)
app.include_router(retrieve_router)
app.include_router(retriever_router)
app.include_router(agent_router)


# ---- 健康检查 ----
@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {
        "status": "ok",
        "version": "1.0.0",
        "service": "面试辅导系统",
    }
