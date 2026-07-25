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
from datetime import datetime, timezone
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


def _to_iso_with_tz(dt) -> str:
    """将数据库中的 naive UTC 时间转换为带时区的 ISO 字符串

    数据库列定义为 ``default=datetime.utcnow``，存储的是无时区的 UTC 时间。
    直接 ``isoformat()`` 会得到 ``2026-07-20T07:30:45``（无时区标识），
    前端 ``new Date()`` 会将其误判为本地时间，导致显示比实际慢 8 小时。

    本函数显式为其附加 ``+00:00`` 时区标识，前端解析后可自动转换为本地时间。
    """
    if dt is None:
        return None
    # 已经带时区的时间直接 isoformat
    if dt.tzinfo is not None:
        return dt.isoformat()
    # naive UTC 时间 → 显式标注 UTC
    return dt.replace(tzinfo=timezone.utc).isoformat()


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


def _calc_duration_seconds(interview: Interview) -> int:
    """根据 created_at 和 updated_at 计算面试时长（秒）"""
    if not interview.created_at or not interview.updated_at:
        return 0
    delta = interview.updated_at - interview.created_at
    return max(0, int(delta.total_seconds()))


# 复盘评估JSON的关键字段集合（用于识别混入消息流的评估对象）
_EVALUATION_KEYS = {
    "total_score", "section_scores", "stage_analysis",
    "question_by_question", "overall_problems",
    "improvement_plan", "overall_comment",
    "dimension_scores", "dimension_improvements",
    "stages",
}


def _try_parse_evaluation(content: str):
    """检测 content 是否为复盘评估 JSON 对象

    返回：
    - 解析成功的 dict（命中评估字段）→ 返回该 dict
    - 解析失败或非评估对象 → 返回 None
    """
    if not content:
        return None
    text = content.strip()
    # 必须以 { 开头、} 结尾才可能是 JSON 对象
    if not (text.startswith("{") and text.endswith("}")):
        return None
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    # 命中任意评估字段即判定为评估对象
    if _EVALUATION_KEYS & set(obj.keys()):
        return obj
    return None


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
        raise HTTPException(status_code=400, detail="本场面试无有效答题记录，无法重新生成报告")

    # Phase 14 修复：重新生成前确保 Redis session_ctx 中的评分数据完整
    # 避免 session_ctx 中 total_score/section_scores/question_records 丢失导致重新生成时评分为0
    if orchestrator:
        try:
            session_ctx = await orchestrator._load_session(session_id) or {}
            # 从 Interview 表恢复 question_records 到 session_ctx
            if not session_ctx.get("question_records") and interview.questions_answers:
                session_ctx["question_records"] = [
                    {
                        "stage": qa.get("stage", ""),
                        "question": qa.get("question", ""),
                        "answer": qa.get("answer", ""),
                        "review": qa.get("feedback", ""),
                        "score": qa.get("score", 0),
                        "skipped": not qa.get("answer", "").strip(),
                    }
                    for qa in interview.questions_answers
                ]
            # 从 Interview 表恢复评分数据到 session_ctx
            if not session_ctx.get("total_score") and interview.overall_score:
                session_ctx["total_score"] = interview.overall_score
            if not session_ctx.get("section_scores") and interview.phase_scores:
                session_ctx["section_scores"] = interview.phase_scores
            # 确保岗位和公司信息完整
            session_ctx["target_position"] = (
                session_ctx.get("target_position")
                or interview.position
                or ""
            )
            user_assets = session_ctx.get("user_assets", {})
            user_assets["target_position"] = session_ctx["target_position"]
            if interview.target_company_name:
                session_ctx["target_company"] = interview.target_company_name
                user_assets["target_company"] = interview.target_company_name
            session_ctx["user_assets"] = user_assets
            # 重置 session_status 为 finished（确保 planner 路由到 review_agent）
            session_ctx["session_status"] = "finished"
            await orchestrator._save_session(session_id, session_ctx)
            logger.info(
                f"重新生成前同步 session_ctx | interview_id={interview_id} "
                f"questions={len(session_ctx.get('question_records', []))} "
                f"total_score={session_ctx.get('total_score', 0)}"
            )
        except Exception as e:
            logger.warning(f"重新生成前同步 session_ctx 失败: {e}")

    # 构建 user_config（包含公司信息，确保 ReviewAgent 上下文完整）
    user_config = {
        "target_position": interview.position or "",
    }
    # 优先使用 target_company_name
    if interview.target_company_name:
        user_config["target_company"] = interview.target_company_name
    if interview.company_id:
        user_config["target_company_id"] = str(interview.company_id)
        if "target_company" not in user_config:
            try:
                from ..models.company import Company
                company_result = await db.execute(
                    select(Company.name).where(Company.id == interview.company_id)
                )
                company_name = company_result.scalar_one_or_none()
                if company_name:
                    user_config["target_company"] = company_name
            except Exception:
                pass

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
                        # Phase 14：透传 review_status META 信号给前端
                        meta = event.get("meta")
                        if isinstance(meta, dict):
                            yield f"data: {json.dumps({'type': 'meta', 'meta': meta}, ensure_ascii=False)}\n\n"
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

        # 公司信息优先级：target_company_name（用户输入字符串）> company_id 关联查询 > "未指定公司"
        company_name = ""
        if interview.target_company_name:
            company_name = interview.target_company_name
        if not company_name:
            company = companies_map.get(interview.company_id) if interview.company_id else None
            company_name = company.name if company else ""
        # 兜底：若用户未指定公司，返回友好提示而非空字符串
        if not company_name:
            company_name = "未指定公司"

        # 完成阶段中文标签
        completed_stage = STAGE_LABEL_MAP.get(interview.phase or "", interview.phase or "")

        reviews.append({
            "id": str(interview.id),
            "position": interview.position or "未知岗位",
            "overall_score": interview.overall_score or 0,
            "has_review": bool(interview.review_report),
            "created_at": _to_iso_with_tz(interview.created_at),
            # 新增完整字段
            "company_id": str(interview.company_id) if interview.company_id else None,
            "company_name": company_name,
            "difficulty": _calc_difficulty(interview),
            "duration": _calc_duration_minutes(interview),
            "duration_seconds": _calc_duration_seconds(interview),
            "completed_stage": completed_stage,
            # 复盘报告状态标记
            "status": interview.status,
        })
    return {"reviews": reviews}


