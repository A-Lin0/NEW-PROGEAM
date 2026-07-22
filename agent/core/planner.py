# agent/core/planner.py
"""
任务规划大脑 TaskPlanner（Plan-Solve 架构的 Plan 阶段核心模块）

职责：
1. 上下文状态校验（长会话保护：面试进行中禁止切换任务）
2. 意图识别与任务归类（LLM 语义拆解 / 关键词规则降级）
3. 组装标准化调度参数 task_params（自动从 user_assets 提取简历/JD/公司）
4. 生成联动标识 auto_next_agent（面试结束自动触发复盘）

严格边界：仅输出标准化调度指令 JSON，不执行任何业务操作。
"""

import json
import os
from typing import Optional


# ---- 任务类型枚举 ----
TASK_INFO_RETRIEVE = "info_retrieve"
TASK_RESUME_OPTIMIZE = "resume_optimize"
TASK_INTERVIEW_SESSION = "interview_session"
TASK_INTERVIEW_REVIEW = "interview_review"
TASK_COMPANY_QA = "company_qa"  # 新增：公司知识问答
TASK_INVALID = "invalid"

# ---- 目标 Agent 枚举（与 orchestrator.agents 字典键名一致）----
AGENT_RETRIEVER = "retriever_agent"
AGENT_RESUME = "resume_agent"
AGENT_INTERVIEW = "interview_agent"
AGENT_REVIEW = "review_agent"
AGENT_NONE = "none"

# ---- 会话状态枚举 ----
SESSION_NEW = "new"
SESSION_ONGOING = "ongoing"
SESSION_FINISHED = "finished"
SESSION_ERROR = "error"

# ---- 检索查询类型枚举 ----
QUERY_TYPE_KEYWORD = "keyword"  # 关键词结构化列表查询
QUERY_TYPE_QA = "qa"            # 自然语言语义问答

# 各 Agent 必填入参清单（用于校验）
REQUIRED_PARAMS = {
    AGENT_RETRIEVER: ["query", "retrieve_type", "company_name", "target_position", "top_k"],
    AGENT_RESUME: ["resume_text", "optimize_type", "jd_text", "target_position", "difficulty"],
    AGENT_INTERVIEW: ["session_stage", "target_position", "interview_type", "difficulty",
                      "resume_summary", "jd_summary", "dialogue_history", "user_input"],
    AGENT_REVIEW: ["interview_history", "target_position", "interview_type", "difficulty"],
}

# ---- 已知公司名列表（用于从 query 中智能提取公司名） ----
_KNOWN_COMPANY_NAMES = [
    "字节跳动", "阿里巴巴", "腾讯", "百度", "美团", "京东", "网易", "华为",
    "小米", "拼多多", "快手", "滴滴", "小红书", "哔哩哔哩", "B站",
    "蚂蚁集团", "蚂蚁金服", "携程", "大疆", "商汤", "旷视", "依图",
    "蔚来", "理想", "小鹏", "比亚迪", "宁德时代", "大华", "海康威视",
    "知乎", "微博", "搜狐", "新浪", "360", "奇安信",
    "金山", "用友", "金蝶", "深信服", "中兴", "OPPO", "vivo",
    "荣耀", "联想", "IBM", "微软", "Google", "谷歌", "Apple", "苹果",
    "Amazon", "亚马逊", "Meta", "Facebook", "Netflix", "奈飞",
    "Shopee", "Grab", "Lazada", "SHEIN", "Anker", "大疆创新",
]


class TaskPlanner:
    """任务规划大脑"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "gpt-4o",
    ):
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

    # ==================== 主入口 ====================

    async def plan(self, user_input: str, context: dict) -> dict:
        """
        Plan 阶段主入口：按标准流程执行四步

        :param user_input: 用户当前最新自然语言输入
        :param context: {
            session_id, session_ctx: {session_status, current_stage, dialogue_history, user_assets}
        }
        :return: 标准化调度指令 JSON（见输出格式规范）
        """
        session_ctx = context.get("session", {}) or {}
        session_status = session_ctx.get("session_status", SESSION_NEW)
        current_stage = session_ctx.get("current_stage", "init")
        dialogue_history = session_ctx.get("dialogue_history", []) or session_ctx.get("history", [])
        user_assets = session_ctx.get("user_assets", {}) or {}
        llm_key_enable = bool(self.api_key)

        # ---- 步骤1：上下文状态校验（长会话保护）----
        guard_result = self._guard_long_session(
            user_input, session_status, current_stage, dialogue_history
        )
        if guard_result:
            # 面试进行中且用户未明确结束 → 强制路由到 interview_agent
            return self._build_plan(
                task_type=TASK_INTERVIEW_SESSION,
                target_agent=AGENT_INTERVIEW,
                session_status=SESSION_ONGOING,
                task_params=self._assemble_interview_params(
                    user_input, session_ctx, user_assets
                ),
                response_to_user=guard_result,
                auto_next_agent=False,
                next_step_hint="长会话保护：持续 interview_agent，禁止切换",
            )

        # 面试已结束（session_status=finished）→ 自动触发复盘
        if session_status == SESSION_FINISHED:
            return self._build_plan(
                task_type=TASK_INTERVIEW_REVIEW,
                target_agent=AGENT_REVIEW,
                session_status=SESSION_FINISHED,
                task_params=self._assemble_review_params(session_ctx, user_assets),
                response_to_user="面试已结束，正在生成复盘报告...",
                auto_next_agent=True,
                next_step_hint="面试流程结束，自动串联 review_agent",
            )

        # ---- 步骤2：意图识别 ----
        if llm_key_enable:
            intent = await self._recognize_with_llm(user_input, session_ctx, user_assets)
        else:
            intent = self._recognize_with_rules(user_input, session_ctx)

        # ---- 步骤3：组装 task_params ----
        # ---- 步骤4：生成 auto_next_agent ----
        return self._assemble_plan_from_intent(intent, user_input, session_ctx, user_assets)

    # ==================== 步骤1：长会话保护 ====================

    @staticmethod
    def _guard_long_session(
        user_input: str, session_status: str,
        current_stage: str, dialogue_history: list,
    ) -> Optional[str]:
        """
        长会话保护：面试进行中禁止切换任务
        :return: 非空字符串表示拦截提示，None 表示放行
        """
        if session_status != SESSION_ONGOING:
            return None
        if current_stage in ("end", "init") and not dialogue_history:
            return None

        msg = user_input.lower()
        # 用户明确要求结束面试
        end_signals = ["结束面试", "结束", "完成面试", "不面试了", "退出面试", "面试结束"]
        if any(sig in msg for sig in end_signals):
            return None  # 放行，允许进入结束流程

        # 用户在面试中提出切换任务
        switch_signals = ["查公司", "查腾讯", "查阿里", "查字节", "优化简历", "改简历",
                          "查薪资", "查面经", "行业分析", "帮我改"]
        if any(sig in msg for sig in switch_signals):
            return (
                "当前面试尚未结束，确认是否终止本次面试再执行新需求？"
                "回复「结束面试」可终止当前面试并自动生成复盘报告。"
            )

        # 面试进行中，持续走 interview_agent
        return None

    # ==================== 步骤2：意图识别 ====================

    async def _recognize_with_llm(
        self, user_input: str, session_ctx: dict, user_assets: dict,
    ) -> dict:
        """LLM 语义拆解识别用户真实意图"""
        await self._ensure_client()
        if not self._client:
            return self._recognize_with_rules(user_input, session_ctx)

        assets_summary = {
            "has_resume": bool(user_assets.get("resume_text")),
            "has_jd": bool(user_assets.get("jd_text")),
            "target_company": user_assets.get("target_company", ""),
            "target_position": user_assets.get("target_position", ""),
        }
        prompt = f"""你是任务规划大脑。识别用户求职意图，输出标准化调度指令。

用户输入: {user_input}
会话状态: {session_ctx.get('session_status', 'new')}
当前阶段: {session_ctx.get('current_stage', 'init')}
用户资产: {assets_summary}

下辖可调度 Agent:
1. retriever_agent（信息检索）: 公司信息/面经/薪资/行业查询
   task_params: query, retrieve_type(company_info/interview_exp/salary_query/industry_analysis/mixed), company_name, target_position, top_k
2. resume_agent（简历优化）: 简历润色/ATS诊断/JD匹配
   task_params: resume_text, optimize_type(section/full/ats_match), jd_text, target_position, difficulty
3. interview_agent（面试模拟）: 多轮面试对话
   task_params: session_stage(init/self_intro/core_qa/reverse_qa/end), target_position, interview_type(tech_1/tech_2/hr/comprehensive), difficulty(junior/middle/senior), resume_summary, jd_summary, dialogue_history, user_input
4. review_agent（面试复盘）: 四维评分+逐题点评
   task_params: interview_history, target_position, interview_type, difficulty

规则:
1. 用户对某公司/行业提出自然语言问题（如"腾讯的加班严重吗""字节的面试难吗""阿里的福利怎么样"）→ company_qa，路由到 retriever_agent
2. 用户明确要求列出公司列表/面经列表/薪资列表（如"列出所有公司""查字节面经"）→ info_retrieve，路由到 retriever_agent
3. 用户上传简历/要求修改/ATS诊断 → resume_agent
4. 用户发起模拟面试/提交面试回答 → interview_agent
5. 面试流程结束 → review_agent（auto_next_agent=true）

区分 info_retrieve 与 company_qa 的核心标准：
- info_retrieve：用户期望获得结构化列表/多条数据，如"查腾讯面经""列出互联网公司"
- company_qa：用户提出自然语言问题，期望获得一个直接的答案，如"腾讯的加班多吗""字节的面试难不难"

