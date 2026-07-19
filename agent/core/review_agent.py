# agent/core/review_agent.py
"""
面试复盘 Agent

职责：
- 消费面试Agent已计算的阶段评分数据（section_scores / total_score / question_records）
- 结合对话记录，由 LLM 生成逐题分析、薄弱点、改进建议
- 输出结构化 JSON 报告，供前端复盘页展示

触发方式：API 显式调用（POST /api/review/{id}/generate）或 auto_route 自动联动
"""

import json
import os
from typing import Optional, Any


class ReviewAgent:
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

    async def stream(self, payload: dict):
        """
        输出结构化 JSON 报告:
        {
          "total_score": 数值,
          "section_scores": {...},
          "stage_analysis": [...],
          "question_by_question": [...],
          "overall_problems": [...],
          "improvement_plan": {...},
          "overall_comment": "..."
        }
        """
        # ---- 数据提取 ----
        transcript = (
            payload.get("interview_history") or payload.get("transcript") or []
        )
        session_ctx = payload.get("session_ctx")
        if session_ctx and not transcript:
            transcript = session_ctx.get("history", [])

        target_position = payload.get("target_position", "")
        interview_type = payload.get("interview_type", "tech_1")
        difficulty = payload.get("difficulty", "middle")

        # 面试Agent已计算的评分数据
        question_records = payload.get("question_records", [])
        stage_scores = payload.get("stage_scores", {})
        section_scores = payload.get("section_scores", {})
        total_score = payload.get("total_score", 0)

        await self._ensure_client()

        # 无 LLM 降级：返回纯评分数据
        if not self._client:
            yield json.dumps({
                "total_score": total_score,
                "section_scores": section_scores,
                "stage_analysis": self._build_stage_analysis(section_scores, question_records),
                "question_by_question": self._build_qa_summary(question_records),
                "overall_problems": ["LLM 未配置，无法生成深度分析"],
                "improvement_plan": {"short_term": [], "long_term": [], "practice_suggestions": []},
                "overall_comment": "请在 .env 中配置 LLM_API_KEY 后重新生成复盘报告。",
                "degraded": True,
            }, ensure_ascii=False)
            yield "[DONE]"
            return

        # 对话记录为空
        if not transcript:
            yield json.dumps({
                "total_score": total_score,
                "section_scores": section_scores,
                "stage_analysis": self._build_stage_analysis(section_scores, question_records),
                "question_by_question": self._build_qa_summary(question_records),
                "overall_problems": ["对话记录为空，无法评估"],
                "improvement_plan": {"short_term": [], "long_term": [], "practice_suggestions": []},
                "overall_comment": "未检测到面试对话内容。",
                "empty": True,
            }, ensure_ascii=False)
            yield "[DONE]"
            return

        # ---- 构造复盘 prompt（含已计算评分数据）----
        transcript_text = self._format_transcript(transcript)
        prompt = self._build_review_prompt(
            transcript_text, target_position, interview_type, difficulty,
            total_score, section_scores, question_records
        )

        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            content = response.choices[0].message.content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[-1].rsplit("```", 1)[0]

            try:
                llm_result = json.loads(content)
            except json.JSONDecodeError:
                llm_result = {
                    "question_by_question": [],
                    "overall_problems": [],
                    "improvement_plan": {"short_term": [], "long_term": [], "practice_suggestions": []},
                    "overall_comment": content,
                }

            # 合并：评分数据来自面试Agent，分析数据来自LLM
            report = {
                "total_score": total_score,
                "section_scores": section_scores,
                "stage_analysis": self._build_stage_analysis(section_scores, question_records),
                "question_by_question": llm_result.get("question_by_question", []),
                "overall_problems": llm_result.get("overall_problems", []),
                "improvement_plan": llm_result.get("improvement_plan", {
                    "short_term": [], "long_term": [], "practice_suggestions": []
                }),
                "overall_comment": llm_result.get("overall_comment", ""),
            }
            yield json.dumps(report, ensure_ascii=False)
        except Exception as e:
            yield json.dumps({
                "total_score": total_score,
                "section_scores": section_scores,
                "stage_analysis": self._build_stage_analysis(section_scores, question_records),
                "question_by_question": self._build_qa_summary(question_records),
                "overall_problems": [f"复盘生成失败: {str(e)}"],
                "improvement_plan": {"short_term": [], "long_term": [], "practice_suggestions": []},
                "overall_comment": "复盘服务异常，请稍后重试。",
                "error": True,
            }, ensure_ascii=False)

        yield "[DONE]"

    # ============================================================
    # 辅助方法
    # ============================================================

    @staticmethod
    def _format_transcript(transcript: list) -> str:
        """格式化对话记录"""
        lines = []
        for item in transcript:
            role = item.get("role", "unknown")
            content = item.get("content", "")
            label = "面试官" if role in ("interviewer", "assistant") else "候选人"
            lines.append(f"[{label}] {content}")
        return "\n".join(lines)

    @staticmethod
    def _build_qa_summary(question_records: list) -> list:
        """从 question_records 构造逐题摘要（无LLM降级时使用）"""
        result = []
        for i, rec in enumerate(question_records, 1):
            q_text = rec.get("question", "")[:100]
            a_text = rec.get("answer", "")[:100]
            if not a_text and rec.get("skipped"):
                a_text = "（已跳过）"
            result.append({
                "index": i,
                "stage": rec.get("stage", ""),
                "question": q_text,
                "answer": a_text,
                "score": rec.get("score", 0),
                "skipped": rec.get("skipped", False),
            })
        return result

    @staticmethod
    def _build_stage_analysis(section_scores: dict, question_records: list) -> list:
        """从评分数据构造阶段分析"""
        stage_labels = {
            "self_intro": "自我介绍",
            "tech_qa": "专业技术",
            "star_qa": "行为面试",
            "project_qa": "项目案例",
            "reverse_qa": "反向提问",
        }
        result = []
        for stage, label in stage_labels.items():
            score = section_scores.get(stage, 0)
            q_count = len([r for r in question_records if r.get("stage") == stage])
            result.append({
                "stage": stage,
                "label": label,
                "score": score,
                "question_count": q_count,
                "comment": f"{label}环节得分 {score}/100，共{q_count}题" if q_count > 0 else f"{label}环节未进行",
            })
        return result

    @staticmethod
    def _build_review_prompt(
        transcript: str, target_position: str,
        interview_type: str, difficulty: str,
        total_score: float, section_scores: dict,
        question_records: list,
    ) -> str:
        """构造复盘 prompt，包含面试Agent已计算的评分数据"""
        # 整理问答记录
        qa_lines = []
        for i, rec in enumerate(question_records, 1):
            stage = rec.get("stage", "")
            q = rec.get("question", "")[:150]
            a = rec.get("answer", "")[:150]
            score = rec.get("score", 0)
            skipped = rec.get("skipped", False)
            status = "跳过" if skipped else f"得分{score}"
            qa_lines.append(f"{i}. [{stage}] Q: {q} | A: {a} | {status}")

        # 阶段得分
        stage_info = json.dumps(section_scores, ensure_ascii=False)

        return f"""你是拥有10年一线招聘经验的资深面试复盘专家。请基于以下面试数据进行专业分析与建议。

## 面试基本信息
- 目标岗位: {target_position}
- 面试类型: {interview_type}
- 难度等级: {difficulty}

## 评分数据（由面试系统自动计算，请直接使用）
- 综合总分: {total_score}/100
- 各阶段得分: {stage_info}

## 问答记录
{chr(10).join(qa_lines)}

## 完整对话记录
{transcript}

## 任务
请基于以上数据，输出以下内容（严格JSON格式，不要输出其他文字）:

{{
  "question_by_question": [
    {{
      "stage": "阶段标识",
      "question": "面试官原题（截取关键部分）",
      "answer": "候选人回答摘要",
      "score": 得分,
      "advantages": ["优点1"],
      "shortcomings": ["不足1"],
      "optimization": "具体优化建议（50字以内）"
    }}
  ],
  "overall_problems": ["整体性问题1", "整体性问题2"],
  "improvement_plan": {{
    "short_term": ["1周内可执行的提升点1", "提升点2"],
    "long_term": ["1-3个月长期提升点1"],
    "practice_suggestions": ["具体练习建议1"]
  }},
  "overall_comment": "200字以内整体评价，包含总分、亮点、主要短板、核心建议"
}}"""