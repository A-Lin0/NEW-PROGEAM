# agent/core/review_agent.py
"""
面试复盘 Agent

职责：
- 消费面试Agent已计算的阶段评分数据（section_scores / total_score / question_records）
- 结合对话记录，由 LLM 生成逐题分析、薄弱点、改进建议
- 输出结构化 JSON 报告，供前端复盘页展示

触发方式：API 显式调用（POST /api/review/{id}/generate）或 auto_route 自动联动

Phase 14 修复：重新生成时执行评分全量重算
- LLM 重新评估每道题的得分（question_by_question[].score）
- 基于重评估的单题得分，重算各阶段得分（section_scores）和综合总分（total_score）
- 全量覆盖原有评分数据，确保重新生成后评分与点评均发生更新
"""

import json
import logging
import os
from typing import Optional, Any


# 各环节权重（加权计算总分，总和=1.0）
# 与 interview_agent.STAGE_WEIGHTS 保持一致，避免跨模块依赖
STAGE_WEIGHTS = {
    "self_intro":  0.10,
    "tech_qa":     0.30,
    "star_qa":     0.20,
    "project_qa":  0.25,
    "reverse_qa":  0.15,
}

# 各阶段应有题数（与 interview_agent.QUESTION_BANK_CONFIG 保持一致）
QUESTION_BANK_CONFIG = {
    "self_intro":  1,
    "tech_qa":     3,
    "star_qa":     2,
    "project_qa":  3,
    "reverse_qa":  1,
}


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

        # ---- 构造复盘 prompt（让 LLM 重新评估每道题得分，实现评分全量重算）----
        transcript_text = self._format_transcript(transcript)
        prompt = self._build_review_prompt(
            transcript_text, target_position, interview_type, difficulty,
            question_records
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

            # Phase 14：评分全量重算
            # 基于 LLM 重新评估的单题得分，更新 question_records 并重算 section_scores/total_score
            llm_qa_list = llm_result.get("question_by_question", [])
            recalculated_records = self._merge_llm_scores_to_records(
                question_records, llm_qa_list
            )
            recalculated_section_scores, recalculated_total_score = (
                self._recalculate_scores(recalculated_records)
            )

            # 优先使用重算结果；若重算失败（如 LLM 未返回 score），回退到原评分
            final_section_scores = (
                recalculated_section_scores if recalculated_total_score > 0 else section_scores
            )
            final_total_score = (
                recalculated_total_score if recalculated_total_score > 0 else total_score
            )

            logging.getLogger(__name__).info(
                "复盘评分重算完成 | 原总分=%.1f → 重算总分=%.1f | 原阶段=%s → 重算阶段=%s",
                total_score, final_total_score,
                section_scores, final_section_scores,
            )

            # 合并：评分数据来自重算结果，分析数据来自LLM
            report = {
                "total_score": final_total_score,
                "section_scores": final_section_scores,
                "stage_analysis": self._build_stage_analysis(final_section_scores, recalculated_records),
                "question_by_question": llm_qa_list,
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
    def _merge_llm_scores_to_records(
        question_records: list, llm_qa_list: list,
    ) -> list:
        """将 LLM 重新评估的单题得分合并回 question_records

        Phase 14 评分全量重算核心步骤：
        - 基于 LLM 返回的 question_by_question[].score 更新 question_records[].score
        - 匹配规则：按索引顺序一一对应（LLM 应按 question_records 顺序输出）
        - 若 LLM 未返回 score 或格式异常，保留原 score

        :param question_records: 面试Agent记录的原始问答数据
        :param llm_qa_list: LLM 重新评估的逐题分析（含 score 字段）
        :return: 合并 LLM 评分后的 question_records 副本
        """
        if not llm_qa_list:
            return list(question_records)

        merged_records = []
        for idx, rec in enumerate(question_records):
            new_rec = dict(rec)  # 浅拷贝，避免修改原数据
            if idx < len(llm_qa_list):
                llm_score = llm_qa_list[idx].get("score")
                if llm_score is not None:
                    try:
                        # 评分范围校验：0-100
                        score_val = max(0, min(100, int(llm_score)))
                        new_rec["score"] = score_val
                    except (TypeError, ValueError):
                        pass  # 保留原 score
            merged_records.append(new_rec)
        return merged_records

    @staticmethod
    def _recalculate_scores(question_records: list) -> tuple:
        """基于 question_records 重新计算各环节评分与综合总分

        Phase 14 评分全量重算：
        - 逻辑与 interview_agent._calc_final_scores 保持一致
        - 按 stage 分组计算实际作答题目的均分
        - 跳过/未作答的题目计 0 分
        - 阶段均分 = 该阶段所有题目评分之和 / 该阶段应有题数
        - 综合总分 = Σ(阶段均分 × 阶段权重)

        :return: (section_scores dict, total_score float)
        """
        # 按 stage 分组收集评分
        stage_actual_scores = {}
        for rec in question_records:
            stage = rec.get("stage", "")
            if not stage or stage in ("init", "end"):
                continue
            skipped = rec.get("skipped", False)
            answer = (rec.get("answer", "") or "").strip()
            # 跳过或未作答的题目计 0 分
            if skipped or not answer:
                stage_actual_scores.setdefault(stage, []).append(0)
            else:
                score = rec.get("score", 0)
                try:
                    score = max(0, min(100, int(score)))
                except (TypeError, ValueError):
                    score = 0
                stage_actual_scores.setdefault(stage, []).append(score)

        # 计算各阶段均分（分母用 QUESTION_BANK_CONFIG 中的应有题数）
        section_scores = {}
        for stage, weight in STAGE_WEIGHTS.items():
            expected_count = QUESTION_BANK_CONFIG.get(stage, 1)
            actual_scores = stage_actual_scores.get(stage, [])
            if not actual_scores:
                section_scores[stage] = 0
                continue
            # 分母用 expected_count（跳过题拉低均分）
            denom = max(expected_count, len(actual_scores))
            total = sum(actual_scores)
            section_scores[stage] = round(total / denom, 1)

        # 加权总分
        total = 0.0
        for stage, weight in STAGE_WEIGHTS.items():
            total += section_scores.get(stage, 0) * weight
        total_score = round(total, 1)

        return section_scores, total_score

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
        question_records: list,
    ) -> str:
        """构造复盘 prompt，让 LLM 重新评估每道题得分并生成专业分析

        Phase 14 修复：评分全量重算
        - 不再传入面试Agent已计算的评分数据，避免 LLM 直接复用
        - 要求 LLM 基于答题内容独立评估每道题的得分（0-100）
        - 后续基于 LLM 评估的单题得分重算 section_scores 和 total_score
        """
        # 整理问答记录
        qa_lines = []
        for i, rec in enumerate(question_records, 1):
            stage = rec.get("stage", "")
            q = rec.get("question", "")[:150]
            a = rec.get("answer", "")[:150]
            skipped = rec.get("skipped", False)
            status = "跳过" if skipped else "待评估"
            qa_lines.append(f"{i}. [{stage}] Q: {q} | A: {a} | {status}")

        return f"""你是拥有10年一线招聘经验的资深面试复盘专家。请基于以下面试数据进行专业分析与建议。

## 面试基本信息
- 目标岗位: {target_position}
- 面试类型: {interview_type}
- 难度等级: {difficulty}

## 问答记录
{chr(10).join(qa_lines)}

## 完整对话记录
{transcript}

## 任务
请基于以上数据，独立评估每道题的得分（0-100分），并输出以下内容（严格JSON格式，不要输出其他文字）:

评分标准：
- 90-100：回答精准、逻辑清晰、有深度、贴合岗位要求
- 75-89：回答完整、基本正确、有一定深度
- 60-74：回答基本可用，但存在明显不足或深度不够
- 40-59：回答有重大缺陷或偏离问题
- 0-39：未作答、跳过或回答完全错误

{{
  "question_by_question": [
    {{
      "stage": "阶段标识（self_intro/tech_qa/star_qa/project_qa/reverse_qa）",
      "question": "面试官原题（截取关键部分）",
      "answer": "候选人回答摘要",
      "score": 0-100的整数得分（跳过的题目给0分）,
      "advantages": ["优点1", "优点2"],
      "shortcomings": ["不足1", "不足2"],
      "optimization": "具体优化建议（50字以内）"
    }}
  ],
  "overall_problems": ["整体性问题1", "整体性问题2"],
  "improvement_plan": {{
    "short_term": ["1周内可执行的提升点1", "提升点2"],
    "long_term": ["1-3个月长期提升点1"],
    "practice_suggestions": ["具体练习建议1"]
  }},
  "overall_comment": "200字以内整体评价，包含核心亮点、主要短板、核心建议"
}}"""