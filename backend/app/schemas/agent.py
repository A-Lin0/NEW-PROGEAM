"""
Agent 接口 Pydantic 模型

请求体 / 响应体定义，字段完整校验
统一响应格式: {"code":0, "message":"", "data":{}}
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, Any, List
from datetime import datetime
from uuid import UUID


# ==================== 通用响应 ====================

class ApiResponse(BaseModel):
    """统一响应格式"""
    code: int = Field(0, description="0=成功，非0=失败")
    message: str = Field("", description="可读错误信息")
    data: Optional[Any] = Field(None, description="业务数据")

    @classmethod
    def success(cls, data: Any = None, message: str = "ok") -> "ApiResponse":
        return cls(code=0, message=message, data=data)

    @classmethod
    def error(cls, code: int = 500, message: str = "服务异常", data: Any = None) -> "ApiResponse":
        return cls(code=code, message=message, data=data)


# ==================== 请求体 ====================

class AgentSyncRequest(BaseModel):
    """同步执行请求（检索/简历优化/复盘）"""
    user_input: str = Field(..., min_length=1, max_length=5000, description="用户输入文本")
    session_id: Optional[str] = Field(None, description="会话 ID，为空则新建")
    user_config: dict = Field(
        default_factory=dict,
        description="用户资产与配置：resume_text/jd_text/target_company/target_position 等"
    )

    @field_validator("user_input")
    @classmethod
    def strip_input(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("user_input 不能为空白")
        return v


class AgentStreamRequest(BaseModel):
    """流式执行请求（面试模拟/流式简历优化）"""
    user_input: str = Field(..., min_length=1, max_length=5000, description="用户输入文本")
    session_id: Optional[str] = Field(None, description="会话 ID，为空则新建")
    user_config: dict = Field(
        default_factory=dict,
        description="用户资产与配置"
    )

    @field_validator("user_input")
    @classmethod
    def strip_input(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("user_input 不能为空白")
        return v


class SessionEndRequest(BaseModel):
    """结束会话请求"""
    trigger_review: bool = Field(
        True, description="是否触发面试复盘联动（面试场景自动串联 review_agent）"
    )


# ==================== 响应体 ====================

class DialogueRecordOut(BaseModel):
    """对话明细响应"""
    id: UUID
    seq: int
    role: str
    content: str
    agent_key: Optional[str] = None
    event_type: Optional[str] = None
    meta: dict = {}
    created_at: datetime

    class Config:
        from_attributes = True


class AgentSessionOut(BaseModel):
    """会话响应"""
    id: UUID
    session_id: str
    user_id: UUID
    title: str
    task_type: str
    target_agent: str
    session_status: str
    message_count: int
    auto_next_triggered: bool
    created_at: datetime
    updated_at: datetime
    ended_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AgentSessionDetailOut(AgentSessionOut):
    """会话详情（含对话历史）"""
    user_assets: dict = {}
    context_summary: dict = {}
    dialogues: List[DialogueRecordOut] = []


class SyncResultData(BaseModel):
    """同步执行结果数据"""
    session_id: str
    task_type: str
    target_agent: str
    session_status: str
    response_to_user: str = ""
    auto_next_triggered: bool = False
    result: Any = None


class HealthData(BaseModel):
    """健康检查数据"""
    orchestrator_ready: bool
    vector_store: bool
    embedder: bool
    redis: bool
    db: bool
    llm_enabled: bool
    agents: dict = {}
    degraded_mode: bool = False
