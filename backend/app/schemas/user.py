"""
用户 Pydantic 模型
"""

from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime
from uuid import UUID


# 用户名规则：支持中文、字母、数字、下划线、连字符，长度 3-50
USERNAME_PATTERN = r'^[\u4e00-\u9fa5a-zA-Z0-9_-]+$'
_USERNAME_RULE = "仅支持中文、字母、数字、下划线和连字符，长度 3-50"


class UserCreate(BaseModel):
    """创建用户请求"""
    username: str = Field(
        ...,
        min_length=2,
        max_length=50,
        pattern=USERNAME_PATTERN,
        description="用户名支持中文、字母、数字、下划线和连字符",
    )
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=100)


class UserLogin(BaseModel):
    """用户登录请求

    登录时不限制用户名格式，只做账号匹配，避免历史用户因规则变更无法登录。
    """
    username: str = Field(..., min_length=1, max_length=50)
    password: str


class UserResponse(BaseModel):
    """用户信息响应"""
    id: UUID
    username: str
    email: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    """Token 响应"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse
