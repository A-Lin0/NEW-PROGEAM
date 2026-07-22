# agent/orchestrator.py
"""
多 Agent 编排器（Plan-Solve 架构 + 文件持久化）

核心职责：
1. 自动意图调度：调用 TaskPlanner 解析用户输入，分配到对应子 Agent
2. 依赖注入：将 vector_store / db_session / redis 统一注入各子 Agent
3. Redis 会话存储：维护多轮面试/简历优化的会话上下文
4. 文件持久化：对话历史存入文件，切换模块后历史不丢失
5. 面试自动复盘联动：检测 auto_next_agent=true，自动触发 ReviewAgent

调用入口：
- auto_route(user_message, ...)    Plan-Solve 自动路由（流式事件）
- handle_message(session_id, ...)  SSE 接口直接调用（流式字符串）
- execute(task_type, payload)      显式任务类型（API 层直接调用）
"""

import asyncio
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Optional, AsyncGenerator, Any

from agent.core.planner import (
    TaskPlanner, AGENT_RETRIEVER, AGENT_RESUME,
    AGENT_INTERVIEW, AGENT_REVIEW, AGENT_NONE,
)
from agent.core.resume_agent import ResumeAgent
from agent.core.interview_agent import InterviewAgent
from agent.core.review_agent import ReviewAgent
from agent.core.retriever_agent import RetrieverAgent
from agent.knowledge.embeddings import EmbeddingModel
from agent.knowledge.vector_store import VectorStore


# 有效的 Agent 键名（与 planner 输出的 target_agent 一致）
VALID_AGENTS = {AGENT_RETRIEVER, AGENT_RESUME, AGENT_INTERVIEW, AGENT_REVIEW}

# intent → agent_key 映射（供 handle_message 显式 intent 调用）
INTENT_TO_AGENT = {
    "interview": AGENT_INTERVIEW,
    "review": AGENT_REVIEW,
    "resume": AGENT_RESUME,
    "retrieve": AGENT_RETRIEVER,
    "info_retrieve": AGENT_RETRIEVER,
    "resume_optimize": AGENT_RESUME,
    "interview_session": AGENT_INTERVIEW,
    "interview_review": AGENT_REVIEW,
}

# Redis 会话 key 前缀与过期时间
SESSION_PREFIX = "session"
SESSION_TTL = 3600  # 1小时

# 文件持久化目录
DEFAULT_HISTORY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "interview_history")