仅输出纯净JSON，禁止任何解释文字:
{{
  "task_type": "info_retrieve/company_qa/resume_optimize/interview_session/interview_review/invalid",
  "target_agent": "retriever_agent/resume_agent/interview_agent/review_agent/none",
  "session_status": "new/ongoing/finished/error",
  "task_params": {{}},
  "response_to_user": "展示给用户的引导文本",
  "auto_next_agent": false,
  "next_step_hint": "调度器执行提示"
}}"""
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            plan_text = response.choices[0].message.content.strip()
            if plan_text.startswith("```"):
                plan_text = plan_text.split("\n", 1)[-1].rsplit("```", 1)[0]
            return json.loads(plan_text)
        except Exception:
            return self._recognize_with_rules(user_input, session_ctx)

    @staticmethod
    def _recognize_with_rules(user_input: str, session_ctx: dict) -> dict:
        """关键词规则降级路由"""
        msg = user_input.lower()

        # 面试结束信号
        end_signals = ["结束面试", "面试结束", "完成面试", "不面试了", "退出面试"]
        if any(sig in msg for sig in end_signals):
            return {
                "task_type": TASK_INTERVIEW_REVIEW,
                "target_agent": AGENT_REVIEW,
                "session_status": SESSION_FINISHED,
                "auto_next_agent": True,
            }

        # 复合场景：面试并复盘
        if any(k in msg for k in ["面试并复盘", "模拟面试加复盘", "面试加评估"]):
            return {
                "task_type": TASK_INTERVIEW_SESSION,
                "target_agent": AGENT_INTERVIEW,
                "session_status": SESSION_NEW,
                "auto_next_agent": True,
            }

        # 简历优化
        if any(k in msg for k in ["简历", "优化简历", "改简历", "ats", "简历修改", "润色"]):
            return {
                "task_type": TASK_RESUME_OPTIMIZE,
                "target_agent": AGENT_RESUME,
                "session_status": SESSION_NEW,
                "auto_next_agent": False,
            }

        # 面试复盘/评估
        if any(k in msg for k in ["复盘", "评估", "评分", "打分", "报告"]):
            return {
                "task_type": TASK_INTERVIEW_REVIEW,
                "target_agent": AGENT_REVIEW,
                "session_status": SESSION_FINISHED,
                "auto_next_agent": True,
            }

        # 面试模拟
        if any(k in msg for k in ["面试", "模拟", "出题", "面试题", "问问题", "开始面试"]):
            return {
                "task_type": TASK_INTERVIEW_SESSION,
                "target_agent": AGENT_INTERVIEW,
                "session_status": SESSION_NEW,
                "auto_next_agent": False,
            }

        # 薪资
        if any(k in msg for k in ["薪资", "工资", "待遇", "薪酬", "多少钱", "年薪"]):
            return {
                "task_type": TASK_INFO_RETRIEVE,
                "target_agent": AGENT_RETRIEVER,
                "task_params_extra": {"retrieve_type": "salary_query"},
                "session_status": SESSION_NEW,
                "auto_next_agent": False,
            }

        # 面经
        if any(k in msg for k in ["面经", "真题", "面试经验", "面试流程"]):
            return {
                "task_type": TASK_INFO_RETRIEVE,
                "target_agent": AGENT_RETRIEVER,
                "task_params_extra": {"retrieve_type": "interview_exp"},
                "session_status": SESSION_NEW,
                "auto_next_agent": False,
            }

        # 行业
        if any(k in msg for k in ["行业", "竞品", "前景", "趋势", "对比"]):
            return {
                "task_type": TASK_INFO_RETRIEVE,
                "target_agent": AGENT_RETRIEVER,
                "task_params_extra": {"retrieve_type": "industry_analysis"},
                "session_status": SESSION_NEW,
                "auto_next_agent": False,
            }

        # 公司知识问答：自然语言疑问句（非列表查询）→ qa 模式
        qa_patterns = [
            "吗", "怎么样", "如何", "好不好", "难不难", "多不多", "累不累",
            "值得去", "加班", "文化", "氛围", "工作强度", "福利怎么",
            "发展前景", "值得去吗", "适合", "推荐", "建议",
        ]
        if any(k in msg for k in qa_patterns):
            return {
                "task_type": TASK_COMPANY_QA,
                "target_agent": AGENT_RETRIEVER,
                "task_params_extra": {"retrieve_type": "mixed", "query_type": QUERY_TYPE_QA},
                "session_status": SESSION_NEW,
                "auto_next_agent": False,
            }

        # 默认：混合检索
        return {
            "task_type": TASK_INFO_RETRIEVE,
            "target_agent": AGENT_RETRIEVER,
            "task_params_extra": {"retrieve_type": "mixed"},
            "session_status": SESSION_NEW,
            "auto_next_agent": False,
        }

    # ==================== 步骤3+4：组装 task_params & auto_next_agent ====================

    def _assemble_plan_from_intent(
        self, intent: dict, user_input: str,
        session_ctx: dict, user_assets: dict,
    ) -> dict:
        """根据意图识别结果组装最终 plan"""
        target_agent = intent.get("target_agent", AGENT_NONE)
        task_type = intent.get("task_type", TASK_INVALID)
        session_status = intent.get("session_status", SESSION_NEW)
        auto_next = intent.get("auto_next_agent", False)
        extra_params = intent.get("task_params_extra", {}) or {}

        # 按目标 Agent 组装必填入参
        if target_agent == AGENT_RETRIEVER:
            task_params = self._assemble_retriever_params(
                user_input, user_assets, extra_params
            )
            # 公司知识问答使用不同的响应文案
            if task_type == TASK_COMPANY_QA:
                response = f"正在为您查询「{user_input[:30]}」..."
            else:
                response = f"正在为您检索「{user_input[:30]}」相关信息..."
        elif target_agent == AGENT_RESUME:
            task_params = self._assemble_resume_params(user_input, user_assets)
            response = "正在为您优化简历..."
        elif target_agent == AGENT_INTERVIEW:
            task_params = self._assemble_interview_params(user_input, session_ctx, user_assets)
            response = "正在进入面试模拟..."
        elif target_agent == AGENT_REVIEW:
            task_params = self._assemble_review_params(session_ctx, user_assets)
            response = "正在生成面试复盘报告..."
        else:
            return self._build_invalid_plan(user_input)

        return self._build_plan(
            task_type=task_type,
            target_agent=target_agent,
            session_status=session_status,
            task_params=task_params,
            response_to_user=intent.get("response_to_user", response),
            auto_next_agent=auto_next,
            next_step_hint=f"调度器执行 {target_agent}，auto_next={auto_next}",
        )

    @staticmethod
    def _assemble_retriever_params(
        user_input: str, user_assets: dict, extra_params: dict,
    ) -> dict:
        """组装 retriever_agent 必填入参（自动从 query 提取公司名）"""
        # 优先使用 user_assets 中的公司名，否则从 query 中智能提取
        company_name = user_assets.get("target_company", "")
        if not company_name:
            company_name = TaskPlanner._extract_company_from_query(user_input)
        return {
            "query": user_input,
            "retrieve_type": extra_params.get("retrieve_type", "mixed"),
            "query_type": extra_params.get("query_type", QUERY_TYPE_KEYWORD),
            "company_name": company_name,
            "company_id": extra_params.get("company_id", user_assets.get("target_company_id", "")),
            "target_position": user_assets.get("target_position", ""),
            "top_k": 5,
        }

    @staticmethod
    def _extract_company_from_query(query: str) -> str:
        """从用户问题中智能提取公司名（按长度降序匹配，优先长名称）"""
        if not query:
            return ""
        sorted_names = sorted(_KNOWN_COMPANY_NAMES, key=len, reverse=True)
        for name in sorted_names:
            if name in query:
                return name
        return ""

    @staticmethod
    def _assemble_resume_params(user_input: str, user_assets: dict) -> dict:
        """组装 resume_agent 必填入参"""
        # 根据 user_input 判断优化类型
        msg = user_input.lower()
        if any(k in msg for k in ["全文", "整体", "完整"]):
            optimize_type = "full"
        elif any(k in msg for k in ["ats", "匹配", "诊断", "通过率"]):
            optimize_type = "ats_match"
        else:
            optimize_type = "section"
        return {
            "resume_text": user_assets.get("resume_text", ""),
            "optimize_type": optimize_type,
            "jd_text": user_assets.get("jd_text", ""),
            "target_position": user_assets.get("target_position", ""),
            "difficulty": "middle",
        }

    @staticmethod
    def _assemble_interview_params(
        user_input: str, session_ctx: dict, user_assets: dict,
    ) -> dict:
        """组装 interview_agent 必填入参"""
        current_stage = session_ctx.get("current_stage", "init")
        dialogue_history = session_ctx.get("dialogue_history", []) or session_ctx.get("history", [])
        # 根据历史长度推断面试类型与难度
        interview_type = session_ctx.get("interview_type", "tech_1")
        difficulty = session_ctx.get("difficulty", "middle")
        return {
            "session_stage": current_stage,
            "target_position": user_assets.get("target_position", ""),
            "interview_type": interview_type,
            "difficulty": difficulty,
            "resume_summary": user_assets.get("resume_text", "")[:500],
            "jd_summary": user_assets.get("jd_text", "")[:500],
            "dialogue_history": dialogue_history,
            "user_input": user_input,
        }

    @staticmethod
    def _assemble_review_params(session_ctx: dict, user_assets: dict) -> dict:
        """组装 review_agent 必填入参"""
        dialogue_history = session_ctx.get("dialogue_history", []) or session_ctx.get("history", [])
        return {
            "interview_history": dialogue_history,
            "transcript": dialogue_history,  # 兼容旧参数名
            "target_position": (
                session_ctx.get("target_position")
                or user_assets.get("target_position", "")
            ),
            "target_company": (
                session_ctx.get("target_company")
                or user_assets.get("target_company", "")
            ),
            "interview_type": session_ctx.get("interview_type", "tech_1"),
            "difficulty": session_ctx.get("difficulty", "middle"),
            # Phase 14 修复：传递面试Agent已计算的评分数据，避免重新生成时评分全为0
            "question_records": session_ctx.get("question_records", []),
            "stage_scores": session_ctx.get("stage_scores", {}),
            "section_scores": session_ctx.get("section_scores", {}),
            "total_score": session_ctx.get("total_score", 0),
        }

    # ==================== 工具方法 ====================

    @staticmethod
    def _build_plan(
        task_type: str, target_agent: str, session_status: str,
        task_params: dict, response_to_user: str,
        auto_next_agent: bool, next_step_hint: str,
    ) -> dict:
        """构造标准化输出"""
        return {
            "task_type": task_type,
            "target_agent": target_agent,
            "session_status": session_status,
            "task_params": task_params,
            "response_to_user": response_to_user,
            "auto_next_agent": auto_next_agent,
            "next_step_hint": next_step_hint,
        }

    @staticmethod
    def _build_invalid_plan(user_input: str) -> dict:
        """构造无效任务响应"""
        return {
            "task_type": TASK_INVALID,
            "target_agent": AGENT_NONE,
            "session_status": SESSION_ERROR,
            "task_params": {},
            "response_to_user": f"无法识别您的需求「{user_input[:30]}」，请明确说明您想：查询公司信息 / 优化简历 / 模拟面试 / 面试复盘。",
            "auto_next_agent": False,
            "next_step_hint": "意图识别失败，需用户澄清",
        }
