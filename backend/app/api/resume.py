"""
简历优化接口 (SSE 流式)

支持：
- 简历 CRUD
- AI 简历分析（流式 SSE）
- AI 简历段落优化（流式 SSE）
- 直接调用 ResumeAgent 专用方法，支持岗位/JD 适配
"""

import json
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from uuid import UUID

from ..db.session import get_db
from ..schemas.resume import ResumeCreate, ResumeResponse, ResumeOptimizeRequest
from ..services.resume_service import ResumeService
from ..api.auth import get_current_user
from ..models.user import User
from ..middleware.log import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/resume", tags=["简历优化"])


@router.post("/", response_model=ResumeResponse, status_code=201)
async def create_resume(
    data: ResumeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建简历"""
    service = ResumeService(db)
    resume = await service.create(current_user.id, data)
    return resume


@router.get("/", response_model=list[ResumeResponse])
async def list_resumes(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取我的简历列表"""
    service = ResumeService(db)
    return await service.list_by_user(current_user.id)


@router.get("/{resume_id}", response_model=ResumeResponse)
async def get_resume(
    resume_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取简历详情"""
    service = ResumeService(db)
    resume = await service.get(resume_id)
    if not resume or resume.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="简历不存在")
    return resume


@router.put("/{resume_id}", response_model=ResumeResponse)
async def update_resume(
    resume_id: UUID,
    data: ResumeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新简历（创建新版本）"""
    service = ResumeService(db)
    resume = await service.update(resume_id, data)
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")
    return resume


@router.delete("/{resume_id}", status_code=204)
async def delete_resume(
    resume_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除简历"""
    service = ResumeService(db)
    deleted = await service.delete(resume_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="简历不存在")


# ============================================================
# 辅助函数
# ============================================================

def _build_jd_context(data: ResumeOptimizeRequest) -> str:
    """构建完整的 JD 上下文（含目标岗位 + JD 文本）"""
    parts = []
    if data.target_position:
        parts.append(f"【目标岗位】{data.target_position}")
    if data.job_description and data.job_description.strip():
        parts.append(f"【岗位JD】{data.job_description.strip()}")
    return "\n".join(parts)


def _validate_content(content: str) -> Optional[str]:
    """内容校验：返回错误提示，None 表示通过"""
    if not content or not content.strip():
        return "请输入需要优化/分析的简历内容后再操作"
    if len(content.strip()) < 20:
        return "请输入更完整的简历内容，以便为你提供精准的优化建议"
    return None


def _sse(data: dict) -> str:
    """格式化 SSE 数据"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _get_resume_agent(request: Request):
    """获取 ResumeAgent 实例，未就绪时返回 None"""
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator is None:
        return None
    return getattr(orchestrator, "resume_agent", None)


# ============================================================
# 智能优化
# ============================================================

@router.post("/optimize")
async def optimize_resume(
    data: ResumeOptimizeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AI 智能优化（SSE 流式响应）

    优化逻辑：
    1. 无岗位信息：基础润色 + STAR 法则 + 量化成果 + 专业术语
    2. 有岗位/JD：优先匹配 JD 关键词，将经历向岗位需求对齐

    输出：优化后全文 + 分隔符 + 优化说明（分点）
    """
    err = _validate_content(data.content)
    if err:
        raise HTTPException(status_code=400, detail=err)

    resume_agent = _get_resume_agent(request)
    if resume_agent is None:
        raise HTTPException(status_code=503, detail="简历优化服务未就绪，请稍后重试")

    jd_context = _build_jd_context(data)
    # 原始简历内容与岗位上下文严格分离，禁止拼接，避免 LLM 混淆输入边界
    original_content = data.content

    async def generate():
        try:
            # 1. 输出优化后的完整文本（调用 ResumeAgent.optimize_section）
            # 原始简历作为 content，岗位上下文独立传入 job_context
            optimized_parts: list[str] = []
            async for chunk in resume_agent.optimize_section(
                original_content, section_type=data.section_type,
                job_context=jd_context,
            ):
                if isinstance(chunk, str) and chunk.startswith("\n\n__META__"):
                    continue
                optimized_parts.append(chunk if isinstance(chunk, str) else str(chunk))
                yield _sse({"content": chunk})

            optimized_text = "".join(optimized_parts).strip()

            # 2. 分隔符
            yield _sse({"content": "\n\n---\n"})

            # 3. 输出核心修改说明（对比原文与优化结果，列出 3-5 条修改点）
            # 关键修复：将原文与优化后文本同时传入 prompt，让 LLM 基于真实差异生成说明
            # 杜绝"未提供优化结果文本"这类无状态导致的自相矛盾提示
            explain_prompt = f"""你是资深 HR，请对比下方「原始段落」与「优化后段落」，列出本次优化的核心修改点（3-5 条）。

要求：
1. 每条修改点需说明：改了什么 + 为什么这样改 + 带来的优化价值
2. 修改点必须基于两段文本的真实差异，禁止编造未发生的修改
3. 严禁输出"未提供优化结果文本"类提示——两段文本均已提供
4. 严格按以下格式输出：

**核心修改说明**
1. 【修改点】... 【原因】... 【价值】...
2. 【修改点】... 【原因】... 【价值】...
3. 【修改点】... 【原因】... 【价值】...
"""
            if jd_context:
                explain_prompt += f"\n目标岗位上下文：\n{jd_context}\n"
            explain_prompt += f"""
【原始段落】
{original_content}

【优化后段落】
{optimized_text}
"""
            try:
                await resume_agent._ensure_client()
                if resume_agent._client is None:
                    yield _sse({"content": "**核心修改说明**\n（优化说明生成失败：LLM 未配置）"})
                else:
                    stream = await resume_agent._client.chat.completions.create(
                        model=resume_agent.model,
                        messages=[{"role": "user", "content": explain_prompt}],
                        stream=True,
                        temperature=0.4,
                    )
                    async for chunk in stream:
                        delta = chunk.choices[0].delta
                        c = delta.content if delta and delta.content else None
                        if c:
                            yield _sse({"content": c})
            except Exception as e:
                logger.warning(f"生成优化说明失败: {e}")
                yield _sse({"content": "**核心修改说明**\n（优化说明生成失败，请稍后重试）"})

            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error(f"简历优化失败: {e}", exc_info=True)
            yield _sse({"content": "当前生成失败，请稍后重试，或检查输入内容后再次提交"})
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


# ============================================================
# 全面分析
# ============================================================

@router.post("/analyze")
async def analyze_resume(
    data: ResumeOptimizeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AI 全面分析（SSE 流式响应）

    分析维度：
    1. 内容完整性：模块是否齐全、关键信息是否缺失
    2. 表达专业性：口语化/冗余问题、待优化语句
    3. 亮点突出度：核心优势、项目成果是否醒目
    4. 逻辑与结构：排版、叙事逻辑通顺度
    5. 风险点排查：时间断层、职责模糊、经历不匹配
    6. 岗位匹配度（有 JD 时）：匹配度评分、匹配项、待补充项
    """
    err = _validate_content(data.content)
    if err:
        raise HTTPException(status_code=400, detail=err)

    resume_agent = _get_resume_agent(request)
    if resume_agent is None:
        raise HTTPException(status_code=503, detail="简历分析服务未就绪，请稍后重试")

    jd_context = _build_jd_context(data)

    async def generate():
        try:
            prompt = f"""你是资深HR和简历顾问，请对以下简历进行深度全面分析。

{f"岗位上下文：{jd_context}" if jd_context else "未指定目标岗位"}

简历内容：
{data.content}

请按以下5个维度输出结构化分析报告，每个维度包含「评分(0-100) + 问题描述 + 改进建议」：

## 1. 内容完整性
（评估简历模块是否齐全、关键信息是否缺失）

## 2. 表达专业性
（评估表述是否职场化、有无口语化/冗余问题，标注待优化语句）

## 3. 亮点突出度
（评估核心优势、项目成果是否清晰醒目，给出强化方向）

## 4. 逻辑与结构
（评估内容排版、经历叙事的逻辑通顺度，给出结构调整建议）

## 5. 风险点排查
（识别时间断层、职责模糊、经历不匹配等潜在减分项）

"""
            if jd_context:
                prompt += """## 6. 岗位匹配度
（给出匹配度评分(0-100)，列出匹配项、待补充项，指导针对性修改）

"""
            prompt += """最后给出「整体优化优先级排序」，指导用户按顺序修改。

请直接输出报告（Markdown 格式）："""

            await resume_agent._ensure_client()
            if resume_agent._client is None:
                yield _sse({"content": "LLM 未配置，无法进行简历分析。请在 .env 中配置 LLM_API_KEY。"})
                yield "data: [DONE]\n\n"
                return

            stream = await resume_agent._client.chat.completions.create(
                model=resume_agent.model,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
                temperature=0.4,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta
                c = delta.content if delta and delta.content else None
                if c:
                    yield _sse({"content": c})

            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error(f"简历分析失败: {e}", exc_info=True)
            yield _sse({"content": "当前生成失败，请稍后重试，或检查输入内容后再次提交"})
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