"""
简历模型
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Integer, JSON
from sqlalchemy.orm import relationship

from ..db.session import Base
from ..db.types import GUID


class Resume(Base):
    __tablename__ = "resumes"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID, ForeignKey("users.id"), nullable=False)
    title = Column(String(200), nullable=False)
    version = Column(Integer, default=1)

    # 简历各部分内容
    summary = Column(Text)         # 个人总结
    experience = Column(JSON)      # 工作经历 [{company, position, start, end, description}]
    education = Column(JSON)       # 教育背景 [{school, degree, major, start, end}]
    skills = Column(JSON)          # 技能列表
    projects = Column(JSON)        # 项目经历
    certificates = Column(JSON)    # 证书/奖项

    # 优化建议与评分
    ai_suggestions = Column(Text)  # AI 优化建议
    score = Column(Integer)

    # 目标公司/岗位
    target_company = Column(String(200))
    target_position = Column(String(200))

    raw_text = Column(Text)        # 原始文本
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联
    user = relationship("User", back_populates="resumes")

    def __repr__(self):
        return f"<Resume {self.title} v{self.version}>"
