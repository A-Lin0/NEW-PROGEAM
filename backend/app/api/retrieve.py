"""
信息检索接口

对接 RetrieverAgent，支持公司信息 / 面经 / 薪资 / 行业分析 / 混合检索 / 智能问答
统一返回标准 JSON，前端直接渲染详情页
"""

import json
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.session import get_db
from ..schemas.retrieve import RetrieveRequest, RetrieveResponse
from ..api.auth import get_current_user
from ..models.user import User
from ..middleware.log import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/retrieve", tags=["信息检索"])


# ==================== 智能问答请求/响应模型 ====================

class QARequest(BaseModel):
    """智能问答请求"""
    query: str = Field(..., min_length=1, description="用户自然语言问题")
    company_id: Optional[str] = Field(None, description="限定公司上下文（可选）")


class RelatedCompany(BaseModel):
    """关联公司条目"""
    id: str
    name: str
    industry: str = ""
    location: str = ""
    avg_difficulty: float = 0.0
    relevance: str = ""  # 关联说明


class QAData(BaseModel):
    """问答数据"""
    answer: str = ""
    related_companies: List[RelatedCompany] = []
    has_result: bool = True


class QAResponse(BaseModel):
    """统一响应格式"""
    code: int = 0
    message: str = ""
    data: QAData = QAData()


@router.post("/", response_model=RetrieveResponse)
async def retrieve_info(
    data: RetrieveRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    信息检索统一入口

    - company_info：公司基础信息查询
    - interview_exp：面经与真题检索
    - salary_query：薪资福利查询
    - industry_analysis：行业与竞品分析
    - mixed：混合检索
    """
    orchestrator = request.app.state.orchestrator
    retriever = orchestrator.retriever_agent if orchestrator else None
    if retriever is None:
        raise HTTPException(status_code=503, detail="检索服务未就绪")

    # 构造 payload，注入 db_session 让 Agent 能查结构化数据库
    payload = {
        "query": data.query,
        "retrieve_type": data.retrieve_type,
        "company_name": data.company_name,
        "target_position": data.target_position,
        "top_k": data.top_k,
        "db_session": db,
    }

    try:
        result = await retriever.retrieve(payload)
        logger.info(
            f"用户 {current_user.username} 检索 type={data.retrieve_type} "
            f"has_result={result.get('has_result')}"
        )
        return result
    except Exception as e:
        logger.error(f"检索失败: {e}")
        raise HTTPException(status_code=500, detail=f"检索服务内部错误: {str(e)}")


@router.post("/qa", response_model=QAResponse)
async def intelligent_qa(
    data: QARequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    智能问答接口（RAG）

    用户自然语言提问，基于公司知识库语义检索 + LLM 生成答案。
    支持限定公司上下文（company_id），未指定时自动从 query 中提取公司名。
    """
    orchestrator = request.app.state.orchestrator
    retriever = orchestrator.retriever_agent if orchestrator else None
    if retriever is None:
        return QAResponse(
            code=503,
            message="检索服务未就绪",
            data=QAData(answer="检索服务暂不可用，请稍后重试", has_result=False),
        )

    # 确定公司名称（用于限定上下文）
    company_name = ""
    company_id = data.company_id or ""
    if company_id:
        # 先尝试 DB 查询
        try:
            from sqlalchemy import select
            from ..models.company import Company
            stmt = select(Company).where(Company.id == company_id)
            result = await db.execute(stmt)
            company = result.scalar_one_or_none()
            if company:
                company_name = company.name
        except Exception:
            pass
        # DB 未命中 → companies.json 兜底（支持 c001-c015 等前端短 ID）
        if not company_name:
            try:
                from agent.core.retriever_agent import _load_companies_json, _find_company_in_json
                companies_json = _load_companies_json()
                c = _find_company_in_json(companies_json, company_id=company_id)
                if c:
                    company_name = c.get("name", "")
            except Exception:
                pass

    # 使用 RetrieverAgent 的 _handle_qa_mode 进行语义问答
    # 直接调用 retriever.retrieve 并传入 qa query_type
    retrieve_payload = {
        "query": data.query,
        "query_type": "qa",  # 关键：触发 QA 模式
        "retrieve_type": "company_qa",
        "company_name": company_name,
        "company_id": company_id,
        "top_k": 5,
        "db_session": db,
    }
    try:
        retrieve_result = await retriever.retrieve(retrieve_payload)
    except Exception as e:
        logger.error(f"QA 检索失败: {e}")
        return QAResponse(
            code=500,
            message=f"检索失败: {str(e)}",
            data=QAData(answer="检索服务异常，请稍后重试", has_result=False),
        )

    answer = retrieve_result.get("answer", "暂无相关数据，请尝试其他问题。")
    has_result = retrieve_result.get("has_result", False)

    # 提取关联公司
    related_companies = []
    for rc in retrieve_result.get("related_companies", []):
        if rc.get("company_name"):
            related_companies.append(RelatedCompany(
                id=rc.get("company_id", ""),
                name=rc.get("company_name", ""),
                industry=rc.get("industry", ""),
                location=rc.get("location", ""),
                avg_difficulty=rc.get("avg_difficulty", 0.0),
                relevance="直接匹配",
            ))

    logger.info(
        f"用户 {current_user.username} QA: {data.query[:50]}... → "
        f"答案{len(answer)}字，关联{len(related_companies)}家公司"
    )

    return QAResponse(
        code=0,
        message="ok",
        data=QAData(
            answer=answer,
            related_companies=[c for c in related_companies if c.name],
            has_result=has_result,
        ),
    )
