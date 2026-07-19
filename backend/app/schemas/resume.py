"""
简历 Pydantic 模型
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from uuid import UUID


class ResumeCreate(BaseModel):
    """创建简历"""
    title: str = Field(..., max_length=200)
    summary: Optional[str] = None
    experience: Optional[list[dict]] = None
    education: Optional[list[dict]] = None
    skills: Optional[list[str]] = None
    projects: Optional[list[dict]] = None
    certificates: Optional[list[dict]] = None
    target_company: Optional[str] = None
    target_position: Optional[str] = None
    raw_text: Optional[str] = None


class ResumeResponse(BaseModel):
    """简历响应"""
    id: UUID
    user_id: UUID
    title: str
    version: int
    summary: Optional[str]
    experience: Optional[list]
    education: Optional[list]
    skills: Optional[list]
    projects: Optional[list]
    certificates: Optional[list]
    ai_suggestions: Optional[str]
    score: Optional[int]
    target_company: Optional[str]
    target_position: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ResumeOptimizeRequest(BaseModel):
    """简历优化请求"""
    resume_id: Optional[UUID] = None
    content: str = Field(..., min_length=1)
    section_type: str = Field(default="experience")
    job_description: Optional[str] = None
    company_id: Optional[str] = None
    target_position: Optional[str] = None
