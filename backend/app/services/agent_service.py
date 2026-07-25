"""
Agent 服务层

职责：
1. 适配 AgentOrchestrator（auto_route 流式事件 → 同步聚合 / SSE 转换）
2. 会话主表 agent_sessions CRUD
3. 对话明细 agent_dialogue_records 持久化
4. Redis 会话上下文双写（实时缓存 + 异步落库）

调用关系：
- sync_execute: 调用 orchestrator.auto_route 收集所有事件，聚合为单一结果
- stream_execute: 调用 orchestrator.auto_route，逐事件转 SSE
- Redis 由 orchestrator 内部维护，本服务只负责 DB 持久化与查询
"""

import json
import time
import uuid
from datetime import datetime
from typing import Optional, AsyncGenerator, Any

from sqlalchemy import select, update, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.session import AgentSession, AgentDialogueRecord
from ..models.user import User
from ..schemas.agent import (
    AgentSessionOut, AgentSessionDetailOut, DialogueRecordOut, SyncResultData,
)
from ..middleware.log import get_logger

logger = get_logger(__name__)

# 错误码常量
ERR_ORCHESTRATOR_NOT_READY = 5001
ERR_SESSION_NOT_FOUND = 4001
ERR_SESSION_FORBIDDEN = 4003
ERR_AGENT_EXEC_FAILED = 5002
ERR_PARAM_INVALID = 4000

# intent → agent_key 映射（与 orchestrator.INTENT_TO_AGENT 保持一致）
INTENT_TO_AGENT_MAP = {
    "interview": "interview_agent",
    "review": "review_agent",
    "resume": "resume_agent",
    "retrieve": "retriever_agent",
    "info_retrieve": "retriever_agent",
    "resume_optimize": "resume_agent",
    "interview_session": "interview_agent",
    "interview_review": "review_agent",
}

# intent → task_type 映射
INTENT_TO_TASK_TYPE = {
    "interview": "interview_session",
    "review": "interview_review",
    "resume": "resume_optimize",
    "retrieve": "info_retrieve",
    "info_retrieve": "info_retrieve",
    "resume_optimize": "resume_optimize",
    "interview_session": "interview_session",
    "interview_review": "interview_review",
}


