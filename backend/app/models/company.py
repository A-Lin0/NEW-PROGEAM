"""
公司信息模型
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Float
from sqlalchemy.orm import relationship

from ..db.session import Base
from ..db.types import GUID


class Company(Base):
    __tablename__ = "companies"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False, index=True)
    industry = Column(String(100))
    size = Column(String(50))  # 公司规模
    location = Column(String(200))
    description = Column(Text)
    culture = Column(Text)     # 企业文化
    benefits = Column(Text)    # 福利待遇
    website = Column(String(300))

    # 面试相关
    interview_process = Column(Text)  # 面试流程
    avg_difficulty = Column(Float, default=0.0)  # 平均难度
    avg_salary = Column(String(50))

    # 文档路径
    doc_path = Column(String(500))

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联
    interviews = relationship("Interview", back_populates="company")

    def __repr__(self):
        return f"<Company {self.name}>"
