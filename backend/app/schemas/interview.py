"""
面试 Pydantic 模型
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from uuid import UUID


class InterviewStart(BaseModel):
    """开始面试"""
    company_id: Optional[UUID] = None
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