class AgentService:
    """Agent 会话与对话服务"""

    def __init__(self, db: AsyncSession, orchestrator=None):
        self.db = db
        self.orchestrator = orchestrator

    # ==================== 会话主表 CRUD ====================

    async def create_session(
        self,
        user: User,
        session_id: str,
        task_type: str = "unknown",
        target_agent: str = "unknown",
        user_assets: Optional[dict] = None,
        title: str = "",
    ) -> AgentSession:
        """创建会话主表记录"""
        session = AgentSession(
            session_id=session_id,
            user_id=user.id,
            task_type=task_type,
            target_agent=target_agent,
            session_status="new",
            user_assets=user_assets or {},
            title=title or "新会话",
            message_count=0,
        )
        self.db.add(session)
        await self.db.flush()
        await self.db.refresh(session)
        logger.info(f"创建会话 session_id={session_id} user={user.username}")
        return session

    async def get_session_by_id(self, session_id: str) -> Optional[AgentSession]:
        """根据业务 session_id 查询会话"""
        result = await self.db.execute(
            select(AgentSession).where(AgentSession.session_id == session_id)
        )
        return result.scalar_one_or_none()

    async def list_sessions_by_user(
        self, user_id, skip: int = 0, limit: int = 20,
    ) -> tuple[list[AgentSession], int]:
        """分页查询用户会话列表"""
        base_query = select(AgentSession).where(AgentSession.user_id == user_id)
        # 总数
        count_q = select(func.count()).select_from(base_query.subquery())
        total = (await self.db.execute(count_q)).scalar() or 0
        # 分页
        items_q = base_query.order_by(AgentSession.created_at.desc()).offset(skip).limit(limit)
        items = list((await self.db.execute(items_q)).scalars().all())
        return items, total

    async def update_session_status(
        self, session_id: str, status: str,
        task_type: Optional[str] = None,
        target_agent: Optional[str] = None,
        context_summary: Optional[dict] = None,
        auto_next_triggered: Optional[bool] = None,
    ) -> Optional[AgentSession]:
        """更新会话状态"""
        values: dict = {"session_status": status, "updated_at": datetime.utcnow()}
        if status == "finished":
            values["ended_at"] = datetime.utcnow()
        if task_type:
            values["task_type"] = task_type
        if target_agent:
            values["target_agent"] = target_agent
        if context_summary is not None:
            values["context_summary"] = context_summary
        if auto_next_triggered is not None:
            values["auto_next_triggered"] = auto_next_triggered

        await self.db.execute(
            update(AgentSession)
            .where(AgentSession.session_id == session_id)
            .values(**values)
        )
        await self.db.flush()
        return await self.get_session_by_id(session_id)

    async def delete_session(self, session_id: str) -> bool:
        """删除会话及关联对话记录（级联删除）"""
        session = await self.get_session_by_id(session_id)
        if not session:
            return False
        await self.db.delete(session)
        await self.db.flush()
        return True

    # ==================== 对话明细持久化 ====================

    async def append_dialogue(
        self,
        session_pk,
        seq: int,
        role: str,
        content: str,
        agent_key: Optional[str] = None,
        event_type: Optional[str] = None,
        meta: Optional[dict] = None,
    ) -> AgentDialogueRecord:
        """追加一条对话记录"""
        record = AgentDialogueRecord(
            session_pk=session_pk,
            seq=seq,
            role=role,
            content=content,
            agent_key=agent_key,
            event_type=event_type,
            meta=meta or {},
        )
        self.db.add(record)
        # 同步更新会话主表 message_count
        await self.db.execute(
            update(AgentSession)
            .where(AgentSession.id == session_pk)
            .values(message_count=seq + 1, updated_at=datetime.utcnow())
        )
        await self.db.flush()
        return record

    async def list_dialogues(self, session_pk) -> list[AgentDialogueRecord]:
        """查询会话的所有对话记录"""
        result = await self.db.execute(
            select(AgentDialogueRecord)
            .where(AgentDialogueRecord.session_pk == session_pk)
            .order_by(AgentDialogueRecord.seq.asc())
        )
        return list(result.scalars().all())

    # ==================== 同步执行（聚合 auto_route 事件）====================

    async def sync_execute(
        self, user: User, user_input: str,
        session_id: Optional[str] = None,
        user_config: Optional[dict] = None,
    ) -> SyncResultData:
        """
        同步执行单任务：调用 orchestrator.auto_route 收集所有事件，聚合为单一结果

        :return: SyncResultData
        """
        if not self.orchestrator:
            raise RuntimeError("orchestrator 未就绪")

        session_id = session_id or f"sync-{uuid.uuid4().hex[:12]}"
        user_config = user_config or {}

        # 1. 创建/更新会话主表
        session = await self.get_session_by_id(session_id)
        if session is None:
            session = await self.create_session(
                user=user, session_id=session_id,
                user_assets=user_config, title=user_input[:30],
            )

        # 2. 写入 user 消息到 DB
        user_seq = (session.message_count or 0)
        await self.append_dialogue(
            session_pk=session.id, seq=user_seq + 1,
            role="user", content=user_input,
        )

        # 3. 调用 orchestrator.auto_route 收集事件
        collected_text_parts: list[str] = []
        plan_info: dict = {}
        final_status = "new"
        target_agent_key = "unknown"
        task_type = "unknown"
        response_to_user = ""
        auto_next_triggered = False
        assistant_seq = user_seq + 2

        try:
            async for event in self.orchestrator.auto_route(
                user_input, session_id=session_id,
                context={"user_assets": user_config},
            ):
                etype = event.get("type")
                if etype == "plan":
                    plan_info = event.get("plan", {})
                    target_agent_key = plan_info.get("target_agent", "unknown")
                    task_type = plan_info.get("task_type", "unknown")
                    response_to_user = plan_info.get("response_to_user", "")
                    final_status = plan_info.get("session_status", "ongoing")
                elif etype == "task_start":
                    resp = event.get("response_to_user")
                    if resp:
                        collected_text_parts.append(resp)
                        await self.append_dialogue(
                            session_pk=session.id, seq=assistant_seq,
                            role="assistant", content=resp,
                            agent_key=event.get("task"), event_type=etype,
                        )
                        assistant_seq += 1
                elif etype == "data":
                    content = event.get("content")
                    if isinstance(content, dict):
                        # 结构化结果（检索 JSON / 复盘报告）
                        text = json.dumps(content, ensure_ascii=False)
                    else:
                        text = str(content) if content else ""
                    if text:
                        collected_text_parts.append(text)
                        await self.append_dialogue(
                            session_pk=session.id, seq=assistant_seq,
                            role="assistant", content=text,
                            agent_key=target_agent_key, event_type=etype,
                            meta={"content_type": "dict" if isinstance(content, dict) else "str"},
                        )
                        assistant_seq += 1
                        # 检测面试结束信号
                        if (isinstance(content, dict)
                                and content.get("session_finished")
                                and target_agent_key == "interview_agent"):
                            auto_next_triggered = True
                            final_status = "finished"
                elif etype == "review_triggered":
                    auto_next_triggered = True
                    await self.append_dialogue(
                        session_pk=session.id, seq=assistant_seq,
                        role="system", content="[自动触发面试复盘]",
                        event_type=etype,
                    )
                    assistant_seq += 1
                elif etype == "error":
                    err_msg = event.get("message", "未知错误")
                    collected_text_parts.append(f"[错误] {err_msg}")
                    await self.append_dialogue(
                        session_pk=session.id, seq=assistant_seq,
                        role="system", content=err_msg,
                        event_type=etype, meta={"error": True},
                    )
                    assistant_seq += 1
                    final_status = "error"
                elif etype == "done":
                    final_status = event.get("session_status", final_status) or final_status
        except Exception as e:
            logger.error(f"sync_execute 失败 session={session_id}: {e}", exc_info=True)
            await self.update_session_status(session_id, "error")
            raise RuntimeError("服务暂时不可用，请稍后重试") from e

        # 4. 更新会话主表
        await self.update_session_status(
            session_id, final_status,
            task_type=task_type, target_agent=target_agent_key,
            context_summary=plan_info, auto_next_triggered=auto_next_triggered,
        )

        return SyncResultData(
            session_id=session_id,
            task_type=task_type,
            target_agent=target_agent_key,
            session_status=final_status,
            response_to_user=response_to_user,
            auto_next_triggered=auto_next_triggered,
            result="".join(collected_text_parts) if collected_text_parts else None,
        )

    # ==================== 流式执行（按 intent 路由，SSE）====================

    async def stream_with_intent(
        self, user: User, user_input: str,
        intent: str,
        session_id: Optional[str] = None,
        user_config: Optional[dict] = None,
    ) -> AsyncGenerator[str, None]:
        """
        按显式 intent 流式执行：调用 orchestrator.handle_message，同时做 DB 会话持久化

        与 stream_execute 的区别：
        - stream_execute 走 orchestrator.auto_route（Plan-Solve 全流程）
        - stream_with_intent 走 orchestrator.handle_message（显式 intent，跳过 Planner）

        适用于 interview.py / review.py / resume.py 等已明确 intent 的 API
        """
        if not self.orchestrator:
            yield self._sse({"type": "error", "message": "orchestrator 未就绪"})
            return

        session_id = session_id or f"intent-{uuid.uuid4().hex[:12]}"
        user_config = user_config or {}

        # 1. 创建/更新会话主表
        session = await self.get_session_by_id(session_id)
        if session is None:
            session = await self.create_session(
                user=user, session_id=session_id,
                task_type=self._intent_to_task_type(intent),
                target_agent=INTENT_TO_AGENT_MAP.get(intent, "unknown"),
                user_assets=user_config, title=user_input[:30],
            )

        # 2. 写入 user 消息
        user_seq = (session.message_count or 0)
        await self.append_dialogue(
            session_pk=session.id, seq=user_seq + 1,
            role="user", content=user_input,
        )
        await self.db.commit()

        # 3. 流式调用 orchestrator.handle_message
        assistant_seq = user_seq + 2
        final_status = "ongoing"
        target_agent_key = INTENT_TO_AGENT_MAP.get(intent, "unknown")

        # 批量累积 assistant 内容，流结束后一次性写入 DB（避免每 chunk 做 DB 写入导致 SSE 卡顿）
        assistant_chunks = []

        try:
            async for chunk in self.orchestrator.handle_message(
                session_id=session_id, message=user_input, intent=intent,
            ):
                # 处理 META 信号（解析后透传给前端，确保前端能读取字段）
                if isinstance(chunk, str) and chunk.startswith("\n\n__META__"):
                    meta = None
                    try:
                        meta = json.loads(chunk[len("\n\n__META__"):])
                        if meta.get("session_finished"):
                            final_status = "finished"
                        # Phase 14：review_agent 状态机信号
                        if meta.get("review_status") == "success":
                            final_status = "finished"
                        elif meta.get("review_status") == "fail":
                            final_status = "finished"  # 失败也标记为 finished，避免永久 ongoing
                    except Exception:
                        meta = None
                    # 传解析后的 dict 给前端，前端可直接读取 meta.question_index 等
                    if meta is not None:
                        yield self._sse({"type": "meta", "meta": meta})
                    continue

                # 普通文本内容：累积 + 立即透传（不阻塞 SSE 流）
                text = chunk if isinstance(chunk, str) else str(chunk)
                if text.strip():
                    assistant_chunks.append(text)
                yield self._sse({"type": "content", "content": chunk})

        except Exception as e:
            logger.error(f"stream_with_intent 失败 session={session_id}: {e}", exc_info=True)
            yield self._sse({"type": "error", "message": "服务暂时不可用，请稍后重试"})
            final_status = "error"
        finally:
            # 4. 批量写入 assistant 对话记录（流结束后一次性持久化，不阻塞 SSE）
            if assistant_chunks:
                try:
                    full_assistant_text = "".join(assistant_chunks)
                    await self.append_dialogue(
                        session_pk=session.id, seq=assistant_seq,
                        role="assistant", content=full_assistant_text,
                        agent_key=target_agent_key, event_type="data",
                    )
                except Exception as e:
                    logger.warning(f"批量写入 assistant 对话记录失败: {e}")

            # 5. 更新会话状态
            await self.update_session_status(session_id, final_status,
                                              task_type=self._intent_to_task_type(intent),
                                              target_agent=target_agent_key)
            try:
                await self.db.commit()
            except Exception as e:
                logger.warning(f"流式会话提交失败: {e}")
                await self.db.rollback()

    # ==================== 流式执行（auto_route，SSE）====================

    async def stream_execute(
        self, user: User, user_input: str,
        session_id: Optional[str] = None,
        user_config: Optional[dict] = None,
    ) -> AsyncGenerator[str, None]:
        """
        流式执行：调用 orchestrator.auto_route，逐事件转 SSE 格式字符串

        yield SSE 格式: data: {json}\n\n
        """
        if not self.orchestrator:
            yield self._sse({"type": "error", "message": "orchestrator 未就绪"})
            return

        session_id = session_id or f"stream-{uuid.uuid4().hex[:12]}"
        user_config = user_config or {}

        # 1. 创建/更新会话主表
        session = await self.get_session_by_id(session_id)
        if session is None:
            session = await self.create_session(
                user=user, session_id=session_id,
                user_assets=user_config, title=user_input[:30],
            )

        # 2. 写入 user 消息
        user_seq = (session.message_count or 0)
        await self.append_dialogue(
            session_pk=session.id, seq=user_seq + 1,
            role="user", content=user_input,
        )
        await self.db.commit()  # 先提交用户消息，保证持久化

        # 3. 流式调用 orchestrator.auto_route，实时转 SSE + 双写 DB
        assistant_seq = user_seq + 2
        final_status = "ongoing"
        target_agent_key = "unknown"
        task_type = "unknown"
        auto_next_triggered = False

        try:
            async for event in self.orchestrator.auto_route(
                user_input, session_id=session_id,
                context={"user_assets": user_config},
            ):
                etype = event.get("type")
                if etype == "plan":
                    plan = event.get("plan", {})
                    target_agent_key = plan.get("target_agent", "unknown")
                    task_type = plan.get("task_type", "unknown")
                    final_status = plan.get("session_status", "ongoing")
                    yield self._sse(event)
                elif etype == "task_start":
                    resp = event.get("response_to_user")
                    if resp:
                        await self.append_dialogue(
                            session_pk=session.id, seq=assistant_seq,
                            role="assistant", content=resp,
                            agent_key=event.get("task"), event_type=etype,
                        )
                        assistant_seq += 1
                    yield self._sse(event)
                elif etype == "data":
                    content = event.get("content")
                    if isinstance(content, dict):
                        text = json.dumps(content, ensure_ascii=False)
                        if content.get("session_finished") and target_agent_key == "interview_agent":
                            auto_next_triggered = True
                            final_status = "finished"
                    else:
                        text = str(content) if content else ""
                    if text:
                        await self.append_dialogue(
                            session_pk=session.id, seq=assistant_seq,
                            role="assistant", content=text,
                            agent_key=target_agent_key, event_type=etype,
                        )
                        assistant_seq += 1
                    yield self._sse(event)
                elif etype == "review_triggered":
                    auto_next_triggered = True
                    await self.append_dialogue(
                        session_pk=session.id, seq=assistant_seq,
                        role="system", content="[自动触发面试复盘]",
                        event_type=etype,
                    )
                    assistant_seq += 1
                    yield self._sse(event)
                elif etype == "error":
                    yield self._sse(event)
                elif etype == "done":
                    final_status = event.get("session_status", final_status) or final_status
                    yield self._sse(event)
        except Exception as e:
            logger.error(f"stream_execute 失败 session={session_id}: {e}", exc_info=True)
            yield self._sse({"type": "error", "message": "服务暂时不可用，请稍后重试"})
            final_status = "error"
        finally:
            # 4. 更新会话状态并提交
            await self.update_session_status(
                session_id, final_status,
                task_type=task_type, target_agent=target_agent_key,
                auto_next_triggered=auto_next_triggered,
            )
            try:
                await self.db.commit()
            except Exception as e:
                logger.warning(f"流式会话提交失败: {e}")
                await self.db.rollback()

    # ==================== 结束会话（面试场景触发复盘）====================

    async def end_session(
        self, user: User, session_id: str, trigger_review: bool = True,
    ) -> dict:
        """手动结束会话，面试场景自动触发复盘"""
        session = await self.get_session_by_id(session_id)
        if not session:
            return {"ok": False, "code": ERR_SESSION_NOT_FOUND, "message": "会话不存在"}
        if session.user_id != user.id:
            return {"ok": False, "code": ERR_SESSION_FORBIDDEN, "message": "无权操作此会话"}

        review_result = None
        # 仅面试类会话且需触发复盘时执行
        if (trigger_review and session.target_agent == "interview_agent"
                and session.session_status != "finished"):
            try:
                review_params = {
                    "session_id": session_id,
                    "transcript": [],  # orchestrator 会从 Redis 加载历史
                    "source": "manual_end",
                }
                async for event in self.orchestrator.auto_route(
                    "请生成面试复盘报告", session_id=session_id,
                    context={"force_review": True, **review_params},
                ):
                    if event.get("type") == "data":
                        review_result = event.get("content")
            except Exception as e:
                logger.error(f"结束会话触发复盘失败: {e}", exc_info=True)

        await self.update_session_status(session_id, "finished")
        return {"ok": True, "review_result": review_result}

    # ==================== 健康检查 ====================

    def health_check(self) -> dict:
        """检查 orchestrator 与各子 Agent 初始化状态"""
        orch = self.orchestrator
        if not orch:
            return {
                "orchestrator_ready": False,
                "vector_store": False, "embedder": False,
                "redis": False, "db": True,
                "llm_enabled": False,
                "agents": {},
                "degraded_mode": True,
            }
        agents_status = {}
        for key, agent in (orchestrator_agents := getattr(orch, "agents", {}) or {}).items():
            agents_status[key] = agent is not None

        return {
            "orchestrator_ready": True,
            "vector_store": getattr(orch, "vector_store", None) is not None,
            "embedder": getattr(orch, "embedder", None) is not None,
            "redis": getattr(orch, "redis", None) is not None,
            "db": self.db is not None,
            "llm_enabled": bool(getattr(orch, "llm_api_key", "")),
            "agents": agents_status,
            "degraded_mode": not bool(getattr(orch, "llm_api_key", "")),
        }

    # ==================== 工具方法 ====================

    @staticmethod
    def _intent_to_task_type(intent: str) -> str:
        """将 intent 映射为 task_type"""
        return INTENT_TO_TASK_TYPE.get(intent, "unknown")

    @staticmethod
    def _sse(event: dict) -> str:
        """将事件 dict 转为 SSE data 行"""
        return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

    @staticmethod
    def to_session_out(session: AgentSession) -> AgentSessionOut:
        return AgentSessionOut.model_validate(session)

    async def to_session_detail_out(self, session: AgentSession) -> AgentSessionDetailOut:
        dialogues = await self.list_dialogues(session.id)
        return AgentSessionDetailOut(
            id=session.id, session_id=session.session_id, user_id=session.user_id,
            title=session.title, task_type=session.task_type,
            target_agent=session.target_agent, session_status=session.session_status,
            message_count=session.message_count,
            auto_next_triggered=session.auto_next_triggered,
            created_at=session.created_at, updated_at=session.updated_at,
            ended_at=session.ended_at,
            user_assets=session.user_assets or {},
            context_summary=session.context_summary or {},
            dialogues=[DialogueRecordOut.model_validate(d) for d in dialogues],
        )
