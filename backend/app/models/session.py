"""
Agent 会话与对话记录模型

- AgentSession: 会话主表，记录用户一次完整 Agent 会话
- AgentDialogueRecord: 对话明细表，记录会话中每轮 user/assistant 消息
"""

import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Text, DateTime, ForeignKey, Integer, JSON, Boolean
)
from sqlalchemy.orm import relationship

from ..db.session import Base
from ..db.types import GUID


class AgentSession(Base):
    """Agent 会话主表"""
    __tablename__ = "agent_sessions"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    # 业务 session_id（Redis 主键，字符串形式，与 UUID 解耦）
    session_id = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(GUID, ForeignKey("users.id"), nullable=False, index=True)

    # 会话元信息
    title = Column(String(200), default="")                # 会话标题（取首条消息摘要）
    task_type = Column(String(32), default="unknown")      # info_retrieve/resume_optimize/interview_session/interview_review
    target_agent = Column(String(32), default="unknown")   # retriever_agent/resume_agent/interview_agent/review_agent
    session_status = Column(String(16), default="new")     # new/ongoing/finished/error

    # 用户资产快照（简历/JD/意向公司等，JSON 存储）
    user_assets = Column(JSON, default=dict)
    # 会话上下文摘要（当前阶段、面试类型、难度等）
    context_summary = Column(JSON, default=dict)

    # 统计
    message_count = Column(Integer, default=0)             # 对话轮数
    auto_next_triggered = Column(Boolean, default=False)  # 是否触发了自动复盘联动

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)             # 会话结束时间

    # 关联
    user = relationship("User", backref="agent_sessions")
    dialogues = relationship(
        "AgentDialogueRecord",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="AgentDialogueRecord.seq",
    )

    def __repr__(self):
        return f"<AgentSession {self.session_id} status={self.session_status}>"


class AgentDialogueRecord(Base):
    """Agent 对话明细表"""
    __tablename__ = "agent_dialogue_records"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    session_pk = Column(
        GUID,
        ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    seq = Column(Integer, nullable=False)                  # 该会话内的消息序号（从 1 递增）

    role = Column(String(16), nullable=False)              # user / assistant / system
    content = Column(Text, nullable=False)                 # 消息内容
    agent_key = Column(String(32), nullable=True)          # 产生此消息的 agent（retriever_agent 等）
    event_type = Column(String(32), nullable=True)         # 事件类型（plan/task_start/data/done 等）

    # 元数据（如面试阶段、评分、token 用量等）
    meta = Column(JSON, default=dict)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # 关联
    session = relationship("AgentSession", back_populates="dialogues")

    def __repr__(self):
        return f"<AgentDialogueRecord seq={self.seq} role={self.role}>"