# 对话消息类型推断关键词
_FEEDBACK_KEYWORDS = ("优点", "不足", "改进", "点评", "建议", "亮点", "欠缺", "提升空间", "回答得", "评分")
_TRANSITION_KEYWORDS = ("进入", "下一阶段", "环节", "接下来我们", "下面进入", "到此结束", " transitions", "过渡")
_GREETING_KEYWORDS = ("你好", "欢迎", "我是", "面试官", "开始面试", "请做一下自我介绍", "请先做")
_CLOSING_KEYWORDS = ("面试结束", "感谢你的参与", "本次面试", "祝你好运", "感谢您", "感谢参加")
_COMMAND_INPUTS = {"开始面试", "下一题", "结束面试", "skip", "next", "end", "start"}


def _infer_message_type(role: str, content: str) -> str:
    """根据角色和内容推断消息类型

    - user 角色：默认 answer，控制命令标记为 command
    - assistant 角色：按内容关键词区分 question/feedback/transition/greeting/closing
    """
    text = (content or "").strip()
    if role == "user":
        if text in _COMMAND_INPUTS or text.startswith("（面试结束）"):
            return "command"
        return "answer"
    # assistant 角色
    if any(k in text for k in _CLOSING_KEYWORDS):
        return "closing"
    if any(k in text for k in _FEEDBACK_KEYWORDS):
        # 优先识别点评（点评通常包含「优点/不足/改进」等词）
        return "feedback"
    if any(k in text for k in _TRANSITION_KEYWORDS):
        return "transition"
    if any(k in text for k in _GREETING_KEYWORDS):
        return "greeting"
    return "question"


