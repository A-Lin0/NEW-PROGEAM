"""
RAG 语义检索接口

提供语义问答、向量库初始化、单条同步/删除功能
路由前缀：/api/retriever
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.session import get_db
from ..api.auth import get_current_user
from ..models.user import User
from ..services.retriever_service import RetrieverService
from ..middleware.log import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/retriever", tags=["RAG语义检索"])


# ==================== Pydantic 模型 ====================

class QARequest(BaseModel):
    """语义问答请求"""
    query: str = Field(..., min_length=1, max_length=1000, description="用户自然语言问题")
    company_id: Optional[str] = Field(None, description="限定公司上下文（可选）")


class RelatedCompany(BaseModel):
    """关联公司条目"""
    id: str
    name: str
    industry: str = ""
    location: str = ""
    avg_difficulty: float = 0.0
    relevance: str = ""


class QAData(BaseModel):
    """问答数据"""
    answer: str = ""
    related_companies: List[RelatedCompany] = []
    detail_items: List[dict] = []
    has_result: bool = True


class QAResponse(BaseModel):
    """问答响应"""
    code: int = 0
    message: str = ""
    data: QAData = QAData()


class VectorInitResponse(BaseModel):
    """向量初始化响应"""
    code: int = 0
    message: str = ""
    data: dict = Field(default_factory=dict)


class VectorSyncResponse(BaseModel):
    """向量同步响应"""
    code: int = 0
    message: str = ""
    data: Optional[dict] = None


class VectorDeleteResponse(BaseModel):
    """向量删除响应"""
    code: int = 0
    message: str = ""
    data: Optional[dict] = None


# ==================== 权限校验 ====================

def require_admin(current_user: User = Depends(get_current_user)):
    """仅管理员可调用"""
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="仅管理员可执行此操作")
    return current_user


# ==================== 接口端点 ====================

@router.post("/qa", response_model=QAResponse)
async def semantic_qa(
    data: QARequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    语义问答主接口

    调用 RetrieverAgent 的语义检索模式，返回问答结果与关联公司。
    登录用户均可调用。
    """
    vector_store = getattr(request.app.state, "vector_store", None)
    if not vector_store:
        raise HTTPException(status_code=503, detail="向量库未就绪")

    service = RetrieverService(db)
    result = await service.qa_answer(
        query=data.query,
        vector_store=vector_store,
        db_session=db,
        company_id=data.company_id,
    )
    logger.info(f"用户 {current_user.username} 语义问答: {data.query[:50]}...")
    return result


@router.post("/vector/init", response_model=VectorInitResponse)
async def vector_init(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """
    向量库全量初始化

    读取全量公司数据，批量向量化写入向量库。
    仅管理员可调用。
    """
    vector_store = getattr(request.app.state, "vector_store", None)
    embedder = getattr(request.app.state, "embedder", None)

    if not vector_store:
        raise HTTPException(status_code=503, detail="向量库未就绪")

    service = RetrieverService(db)
    result = await service.vector_init_all(vector_store, embedder)
    logger.info(f"管理员 {admin.username} 触发向量库全量初始化")
    return result


@router.post("/vector/sync/{company_id}", response_model=VectorSyncResponse)
async def vector_sync(
    company_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """
    单条公司向量数据同步

    新增/编辑公司后，同步更新对应条目的向量数据。
    仅管理员可调用。
    """
    vector_store = getattr(request.app.state, "vector_store", None)
    embedder = getattr(request.app.state, "embedder", None)

    if not vector_store:
        raise HTTPException(status_code=503, detail="向量库未就绪")

    service = RetrieverService(db)
    result = await service.vector_sync_one(company_id, vector_store, embedder)
    logger.info(f"管理员 {admin.username} 同步向量: {company_id}")
    return result


@router.delete("/vector/{company_id}", response_model=VectorDeleteResponse)
async def vector_delete(
    company_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """
    删除单条公司向量数据

    删除公司后，同步移除向量库中对应数据。
    仅管理员可调用。
    """
    vector_store = getattr(request.app.state, "vector_store", None)

    if not vector_store:
        raise HTTPException(status_code=503, detail="向量库未就绪")

    service = RetrieverService(db)
    result = await service.vector_delete_one(company_id, vector_store)
    logger.info(f"管理员 {admin.username} 删除向量: {company_id}")
    return result