"""
公司信息接口

提供公司 CRUD + 智能问答
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from uuid import UUID

from ..db.session import get_db
from ..schemas.company import CompanyCreate, CompanyResponse, CompanyQuery
from ..services.company_service import CompanyService
from ..services.retriever_service import RetrieverService
from ..api.auth import get_current_user
from ..models.user import User
from ..middleware.log import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/companies", tags=["公司信息"])


@router.post("/", response_model=CompanyResponse, status_code=201)
async def create_company(
    data: CompanyCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建公司信息"""
    service = CompanyService(db)
    company = await service.create(data)
    logger.info(f"创建公司: {company.name}")

    # 自动同步向量库
    try:
        vector_store = getattr(request.app.state, "vector_store", None)
        embedder = getattr(request.app.state, "embedder", None)
        if vector_store and embedder:
            retriever_svc = RetrieverService(db)
            await retriever_svc.vector_sync_one(str(company.id), vector_store, embedder)
    except Exception as e:
        logger.warning(f"向量同步失败（不影响主流程）: {e}")

    return company


@router.get("/", response_model=list[CompanyResponse])
async def list_companies(
    keyword: Optional[str] = Query(None, description="搜索关键词"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """搜索/列表公司"""
    service = CompanyService(db)
    return await service.list(keyword=keyword, skip=skip, limit=limit)


@router.get("/{company_id}", response_model=CompanyResponse)
async def get_company(
    company_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """获取公司详情"""
    service = CompanyService(db)
    company = await service.get(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="公司不存在")
    return company


@router.put("/{company_id}", response_model=CompanyResponse)
async def update_company(
    company_id: UUID,
    data: CompanyCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新公司信息"""
    service = CompanyService(db)
    company = await service.update(company_id, data)
    if not company:
        raise HTTPException(status_code=404, detail="公司不存在")

    # 自动同步向量库
    try:
        vector_store = getattr(request.app.state, "vector_store", None)
        embedder = getattr(request.app.state, "embedder", None)
        if vector_store and embedder:
            retriever_svc = RetrieverService(db)
            await retriever_svc.vector_sync_one(str(company.id), vector_store, embedder)
    except Exception as e:
        logger.warning(f"向量同步失败（不影响主流程）: {e}")

    return company


@router.delete("/{company_id}", status_code=204)
async def delete_company(
    company_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除公司"""
    service = CompanyService(db)
    deleted = await service.delete(company_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="公司不存在")

    # 自动删除向量库对应数据
    try:
        vector_store = getattr(request.app.state, "vector_store", None)
        if vector_store:
            retriever_svc = RetrieverService(db)
            await retriever_svc.vector_delete_one(str(company_id), vector_store)
    except Exception as e:
        logger.warning(f"向量删除失败（不影响主流程）: {e}")


@router.post("/smart-search")
async def smart_search(
    query: CompanyQuery,
    db: AsyncSession = Depends(get_db),
):
    """智能搜索公司（数据库 + 向量检索）"""
    service = CompanyService(db)
    # 这里 retriever 需要从应用状态获取
    results = await service.search_smart(query.keyword, retriever=None, top_k=query.top_k)
    return {"results": results, "total": len(results)}
