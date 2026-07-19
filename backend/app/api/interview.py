"""
面试模拟接口 (SSE 流式)

支持：
- 创建/获取面试会话
- 开始面试
- 提交回答（流式评估）
- 下一题/跳过
- 结束面试
- 会话状态恢复（从 Redis/文件持久化）
- 会话重置
"""

import json
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from uuid import UUID

from ..db.session import get_db
from ..schemas.interview import (
    InterviewStart, InterviewAnswer, InterviewCommand, InterviewResponse
)
from ..services.interview_service import InterviewService
from ..services.agent_service import AgentService
from ..api.auth import get_current_user
from ..models.user import User
from ..middleware.log import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/interview", tags=["面试模拟"])


def get_agent_service(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AgentService:
    """获取 AgentService（注入 orchestrator + db）"""
    orch = getattr(request.app.state, "orchestrator", None)
    return AgentService(db=db, orchestrator=orch)


@router.post("/", response_model=InterviewResponse, status_code=201)
async def start_interview(
    data: InterviewStart,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建面试会话"""
    service = InterviewService(db)
    interview = await service.create(
        user_id=current_user.id,
        company_id=data.company_id,
        position=data.position or "",
    )
    logger.info(f"用户 {current_user.username} 开始面试: {interview.id}")
    return interview


@router.get("/", response_model=list[InterviewResponse])
async def list_interviews(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取面试历史"""
    service = InterviewService(db)
    return await service.list_by_user(current_user.id)


@router.get("/{interview_id}", response_model=InterviewResponse)
async def get_interview(
    interview_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取面试详情"""
    service = InterviewService(db)
    interview = await service.get(interview_id)
    if not interview or interview.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="面试不存在")
    return interview


@router.post("/{interview_id}/chat")
async def interview_chat(
    interview_id: UUID,
    data: InterviewAnswer,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service),
):
    """面试对话（SSE 流式）- 通过 agent_service 统一管理会话与对话记录持久化"""
    service = InterviewService(db)
    interview = await service.get(interview_id)
    if not interview or interview.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="面试不存在")

    orchestrator = request.app.state.orchestrator
    session_id = data.session_id or str(interview_id)

    # 构建 user_config（岗位、公司信息）供 agent_service 持久化
    user_config = {
        "target_position": interview.position or "",
    }
    if interview.company_id:
        user_config["target_company_id"] = str(interview.company_id)
        try:
            from backend.app.models.company import Company
            from sqlalchemy import select
            company_result = await db.execute(
                select(Company.name).where(Company.id == interview.company_id)
            )
            company_name = company_result.scalar_one_or_none()
            if company_name:
                user_config["target_company"] = company_name
        except Exception:
            pass

    async def generate():
        # 确保岗位信息已注入 Redis 会话上下文
        session_ctx = await orchestrator._load_session(session_id) or {}
        user_assets = session_ctx.get("user_assets", {})
        if not user_assets.get("target_position") and interview.position:
            user_assets["target_position"] = interview.position
            if interview.company_id:
                user_assets["target_company_id"] = str(interview.company_id)
                if user_config.get("target_company"):
                    user_assets["target_company"] = user_config["target_company"]
            session_ctx["user_assets"] = user_assets
            await orchestrator._save_session(session_id, session_ctx)

        full_question_parts = []
        # 通过 agent_service.stream_with_intent 统一管理 DB 持久化
        async for sse_str in agent_service.stream_with_intent(
            user=current_user,
            user_input=data.answer,
            intent="interview",
            session_id=session_id,
            user_config=user_config,
        ):
            # sse_str 格式: "data: {...}\n\n"
            if sse_str.startswith("data: ") and sse_str.endswith("\n\n"):
                payload = sse_str[len("data: "):-2]
                try:
                    event = json.loads(payload)
                    etype = event.get("type")
                    if etype == "meta":
                        # META 信号透传给前端做 UI 同步
                        # agent_service 已解析为 dict，直接转发
                        meta = event.get("meta")
                        if isinstance(meta, dict):
                            yield f"data: {json.dumps({'type': 'meta', 'meta': meta}, ensure_ascii=False)}\n\n"
                            # 检测面试自然结束信号（reverse_qa 答完自动结束）：保存评分数据到 Interview 表
                            if meta.get("session_finished"):
                                try:
                                    total_score = meta.get("total_score")
                                    section_scores = meta.get("section_scores")
                                    if total_score is not None and section_scores:
                                        await service.complete(
                                            interview_id, total_score, section_scores
                                        )
                                        await db.commit()
                                except Exception as e:
                                    logger.warning(f"保存面试评分失败: {e}")
                        continue
                    elif etype == "content":
                        chunk = event.get("content", "")
                        full_question_parts.append(chunk)
                        yield f"data: {json.dumps({'type': 'content', 'content': chunk}, ensure_ascii=False)}\n\n"
                    elif etype == "error":
                        yield f"data: {json.dumps({'type': 'error', 'message': event.get('message', '')}, ensure_ascii=False)}\n\n"
                except json.JSONDecodeError:
                    yield f"data: {payload}\n\n"
            else:
                yield sse_str

        # 持久化问答记录到 Interview 表（兼容旧数据结构）
        question_text = "".join(full_question_parts).strip()
        if question_text:
            try:
                await service.add_qa(
                    interview_id,
                    question=question_text,
                    answer=data.answer or "",
                )
                await db.commit()
            except Exception as e:
                logger.warning(f"保存问答记录失败: {e}")
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{interview_id}/session-state")
async def get_session_state(
    interview_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """获取面试会话状态（用于用户切换页面后恢复面试进度）

    优先从 Redis 读取，Redis 不可用时从文件持久化恢复
    """
    orchestrator = request.app.state.orchestrator
    session_id = str(interview_id)
    session_ctx = await orchestrator._load_session(session_id) or {}

    # 如果 Redis 中没有数据，尝试从文件恢复
    if not session_ctx or not session_ctx.get("history"):
        file_data = orchestrator.get_persisted_history(session_id)
        if file_data:
            session_ctx = file_data
            # 回写到 Redis，恢复会话状态
            await orchestrator._save_session(session_id, session_ctx)

    history = session_ctx.get("history", [])
    # 计算全局题号（与 META 的 question_index 保持一致）
    # session_ctx 中 question_index 是阶段本地，需转换为全局
    current_stage = session_ctx.get("current_stage", "init")
    stage_q_index = session_ctx.get("question_index", 0)
    # STAGE_START_INDEX 与 interview_agent 中定义一致
    STAGE_START_INDEX = {
        "self_intro": 0, "tech_qa": 1, "star_qa": 4,
        "project_qa": 6, "reverse_qa": 9, "init": 0, "end": 10,
    }
    TOTAL_QUESTIONS = 10
    if current_stage == "end":
        global_q_index = TOTAL_QUESTIONS - 1
    else:
        global_q_index = STAGE_START_INDEX.get(current_stage, 0) + stage_q_index
    global_q_index = max(0, min(global_q_index, TOTAL_QUESTIONS - 1))

    return {
        "session_id": session_id,
        "session_status": session_ctx.get("session_status", "new"),
        "current_stage": current_stage,
        "question_index": global_q_index,
        "stage_question_index": stage_q_index,
        "total_questions": TOTAL_QUESTIONS,
        "question_records": session_ctx.get("question_records", []),
        "stage_scores": session_ctx.get("stage_scores", {}),
        "total_score": session_ctx.get("total_score", 0),
        "section_scores": session_ctx.get("section_scores", {}),
        "completed_stages": session_ctx.get("completed_stages", []),
        "user_assets": session_ctx.get("user_assets", {}),
        "messages_count": len(history),
        "history": [{"role": h.get("role", "interviewer"), "content": h.get("content", ""), "time": h.get("time", None)} for h in history],
        "persisted": True,  # 标记是否从文件恢复
    }


@router.post("/{interview_id}/reset")
async def reset_interview_session(
    interview_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """重置面试会话：清空对话历史、阶段进度、题目计数，开启全新面试
    
    同时清理 Redis 缓存和文件持久化数据
    """
    service = InterviewService(db)
    interview = await service.get(interview_id)
    if not interview or interview.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="面试不存在")

    orchestrator = request.app.state.orchestrator
    session_id = str(interview_id)

    # 1. 重置 Redis 会话数据
    result = await orchestrator.interview_agent.reset_session(session_id)

    # 2. 清理文件持久化数据
    if result.get("success"):
        orchestrator.delete_persisted_history(session_id)
        try:
            await service.update_phase(interview_id, "pending")
            await db.commit()
        except Exception as e:
            logger.warning(f"重置后更新面试状态失败: {e}")

    return result


@router.post("/{interview_id}/command")
async def interview_command(
    interview_id: UUID,
    data: InterviewCommand,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service),
):
    """面试控制命令（开始/下一题/跳过/结束）- 通过 agent_service 统一管理会话与对话记录持久化"""
    service = InterviewService(db)
    interview = await service.get(interview_id)
    if not interview or interview.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="面试不存在")

    orchestrator = request.app.state.orchestrator
    session_id = data.session_id or str(interview_id)

    # 构建 user_config
    user_config = {
        "target_position": interview.position or "",
    }
    if interview.company_id:
        user_config["target_company_id"] = str(interview.company_id)
        try:
            from backend.app.models.company import Company
            from sqlalchemy import select
            company_result = await db.execute(
                select(Company.name).where(Company.id == interview.company_id)
            )
            company_name = company_result.scalar_one_or_none()
            if company_name:
                user_config["target_company"] = company_name
        except Exception:
            pass

    # 确定消息文本
    if data.command == "start":
        message = "开始面试"
    elif data.command == "next":
        message = "下一题"
    elif data.command == "skip":
        message = "下一题"
    elif data.command == "end":
        message = "结束面试"
    else:
        message = data.command

    async def generate():
        # 注入岗位和公司信息到 Redis 会话上下文
        if data.command == "start":
            session_ctx = await orchestrator._load_session(session_id) or {}
            user_assets = session_ctx.get("user_assets", {})
            user_assets["target_position"] = interview.position or ""
            if interview.company_id:
                user_assets["target_company_id"] = str(interview.company_id)
                if user_config.get("target_company"):
                    user_assets["target_company"] = user_config["target_company"]
            session_ctx["user_assets"] = user_assets
            await orchestrator._save_session(session_id, session_ctx)

        if data.command == "end":
            try:
                await service.update_phase(interview_id, "completed")
                await db.commit()
            except Exception as e:
                logger.warning(f"更新面试阶段失败: {e}")

        # 收集面试官话术（end 命令时用于保存结束语到 questions_answers）
        full_question_parts = []

        # 通过 agent_service.stream_with_intent 统一管理 DB 持久化
        async for sse_str in agent_service.stream_with_intent(
            user=current_user,
            user_input=message,
            intent="interview",
            session_id=session_id,
            user_config=user_config,
        ):
            if sse_str.startswith("data: ") and sse_str.endswith("\n\n"):
                payload = sse_str[len("data: "):-2]
                try:
                    event = json.loads(payload)
                    etype = event.get("type")
                    if etype == "meta":
                        # META 信号透传给前端做 UI 同步
                        # agent_service 已解析为 dict，直接转发
                        meta = event.get("meta")
                        if isinstance(meta, dict):
                            yield f"data: {json.dumps({'type': 'meta', 'meta': meta}, ensure_ascii=False)}\n\n"
                            # 检测面试结束信号：保存评分数据到 Interview 表
                            if meta.get("session_finished") and data.command == "end":
                                try:
                                    total_score = meta.get("total_score")
                                    section_scores = meta.get("section_scores")
                                    if total_score is not None and section_scores:
                                        await service.complete(
                                            interview_id, total_score, section_scores
                                        )
                                        await db.commit()
                                except Exception as e:
                                    logger.warning(f"保存面试评分失败: {e}")
                        continue
                    elif etype == "content":
                        chunk = event.get("content", "")
                        full_question_parts.append(chunk)
                        yield f"data: {json.dumps({'type': 'content', 'content': chunk}, ensure_ascii=False)}\n\n"
                    elif etype == "error":
                        yield f"data: {json.dumps({'type': 'error', 'message': event.get('message', '')}, ensure_ascii=False)}\n\n"
                except json.JSONDecodeError:
                    yield f"data: {payload}\n\n"
            else:
                yield sse_str

        # end 命令：将面试官结束语保存到 questions_answers，确保复盘时有数据
        if data.command == "end":
            end_text = "".join(full_question_parts).strip()
            if end_text:
                try:
                    await service.add_qa(
                        interview_id,
                        question=end_text,
                        answer="（面试结束）",
                    )
                    await db.commit()
                except Exception as e:
                    logger.warning(f"保存面试结束语失败: {e}")

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