@router.get("/{interview_id}/conversation")
async def get_conversation(
    interview_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取面试对话历史（完整还原整场面试问答过程）

    数据来源（按优先级）：
    1. agent_dialogue_records 表：通过 AgentSession.session_id=str(interview_id) 关联，
       查询全量对话记录（含开场白、所有提问、回答、点评、过渡话术、结束语），
       按 seq 正序排列，禁止过滤任何消息类型
    2. 兜底：Interview.questions_answers JSON 数组（解析为 question/answer/feedback 三类消息）

    转换规则：
    - role=assistant → role=interviewer（前端期望）
    - role=user → role=user
    - role=system → 跳过（系统调度信号，非面试对话内容）
    - type 字段：根据内容关键词推断（question/answer/feedback/transition/greeting/closing/command）

    异常处理：
    - 记录不存在或已删除 → 404
    - 非记录归属人 → 403
    - 无对话数据 → 200 + 空列表 + has_data=false

    返回结构：
    {
      "interview": {基础信息：公司/岗位/时间/时长},
      "messages": [{role, content, type, time, seq}],
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

    # 公司信息优先级：target_company_name（用户输入字符串）> company_id 关联查询 > "未指定公司"
    company_name = ""
    company_id = None
    if interview.target_company_name:
        company_name = interview.target_company_name
    if not company_name and interview.company_id:
        result = await db.execute(
            select(Company).where(Company.id == interview.company_id)
        )
        company = result.scalar_one_or_none()
        if company:
            company_name = company.name
            company_id = str(company.id)
    # 兜底：若用户未指定公司，返回友好提示而非空字符串
    if not company_name:
        company_name = "未指定公司"

    # ============ 主数据源：agent_dialogue_records 全量对话记录 ============
    # 同一 interview_id 在 agent_sessions 表中可能存在多条记录
    # （interview_agent 会话 + review_agent 会话），需要聚合查询全部对话记录
    messages = []
    # 评估JSON对象（若 review_agent 把整份评估报告作为一条消息写入，需抽取为独立字段）
    evaluation = None
    try:
        from ..models.session import AgentSession, AgentDialogueRecord

        # 优先取 interview_agent 的 session（面试原始对话），
        # 若无（如老数据已清理）则取 review_agent 的 session（复盘时复制的完整对话快照）
        session_result = await db.execute(
            select(AgentSession)
            .where(AgentSession.session_id == str(interview_id))
            .order_by(AgentSession.target_agent.asc())  # interview_agent 排在前
        )
        agent_sessions = list(session_result.scalars().all())

        # 收集所有 session_pk
        session_pks = [s.id for s in agent_sessions]
        # 记录 session_pk 到 target_agent 的映射，用于排序
        pk_to_agent = {s.id: s.target_agent for s in agent_sessions}

        if session_pks:
            # 查询所有 session 的全量对话记录，仅过滤 system 调度信号
            # 排序规则：interview_agent 优先，其次 review_agent；同 session 内按 seq 正序
            dialogue_result = await db.execute(
                select(AgentDialogueRecord)
                .where(AgentDialogueRecord.session_pk.in_(session_pks))
                .where(AgentDialogueRecord.role != "system")  # 排除系统调度信号
                .order_by(
                    AgentDialogueRecord.session_pk.asc(),
                    AgentDialogueRecord.seq.asc(),
                )
            )
            dialogues = list(dialogue_result.scalars().all())

            # 若 interview_agent session 存在且有对话，则仅使用 interview_agent 数据
            # 否则使用 review_agent 数据（兼容老数据场景）
            interview_pks = [pk for pk, ag in pk_to_agent.items() if ag == "interview_agent"]
            review_pks = [pk for pk, ag in pk_to_agent.items() if ag == "review_agent"]

            iv_dialogues = [d for d in dialogues if d.session_pk in interview_pks]
            rv_dialogues = [d for d in dialogues if d.session_pk in review_pks]

            # 优先使用 interview_agent 的对话；若为空则用 review_agent 的对话
            use_dialogues = iv_dialogues if iv_dialogues else rv_dialogues

            # 二次保险：按 created_at 升序排序，保证时间线正确
            use_dialogues.sort(key=lambda x: (x.created_at or x.seq, x.seq))

            for d in use_dialogues:
                content = (d.content or "").strip()
                if not content:
                    continue

                # 【关键】检测评估JSON：若 content 是含 total_score/question_by_question
                # 等字段的 JSON 对象，则抽取为独立 evaluation 字段，不混入 messages 数组
                eval_obj = _try_parse_evaluation(content)
                if eval_obj is not None:
                    evaluation = eval_obj
                    logger.info(f"抽取评估JSON为独立字段 interview_id={interview_id} seq={d.seq}")
                    continue

                # role 映射：assistant → interviewer
                front_role = "interviewer" if d.role == "assistant" else d.role
                msg_type = _infer_message_type(d.role, content)
                messages.append({
                    "role": front_role,
                    "content": content,
                    "type": msg_type,
                    "seq": d.seq,
                    "time": _to_iso_with_tz(d.created_at),
                })
    except Exception as e:
        logger.warning(f"从 agent_dialogue_records 查询对话历史失败 interview_id={interview_id}: {e}")

    # ============ 兜底数据源：Interview.questions_answers JSON 数组 ============
    if not messages:
        qa_list = interview.questions_answers or []
        for idx, qa in enumerate(qa_list):
            if not isinstance(qa, dict):
                continue
            question = (qa.get("question") or "").strip()
            answer = (qa.get("answer") or "").strip()
            feedback = (qa.get("feedback") or "").strip()

            if question:
                messages.append({
                    "role": "interviewer",
                    "content": question,
                    "type": _infer_message_type("assistant", question),
                    "index": idx,
                })
            if answer:
                messages.append({
                    "role": "user",
                    "content": answer,
                    "type": "answer",
                    "index": idx,
                })
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
            "created_at": _to_iso_with_tz(interview.created_at),
            "duration": _calc_duration_minutes(interview),
            "duration_seconds": _calc_duration_seconds(interview),
            "completed_stage": STAGE_LABEL_MAP.get(interview.phase or "", interview.phase or ""),
            "total_messages": len(messages),
            "total_score": interview.overall_score if interview.overall_score is not None else 0,
        },
        "messages": messages,
        "evaluation": evaluation,
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
