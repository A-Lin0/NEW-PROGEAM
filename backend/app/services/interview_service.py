"""
面试模拟业务逻辑层
"""

from typing import Optional, AsyncGenerator
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..models.interview import Interview


class InterviewService:
    """面试服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        user_id: UUID,
        company_id: Optional[UUID] = None,
        position: str = "",
    ) -> Interview:
        """创建面试会话"""
        interview = Interview(
            user_id=user_id,
            company_id=company_id,
            position=position,
            status="in_progress",
            questions_answers=[],
            phase="intro",
        )
        self.db.add(interview)
        await self.db.flush()
        await self.db.refresh(interview)
        return interview

    async def get(self, interview_id: UUID) -> Optional[Interview]:
        """获取面试"""
        result = await self.db.execute(
            select(Interview).where(Interview.id == interview_id)
        )
        return result.scalar_one_or_none()

    async def list_by_user(
        self, user_id: UUID, skip: int = 0, limit: int = 100
    ) -> list[Interview]:
        """获取用户的面试列表（自动过滤已逻辑删除的记录）"""
        result = await self.db.execute(
            select(Interview)
            .where(Interview.user_id == user_id)
            .where(Interview.status != "deleted")  # 过滤逻辑删除记录
            .order_by(Interview.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def add_qa(
        self,
        interview_id: UUID,
        question: str,
        answer: str,
        score: Optional[float] = None,
        feedback: str = "",
    ) -> Optional[dict]:
        """添加问答记录"""
        interview = await self.get(interview_id)
        if not interview:
            return None

        qa = {
            "question": question,
            "answer": answer,
            "score": score,
            "feedback": feedback,
        }
        qa_list = interview.questions_answers or []
        qa_list.append(qa)
        interview.questions_answers = qa_list
        await self.db.flush()
        return qa

    async def update_phase(
        self, interview_id: UUID, phase: str
    ) -> Optional[Interview]:
        """更新面试阶段"""
        interview = await self.get(interview_id)
        if interview:
            interview.phase = phase
            await self.db.flush()
            await self.db.refresh(interview)
        return interview

    async def complete(
        self,
        interview_id: UUID,
        overall_score: float,
        phase_scores: dict,
    ) -> Optional[Interview]:
        """完成面试并记录分数"""
        interview = await self.get(interview_id)
        if interview:
            interview.status = "completed"
            interview.overall_score = overall_score
            interview.phase_scores = phase_scores
            await self.db.flush()
            await self.db.refresh(interview)
        return interview

    async def save_review(
        self, interview_id: UUID, report: str
    ) -> Optional[Interview]:
        """保存复盘报告"""
        interview = await self.get(interview_id)
        if interview:
            interview.review_report = report
            await self.db.flush()
            await self.db.refresh(interview)
        return interview

    async def soft_delete(
        self, interview_id: UUID, user_id: UUID
    ) -> tuple[bool, str, Optional[Interview]]:
        """逻辑删除面试记录（含权限校验）

        级联处理：将主记录 status 设为 'deleted'，
        关联的问答、评分、复盘报告通过主记录状态一并失效，
        避免孤立脏数据。

        :return: (success, message, interview)
        """
        interview = await self.get(interview_id)
        if not interview:
            return False, "目标记录不存在或已删除", None

        # 权限校验：仅允许删除自己的记录
        if str(interview.user_id) != str(user_id):
            return False, "无权限执行该操作", None

        # 已删除状态校验
        if interview.status == "deleted":
            return False, "目标记录不存在或已删除", None

        # 执行逻辑删除：标记主记录
        interview.status = "deleted"
        # 清空敏感内容（保留记录骨架用于回溯，但前端不再展示）
        # 注意：不清理 questions_answers/phase_scores/review_report，
        # 保留数据可回溯能力，但通过 status='deleted' 隔离
        await self.db.flush()
        await self.db.refresh(interview)
        return True, "删除成功", interview