class AgentOrchestrator:
    """多 Agent 编排器"""

    def __init__(
        self,
        vector_store: Optional[VectorStore] = None,
        embedder: Optional[EmbeddingModel] = None,
        redis_client: Optional[Any] = None,
        db_session_factory: Optional[Any] = None,
        llm_api_key: str = "",
        llm_base_url: str = "",
        llm_model: str = "gpt-4o",
        history_dir: str = "",
    ):
        """
        :param vector_store: 已初始化的向量库实例
        :param embedder: 嵌入模型实例
        :param redis_client: redis.asyncio.Redis 实例（用于会话存储）
        :param db_session_factory: AsyncSession 工厂（callable，返回 AsyncSession 上下文）
        :param llm_*: LLM 配置，透传给各 Agent
        :param history_dir: 对话历史文件持久化目录，默认 data/interview_history/
        """
        self.vector_store = vector_store
        self.embedder = embedder
        self.redis = redis_client
        self.db_session_factory = db_session_factory
        self.llm_api_key = llm_api_key
        # 内存会话存储（Redis 不可用时的降级方案）
        self._mem_sessions: dict = {}
        self._mem_sessions_ttl: dict = {}
        self.llm_base_url = llm_base_url
        self.llm_model = llm_model

        # 文件持久化目录
        self._history_dir = history_dir or DEFAULT_HISTORY_DIR
        os.makedirs(self._history_dir, exist_ok=True)

        # 规划器（Plan 阶段）
        self.planner = TaskPlanner(
            api_key=llm_api_key, base_url=llm_base_url, model=llm_model
        )

        # 统一初始化子 Agent，注入依赖（避免硬编码实例化）
        # 键名与 planner 输出的 target_agent 保持一致
        shared_deps = {
            "vector_store": vector_store,
            "embedder": embedder,
            "redis_client": redis_client,
            "db_session_factory": db_session_factory,
            "api_key": llm_api_key,
            "base_url": llm_base_url,
            "model": llm_model,
        }
        self.agents = {}
        # 逐个初始化 Agent，单个失败不影响整体
        agent_factories = {
            AGENT_RETRIEVER: lambda: RetrieverAgent(
                vector_store=vector_store, embedder=embedder,
                llm_api_key=llm_api_key, llm_base_url=llm_base_url, llm_model=llm_model,
            ),
            AGENT_RESUME: lambda: ResumeAgent(**shared_deps),
            AGENT_INTERVIEW: lambda: InterviewAgent(**shared_deps),
            AGENT_REVIEW: lambda: ReviewAgent(**shared_deps),
        }
        for agent_key, factory in agent_factories.items():
            try:
                self.agents[agent_key] = factory()
                logging.getLogger(__name__).info("Agent [%s] 初始化成功", agent_key)
            except Exception as e:
                logging.getLogger(__name__).error("Agent [%s] 初始化失败: %s", agent_key, e, exc_info=True)
                # 降级：创建占位 None，后续调用时检查
                self.agents[agent_key] = None

    # ==================== 属性访问（兼容旧代码 orchestrator.resume_agent）====================

    @property
    def resume_agent(self) -> ResumeAgent:
        return self.agents.get(AGENT_RESUME)

    @property
    def interview_agent(self) -> InterviewAgent:
        return self.agents.get(AGENT_INTERVIEW)

    @property
    def review_agent(self) -> ReviewAgent:
        return self.agents.get(AGENT_REVIEW)

    @property
    def retriever_agent(self):
        return self.agents.get(AGENT_RETRIEVER)

    # ==================== 入口1：自动路由（Plan-Solve） ====================

    async def auto_route(
        self,
        user_message: str,
        session_id: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> AsyncGenerator[dict, None]:
        """
        自动路由入口：Plan 阶段拆解 → Solve 阶段执行 → 流式返回

        流程：
        1. 读取 Redis 会话上下文（若有 session_id）
        2. TaskPlanner.plan() 解析用户意图，生成标准化调度指令
        3. 执行 target_agent
        4. 若 auto_next_agent=true 且 interview 结束，自动触发 review_agent
        5. 更新 Redis 会话上下文

        yield 事件格式:
            {"type":"plan", "plan":{...}}                       计划阶段
            {"type":"task_start", "task":"...", "response_to_user":"..."}
            {"type":"data", "content":..., "task":"..."}         执行结果
            {"type":"review_triggered", "session_id":"..."}       触发复盘联动
            {"type":"error", "message":"..."}                    错误
            {"type":"done", "session_id":"...", "session_status":"..."}
        """
        session_id = session_id or str(uuid.uuid4())
        session_ctx = await self._load_session(session_id) or {}
        session_ctx["history"] = session_ctx.get("history", [])
        session_ctx["history"].append({"role": "user", "content": user_message})
        session_ctx["session_status"] = session_ctx.get("session_status", "new")
        session_ctx["current_stage"] = session_ctx.get("current_stage", "init")
        session_ctx["user_assets"] = session_ctx.get("user_assets", {})
        session_ctx["completed_stages"] = session_ctx.get("completed_stages", [])
        context = {**(context or {}), "session": session_ctx}

        # ---- Plan 阶段 ----
        try:
            plan = await self.planner.plan(user_message, context)
        except Exception as e:
            yield {"type": "error", "message": f"规划失败: {e}"}
            return

        yield {"type": "plan", "plan": plan, "session_id": session_id}

        target_agent = plan.get("target_agent", AGENT_NONE)
        task_params = plan.get("task_params", {}) or {}
        auto_next = plan.get("auto_next_agent", False)
        response_to_user = plan.get("response_to_user", "")

        # 无效任务直接返回
        if target_agent not in VALID_AGENTS:
            yield {
                "type": "data",
                "content": {"message": response_to_user},
                "task": "none",
            }
            await self._save_session(session_id, session_ctx)
            yield {"type": "done", "session_id": session_id}
            return

        # 注入会话上下文
        task_params["session_id"] = session_id
        task_params["session_ctx"] = session_ctx

        yield {
            "type": "task_start",
            "task": target_agent,
            "response_to_user": response_to_user,
        }

        # ---- Solve 阶段：执行目标 Agent ----
        interview_finished = False
        async for event in self._execute_with_hooks(target_agent, task_params):
            yield event
            # 检测面试结束信号（更新会话状态 + 标记联动）
            if (
                target_agent == AGENT_INTERVIEW
                and event.get("type") == "data"
                and isinstance(event.get("content"), dict)
                and event["content"].get("session_finished")
            ):
                interview_finished = True
                session_ctx["session_status"] = "finished"
                session_ctx["current_stage"] = "end"

        # ---- auto_next_agent 联动：面试结束自动触发复盘 ----
        if auto_next and target_agent == AGENT_INTERVIEW and interview_finished:
            yield {"type": "review_triggered", "session_id": session_id}
            review_params = self._build_review_params(session_ctx)
            review_params["session_id"] = session_id
            review_params["session_ctx"] = session_ctx

            yield {
                "type": "task_start",
                "task": AGENT_REVIEW,
                "response_to_user": "面试已结束，正在生成复盘报告...",
            }
            async for event in self._execute_with_hooks(AGENT_REVIEW, review_params):
                yield event

        # 显式 review 任务也更新会话状态为 finished
        if target_agent == AGENT_REVIEW:
            session_ctx["session_status"] = "finished"

        # ---- 更新会话上下文 ----
        await self._save_session(session_id, session_ctx)
        yield {
            "type": "done",
            "session_id": session_id,
            "session_status": session_ctx.get("session_status", "new"),
        }

    # ==================== 入口2：SSE 直接调用（供 interview/review API 使用）====================

    async def handle_message(
        self,
        session_id: str,
        message: str,
        intent: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        SSE 接口直接调用入口：按 intent 路由到对应 Agent，返回字符串流

        :param session_id: Redis 会话 ID
        :param message: 用户消息
        :param intent: 显式意图（interview/review/resume/retrieve），为空则走 planner 自动路由
        """
        session_ctx = await self._load_session(session_id) or {}
        session_ctx["history"] = session_ctx.get("history", [])
        session_ctx["history"].append({"role": "user", "content": message})
        session_ctx["session_status"] = session_ctx.get("session_status", "new")
        session_ctx["current_stage"] = session_ctx.get("current_stage", "init")
        session_ctx["user_assets"] = session_ctx.get("user_assets", {})
        # 题库相关上下文
        session_ctx["question_index"] = session_ctx.get("question_index", 0)
        session_ctx["question_records"] = session_ctx.get("question_records", [])
        session_ctx["stage_scores"] = session_ctx.get("stage_scores", {})
        session_ctx["completed_stages"] = session_ctx.get("completed_stages", [])
        # 结束状态锁：持久化到 Redis，刷新页面后状态保持一致
        session_ctx["ended"] = bool(session_ctx.get("ended", False))

        # Phase 14 调试日志：记录 handle_message 加载的 session_ctx
        import logging as _logging
        _logging.getLogger(__name__).info(
            "[ Phase14 调试 handle_message ] "
            "session_id=%s | intent=%s | message=%s | "
            "user_assets=%s | session_status=%s | current_stage=%s | "
            "session_ctx keys=%s",
            session_id, intent, message,
            json.dumps(session_ctx.get("user_assets", {}), ensure_ascii=False),
            session_ctx.get("session_status"),
            session_ctx.get("current_stage"),
            list(session_ctx.keys()),
        )

        # 识别面试命令
        command = "chat"
        if intent == "interview":
            if message in ("开始面试", "start"):
                command = "start"
            elif message in ("下一题", "next", "skip", "跳过"):
                command = "skip"
            elif message in ("结束面试", "end"):
                command = "end"
        session_ctx["command"] = command

        # 决定 agent_key
        if intent:
            agent_key = INTENT_TO_AGENT.get(intent)
        else:
            # 走 planner 自动路由
            context = {"session": session_ctx}
            try:
                plan = await self.planner.plan(message, context)
            except Exception as e:
                yield f"[错误] 规划失败: {e}"
                await self._save_session(session_id, session_ctx)
                return
            agent_key = plan.get("target_agent")
            task_params = plan.get("task_params", {}) or {}
            response_to_user = plan.get("response_to_user", "")
            if response_to_user:
                yield response_to_user
            if agent_key not in VALID_AGENTS:
                await self._save_session(session_id, session_ctx)
                return

        if intent:
            # 显式 intent：构造默认参数
            task_params = self._build_params_for_intent(intent, message, session_ctx)

        agent = self.agents.get(agent_key) if agent_key else None
        if agent is None:
            yield f"[错误] Agent 未注册: {agent_key}"
            await self._save_session(session_id, session_ctx)
            return

        # 注入会话上下文
        task_params["session_id"] = session_id
        task_params["session_ctx"] = session_ctx

        # 累积面试官话术，用于回填到 history（保持多轮对话上下文连贯）
        assistant_text_parts = []

        try:
            async for chunk in agent.stream(task_params):
                if chunk == "[DONE]":
                    break
                # 检测面试 META 信号：更新会话状态，同时透传给 API 层做前端 UI 同步
                is_meta = (
                    agent_key == AGENT_INTERVIEW
                    and isinstance(chunk, str)
                    and chunk.startswith("\n\n__META__")
                )
                if is_meta:
                    try:
                        meta = json.loads(chunk[len("\n\n__META__"):])
                        # 仅同步面试结束状态与评分数据到 session_ctx
                        # 注意：current_stage / question_index 由 interview_agent 自己维护
                        #（session_ctx 是按引用传递，agent 已在 META 之前完成写入）
                        # 此处不能再覆盖，否则会破坏 agent 的 stage-local 计数逻辑
                        if meta.get("session_finished"):
                            session_ctx["session_status"] = "finished"
                        if "total_score" in meta:
                            session_ctx["total_score"] = meta["total_score"]
                        if "section_scores" in meta:
                            session_ctx["section_scores"] = meta["section_scores"]
                    except Exception:
                        pass
                # 累积非 META 的文本内容（面试官话术），META 透传给 API 层
                if isinstance(chunk, str) and not is_meta:
                    assistant_text_parts.append(chunk)
                yield chunk
        finally:
            # 回填面试官话术到 history，确保下一轮 LLM 能看到自己上一轮的输出
            assistant_text = "".join(assistant_text_parts).strip()
            if assistant_text:
                session_ctx["history"].append({
                    "role": "interviewer",
                    "content": assistant_text,
                })
            await self._save_session(session_id, session_ctx)

    @staticmethod
    def _build_params_for_intent(intent: str, message: str, session_ctx: dict) -> dict:
        """根据 intent 构造默认 task_params"""
        user_assets = session_ctx.get("user_assets", {})
        params = {"user_input": message}
        if intent in ("interview", "interview_session"):
            # 优先从 session_ctx 直接读取（_handle_start 写入），其次从 user_assets
            target_position = (
                session_ctx.get("target_position")
                or user_assets.get("target_position")
                or ""
            )
            params.update({
                "session_stage": session_ctx.get("current_stage", "init"),
                "target_position": target_position,
                "company_name": user_assets.get("target_company", ""),
                "company_id": user_assets.get("target_company_id", ""),
                "interview_type": session_ctx.get("interview_type", "tech_1"),
                "difficulty": session_ctx.get("difficulty", "middle"),
                "resume_summary": user_assets.get("resume_text", "")[:500],
                "jd_summary": user_assets.get("jd_text", "")[:500],
                "dialogue_history": session_ctx.get("history", []),
                "command": session_ctx.get("command", "chat"),
                "question_index": session_ctx.get("question_index", 0),
                "question_records": session_ctx.get("question_records", []),
                "stage_scores": session_ctx.get("stage_scores", {}),
            })
        elif intent in ("review", "interview_review"):
            params.update({
                "interview_history": session_ctx.get("history", []),
                "transcript": session_ctx.get("history", []),
                "target_position": (
                    session_ctx.get("target_position")
                    or user_assets.get("target_position")
                    or ""
                ),
                "interview_type": session_ctx.get("interview_type", "tech_1"),
                "difficulty": session_ctx.get("difficulty", "middle"),
                # 传递面试Agent已计算的评分数据，供 ReviewAgent 使用
                "question_records": session_ctx.get("question_records", []),
                "stage_scores": session_ctx.get("stage_scores", {}),
                "section_scores": session_ctx.get("section_scores", {}),
                "total_score": session_ctx.get("total_score", 0),
            })
        elif intent in ("resume", "resume_optimize"):
            params.update({
                "raw_resume": message,
                "resume_text": user_assets.get("resume_text", message),
                "job_description": user_assets.get("jd_text", ""),
                "jd_text": user_assets.get("jd_text", ""),
                "optimize_type": "section",
                "target_position": user_assets.get("target_position", ""),
                "difficulty": "middle",
            })
        elif intent in ("retrieve", "info_retrieve"):
            params.update({
                "query": message,
                "retrieve_type": "mixed",
                "query_type": "keyword",
                "company_name": user_assets.get("target_company", ""),
                "company_id": user_assets.get("target_company_id", ""),
                "target_position": user_assets.get("target_position", ""),
                "top_k": 5,
            })
        return params

    @staticmethod
    def _build_review_params(session_ctx: dict) -> dict:
        """构造复盘 Agent 参数（auto_next 联动时使用）"""
        user_assets = session_ctx.get("user_assets", {})
        history = session_ctx.get("history", [])
        return {
            "interview_history": history,
            "transcript": history,  # 兼容旧参数名
            "target_position": (
                session_ctx.get("target_position")
                or user_assets.get("target_position")
                or ""
            ),
            "interview_type": session_ctx.get("interview_type", "tech_1"),
            "difficulty": session_ctx.get("difficulty", "middle"),
            # 传递面试Agent已计算的评分数据
            "question_records": session_ctx.get("question_records", []),
            "stage_scores": session_ctx.get("stage_scores", {}),
            "section_scores": session_ctx.get("section_scores", {}),
            "total_score": session_ctx.get("total_score", 0),
        }

    # ==================== 入口3：显式执行 ====================

    async def execute(self, task_type: str, payload: dict) -> AsyncGenerator[dict, None]:
        """显式指定任务类型执行（供 API 层直接调用）"""
        if task_type not in VALID_AGENTS:
            # 兼容旧键名
            legacy_mapping = {
                "resume": AGENT_RESUME,
                "interview": AGENT_INTERVIEW,
                "review": AGENT_REVIEW,
                "retrieve": AGENT_RETRIEVER,
                "retriever": AGENT_RETRIEVER,
            }
            task_type = legacy_mapping.get(task_type, task_type)
        if task_type not in VALID_AGENTS:
            yield {"error": f"未知任务类型: {task_type}"}
            return
        async for event in self._execute_with_hooks(task_type, payload):
            yield event

    async def _execute_with_hooks(
        self, task_type: str, payload: dict
    ) -> AsyncGenerator[dict, None]:
        """带超时、错误捕获的执行包装"""
        agent = self.agents.get(task_type)
        if agent is None:
            yield {"type": "error", "message": f"Agent 未注册: {task_type}"}
            return
        try:
            async for chunk in self._stream_with_timeout(agent, payload, timeout=60):
                yield chunk
        except asyncio.TimeoutError:
            yield {"type": "error", "message": "任务执行超时，请稍后重试"}
        except Exception as e:
            yield {"type": "error", "message": f"服务内部错误: {str(e)}"}

    async def _stream_with_timeout(
        self, agent, payload, timeout=60
    ) -> AsyncGenerator[dict, None]:
        """流式输出 + 超时控制"""
        gen = agent.stream(payload)
        while True:
            try:
                chunk = await asyncio.wait_for(gen.__anext__(), timeout=timeout)
                yield {"type": "data", "content": chunk, "task": payload.get("session_id", "")}
            except StopAsyncIteration:
                break

    # ==================== Redis 会话存储 + 文件持久化 ====================

    async def _load_session(self, session_id: str) -> Optional[dict]:
        """从 Redis 读取会话上下文，Redis 不可用时降级为内存存储，最后尝试文件"""
        if self.redis:
            try:
                raw = await self.redis.get(f"{SESSION_PREFIX}:{session_id}")
                if raw:
                    return json.loads(raw)
            except Exception:
                pass  # Redis 异常时尝试内存降级
        # 内存降级
        key = f"{SESSION_PREFIX}:{session_id}"
        if key in self._mem_sessions:
            if time.time() < self._mem_sessions_ttl.get(key, 0):
                return self._mem_sessions[key]
            else:
                del self._mem_sessions[key]
                self._mem_sessions_ttl.pop(key, None)
        # 文件降级：Redis 和内存都不可用时，从文件加载
        return self._load_history_from_file(session_id)

    async def _save_session(self, session_id: str, ctx: dict) -> None:
        """持久化会话上下文到 Redis + 文件（双重保障，切换模块不丢失）"""
        ctx["updated_at"] = int(time.time())
        if self.redis:
            try:
                await self.redis.setex(
                    f"{SESSION_PREFIX}:{session_id}",
                    SESSION_TTL,
                    json.dumps(ctx, ensure_ascii=False, default=str),
                )
            except Exception:
                pass  # Redis 不可用时降级为内存+文件存储
        # 内存降级
        key = f"{SESSION_PREFIX}:{session_id}"
        self._mem_sessions[key] = ctx
        self._mem_sessions_ttl[key] = time.time() + SESSION_TTL
        # 文件持久化：每次对话后保存，确保切换模块后历史不丢失
        self._save_history_to_file(session_id, ctx)

    # ==================== 文件持久化（核心新增） ====================

    def _get_history_file_path(self, session_id: str) -> str:
        """获取会话历史文件路径"""
        # 对 session_id 做安全处理，防止路径穿越
        safe_id = "".join(c for c in session_id if c.isalnum() or c in "-_")
        return os.path.join(self._history_dir, f"{safe_id}.json")

    def _save_history_to_file(self, session_id: str, ctx: dict) -> None:
        """将对话历史保存到文件（持久化存储，不受 Redis TTL 限制）"""
        try:
            file_path = self._get_history_file_path(session_id)
            # 提取需要持久化的核心字段
            # 注意：pending_stage_start 必须持久化，否则从文件恢复时
            # 新阶段第1题不会输出，导致 n-1 计数偏差
            persist_data = {
                "session_id": session_id,
                "history": ctx.get("history", []),
                "question_records": ctx.get("question_records", []),
                "stage_scores": ctx.get("stage_scores", {}),
                "section_scores": ctx.get("section_scores", {}),
                "total_score": ctx.get("total_score", 0),
                "current_stage": ctx.get("current_stage", "init"),
                "question_index": ctx.get("question_index", 0),
                "session_status": ctx.get("session_status", "new"),
                "completed_stages": ctx.get("completed_stages", []),
                "target_position": ctx.get("target_position", ""),
                "user_assets": ctx.get("user_assets", {}),
                "pending_stage_start": ctx.get("pending_stage_start"),
                "ended": ctx.get("ended", False),
                "company_ctx": ctx.get("company_ctx"),
                "position_ctx": ctx.get("position_ctx"),
                # 会话级已出题缓存库（用于题目去重 + 维度多样性管控）
                "question_cache": ctx.get("question_cache", {
                    "asked_questions": [],
                    "asked_dimensions": [],
                }),
                "updated_at": ctx.get("updated_at", int(time.time())),
            }
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(persist_data, f, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            logging.getLogger(__name__).warning("保存历史文件失败: %s", e)

    def _load_history_from_file(self, session_id: str) -> Optional[dict]:
        """从文件加载对话历史（Redis 不可用时的最终降级方案）"""
        try:
            file_path = self._get_history_file_path(session_id)
            if not os.path.exists(file_path):
                return None
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 返回完整的 session_ctx 格式（兼容 Redis 格式）
            # 注意：pending_stage_start 必须恢复，否则新阶段第1题不会输出
            return {
                "history": data.get("history", []),
                "question_records": data.get("question_records", []),
                "stage_scores": data.get("stage_scores", {}),
                "section_scores": data.get("section_scores", {}),
                "total_score": data.get("total_score", 0),
                "current_stage": data.get("current_stage", "init"),
                "question_index": data.get("question_index", 0),
                "session_status": data.get("session_status", "new"),
                "completed_stages": data.get("completed_stages", []),
                "target_position": data.get("target_position", ""),
                "user_assets": data.get("user_assets", {}),
                "pending_stage_start": data.get("pending_stage_start"),
                "ended": data.get("ended", False),
                "company_ctx": data.get("company_ctx"),
                "position_ctx": data.get("position_ctx"),
                # 会话级已出题缓存库（用于题目去重 + 维度多样性管控）
                "question_cache": data.get("question_cache", {
                    "asked_questions": [],
                    "asked_dimensions": [],
                }),
                "updated_at": data.get("updated_at", 0),
            }
        except Exception as e:
            logging.getLogger(__name__).warning("加载历史文件失败: %s", e)
            return None

    def get_persisted_history(self, session_id: str) -> Optional[dict]:
        """公开方法：获取持久化的对话历史（供 API 层恢复会话使用）"""
        return self._load_history_from_file(session_id)

    def delete_persisted_history(self, session_id: str) -> bool:
        """删除持久化的对话历史文件"""
        try:
            file_path = self._get_history_file_path(session_id)
            if os.path.exists(file_path):
                os.remove(file_path)
                return True
            return False
        except Exception as e:
            logging.getLogger(__name__).warning("删除历史文件失败: %s", e)
            return False

    async def _clear_session(self, session_id: str) -> None:
        """清理会话（Redis + 内存 + 文件）"""
        if self.redis:
            try:
                await self.redis.delete(f"{SESSION_PREFIX}:{session_id}")
            except Exception:
                pass
        # 同时清理内存存储
        key = f"{SESSION_PREFIX}:{session_id}"
        self._mem_sessions.pop(key, None)
        self._mem_sessions_ttl.pop(key, None)
        # 清理持久化文件
        self.delete_persisted_history(session_id)
