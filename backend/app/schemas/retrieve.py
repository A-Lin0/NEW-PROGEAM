"""
信息检索 Pydantic 模型

对应 RetrieverAgent 的输入/输出规范
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class RetrieveRequest(BaseModel):
    """检索请求"""
    query: str = Field(..., min_length=1, description="用户原始查询")
    retrieve_type: str = Field(
        "mixed",
        description="检索类型：company_info / interview_exp / salary_query / industry_analysis / mixed",
    )
    company_name: Optional[str] = Field(None, description="目标公司名称")
    target_position: Optional[str] = Field(None, description="目标岗位")
    top_k: int = Field(default=5, ge=1, le=20, description="返回结果条数")


class RetrieveDetailItem(BaseModel):
    """单条检索结果项"""
    category: str
    content: str
    source: str
    reliability: str


class RetrieveResponse(BaseModel):
    """检索结果响应（强制标准JSON，前端直接渲染）"""
    retrieve_type: str
    has_result: bool
    summary: str = ""
    company_basic: Dict[str, str] = Field(default_factory=dict)
    detail_items: List[RetrieveDetailItem] = Field(default_factory=list)
    faq_list: List[str] = Field(default_factory=list)
    empty_reason: str = ""
