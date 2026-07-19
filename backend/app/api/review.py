"""
面试复盘接口

支持：
- 获取面试复盘报告
- 生成面试分析（SSE 流式）
- 通过 agent_service 统一管理会话与对话记录持久化
- 复盘列表（含公司名/难度/时长/完成阶段完整字段）
- 逻辑删除面试记录（软删除 + 归属校验）
- 对话历史查询（完整还原面试问答过程）
"""

import json
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID

from ..db.session import get_db
from ..schemas.interview import InterviewResponse
from ..services.interview_service import InterviewService
from ..services.agent_service import AgentService
from ..api.auth import get_current_user
from ..models.user import User
from ..models.interview import Interview
from ..models.company import Company
from ..middleware.log import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/review", tags=["面试复盘"])


def get_agent_service(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AgentService:
    """获取 AgentService（注入 orchestrator + db）"""
    orch = getattr(request.app.state, "orchestrator", None)
    return AgentService(db=db, orchestrator=orch)


# 面试阶段中文标签映射（用于列表「完成阶段」字段展示）
STAGE_LABEL_MAP = {
    "intro": "开场白",
    "self_intro": "自我介绍",
    "tech_qa": "技术问答",
    "star_qa": "行为面试",
    "project_qa": "案例分析",
    "reverse_qa": "反问环节",
    "end": "已结束",
    "completed": "已完成",
}


def _calc_duration_minutes(interview: Interview) -> int:
    """根据 created_at 和 updated_at 计算面试时长（分钟）"""
    if not interview.created_at or not interview.updated_at:
        return 0
    delta = interview.updated_at - interview.created_at
    return max(0, int(delta.total_seconds() // 60))


def _calc_difficulty(interview: Interview) -> int:
    """根据面试评分推导难度等级（1-5 星）

    评分越高 → 难度感知越低；评分越低 → 难度感知越高。
    无评分时返回 0，前端展示「-」。
    """
    if interview.overall_score is None or interview.overall_score <= 0:
        return 0
    score = interview.overall_score
    if score >= 80:
        return 2
    if score >= 60:
        return 3
    if score >= 40:
        return 4
    return 5


@router.get("/{interview_id}")
async def get_review(
    interview_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取复盘报告"""
    service = InterviewService(db)
    interview = await service.get(interview_id)
    if not interview or interview.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="面试不存在")

    if interview.review_report:
        return {"report": interview.review_report}

    return {"report": None, "message": "复盘报告尚未生成"}


@router.post("/{interview_id}/generate")
async def generate_review(
    interview_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service),
):
    """生成复盘报告（SSE 流式）- 通过 agent_service 统一管理会话与对话记录持久化

    数据兜底策略：
    1. 优先使用 Interview.questions_answers（chat 端点已持久化）
    2. 若为空，从 Redis session_ctx.question_records 恢复并回写
    3. 仍为空才返回 400
    """
    service = InterviewService(db)
    interview = await service.get(interview_id)
    if not interview or interview.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="面试不存在")

    session_id = str(interview_id)
    orchestrator = getattr(request.app.state, "orchestrator", None)

    # 数据兜底：从 Redis session_ctx 恢复 questions_answers
    if not interview.questions_answers and orchestrator:
        try:
            session_ctx = await orchestrator._load_session(session_id) or {}
            question_records = session_ctx.get("question_records", [])
            if question_records:
                # 将 question_records 转换为 questions_answers 格式并回写
                qa_list = []
                for rec in question_records:
                    qa_list.append({
                        "question": rec.get("question", ""),
                        "answer": rec.get("answer", ""),
                        "score": rec.get("score", 0),
                        "feedback": rec.get("review", ""),
                    })
                if qa_list:
                    interview.questions_answers = qa_list
                    # 同步保存评分数据
                    total_score = session_ctx.get("total_score", 0)
                    section_scores = session_ctx.get("section_scores", {})
                    if total_score or section_scores:
                        interview.overall_score = total_score
                        interview.phase_scores = section_scores
                    interview.status = "completed"
                    await db.commit()
                    logger.info(f"从 Redis 恢复面试数据 interview_id={interview_id}，题数={len(qa_list)}")
        except Exception as e:
            logger.warning(f"从 Redis 恢复面试数据失败: {e}")

    if not interview.questions_answers:
        raise HTTPException(status_code=400, detail="暂无面试记录可供复盘")

    # 构建 user_config
    user_config = {
        "target_position": interview.position or "",
    }
    if interview.company_id:
        user_config["target_company_id"] = str(interview.company_id)

    full_report = []

    async def generate():
        # 通过 agent_service.stream_with_intent 统一管理 DB 持久化
        async for sse_str in agent_service.stream_with_intent(
            user=current_user,
            user_input="请复盘",
            intent="review",
            session_id=session_id,
            user_config=user_config,
        ):
            if sse_str.startswith("data: ") and sse_str.endswith("\n\n"):
                payload = sse_str[len("data: "):-2]
                try:
                    event = json.loads(payload)
                    etype = event.get("type")
                    if etype == "content":
                        chunk = event.get("content", "")
                        full_report.append(chunk)
                        yield f"data: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"
                    elif etype == "error":
                        yield f"data: {json.dumps({'type': 'error', 'message': event.get('message', '')}, ensure_ascii=False)}\n\n"
                    elif etype == "meta":
                        # 复盘通常不产生 META 信号，透传即可
                        pass
                except json.JSONDecodeError:
                    yield f"data: {payload}\n\n"
            else:
                yield sse_str

        # 保存报告到 Interview 表
        report_text = "".join(full_report)
        if report_text.strip():
            try:
                await service.save_review(interview_id, report_text)
                await db.commit()  # 立即提交，确保报告文本持久化（无论 JSON 解析是否成功）
            except Exception as e:
                logger.warning(f"保存复盘报告失败: {e}")
                await db.rollback()

            # 解析报告中的评分数据，同步保存到 interview 记录
            try:
                report_json = json.loads(report_text)
                overall_score = report_json.get("total_score", 0)
                section_scores = report_json.get("section_scores", {})
                if overall_score or section_scores:
                    await service.complete(interview_id, overall_score, section_scores)
                    await db.commit()
            except (json.JSONDecodeError, Exception):
                # 报告非 JSON 格式（如 markdown 文本），跳过评分同步，不影响报告保存
                pass

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


@router.get("/")
async def list_reviews(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取所有已完成面试的复盘摘要

    过滤规则：
    1. 仅展示有有效得分或有效岗位信息的记录，过滤完全无数据的脏记录
    2. 仅展示已完成或有复盘报告的记录
    3. 自动过滤已逻辑删除的记录（service.list_by_user 已处理）

    返回字段（前端列表完整填充）：
    - id, position, overall_score, has_review, created_at（原有）
    - company_id, company_name（目标公司，关联 Company 表）
    - difficulty（面试难度，1-5 星，0 表示无评分）
    - duration（面试时长，分钟，根据 created_at/updated_at 计算）
    - completed_stage（完成阶段中文标签，根据 phase 字段映射）
    """
    service = InterviewService(db)
    interviews = await service.list_by_user(current_user.id)

    # 批量预加载公司信息（避免 N+1 查询）
    company_ids = {iv.company_id for iv in interviews if iv.company_id}
    companies_map = {}
    if company_ids:
        result = await db.execute(
            select(Company).where(Company.id.in_(company_ids))
        )
        for c in result.scalars().all():
            companies_map[c.id] = c

    reviews = []
    for interview in interviews:
        # 跳过完全无数据的脏记录：无得分、无岗位、无问答记录
        has_score = interview.overall_score is not None and interview.overall_score > 0
        has_position = bool(interview.position and interview.position.strip())
        has_qa = bool(interview.questions_answers)
        if not (has_score or has_position or has_qa):
            continue
        # 仅展示已完成或有复盘报告的记录
        if interview.status != "completed" and not interview.review_report:
            continue

        # 公司信息
        company = companies_map.get(interview.company_id) if interview.company_id else None
        company_name = company.name if company else ""

        # 完成阶段中文标签
        completed_stage = STAGE_LABEL_MAP.get(interview.phase or "", interview.phase or "")

        reviews.append({
            "id": str(interview.id),
            "position": interview.position or "未知岗位",
            "overall_score": interview.overall_score or 0,
            "has_review": bool(interview.review_report),
            "created_at": interview.created_at.isoformat() if interview.created_at else None,
            # 新增完整字段
            "company_id": str(interview.company_id) if interview.company_id else None,
            "company_name": company_name,
            "difficulty": _calc_difficulty(interview),
            "duration": _calc_duration_minutes(interview),
            "completed_stage": completed_stage,
            # 复盘报告状态标记
            "status": interview.status,
        })
    return {"reviews": reviews}


@router.get("/{interview_id}/conversation")
async def get_conversation(
    interview_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取面试对话历史（完整还原整场面试问答过程）

    数据来源：Interview.questions_answers JSON 数组
    转换规则：
    - 每个 qa 项展开为 2-3 条消息：
      * AI 面试官提问题干（role=interviewer, content=question）
      * 候选人回答（role=user, content=answer）
      * AI 点评（role=interviewer, content=feedback，仅当 feedback 非空时添加）
    - 按 questions_answers 数组顺序正序排列，保证时间线正确

    异常处理：
    - 记录不存在或已删除 → 404
    - 非记录归属人 → 403
    - 无对话数据 → 200 + 空列表 + has_data=false

    返回结构：
    {
      "interview": {基础信息：公司/岗位/时间/时长},
      "messages": [{role, content, time}],
      "has_data": bool
    }
    """
    service = InterviewService(db)
    interview = await service.get(interview_id)

    # 存在性校验
    if not interview or interview.status == "deleted":
        raise HTTPException(status_code=404, detail="记录不存在或已被删除")

    # 归属校验
    if str(interview.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="无权限查看该面试记录")

    # 公司信息
    company_name = ""
    company_id = None
    if interview.company_id:
        result = await db.execute(
            select(Company).where(Company.id == interview.company_id)
        )
        company = result.scalar_one_or_none()
        if company:
            company_name = company.name
            company_id = str(company.id)

    # 构造对话消息列表
    messages = []
    qa_list = interview.questions_answers or []
    for idx, qa in enumerate(qa_list):
        if not isinstance(qa, dict):
            continue
        question = (qa.get("question") or "").strip()
        answer = (qa.get("answer") or "").strip()
        feedback = (qa.get("feedback") or "").strip()

        # AI 提问（必须有题干才输出）
        if question:
            messages.append({
                "role": "interviewer",
                "content": question,
                "type": "question",
                "index": idx,
            })
        # 用户回答
        if answer:
            messages.append({
                "role": "user",
                "content": answer,
                "type": "answer",
                "index": idx,
            })
        # AI 点评（仅当有反馈内容时输出）
        if feedback:
            messages.append({
                "role": "interviewer",
                "content": feedback,
                "type": "feedback",
                "index": idx,
            })

    return {
        "interview": {
            "id": str(interview.id),
            "company_id": company_id,
            "company_name": company_name,
            "position": interview.position or "",
            "created_at": interview.created_at.isoformat() if interview.created_at else None,
            "duration": _calc_duration_minutes(interview),
            "completed_stage": STAGE_LABEL_MAP.get(interview.phase or "", interview.phase or ""),
            "total_messages": len(messages),
        },
        "messages": messages,
        "has_data": len(messages) > 0,
    }


@router.delete("/{interview_id}")
async def delete_review(
    interview_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """逻辑删除面试复盘记录

    删除规则：
    1. 参数校验：record_id 非空且格式合法（UUID 类型由 FastAPI 自动校验）
    2. 存在性校验：记录不存在或已删除 → 404
    3. 权限校验：非记录归属人 → 403
    4. 逻辑删除：status='deleted'，关联数据（问答/评分/报告）一并隔离
    5. 列表查询自动过滤 status='deleted' 的记录

    返回值标准化：
    - 成功：{code: 200, msg: "删除成功"}
    - 失败：对应错误状态码 + 具体失败原因
    """
    service = InterviewService(db)
    try:
        success, message, _ = await service.soft_delete(interview_id, current_user.id)
        if not success:
            # 区分 404（不存在）和 403（无权限）
            if "无权限" in message:
                raise HTTPException(status_code=403, detail=message)
            raise HTTPException(status_code=404, detail=message)
        await db.commit()
        return {"code": 200, "msg": "删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"删除面试记录失败 interview_id={interview_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="系统异常，删除失败，请稍后重试")
