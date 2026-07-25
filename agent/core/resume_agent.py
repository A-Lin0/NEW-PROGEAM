# agent/core/resume_agent.py
"""
简历优化 Agent

职责：简历解析、ATS评分、优化改写
依赖注入：接受 vector_store/embedder/redis_client/db_session_factory/api_key/base_url/model
"""

import json
import logging
import os
from typing import Optional, Any


class ResumeAgent:
    def __init__(
        self,
        vector_store: Optional[Any] = None,
        embedder: Optional[Any] = None,
        redis_client: Optional[Any] = None,
        db_session_factory: Optional[Any] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "gpt-4o",
    ):
        self.vector_store = vector_store
        self.embedder = embedder
        self.redis = redis_client
        self.db_session_factory = db_session_factory
        self.api_key = api_key or os.getenv("LLM_API_KEY", "")
        self.base_url = base_url or os.getenv("LLM_BASE_URL", "")
        self.model = model
        self._client = None

    async def _ensure_client(self):
        if self._client is None and self.api_key:
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(
                    api_key=self.api_key, base_url=self.base_url
                )
            except ImportError:
                pass

    @property
    def scoring_prompt(self) -> str:
        return """
        你是资深ATS评估专家。根据以下维度对简历与岗位的匹配度打分(0-100)：
        1. 关键词覆盖(40分): 岗位描述中最重要的10个关键词在简历中的出现比例。
        2. 格式规范(20分): 是否有清晰段落、联系方式、教育倒序，无拼写错误。
        3. 量化表达(20分): 项目/工作成果是否有数字、百分比、具体指标。
        4. 时间逻辑(20分): 教育/工作经历是否连续，无超过3个月断层。
        返回JSON: {"score": 85, "breakdown": {"keywords":34, "format":18, "quantification":15, "timeline":18}, "diagnosis": "..."}
        """

    async def stream(self, payload: dict):
        """
        流式输出：
        1. 先输出 ATS 评分 JSON
        2. 再流式输出优化后的简历
        """
        raw_resume = (
            payload.get("resume_text") or payload.get("raw_resume")
            or payload.get("resume") or ""
        )
        job_desc = (
            payload.get("jd_text") or payload.get("job_description")
            or payload.get("job_desc") or ""
        )

        # 无 LLM 时降级
        await self._ensure_client()
        if not self._client:
            yield json.dumps({
                "score": 0,
                "breakdown": {"keywords": 0, "format": 0, "quantification": 0, "timeline": 0},
                "diagnosis": "LLM 未配置，无法进行 ATS 评分。请在 .env 中配置 LLM_API_KEY。",
                "degraded": True,
            }, ensure_ascii=False)
            return

        # 1. ATS 评分
        try:
            score_res = await self._get_ats_score(raw_resume, job_desc)
            yield json.dumps(score_res, ensure_ascii=False)
        except Exception as e:
            logging.getLogger(__name__).error("ATS 评分失败: %s", e, exc_info=True)
            yield json.dumps({"error": "ATS 评分暂时不可用，请稍后重试"}, ensure_ascii=False)

        # 2. 流式输出优化后的简历
        optimize_prompt = f"""
        你是资深HR，请根据以下岗位描述优化简历，要求：
        - 突出与岗位关键词匹配的经历
        - 量化成果，使用STAR法则
        - 保持原格式风格
        岗位描述：{job_desc}
        原始简历：{raw_resume}
        输出优化后的完整简历(Markdown)：
        """
        try:
            stream = await self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": optimize_prompt}],
                stream=True,
            )
            async for chunk in stream:
                content = chunk.choices[0].delta.content if chunk.choices[0].delta else None
                if content:
                    yield content
        except Exception as e:
            logging.getLogger(__name__).error("简历优化失败: %s", e, exc_info=True)
            yield "\n\n[简历优化暂时不可用，请稍后重试]"

        yield "[DONE]"

    async def optimize_section(
        self, content: str, section_type: str = "general",
        job_context: str = "",
    ):
        """
        流式优化简历段落（供 resume API 直接调用）

        :param content: 简历段落原文（用户真实输入，严禁与岗位上下文拼接）
        :param section_type: 段落类型（experience/project/skill/education/summary/general）
        :param job_context: 目标岗位/JD 上下文（独立传入，用于优化方向对齐，不混入原文）
        """
        await self._ensure_client()
        if not self._client:
            yield "[降级模式] LLM 未配置，无法优化简历段落。请在 .env 中配置 LLM_API_KEY。"
            return

        type_hint = {
            "experience": "工作经历段落",
            "project": "项目经历段落",
            "skill": "技能段落",
            "education": "教育背景段落",
            "summary": "个人简介段落",
            "general": "通用简历段落",
        }.get(section_type, "通用简历段落")

        # 构建岗位对齐指令（仅在提供岗位上下文时生效）
        job_alignment = ""
        if job_context and job_context.strip():
            job_alignment = f"""
【目标岗位对齐】
目标岗位/JD 上下文：
{job_context}

优化时需向岗位要求对齐：
- 优先突出与目标岗位匹配的能力与经历
- 自然融入 JD 中的关键技能词（仅当原文确有相关经历时）
- 弱化与岗位无关的内容，但不删除核心信息
"""

        prompt = f"""你是资深 HR 与简历顾问，请对用户提交的「{type_hint}」进行定制化优化改写。

【严格约束】
1. 必须严格基于下方「原始段落」进行改写，保留用户真实的公司名、岗位、时间、核心事件与数据
2. 严禁脱离用户原文生成通用模板示例，严禁编造未提及的经历
3. 严禁照抄原文不做修改，必须进行实质性优化
4. 直接输出优化后的完整段落，不要输出任何解释、前言、后记
{job_alignment}
【五维度优化标准】
1. 口语化转专业表达：将口语化描述转为职场化、专业化的表述
2. 补充量化成果：在原文基础上补充合理的量化指标（如提升比例、交付规模、响应时间等），但不得虚构具体数字
3. 梳理 STAR 逻辑：按情境-任务-行动-结果结构组织内容，突出行动与成果
4. 突出岗位匹配度：结合目标岗位（若有）突出匹配的能力与经历
5. 删除冗余表述：精简空洞、重复、无信息量的描述

【原始段落】
{content}
"""
        try:
            stream = await self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
                temperature=0.6,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta
                content_delta = delta.content if delta and delta.content else None
                if content_delta:
                    yield content_delta
        except Exception as e:
            logging.getLogger(__name__).error("简历段落优化失败: %s", e, exc_info=True)
            yield "\n[简历优化暂时不可用，请稍后重试]"

    async def analyze_resume(self, content: str, job_description: str = ""):
        """
        流式输出简历分析报告（供 resume API 直接调用）

        :param content: 简历全文
        :param job_description: 目标岗位 JD（可选）
        """
        await self._ensure_client()
        if not self._client:
            yield json.dumps({
                "score": 0,
                "diagnosis": "LLM 未配置，无法分析简历。",
                "degraded": True,
            }, ensure_ascii=False)
            return

        # 1. 先输出 ATS 评分 JSON
        try:
            score = await self._get_ats_score(content, job_description)
            yield json.dumps(score, ensure_ascii=False) + "\n\n"
        except Exception as e:
            logging.getLogger(__name__).error("ATS 评分失败: %s", e, exc_info=True)
            yield "[ATS 评分暂时不可用，请稍后重试]\n\n"

        # 2. 流式输出分析报告
        prompt = f"""你是资深HR和简历顾问，请对以下简历进行深度分析。

目标岗位 JD：
{job_description or "未指定"}

简历内容：
{content}

请从以下维度输出分析报告：
1. 整体印象（核心优势 / 主要不足）
2. 各模块点评（教育背景 / 工作经历 / 项目经历 / 技能 / 自我评价）
3. 与目标岗位的匹配度分析（关键词覆盖、能力匹配）
4. 具体改进建议（按优先级排序，给出可执行的操作）

请直接输出报告："""
        try:
            stream = await self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
                temperature=0.4,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta
                content_delta = delta.content if delta and delta.content else None
                if content_delta:
                    yield content_delta
        except Exception as e:
            logging.getLogger(__name__).error("简历分析失败: %s", e, exc_info=True)
            yield "\n[简历分析暂时不可用，请稍后重试]"

    async def _get_ats_score(self, resume: str, job_desc: str) -> dict:
        """调用 LLM 获取 ATS 评分"""
        prompt = self.scoring_prompt + f"\n岗位描述：{job_desc}\n简历：{resume}"
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        content = response.choices[0].message.content.strip()
        # 兼容 ```json ... ``` 包裹
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        # 兜底：提取第一个完整 JSON 对象
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            import re
            match = re.search(r"\{[\s\S]*\}", content)
            if match:
                return json.loads(match.group(0))
            raise
