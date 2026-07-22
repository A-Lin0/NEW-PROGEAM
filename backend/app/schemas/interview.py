"""
面试 Pydantic 模型
"""

from pydantic import BaseModel, Field, field_serializer
from typing import Optional
from datetime import datetime, timezone
from uuid import UUID


class InterviewStart(BaseModel):
    """开始面试"""
    company_id: Optional[UUID] = None
    # 用户在前端选择的目标公司名称（字符串，独立于 company_id 关联）
    company_name: Optional[str] = None
    position: Optional[str] = None


class InterviewAnswer(BaseModel):
    """提交回答"""
    answer: str = Field(..., min_length=1)
    session_id: Optional[str] = None


class InterviewCommand(BaseModel):
    """面试控制命令"""
    command: str = Field(..., pattern=r"^(start|next|skip|end)$")
    session_id: Optional[str] = None


class InterviewResponse(BaseModel):
    """面试记录响应"""
    id: UUID
    user_id: UUID
    company_id: Optional[UUID]
    target_company_name: Optional[str] = None
    position: Optional[str]
    status: str
    questions_answers: Optional[list]
    phase: str
    overall_score: Optional[float]
    phase_scores: Optional[dict]
    review_report: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

    # 数据库列 default=datetime.utcnow 存储的是 naive UTC 时间，
    # Pydantic 默认序列化不带时区标识，前端 new Date() 会误判为本地时间（慢8小时）。
    # 这里在序列化时为其附加 UTC 时区，前端解析后自动转换为本地时间。
    @field_serializer("created_at", "updated_at")
    def _serialize_dt_with_tz(self, value: Optional[datetime]) -> Optional[str]:
        if value is None:
            return None
        if value.tzinfo is not None:
            return value.isoformat()
        return value.replace(tzinfo=timezone.utc).isoformat()
