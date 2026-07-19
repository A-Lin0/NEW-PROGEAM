"""
公司信息 Pydantic 模型
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from uuid import UUID


class CompanyCreate(BaseModel):
    """创建/更新公司"""
    name: str = Field(..., max_length=200)
    industry: Optional[str] = None
    size: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    culture: Optional[str] = None
    benefits: Optional[str] = None
    website: Optional[str] = None
    interview_process: Optional[str] = None
    avg_difficulty: Optional[float] = None
    avg_salary: Optional[str] = None


class CompanyResponse(BaseModel):
    """公司信息响应"""
    id: UUID
    name: str
    industry: Optional[str]
    size: Optional[str]
    location: Optional[str]
    description: Optional[str]
    culture: Optional[str]
    benefits: Optional[str]
    website: Optional[str]
    interview_process: Optional[str]
    avg_difficulty: Optional[float]
    avg_salary: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CompanyQuery(BaseModel):
    """公司搜索查询"""
    keyword: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
