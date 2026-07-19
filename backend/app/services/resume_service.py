"""
简历优化业务逻辑层
"""

from typing import Optional, AsyncGenerator
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..models.resume import Resume
from ..schemas.resume import ResumeCreate


class ResumeService:
    """简历服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, user_id: UUID, data: ResumeCreate) -> Resume:
        """创建新简历"""
        resume = Resume(user_id=user_id, **data.model_dump())
        self.db.add(resume)
        await self.db.flush()
        await self.db.refresh(resume)
        return resume

    async def get(self, resume_id: UUID) -> Optional[Resume]:
        """获取简历"""
        result = await self.db.execute(
            select(Resume).where(Resume.id == resume_id)
        )
        return result.scalar_one_or_none()

    async def list_by_user(
        self, user_id: UUID, skip: int = 0, limit: int = 10
    ) -> list[Resume]:
        """获取用户的简历列表"""
        result = await self.db.execute(
            select(Resume)
            .where(Resume.user_id == user_id)
            .order_by(Resume.updated_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def update(
        self, resume_id: UUID, data: ResumeCreate
    ) -> Optional[Resume]:
        """更新简历（新建版本）"""
        original = await self.get(resume_id)
        if not original:
            return None

        # 创建新版本
        new_version = Resume(
            user_id=original.user_id,
            title=data.title,
            version=original.version + 1,
            summary=data.summary,
            experience=data.experience,
            education=data.education,
            skills=data.skills,
            projects=data.projects,
            certificates=data.certificates,
            target_company=data.target_company,
            target_position=data.target_position,
            raw_text=data.raw_text,
        )
        self.db.add(new_version)
        await self.db.flush()
        await self.db.refresh(new_version)
        return new_version

    async def delete(self, resume_id: UUID) -> bool:
        """删除简历"""
        resume = await self.get(resume_id)
        if resume:
            await self.db.delete(resume)
            await self.db.flush()
            return True
        return False

    async def save_suggestions(
        self, resume_id: UUID, suggestions: str, score: int
    ) -> Optional[Resume]:
        """保存 AI 建议到简历"""
        resume = await self.get(resume_id)
        if resume:
            resume.ai_suggestions = suggestions
            resume.score = score
            await self.db.flush()
            await self.db.refresh(resume)
        return resume

    async def optimize_section(
        self, content: str, section_type: str, resume_agent
    ) -> AsyncGenerator[str, None]:
        """调用 Agent 进行段落优化（流式）"""
        async for chunk in resume_agent.optimize_section(content, section_type):
            yield chunk

    async def analyze_resume(
        self, content: str, job_description: str, resume_agent
    ) -> AsyncGenerator[str, None]:
        """调用 Agent 分析简历（流式）"""
        async for chunk in resume_agent.analyze_resume(content, job_description):
            yield chunk
