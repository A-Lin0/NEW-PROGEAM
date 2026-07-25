# agent/core/interview_agent.py
"""
面试模拟 Agent（题库分层版 + 公司岗位定制化 + 文件持久化）

职责：
- 1+3+2+3+1 题量分配的结构化面试（共10题）
- 基于目标公司+岗位的定制化出题与话术
- AI 回答评估（完整度/关键词/逻辑/量化）
- 跳过/下一题处理
- 5 环节加权评分 + 复盘数据生成
- 阶段自动流转：各环节题目数量达标后自动进入下一环节
- 对话历史文件持久化：切换模块后历史不丢失

题库分层：
  self_intro  : 1 题（开场自我介绍）
  tech_qa     : 3 题（专业技术）
  star_qa     : 2 题（行为面试 STAR）
  project_qa  : 3 题（项目案例综合）
  reverse_qa  : 1 题（反向提问）

定制化能力：
- 传入 company_name/company_id 时，自动读取公司知识库，注入公司业务、面试风格、企业文化作为出题上下文
- 传入 target_position 时，识别岗位大类，匹配对应能力考察点
- 未传入公司岗位参数时，自动降级为通用面试模式
"""

import json
import logging
import os
from typing import Optional, Any


# ============================================================
# 题库配置：1+3+2+3+1
# ============================================================
QUESTION_BANK_CONFIG = {
    "self_intro":  {"count": 1, "type": "自我介绍",     "desc": "开场题"},
    "tech_qa":     {"count": 3, "type": "专业技术",     "desc": "岗位对应技术题"},
    "star_qa":     {"count": 2, "type": "行为面试STAR",  "desc": "情景/经历考察题"},
    "project_qa":  {"count": 3, "type": "项目案例",     "desc": "实战分析大题"},
    "reverse_qa":  {"count": 1, "type": "反向提问",     "desc": "面试官反问题目"},
}

# 阶段顺序
STAGE_FLOW = ["init", "self_intro", "tech_qa", "star_qa", "project_qa", "reverse_qa", "end"]

# 全局累计题目计数（用于前端进度条：总共10题）
TOTAL_QUESTIONS = sum(c["count"] for c in QUESTION_BANK_CONFIG.values())  # = 10

# 各阶段在 STAGE_FLOW 中的累计题目数（用于前端进度条）
STAGE_CUMULATIVE_COUNTS = {}
_cum = 0
for _stage in STAGE_FLOW:
    _cfg = QUESTION_BANK_CONFIG.get(_stage)
    if _cfg:
        _cum += _cfg["count"]
        STAGE_CUMULATIVE_COUNTS[_stage] = _cum

# 各阶段起始题号（全局题号，用于 progress 计算）
# end 阶段起始题号 = 总题数，用于面试结束时进度显示 100%
STAGE_START_INDEX = {}
_start = 0
for _stage in STAGE_FLOW:
    _cfg = QUESTION_BANK_CONFIG.get(_stage)
    if _cfg:
        STAGE_START_INDEX[_stage] = _start
        _start += _cfg["count"]
STAGE_START_INDEX["end"] = TOTAL_QUESTIONS  # end 阶段：全部题目已完成

# 各环节权重（加权计算总分，总和=1.0）
STAGE_WEIGHTS = {
    "self_intro":  0.10,
    "tech_qa":     0.30,
    "star_qa":     0.20,
    "project_qa":  0.25,
    "reverse_qa":  0.15,
}

# 岗位大类 → 核心考察点映射
POSITION_CATEGORIES = {
    "前端": "JavaScript/TypeScript、React/Vue框架、CSS布局、浏览器原理、性能优化、工程化",
    "后端": "分布式系统、数据库设计、API设计、并发编程、微服务架构、系统设计",
    "算法": "数据结构与算法、机器学习、深度学习、模型优化、特征工程、数学基础",
    "产品": "需求分析、用户研究、数据分析、产品设计、项目管理、商业思维",
    "运营": "用户增长、内容运营、数据分析、活动策划、社区运营、渠道管理",
    "数据": "SQL、数据建模、ETL、数据可视化、统计学、大数据技术栈",
    "测试": "自动化测试、性能测试、测试用例设计、CI/CD、质量保障、安全测试",
    "安全": "漏洞挖掘、渗透测试、安全架构、密码学、应急响应、合规审计",
    "客户端": "iOS/Android开发、性能优化、UI/UX、跨平台方案、网络编程",
    "全栈": "前后端技术栈、系统架构、DevOps、数据库、云服务",
    "设计": "视觉设计、交互设计、设计体系、用户研究、跨角色协作、项目落地",
}

# 岗位大类 → 能力维度拆分（用于题目多样性管控，同维度单会话最多1道）
# 每个维度包含多个出题方向，确保题目覆盖岗位核心能力
POSITION_DIMENSIONS = {
    "设计": [
        {"dim": "视觉设计能力", "directions": "视觉风格定义、品牌视觉适配、色彩排版体系、视觉落地还原"},
        {"dim": "交互体验设计", "directions": "用户路径优化、易用性设计、B端复杂场景交互、防误操作设计"},
        {"dim": "从0到1项目落地", "directions": "产品立项到设计上线全流程、需求拆解、方案选型与迭代"},
        {"dim": "设计体系建设", "directions": "组件库搭建、设计规范制定、多端视觉与交互统一"},
        {"dim": "用户研究与数据", "directions": "用户调研方法、可用性测试、数据驱动设计优化"},
        {"dim": "跨角色协作", "directions": "与产品/开发对齐、设计走查、需求变更应对"},
    ],
    "前端": [
        {"dim": "JavaScript核心", "directions": "原型链、闭包、异步编程、ES6+特性、事件循环"},
        {"dim": "框架原理", "directions": "React/Vue响应式原理、虚拟DOM、Diff算法、组件设计模式"},
        {"dim": "浏览器与网络", "directions": "渲染流程、事件机制、HTTP协议、缓存策略、跨域处理"},
        {"dim": "工程化与构建", "directions": "Webpack/Vite配置、模块化、CI/CD、代码规范、性能监控"},
        {"dim": "性能优化", "directions": "首屏加载、运行时优化、长列表渲染、内存管理、监控告警"},
        {"dim": "架构设计", "directions": "微前端、SSR、状态管理、组件库设计、低代码平台"},
    ],
    "后端": [
        {"dim": "语言与基础", "directions": "语言特性、并发模型、内存管理、数据结构、设计模式"},
        {"dim": "数据库设计", "directions": "SQL优化、索引设计、事务隔离、分库分表、NoSQL选型"},
        {"dim": "分布式系统", "directions": "CAP理论、一致性算法、分布式锁、消息队列、服务治理"},
        {"dim": "API与协议", "directions": "RESTful设计、GraphQL、gRPC、鉴权方案、接口版本管理"},
        {"dim": "微服务架构", "directions": "服务拆分、注册发现、配置中心、熔断降级、链路追踪"},
        {"dim": "高并发处理", "directions": "缓存策略、限流算法、异步处理、读写分离、容量规划"},
    ],
    "产品": [
        {"dim": "需求分析", "directions": "用户故事、需求优先级、需求评审、需求变更管理"},
        {"dim": "产品设计", "directions": "产品架构、流程设计、原型设计、交互逻辑、信息架构"},
        {"dim": "数据分析", "directions": "指标体系、AB测试、漏斗分析、用户分群、数据驱动决策"},
        {"dim": "用户研究", "directions": "用户画像、用户访谈、问卷调研、可用性测试、用户旅程"},
        {"dim": "项目管理", "directions": "项目立项、进度管控、风险应对、跨部门协作、敏捷迭代"},
        {"dim": "商业思维", "directions": "商业模式、盈利路径、竞品分析、市场洞察、ROI评估"},
    ],
    "运营": [
        {"dim": "用户增长", "directions": "拉新策略、留存提升、裂变机制、用户分层、增长黑客"},
        {"dim": "内容运营", "directions": "内容规划、选题策划、内容分发、UGC运营、内容生态"},
        {"dim": "数据分析", "directions": "运营指标体系、数据看板、归因分析、ROI计算、决策支撑"},
        {"dim": "活动策划", "directions": "活动方案设计、资源协调、执行落地、效果复盘、预算管控"},
        {"dim": "社区运营", "directions": "社区氛围、KOL运营、用户互动、内容审核、社区增长"},
        {"dim": "渠道管理", "directions": "渠道选择、投放策略、效果监测、合作谈判、ROI优化"},
    ],
    "数据": [
        {"dim": "SQL与查询", "directions": "复杂SQL、窗口函数、性能优化、数据倾斜处理"},
        {"dim": "数据建模", "directions": "维度建模、事实表设计、星型/雪花模型、数据仓库分层"},
        {"dim": "ETL工程", "directions": "数据抽取、清洗转换、调度系统、增量同步、数据质量"},
        {"dim": "数据可视化", "directions": "BI工具、图表设计、Dashboard设计、数据故事化表达"},
        {"dim": "统计学基础", "directions": "假设检验、回归分析、概率分布、抽样方法、显著性"},
        {"dim": "大数据技术", "directions": "Hadoop/Spark、Flink流处理、数据湖、实时计算"},
    ],
    "测试": [
        {"dim": "自动化测试", "directions": "UI自动化、API自动化、框架设计、稳定性优化"},
        {"dim": "性能测试", "directions": "压力测试、负载测试、性能瓶颈分析、监控告警"},
        {"dim": "测试用例设计", "directions": "等价类划分、边界值、场景法、正交试验、缺陷管理"},
        {"dim": "CI/CD集成", "directions": "持续集成、自动化流水线、环境管理、版本控制"},
        {"dim": "质量保障", "directions": "测试策略、风险评估、质量度量、过程改进"},
        {"dim": "安全测试", "directions": "渗透测试、漏洞扫描、安全审计、合规检查"},
    ],
    "算法": [
        {"dim": "数据结构", "directions": "数组、链表、树、图、堆、哈希表的应用与实现"},
        {"dim": "算法设计", "directions": "动态规划、贪心、回溯、分治、图论算法"},
        {"dim": "机器学习", "directions": "监督学习、无监督学习、特征工程、模型评估"},
        {"dim": "深度学习", "directions": "CNN/RNN/Transformer、训练技巧、模型压缩"},
        {"dim": "模型优化", "directions": "超参调优、正则化、损失函数、加速推理"},
        {"dim": "工程落地", "directions": "模型部署、在线服务、A/B测试、特征平台"},
    ],
    "安全": [
        {"dim": "漏洞挖掘", "directions": "Web漏洞、二进制漏洞、逻辑漏洞、0day研究"},
        {"dim": "渗透测试", "directions": "渗透方法论、攻击链构建、权限提升、痕迹清理"},
        {"dim": "安全架构", "directions": "安全设计原则、零信任、防御纵深、加密体系"},
        {"dim": "密码学", "directions": "对称/非对称加密、哈希算法、数字签名、密钥管理"},
        {"dim": "应急响应", "directions": "入侵检测、日志分析、取证溯源、事件处置"},
        {"dim": "合规审计", "directions": "等级保护、GDPR、ISO27001、安全评估、合规建设"},
    ],
    "客户端": [
        {"dim": "iOS/Android开发", "directions": "原生开发、UI组件、生命周期、内存管理"},
        {"dim": "性能优化", "directions": "启动优化、卡顿治理、包体积、电量优化"},
        {"dim": "UI/UX", "directions": "界面设计、动画效果、适配方案、无障碍"},
        {"dim": "跨平台方案", "directions": "Flutter/React Native/小程序、混合开发、性能对比"},
        {"dim": "网络编程", "directions": "HTTP/HTTPS、WebSocket、长连接、网络优化"},
        {"dim": "架构设计", "directions": "组件化、模块化、状态管理、设计模式应用"},
    ],
    "全栈": [
        {"dim": "前端技术", "directions": "框架、性能、工程化、组件设计"},
        {"dim": "后端技术", "directions": "API设计、数据库、并发、服务架构"},
        {"dim": "DevOps", "directions": "容器化、CI/CD、监控、日志、自动化部署"},
        {"dim": "数据库", "directions": "SQL/NoSQL、索引优化、事务、分库分表"},
        {"dim": "云服务", "directions": "AWS/阿里云、服务架构、成本优化、容灾"},
        {"dim": "系统设计", "directions": "高可用、可扩展、微服务、消息队列"},
    ],
}

# 通用岗位能力维度（用于未匹配到大类的岗位）
DEFAULT_DIMENSIONS = [
    {"dim": "专业核心能力", "directions": "岗位核心技能、专业知识、技术应用"},
    {"dim": "项目实战经验", "directions": "项目规划、执行落地、成果产出"},
    {"dim": "问题解决能力", "directions": "问题分析、方案设计、风险应对"},
    {"dim": "沟通协作能力", "directions": "跨部门协作、需求对齐、冲突处理"},
    {"dim": "学习能力", "directions": "新技术学习、知识沉淀、持续改进"},
    {"dim": "业务理解能力", "directions": "业务场景、用户价值、商业逻辑"},
]

# 岗位关键词 → 大类映射
POSITION_KEYWORD_MAP = {
    "前端": "前端", "web": "前端", "react": "前端", "vue": "前端", "javascript": "前端",
    "后端": "后端", "java": "后端", "go": "后端", "python": "后端", "rust": "后端",
    "算法": "算法", "ai": "算法", "机器学习": "算法", "深度学习": "算法", "nlp": "算法",
    "产品": "产品", "pm": "产品", "产品经理": "产品",
    "运营": "运营", "数据分析": "数据", "数据": "数据",
    "测试": "测试", "qa": "测试",
    "安全": "安全",
    "ios": "客户端", "android": "客户端", "移动端": "客户端",
    "全栈": "全栈", "fullstack": "全栈",
    # 设计类岗位（UI/UX/视觉/交互/产品设计）
    "ui": "设计", "ux": "设计", "设计师": "设计", "视觉": "设计",
    "交互": "设计", "设计": "设计", "design": "设计",
    "美工": "设计", "体验设计": "设计",
}

# 语义相似度阈值：题目关键词重合度≥此值判定为重复题，需重新生成
# Phase 12：从 0.6 下调到 0.5，更严格拦截同语义题目
QUESTION_SIMILARITY_THRESHOLD = 0.5


# ============================================================
# 全局结束语语义识别（用于话术前置校验，拦截非法全局结束话术）
# ============================================================
# 触发"全局结束"语义的关键词：仅当系统判定满足三级结束条件时才允许出现
GLOBAL_END_PATTERNS = [
    "面试全部结束", "面试到此结束", "整场面试结束", "面试就到这里",
    "今天面试结束", "本场面试结束", "面试已经结束",
    "感谢你的时间", "感谢你的分享", "感谢你参加今天的面试",
    "后续结果", "结果我们会在", "HR会联系", "HR与你联系", "通知你结果",
    "面试官正在为你生成复盘", "前往面试复盘", "查看复盘报告",
    "一周内通知", "我们会在一周",
]

# 单阶段过渡语义关键词（合法的阶段切换话术，仅由状态机输出，大模型严禁生成）
STAGE_TRANSITION_PATTERNS = [
    "环节告一段落", "接下来进入", "接下来聊聊", "接下来我们",
    "环节到此结束", "进入下一环节", "下面进入",
    "聊下一部分", "我们进入下一", "下一部分", "下一环节",
    "环节结束", "阶段结束", "本环节", "本阶段",
    "进入行为面试", "进入案例分析", "进入技术问答", "进入反问",
    "进入项目案例", "进入自我介绍",
    # 衔接话术（场景1模板已硬编码"请结合你的实际经验回答以下问题"，LLM 不得重复生成）
    "接下来我们看下一题", "下面这道题", "下面我们看", "下面我们聊",
    "下一题是", "下一道题", "我们来看下一题", "我们看下一题",
    "以上就是", "以上就是本环节", "以上就是今天",
    "下面进入下一", "接下来我们进入下一",
]

# 点评内容关键词（题目生成时严禁出现，用于过滤 LLM 越权输出的点评）
# 用途：_push_next_question 输出过滤，确保题目只含题干，不混入点评模块
REVIEW_PATTERNS = [
    "【点评】", "【评价】", "【评估】", "【反馈】", "【回复点评】",
    "优点：", "不足：", "缺失：", "优化建议：", "改进建议：", "改进方向：",
    "亮点：", "可取之处：", "问题：",
    "评分：", "得分：", "总分：",
]

# 答题引导语模式（仅由后端场景1模板固定输出1次，LLM 题干中严禁出现）
# 用于过滤 LLM 在题干中越权生成的引导句，避免与后端模板叠加重复
# 注意：仅包含明确的引导语整句，避免短词误删题干（如"请说明Vue3原理？"是合法题干）
GUIDE_PHRASE_PATTERNS = [
    # 精确匹配句（整句引导语，不会出现在合法题干中）
    "请结合你的实际经验回答以下问题",
    "请结合实际项目作答",
    "请结合实际经验回答",
    "请回答以下问题",
    "请回答下面的问题",
    "请回答这道题",
    "请作答以下问题",
    "请简要回答以下问题",
    "请详细回答以下问题",
    "请针对题目给出你的解答方案",
    "请针对题目给出解答方案",
    "请针对上述场景给出你的解答方案",
    # 引导作答前缀（整句删除）
    "请结合",
    "请回答",
    "请作答",
    "请针对",
    "请你",
]


def _contains_global_end_phrase(text: str) -> Optional[str]:
    """检测文本是否包含全局结束语义。返回匹配到的关键词，无匹配返回 None。"""
    if not text:
        return None
    for pat in GLOBAL_END_PATTERNS:
        if pat in text:
            return pat
    return None


class InterviewAgent:
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
        try:
            self.vector_store = vector_store
            self.embedder = embedder
            self.redis = redis_client
            self.db_session_factory = db_session_factory
            self.api_key = api_key or os.getenv("LLM_API_KEY", "")
            self.base_url = base_url or os.getenv("LLM_BASE_URL", "")
            self.model = model
            self._client = None
            self._init_ok = True
        except Exception as e:
            logging.getLogger(__name__).error("InterviewAgent 初始化失败: %s", e, exc_info=True)
            self.vector_store = None
            self.embedder = None
            self.redis = None
            self.db_session_factory = None
            self.api_key = ""
            self.base_url = ""
            self.model = "gpt-4o"
            self._client = None
            self._init_ok = False

    async def _ensure_client(self):
        if self._client is None and self.api_key:
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(
                    api_key=self.api_key, base_url=self.base_url
                )
            except ImportError:
                pass

    # ============================================================
    # 三级状态机判定 + 话术过滤（核心边界管控）
    # ============================================================
    @staticmethod
    def _is_global_end_condition(session_ctx: dict) -> bool:
        """判定是否满足全局结束条件（三级状态）。
        必须同时满足：
        ① 当前处于最后一个阶段 reverse_qa
        ② reverse_qa 的最后1题已作答完成
        ③ 总答题数 >= 10
        """
        current_stage = session_ctx.get("current_stage", "init")
        question_records = session_ctx.get("question_records", [])
        # 统计已完成答题的题目数（answer 非空或 skipped 均算作答）
        answered = sum(
            1 for r in question_records
            if r.get("answer") or r.get("skipped")
        )
        # 必须当前阶段是 reverse_qa，且该阶段题目已答完
        if current_stage != "reverse_qa":
            return False
        reverse_q_count = QUESTION_BANK_CONFIG.get("reverse_qa", {}).get("count", 1)
        reverse_answered = sum(
            1 for r in question_records
            if r.get("stage") == "reverse_qa" and (r.get("answer") or r.get("skipped"))
        )
        return reverse_answered >= reverse_q_count and answered >= TOTAL_QUESTIONS

    @staticmethod
    def _sanitize_agent_text(text: str, session_ctx: dict) -> tuple:
        """话术前置校验：拦截非法全局结束话术。

        若 LLM 在非全局结束场景下输出了"面试全部结束"类话术，
        直接剔除该片段，返回清洗后的文本。

        :return: (cleaned_text, was_filtered)
        """
        if not text:
            return text, False
        # 满足全局结束条件 → 允许输出
        if InterviewAgent._is_global_end_condition(session_ctx):
            return text, False
        # 不满足全局结束条件 → 检测并剔除非法话术
        hit = _contains_global_end_phrase(text)
        if not hit:
            return text, False
        # 命中非法话术：移除包含结束语义的整段话
        # 策略：按行处理，删除包含 GLOBAL_END_PATTERNS 的行
        cleaned_lines = []
        for line in text.split("\n"):
            if _contains_global_end_phrase(line):
                continue
            cleaned_lines.append(line)
        cleaned = "\n".join(cleaned_lines).strip()
        # 如果清洗后为空，返回一个中性的阶段过渡占位（避免空 yield）
        if not cleaned:
            cleaned = "好的，我们继续下一题。"
        logging.getLogger(__name__).warning(
            "拦截非法全局结束话术：命中关键词「%s」，已剔除。原文本前80字：%s",
            hit, text[:80]
        )
        return cleaned, True

    @staticmethod
    def _sanitize_question_text(text: str) -> str:
        """过滤题目内容中的阶段过渡话术、点评内容、多题目、答题引导语。

        确保题目生成只输出单道题干，不越权输出：
        - 流程类话术（阶段过渡、环节结束等）→ 删除对应行
        - 点评模块（优点/不足/建议等）→ 删除对应行
        - 多道题目（一次出多题）→ 仅保留第一道
        - 答题引导语（"请结合..."等）→ 删除对应行（由后端模板统一输出1次）

        用于 _push_next_question 的输出过滤，彻底执行「状态机唯一管控流程，大模型仅生成内容」原则。

        :param text: LLM 生成的原始题目文本
        :return: 仅保留单道题干的清洗后文本
        """
        if not text:
            return text
        cleaned_lines = []
        for line in text.split("\n"):
            line_stripped = line.strip()
            # 跳过阶段过渡话术行（题目中不应出现阶段切换语）
            if any(pat in line_stripped for pat in STAGE_TRANSITION_PATTERNS):
                continue
            # 跳过点评内容行（题目中不应出现点评模块）
            if any(pat in line_stripped for pat in REVIEW_PATTERNS):
                continue
            # 跳过全局结束话术行
            if any(pat in line_stripped for pat in GLOBAL_END_PATTERNS):
                continue
            # 跳过答题引导语行（仅由后端模板输出1次，LLM 严禁生成）
            # 精确匹配整句引导语（避免误删包含"请说明"等短词的合法题干）
            if any(pat in line_stripped for pat in GUIDE_PHRASE_PATTERNS):
                continue
            cleaned_lines.append(line)
        cleaned = "\n".join(cleaned_lines).strip()

        # 多题目检测：如果文本中包含多个问号且以换行分隔，仅保留第一道题
        # 启发式：连续两个独立问句视为多题目，截断到第一个问号后
        import re as _re
        question_marks = _re.findall(r"[？?]", cleaned)
        if len(question_marks) > 1:
            # 找到第一个问号位置，保留到该问号 + 后续简短补充（不超过20字）
            first_q_idx = cleaned.find("？") if "？" in cleaned else cleaned.find("?")
            if first_q_idx >= 0:
                # 保留到第一个问号，再允许最多20字的补充说明
                end_idx = min(len(cleaned), first_q_idx + 21)
                # 不在句中切断（遇到换行则停止）
                next_newline = cleaned.find("\n", first_q_idx)
                if 0 < next_newline < end_idx:
                    end_idx = next_newline
                cleaned = cleaned[:end_idx].strip()

        # 如果清洗后为空，返回一个中性的提问占位（避免空 yield）
        # 注意：占位文本不得包含引导语，否则会与后端模板叠加重复
        if not cleaned:
            cleaned = "请针对上述场景给出你的解答方案。"
        return cleaned

    @staticmethod
    def _sanitize_review_text(text: str) -> str:
        """过滤点评内容中的流程类话术，并合并多条点评为单条。

        确保点评生成只输出点评内容，不越权输出流程话术。
        多条点评合并为1条，保留首个【点评】标识。

        :param text: LLM 生成的原始点评文本
        :return: 仅保留单条点评的清洗后文本
        """
        if not text:
            return text
        cleaned_lines = []
        review_count = 0
        for line in text.split("\n"):
            line_stripped = line.strip()
            # 跳过阶段过渡话术行（点评中不应出现阶段切换语）
            if any(pat in line_stripped for pat in STAGE_TRANSITION_PATTERNS):
                continue
            # 跳过全局结束话术行
            if any(pat in line_stripped for pat in GLOBAL_END_PATTERNS):
                continue
            # 多条点评检测：仅保留第一条点评
            if "【点评】" in line_stripped or "【评价】" in line_stripped:
                review_count += 1
                if review_count > 1:
                    continue  # 跳过后续重复的点评标识
            cleaned_lines.append(line)
        cleaned = "\n".join(cleaned_lines).strip()
        return cleaned

    @staticmethod
    def _dedupe_guide_phrases(text: str) -> str:
        """全局引导语去重：确保「请结合你的实际经验回答以下问题」仅出现1次。

        后端场景1模板固定输出1次引导语，LLM 题干若残留引导语会叠加重复。
        本方法扫描完整输出，仅保留第1次出现的引导语，其余全部删除。

        :param text: 拼接完成的完整输出文本
        :return: 引导语仅出现1次的文本
        """
        if not text:
            return text
        # 主引导语（后端模板固定输出）
        main_phrase = "请结合你的实际经验回答以下问题"
        # 场景2引导语
        alt_phrase = "请针对题目给出你的解答方案"
        # 所有引导语变体（含精确匹配句，排除主引导语自身）
        all_phrases = [p for p in GUIDE_PHRASE_PATTERNS if p != main_phrase]
        # 找到主引导语首次出现位置，保留该次，删除其余所有引导语
        main_first_idx = text.find(main_phrase)
        if main_first_idx < 0:
            # 主引导语未出现，检查是否是场景2的 alt_phrase
            alt_first_idx = text.find(alt_phrase)
            if alt_first_idx < 0:
                # 两个引导语都未出现（场景3），删除所有引导语变体
                cleaned = text
                for phrase in all_phrases:
                    cleaned = cleaned.replace(phrase, "")
                return cleaned.strip()
            # alt_phrase 出现：保留首次，删除其余
            prefix = text[:alt_first_idx + len(alt_phrase)]
            suffix = text[alt_first_idx + len(alt_phrase):]
            for phrase in all_phrases:
                suffix = suffix.replace(phrase, "")
            suffix = suffix.replace("\n\n\n", "\n\n").strip()
            return f"{prefix}{suffix}"

        # 主引导语出现：保留首次出现，删除其余所有引导语
        prefix = text[:main_first_idx + len(main_phrase)]
        suffix = text[main_first_idx + len(main_phrase):]
        for phrase in all_phrases:
            suffix = suffix.replace(phrase, "")
        suffix = suffix.replace("\n\n\n", "\n\n").strip()
        return f"{prefix}{suffix}"

    @staticmethod
    def _deep_clean_content(text: str) -> str:
        """深度清洗大模型输出内容，彻底过滤所有流程类、衔接类、引导类语句。

        执行四层清洗：
        1. 过渡类句子全删除（环节到此结束、接下来进入、下面进入、我们进入、接下来聊聊）
        2. 引导类句子全删除（请结合、请回答、请作答、请针对、请你 开头的引导作答句）
        3. 重复内容语句级去重（完全重复、高度相似的句子仅保留1句）
        4. 多题目检测：一次出多题 → 仅保留第一道

        用于场景1/场景2 题干清洗，确保 LLM 仅输出纯题干内容。

        :param text: LLM 生成的原始文本
        :return: 仅保留纯内容的清洗后文本
        """
        if not text:
            return text
        cleaned_lines = []
        for line in text.split("\n"):
            line_stripped = line.strip()
            if not line_stripped:
                cleaned_lines.append(line)
                continue
            # 1. 过渡类句子全删除
            if any(pat in line_stripped for pat in STAGE_TRANSITION_PATTERNS):
                continue
            # 2. 引导类句子全删除（整句删除）
            if any(line_stripped.startswith(pat) or pat in line_stripped for pat in GUIDE_PHRASE_PATTERNS):
                continue
            # 3. 点评内容全删除（题干中不应有点评）
            if any(pat in line_stripped for pat in REVIEW_PATTERNS):
                continue
            # 4. 全局结束话术删除
            if any(pat in line_stripped for pat in GLOBAL_END_PATTERNS):
                continue
            cleaned_lines.append(line)
        cleaned = "\n".join(cleaned_lines).strip()

        # 3. 语句级去重：完全重复的句子仅保留1句
        import re as _re
        sentences = _re.split(r'(?<=[。！？!?])', cleaned)
        seen = set()
        deduped = []
        for s in sentences:
            s_stripped = s.strip()
            if not s_stripped:
                continue
            if s_stripped not in seen:
                seen.add(s_stripped)
                deduped.append(s)
        cleaned = "".join(deduped).strip()

        # 4. 多题目检测：一次出多题 → 仅保留第一道
        question_marks = _re.findall(r"[？?]", cleaned)
        if len(question_marks) > 1:
            first_q_idx = cleaned.find("？") if "？" in cleaned else cleaned.find("?")
            if first_q_idx >= 0:
                end_idx = min(len(cleaned), first_q_idx + 21)
                next_newline = cleaned.find("\n", first_q_idx)
                if 0 < next_newline < end_idx:
                    end_idx = next_newline
                cleaned = cleaned[:end_idx].strip()

        # 清洗后为空则返回中性占位（非引导语，避免与后端模板叠加）
        if not cleaned:
            cleaned = "（请基于上述问题给出你的回答）"
        return cleaned

    @staticmethod
    def _dedupe_transition_phrases(text: str) -> str:
        """全局过渡语去重：确保「XX环节到此结束」类过渡语仅出现1次。

        后端场景2模板固定输出1次过渡语，LLM 题干若残留过渡语会叠加重复。
        本方法扫描完整输出，检测到多个过渡语时仅保留第1个，其余删除。

        :param text: 拼接完成的完整输出文本
        :return: 过渡语仅出现1次的文本
        """
        if not text:
            return text
        # 找到首个过渡语位置（通过 STAGE_TRANSITION_PATTERNS 检测）
        first_transition_idx = -1
        first_transition_pat = ""
        for pat in STAGE_TRANSITION_PATTERNS:
            idx = text.find(pat)
            if idx >= 0 and (first_transition_idx < 0 or idx < first_transition_idx):
                first_transition_idx = idx
                first_transition_pat = pat
        if first_transition_idx < 0:
            return text  # 无过渡语，无需去重

        # 保留首次出现的过渡语整句，删除其余所有过渡语句子
        # 定位首次过渡语所在行
        line_start = text.rfind("\n", 0, first_transition_idx) + 1
        line_end = text.find("\n", first_transition_idx)
        if line_end < 0:
            line_end = len(text)
        first_line = text[line_start:line_end]
        prefix = text[:line_end]
        suffix = text[line_end:]
        # 删除 suffix 中所有包含过渡语的行
        suffix_lines = suffix.split("\n")
        cleaned_suffix_lines = []
        for line in suffix_lines:
            line_stripped = line.strip()
            if line_stripped and any(pat in line_stripped for pat in STAGE_TRANSITION_PATTERNS):
                continue  # 删除后续重复的过渡语行
            cleaned_suffix_lines.append(line)
        cleaned_suffix = "\n".join(cleaned_suffix_lines)
        # 清理多余空行
        while "\n\n\n" in cleaned_suffix:
            cleaned_suffix = cleaned_suffix.replace("\n\n\n", "\n\n")
        return f"{prefix}{cleaned_suffix}"

    @staticmethod
    def _validate_review_relevance(review: str, user_answer: str) -> bool:
        """点评贴合度校验：检查点评是否充分引用用户回答原文。

        判定规则（双层强约束 - 符合用户规范"至少2处关键词/原文片段"）：
        - 从用户回答中提取关键词（长度≥2的中文词、数字、英文术语）
        - 若用户回答关键词≥3个：点评必须包含至少2个不同关键词
        - 若用户回答关键词1-2个：点评必须包含至少1个关键词（避免对短回答过度严格）
        - 若用户回答无有效关键词：跳过校验
        - 额外校验：优点/不足两部分均需至少1处原文引用（结构化引用约束）

        :param review: 点评文本
        :param user_answer: 用户回答原文
        :return: True=贴合，False=无效套话
        """
        if not review or not user_answer:
            return True  # 空回答不做贴合度校验
        # 提取用户回答中的关键词（长度≥2的中文词、数字、英文术语）
        import re as _re
        # 中文词（2-6字连续中文）
        cn_words = _re.findall(r"[\u4e00-\u9fa5]{2,6}", user_answer)
        # 数字（含百分比、小数）
        numbers = _re.findall(r"\d+\.?\d*%?", user_answer)
        # 英文术语（长度≥3的英文词）
        en_words = _re.findall(r"[A-Za-z]{3,}", user_answer)
        keywords = set(cn_words + numbers + en_words)
        # 过滤通用词（不参与贴合度判定）
        generic_words = {
            "回答", "问题", "这个", "一个", "我们", "你们", "他们",
            "可以", "可能", "应该", "需要", "进行", "通过", "这种",
            "方面", "情况", "内容", "方式", "方法", "过程",
        }
        keywords = {kw for kw in keywords if kw not in generic_words}
        if not keywords:
            return True  # 无有效关键词，不校验

        # 统计点评中命中的关键词数量
        review_lower = review.lower()
        matched_keywords = [kw for kw in keywords if kw.lower() in review_lower]
        match_count = len(matched_keywords)

        # 双层强约束：
        # - 关键词≥3个：要求至少2处命中
        # - 关键词1-2个：要求至少1处命中
        min_required = 2 if len(keywords) >= 3 else 1
        if match_count < min_required:
            return False

        # 结构化引用约束：优点和不足两部分均需至少1处原文引用
        # 切分优点/不足部分（按 "优点：" / "不足：" 标识）
        review_sections = {"优点": "", "不足": ""}
        if "优点" in review:
            # 提取优点部分（从"优点"到"不足"或"优化建议"之间）
            merit_match = _re.search(r"优点[：:](.*?)(?=不足[：:]|优化建议[：:]|改进建议[：:]|改进方向[：:]|$)",
                                     review, _re.DOTALL)
            if merit_match:
                review_sections["优点"] = merit_match.group(1)
        if "不足" in review:
            flaw_match = _re.search(r"不足[：:](.*?)(?=优化建议[：:]|改进建议[：:]|改进方向[：:]|$)",
                                    review, _re.DOTALL)
            if flaw_match:
                review_sections["不足"] = flaw_match.group(1)
        # 两部分都有内容时，校验每部分至少包含1个关键词
        if review_sections["优点"] and review_sections["不足"]:
            merit_has_kw = any(kw.lower() in review_sections["优点"].lower() for kw in keywords)
            flaw_has_kw = any(kw.lower() in review_sections["不足"].lower() for kw in keywords)
            if not (merit_has_kw and flaw_has_kw):
                return False

        return True

    @staticmethod
    def _validate_output_structure(
        output_text: str, scenario: str,
        current_stage: str, next_stage: str,
    ) -> tuple:
        """校验输出结构是否符合场景模板（返回 is_valid, error_msg）

        场景类型：
        - in_stage: 阶段内推进（点评1条 + 题目1道 + 引导语1条 + 过渡0 + 全局结束0）
        - stage_switch: 阶段切换（点评1条 + 过渡1条 + 题目1道 + 引导语1条 + 全局结束0）
        - global_end: 全局结束（点评1条 + 全局结束1条 + 题目0）
        - reverse_qa: 反问环节（特殊，由 _handle_reverse_qa 处理）
        - skip_in_stage: 跳过-阶段内推进（无点评 + 题目1道 + 引导语1条 + 过渡0 + 全局结束0）
        - skip_stage_switch: 跳过-阶段切换（无点评 + 过渡1条 + 题目1道 + 引导语1条 + 全局结束0）
        - skip_global_end: 跳过-全局结束（无点评 + 全局结束1条 + 题目0）
        - stage_start: 阶段启动（无点评 + 题目1道 + 引导语1条 + 过渡0 + 全局结束0）

        :param output_text: 本次完整输出文本（不含 META）
        :param scenario: 场景标识
        :param current_stage: 当前阶段
        :param next_stage: 下一阶段
        :return: (is_valid, error_msg)
        """
        if not output_text:
            return False, "输出为空"

        # 统计各类模块数量
        review_count = output_text.count("【点评】")
        # 统计题目数量（以问号结尾的独立句子）
        import re as _re
        question_count = len(_re.findall(r"[？?][\s\n]", output_text + "\n"))
        # 统计过渡话术数量（按行统计，包含任意过渡语关键词的行计为1条）
        transition_count = sum(
            1 for line in output_text.split("\n")
            if line.strip() and any(pat in line for pat in STAGE_TRANSITION_PATTERNS)
        )
        # 统计全局结束语数量（按行统计）
        global_end_count = sum(
            1 for line in output_text.split("\n")
            if line.strip() and any(pat in line for pat in GLOBAL_END_PATTERNS)
        )

        # 无点评场景统一处理（skip / stage_start）
        no_review_scenarios = {"skip_in_stage", "skip_stage_switch", "skip_global_end", "stage_start"}
        if scenario in no_review_scenarios:
            if review_count > 0:
                return False, f"场景{scenario}不应出现点评：{review_count}条"

        if scenario in ("in_stage", "skip_in_stage", "stage_start"):
            # 阶段内推进：题目1道 + 过渡话术0条 + 全局结束0条 + 引导语≤1条
            if question_count < 1:
                return False, f"场景{scenario}缺少题目"
            if transition_count > 0:
                return False, f"场景{scenario}出现过渡话术：{transition_count}条（应为0）"
            if global_end_count > 0:
                return False, f"场景{scenario}出现全局结束语：{global_end_count}条（应为0）"
            # 引导语校验：主引导语应≤1次
            guide_count = output_text.count("请结合你的实际经验回答以下问题")
            if guide_count > 1:
                return False, f"场景{scenario}引导语重复：{guide_count}次（应仅1次）"
            # in_stage 场景必须有点评
            if scenario == "in_stage" and review_count != 1:
                return False, f"场景in_stage点评数量异常：{review_count}（应为1）"
        elif scenario in ("stage_switch", "skip_stage_switch"):
            # 阶段切换：过渡话术1条 + 题目1道 + 全局结束0条
            # Phase 12：移除引导语硬约束（允许 guide_count=0，从根源避免引导语叠加重复）
            if transition_count < 1:
                return False, f"场景{scenario}缺少过渡话术"
            if question_count < 1:
                return False, f"场景{scenario}缺少新阶段首题"
            if global_end_count > 0:
                return False, f"场景{scenario}出现全局结束语：{global_end_count}条（应为0）"
            # 引导语校验：场景2引导语应≤1次（Phase 12 默认0次，但兼容历史调用≤1）
            guide_count = output_text.count("请针对题目给出你的解答方案")
            if guide_count > 1:
                return False, f"场景{scenario}引导语重复：{guide_count}次（应≤1次）"
            # 过渡话术校验：应仅1次
            if transition_count > 1:
                return False, f"场景{scenario}过渡话术重复：{transition_count}条（应仅1条）"
            # stage_switch 场景必须有点评
            if scenario == "stage_switch" and review_count != 1:
                return False, f"场景stage_switch点评数量异常：{review_count}（应为1）"
        elif scenario in ("global_end", "skip_global_end"):
            # 全局结束：全局结束1条 + 题目0道
            if global_end_count < 1:
                return False, f"场景{scenario}缺少全局结束语"
            if question_count > 0:
                return False, f"场景{scenario}不应输出题目：{question_count}道"
            # global_end 场景必须有点评
            if scenario == "global_end" and review_count != 1:
                return False, f"场景global_end点评数量异常：{review_count}（应为1）"
        elif scenario == "reverse_qa":
            # 反问环节引导：无点评 + 引导语1条
            pass  # 反问环节由 _handle_reverse_qa 单独处理

        return True, ""

    @staticmethod
    def _run_double_layer_validation(
        full_output: str, scenario: str,
        current_stage: str, next_stage: str,
        review: str = "", user_answer: str = "",
    ) -> tuple:
        """双层校验机制统一入口（不通过禁止返回）

        第一层：内容清洗校验
        - 点评内容：流程/引导类关键词检测；至少2处用户回答关键词/原文片段
        - 题干内容：引导/设问前缀检测；多题仅保留第一道

        第二层：结构校验
        - 引导语句数量 ≤ 1（阶段内/切换场景）
        - 过渡语句数量 = 0（阶段内）或 ≤ 1（切换场景）
        - 点评数量符合场景（in_stage/stage_switch/global_end=1；skip_*=0）
        - 全局结束语义仅在 global_end/skip_global_end 场景出现

        :param full_output: 拼接后的完整输出文本
        :param scenario: 场景标识
        :param current_stage: 当前阶段
        :param next_stage: 下一阶段
        :param review: 点评文本（用于第一层关键词校验）
        :param user_answer: 用户回答原文（用于第一层贴合度校验）
        :return: (is_valid, error_msg, warnings_list)
        """
        warnings_list = []
        if not full_output:
            return False, "完整输出为空", warnings_list

        # === 第一层：内容清洗校验 ===
        # 1a. 点评内容校验（仅当有点评时）
        if review and "【点评】" in full_output:
            # 流程/引导类关键词检测
            for pat in STAGE_TRANSITION_PATTERNS:
                if pat in review:
                    warnings_list.append(f"点评中出现过渡话术：{pat}")
                    break
            for pat in GUIDE_PHRASE_PATTERNS:
                if pat in review:
                    warnings_list.append(f"点评中出现引导语：{pat}")
                    break
            # 贴合度校验（仅在有用户回答时）
            if user_answer and not InterviewAgent._validate_review_relevance(review, user_answer):
                warnings_list.append("点评贴合度不足：未引用足够用户回答关键词/原文片段")

        # 1b. 题干内容校验
        # 引导/过渡话术在题干部分（剔除【点评】+ 后端硬编码引导语后的内容）应不存在
        # 多题检测：完整输出中问号数量（除场景3外应≤1）
        import re as _re
        question_marks = _re.findall(r"[？?]", full_output)
        if scenario in ("in_stage", "skip_in_stage", "stage_start", "stage_switch", "skip_stage_switch"):
            if len(question_marks) > 2:
                warnings_list.append(f"疑似多题目输出：{len(question_marks)}个问号")

        # === 第二层：结构校验 ===
        is_valid, err_msg = InterviewAgent._validate_output_structure(
            full_output, scenario, current_stage, next_stage
        )
        if not is_valid:
            return False, err_msg, warnings_list

        # 全局结束语义检测（仅 global_end/skip_global_end 场景允许）
        if scenario not in ("global_end", "skip_global_end"):
            for pat in GLOBAL_END_PATTERNS:
                if pat in full_output:
                    return False, f"场景{scenario}出现非法全局结束语义：{pat}", warnings_list

        # 引导语次数精确校验（场景1应仅1次；场景2 Phase 12 起允许0次，最多1次）
        if scenario in ("in_stage", "skip_in_stage", "stage_start"):
            guide_count = full_output.count("请结合你的实际经验回答以下问题")
            if guide_count > 1:
                return False, f"场景{scenario}引导语重复{guide_count}次（应仅1次）", warnings_list
        elif scenario in ("stage_switch", "skip_stage_switch"):
            guide_count = full_output.count("请针对题目给出你的解答方案")
            if guide_count > 1:
                return False, f"场景{scenario}引导语重复{guide_count}次（应≤1次）", warnings_list

        # 过渡语次数精确校验
        if scenario in ("in_stage", "skip_in_stage", "stage_start"):
            transition_count = sum(
                1 for line in full_output.split("\n")
                if line.strip() and any(pat in line for pat in STAGE_TRANSITION_PATTERNS)
            )
            if transition_count > 0:
                return False, f"场景{scenario}出现过渡话术{transition_count}条（应为0）", warnings_list
        elif scenario in ("stage_switch", "skip_stage_switch"):
            transition_count = sum(
                1 for line in full_output.split("\n")
                if line.strip() and any(pat in line for pat in STAGE_TRANSITION_PATTERNS)
            )
            if transition_count > 1:
                return False, f"场景{scenario}过渡话术重复{transition_count}条（应仅1条）", warnings_list

        return True, "", warnings_list

    # ============================================================
    # 主入口：根据 command 分发
    # ============================================================
    async def stream(self, payload: dict):
        """流式输出

        payload 额外字段：
          - command: start | chat | skip | end
          - company_name / company_id: 目标公司（定制化出题）
          - target_position: 目标岗位
          - session_ctx.current_stage
          - session_ctx.question_index
          - session_ctx.question_records
          - session_ctx.stage_scores
          - session_ctx.session_status: active | finished
          - session_ctx.ended: bool 结束状态锁
        """
        command = payload.get("command", "chat")
        session_stage = payload.get("session_stage", "init")
        session_ctx = payload.get("session_ctx") or {}

        await self._ensure_client()

        if not self._client:
            yield self._meta_json(session_stage, session_stage,
                                  "LLM 未配置，无法进行面试模拟。请在 .env 中配置 LLM_API_KEY。",
                                  session_finished=False, note="降级模式")
            yield "[DONE]"
            return

        if not getattr(self, "_init_ok", True):
            yield self._meta_json(session_stage, session_stage,
                                  "面试 Agent 初始化异常，请检查配置后重试。",
                                  session_finished=False, note="Agent初始化降级")
            yield "[DONE]"
            return

        # === 结束状态锁：一旦进入结束状态，禁止再出题、禁止重复结束语 ===
        is_ended = bool(session_ctx.get("ended")) or session_ctx.get("session_status") == "finished"
        if is_ended:
            yield "本场面试已结束，可前往面试复盘查看报告。"
            yield self._meta_json(
                "end", "end", "本场面试已结束，可前往面试复盘查看报告。",
                session_finished=True, note="结束锁保护",
                question_index=session_ctx.get("question_index", 0)
            )
            yield "[DONE]"
            return

        try:
            if command == "start":
                async for chunk in self._handle_start(payload):
                    yield chunk
            elif command == "skip":
                async for chunk in self._handle_skip(payload):
                    yield chunk
            elif command == "end":
                async for chunk in self._handle_end(payload):
                    yield chunk
            else:
                async for chunk in self._handle_chat(payload):
                    yield chunk
        except Exception as e:
            logging.getLogger(__name__).error(
                "面试官生成失败: %s", e, exc_info=True
            )
            # 输出友好提示，技术错误仅记录后端日志，禁止透传原始异常/堆栈/错误码
            yield "（面试官暂时不可用，请稍后重试）"
            yield self._meta_json(
                session_stage, session_stage,
                "面试官暂时不可用，请稍后重试",
                session_finished=False, note="错误"
            )

        yield "[DONE]"

    # ============================================================
    # 公司上下文获取
    # ============================================================
    async def _fetch_company_context(self, company_name: str, company_id: str) -> dict:
        """
        获取目标公司上下文信息，用于定制化出题

        优先从向量库语义检索，其次从结构化数据库查询
        :return: {
            "has_company": bool,
            "company_name": str,
            "industry": str,
            "business": str,
            "culture": str,
            "interview_style": str,
            "benefits": str,
            "interview_process": str,
            "avg_difficulty": str,
            "hiring_points": str,
        }
        """
        context = {
            "has_company": False,
            "company_name": company_name or "",
            "industry": "",
            "business": "",
            "culture": "",
            "interview_style": "",
            "benefits": "",
            "interview_process": "",
            "avg_difficulty": "",
            "hiring_points": "",
        }

        search_key = company_name or company_id
        if not search_key:
            return context

        # 1. 尝试从向量库召回
        # Phase 14 关键修复：向量库语义检索可能返回相似但不匹配的公司文档
        # （如查华为返回腾讯文档），导致 company_name 被错误覆盖
        # 修复：向量库返回的公司名必须与传入的 company_name 一致才使用，
        # 否则忽略向量库结果，保持传入公司名不变
        if self.vector_store and self.embedder:
            try:
                query_emb = await self.embedder.embed_query(f"{company_name} 面试 企业文化 业务")
                docs = await self.vector_store.search(query_emb, top_k=1,
                                                       filter_meta={"company_id": company_id} if company_id else None)
                if docs:
                    content = docs[0].get("content", "")
                    meta = docs[0].get("metadata", {})
                    vector_company_name = meta.get("company_name", "")
                    # Phase 14 关键校验：向量库返回的公司名必须与传入公司名匹配
                    # 避免"查华为返回腾讯"的跨公司串扰问题
                    if vector_company_name and company_name and vector_company_name != company_name:
                        # 公司名不匹配，不使用向量库结果，直接返回传入公司名的空 context
                        return context
                    context["has_company"] = True
                    # 保持传入的 company_name，不使用向量库可能错误的公司名覆盖
                    context["company_name"] = company_name
                    context["industry"] = meta.get("industry", "")
                    context["business"] = self._extract_field(content, "description")
                    context["culture"] = self._extract_field(content, "culture")
                    context["benefits"] = self._extract_field(content, "benefits")
                    context["interview_process"] = self._extract_field(content, "interview_process")
                    context["avg_difficulty"] = self._extract_field(content, "avg_difficulty")
                    context["interview_style"] = self._infer_interview_style(context["company_name"], content)
                    context["hiring_points"] = self._infer_hiring_points(context["company_name"], content)
                    return context
            except Exception:
                pass

        # 2. 尝试从结构化数据库查询
        if self.db_session_factory:
            try:
                async with self.db_session_factory() as db:
                    from sqlalchemy import select
                    from backend.app.models.company import Company
                    if company_id:
                        stmt = select(Company).where(Company.id == company_id)
                    else:
                        stmt = select(Company).where(Company.name.ilike(f"%{company_name}%")).limit(1)
                    result = await db.execute(stmt)
                    company = result.scalar_one_or_none()
                    if company:
                        # Phase 14 校验：数据库查询的公司名也必须与传入公司名匹配
                        db_company_name = company.name or ""
                        if db_company_name and company_name and db_company_name != company_name:
                            # 模糊匹配可能返回错误公司，保持传入公司名不变
                            pass
                        else:
                            context["has_company"] = True
                            # 保持传入的 company_name，不使用数据库公司名覆盖
                            context["company_name"] = company_name
                            context["industry"] = company.industry or ""
                            context["business"] = company.description or ""
                            context["culture"] = company.culture or ""
                            context["benefits"] = company.benefits or ""
                            context["interview_process"] = company.interview_process or ""
                            context["avg_difficulty"] = company.avg_difficulty or ""
                            context["interview_style"] = self._infer_interview_style(
                                context["company_name"], str(company.__dict__))
                            context["hiring_points"] = self._infer_hiring_points(
                                context["company_name"], str(company.__dict__))
                            return context
            except Exception:
                pass

        return context

    @staticmethod
    def _extract_field(content: str, field: str) -> str:
        """从向量库文本中提取指定字段值"""
        for line in content.split("\n"):
            if line.startswith(f"{field}:") or line.startswith(f"{field}："):
                return line.split(":", 1)[-1].split("：", 1)[-1].strip()
        return ""

    @staticmethod
    def _infer_interview_style(company_name: str, content: str) -> str:
        """根据公司名称和内容推断面试风格"""
        style_map = {
            "腾讯": "注重基础和项目经验，面试官风格温和但考察细致，算法题中等偏难",
            "字节跳动": "节奏快、题目量大，注重算法和系统设计，面试官风格直接高效",
            "阿里巴巴": "注重价值观和文化匹配，技术面深挖细节，面试官风格严谨",
            "百度": "注重技术深度和工程能力，面试官风格务实，考察综合能力",
            "美团": "注重实战能力和业务理解，面试官风格务实直接",
            "华为": "注重技术基础和综合素质，面试流程规范，考官风格严谨",
            "京东": "注重业务理解和技术落地能力，面试官风格务实",
            "拼多多": "注重技术能力和抗压能力，面试节奏快",
            "网易": "注重技术能力和产品思维，面试官风格温和",
            "小红书": "注重技术能力和业务sense，面试官风格年轻化",
            "快手": "注重算法和工程能力，面试官风格直接",
            "滴滴": "注重系统设计和实战经验，面试官风格务实",
        }
        for key, style in style_map.items():
            if key in (company_name or ""):
                return style
        if "算法" in content.lower() and "系统设计" in content.lower():
            return "注重算法和系统设计，面试风格严谨"
        if "价值观" in content or "文化" in content:
            return "注重文化匹配度，面试风格综合全面"
        return "面试风格专业规范"

    @staticmethod
    def _infer_hiring_points(company_name: str, content: str) -> str:
        """推断公司高频考点"""
        points_map = {
            "腾讯": "C++/Go、网络编程、操作系统、分布式系统、海量数据处理",
            "字节跳动": "算法与数据结构、系统设计、并发编程、高可用架构",
            "阿里巴巴": "Java技术栈、分布式中间件、数据库优化、领域驱动设计",
            "百度": "搜索引擎原理、NLP、机器学习、大规模数据处理",
            "美团": "Java技术栈、分布式系统、数据库、业务架构设计",
            "华为": "操作系统、网络协议、嵌入式、通信协议、系统架构",
        }
        for key, points in points_map.items():
            if key in (company_name or ""):
                return points
        return "核心技术栈、系统设计、项目经验"

    @staticmethod
    def _classify_position(target_position: str) -> dict:
        """
        识别岗位大类，返回核心考察点
        :return: {"category": "前端", "focus_points": "..."}
        """
        pos_lower = (target_position or "").lower()
        for keyword, category in POSITION_KEYWORD_MAP.items():
            if keyword in pos_lower:
                return {
                    "category": category,
                    "focus_points": POSITION_CATEGORIES.get(category, "综合能力"),
                    "dimensions": POSITION_DIMENSIONS.get(category, DEFAULT_DIMENSIONS),
                }
        return {
            "category": "通用",
            "focus_points": "综合能力、专业技能、项目经验",
            "dimensions": DEFAULT_DIMENSIONS,
        }

    # ============================================================
    # 会话级已出题语义缓存库（题目去重 + 维度多样性管控）
    # ============================================================
    @staticmethod
    def _init_question_cache(session_ctx: dict) -> None:
        """初始化会话级已出题缓存库（面试开始时调用）

        缓存库结构：
        {
            "asked_questions": [
                {"question": "题干文本", "keywords": ["关键词1","关键词2"], "dimension": "维度名", "stage": "tech_qa"}
            ],
            "asked_dimensions": ["已考察维度1", "已考察维度2"]
        }
        """
        if "question_cache" not in session_ctx:
            session_ctx["question_cache"] = {
                "asked_questions": [],
                "asked_dimensions": [],
            }

    @staticmethod
    def _extract_question_keywords(question: str) -> list:
        """提取题目的核心关键词（用于语义相似度比对）

        提取策略：
        1. 中文2-4字连续子串（滑动窗口）
        2. 英文术语（≥3字符）
        3. 数字
        4. 过滤通用词和标点符号

        :param question: 题干文本
        :return: 关键词列表
        """
        if not question:
            return []
        import re as _re
        # 提取所有中文字符（连续段）
        cn_segments = _re.findall(r"[\u4e00-\u9fa5]+", question)
        # 英文术语
        en_words = _re.findall(r"[A-Za-z]{3,}", question)
        # 数字
        numbers = _re.findall(r"\d+\.?\d*", question)
        # 使用滑动窗口提取 2-4 字中文子串
        cn_keywords = set()
        for seg in cn_segments:
            if len(seg) < 2:
                continue
            for size in (4, 3, 2):
                for i in range(len(seg) - size + 1):
                    cn_keywords.add(seg[i:i+size])
        # 通用词过滤
        generic_words = {
            "请说", "请描", "请结", "请阐", "请分", "请谈", "请设",
            "以下", "下面", "如何", "怎么", "什么", "为何", "为何",
            "一个", "这个", "那个", "你的", "我们", "你们", "他们",
            "可以", "可能", "应该", "需要", "进行", "通过", "这种",
            "方面", "情况", "内容", "方式", "方法", "过程", "问题",
            "结合", "实际", "经验", "项目", "回答", "说明", "描述",
            "阐述", "分析", "谈谈", "设计", "实现", "思考", "看法",
            "理解", "应用", "使用", "处理", "解决", "方案", "场景",
            "情况", "时候", "时候", "一些", "比如", "例如", "假设",
        }
        cn_keywords = {kw for kw in cn_keywords if kw not in generic_words}
        # 英文关键词转小写
        en_keywords = {w.lower() for w in en_words if len(w) >= 3}
        # 合并去重
        all_keywords = list(cn_keywords) + list(en_keywords) + numbers
        return all_keywords

    @staticmethod
    def _calculate_similarity(question1: str, question2: str) -> float:
        """计算两道题目的语义相似度（基于关键词Jaccard系数）

        :return: 相似度 0.0-1.0，≥0.6判定为重复
        """
        if not question1 or not question2:
            return 0.0
        kw1 = set(InterviewAgent._extract_question_keywords(question1))
        kw2 = set(InterviewAgent._extract_question_keywords(question2))
        if not kw1 or not kw2:
            return 0.0
        intersection = kw1 & kw2
        union = kw1 | kw2
        return len(intersection) / len(union) if union else 0.0

    @staticmethod
    def _check_question_duplicate(
        new_question: str, session_ctx: dict,
        threshold: float = QUESTION_SIMILARITY_THRESHOLD,
    ) -> tuple:
        """检查新题目是否与已出题重复

        :param new_question: 新题目题干
        :param session_ctx: 会话上下文（含 question_cache）
        :param threshold: 相似度阈值
        :return: (is_duplicate, duplicate_with) is_duplicate=True表示重复，duplicate_with为重复的题目
        """
        cache = session_ctx.get("question_cache") or {}
        asked_questions = cache.get("asked_questions", [])
        if not asked_questions or not new_question:
            return False, None
        for item in asked_questions:
            existing_q = item.get("question", "")
            if not existing_q:
                continue
            # 完全相同直接判定重复
            if new_question.strip() == existing_q.strip():
                return True, existing_q
            # 计算语义相似度
            similarity = InterviewAgent._calculate_similarity(new_question, existing_q)
            if similarity >= threshold:
                return True, existing_q
        return False, None

    @staticmethod
    def _detect_question_dimension(
        question: str, dimensions: list,
    ) -> Optional[str]:
        """检测题目所属的能力维度

        通过关键词匹配，将题目归入最接近的能力维度。

        :param question: 题干文本
        :param dimensions: 岗位能力维度列表 [{"dim":"...", "directions":"..."}]
        :return: 维度名，未匹配返回 None
        """
        if not question or not dimensions:
            return None
        # 构建维度→关键词集合 映射
        dim_keywords = {}
        for d in dimensions:
            dim_name = d.get("dim", "")
            directions = d.get("directions", "")
            # 将维度名和方向拆分为关键词
            kw_set = set()
            for seg in [dim_name, directions]:
                # 中文2-4字子串
                import re as _re
                cn_segs = _re.findall(r"[\u4e00-\u9fa5]+", seg)
                for cn in cn_segs:
                    if len(cn) < 2:
                        continue
                    for size in (4, 3, 2):
                        for i in range(len(cn) - size + 1):
                            kw_set.add(cn[i:i+size])
            dim_keywords[dim_name] = kw_set
        # 提取题目关键词
        q_keywords = set(InterviewAgent._extract_question_keywords(question))
        if not q_keywords:
            return None
        # 计算题目与各维度的匹配度
        best_dim = None
        best_score = 0
        for dim_name, kw_set in dim_keywords.items():
            if not kw_set:
                continue
            intersection = q_keywords & kw_set
            score = len(intersection)
            if score > best_score:
                best_score = score
                best_dim = dim_name
        return best_dim if best_score > 0 else None

    @staticmethod
    def _check_dimension_diversity(
        new_question: str, session_ctx: dict, dimensions: list,
    ) -> tuple:
        """检查题目维度多样性：同维度单会话最多1道

        :param new_question: 新题目题干
        :param session_ctx: 会话上下文
        :param dimensions: 岗位能力维度列表
        :return: (dimension, is_duplicate_dim) dimension为题目维度，is_duplicate_dim=True表示维度已存在
        """
        dimension = InterviewAgent._detect_question_dimension(new_question, dimensions)
        if not dimension:
            return None, False
        cache = session_ctx.get("question_cache") or {}
        asked_dimensions = cache.get("asked_dimensions", [])
        is_dup = dimension in asked_dimensions
        return dimension, is_dup

    @staticmethod
    def _check_position_relevance(
        question: str, target_position: str, position_ctx: Optional[dict],
    ) -> bool:
        """检查题目是否贴合目标岗位

        判定规则：
        1. 题目中至少包含1个岗位关键词或岗位类别相关词
        2. 未命中视为泛化题，需重新生成

        :param question: 题干文本
        :param target_position: 目标岗位名
        :param position_ctx: 岗位上下文（含category、focus_points）
        :return: True=贴合，False=泛化题
        """
        if not question:
            return False
        # 提取岗位关键词
        pos_lower = (target_position or "").lower()
        pos_keywords = set()
        # 岗位名本身的关键词
        import re as _re
        for cn_seg in _re.findall(r"[\u4e00-\u9fa5]+", target_position or ""):
            if len(cn_seg) >= 2:
                for size in (4, 3, 2):
                    for i in range(len(cn_seg) - size + 1):
                        pos_keywords.add(cn_seg[i:i+size])
        for en_seg in _re.findall(r"[A-Za-z]{3,}", target_position or ""):
            pos_keywords.add(en_seg.lower())
        # 岗位类别关键词
        if position_ctx:
            category = position_ctx.get("category", "")
            focus_points = position_ctx.get("focus_points", "")
            for seg in [category, focus_points]:
                for cn_seg in _re.findall(r"[\u4e00-\u9fa5]+", seg):
                    if len(cn_seg) >= 2:
                        for size in (4, 3, 2):
                            for i in range(len(cn_seg) - size + 1):
                                pos_keywords.add(cn_seg[i:i+size])
        # 过滤通用词
        generic_words = {
            "岗位", "能力", "技术", "工作", "经验", "专业", "综合",
        }
        pos_keywords = {kw for kw in pos_keywords if kw not in generic_words}
        if not pos_keywords:
            return True  # 无岗位关键词时不做校验
        # 题目关键词与岗位关键词的交集
        q_keywords = set(InterviewAgent._extract_question_keywords(question))
        intersection = q_keywords & pos_keywords
        return len(intersection) > 0

    @staticmethod
    def _record_asked_question(
        question: str, dimension: Optional[str], stage: str, session_ctx: dict,
    ) -> None:
        """记录已出题到会话级缓存库

        :param question: 题干文本
        :param dimension: 题目所属维度（None则尝试自动检测，仍None则不记录维度）
        :param stage: 当前阶段
        :param session_ctx: 会话上下文
        """
        if "question_cache" not in session_ctx:
            InterviewAgent._init_question_cache(session_ctx)
        cache = session_ctx["question_cache"]
        keywords = InterviewAgent._extract_question_keywords(question)
        cache["asked_questions"].append({
            "question": question.strip(),
            "keywords": keywords,
            "dimension": dimension,
            "stage": stage,
        })
        if dimension and dimension not in cache["asked_dimensions"]:
            cache["asked_dimensions"].append(dimension)

    def _run_question_triple_check(
        self, new_question: str, session_ctx: dict,
        target_position: str, position_ctx: Optional[dict],
        stage: str = "",
    ) -> tuple:
        """执行题目三重校验：语义去重 → 维度多样性 → 岗位贴合

        :param new_question: 新题目题干
        :param session_ctx: 会话上下文
        :param target_position: 目标岗位
        :param position_ctx: 岗位上下文
        :param stage: 当前面试阶段（project_qa/star_qa 等抽象阶段放宽岗位贴合校验）
        :return: (is_valid, fail_reason, detected_dimension)
                 is_valid=True 表示通过三重校验
                 fail_reason 为失败原因（None表示通过）
                 detected_dimension 为检测到的题目维度（None表示未匹配到维度）
        """
        # 第一重：语义去重校验
        is_dup, dup_with = self._check_question_duplicate(new_question, session_ctx)
        if is_dup:
            return False, f"语义重复（与已出题相似度≥{QUESTION_SIMILARITY_THRESHOLD}）：{dup_with[:50]}", None

        # 第二重：维度多样性校验
        dimensions = (position_ctx or {}).get("dimensions") or DEFAULT_DIMENSIONS
        dimension, is_dim_dup = self._check_dimension_diversity(new_question, session_ctx, dimensions)
        if is_dim_dup and dimension:
            return False, f"维度重复（{dimension} 维度已出过题）", dimension

        # 第三重：岗位贴合校验
        # Phase 12 修复：project_qa/star_qa 阶段题目天然抽象（项目案例、行为面试），
        # 往往不含具体岗位关键词（如"前端"/"Vue3"），放宽校验避免题干生成全部失败
        # 导致只有话术没有题干的问题
        if stage in ("project_qa", "star_qa", "reverse_qa"):
            # 抽象阶段：仅校验题目非空且非纯引导语，不强制要求岗位关键词
            if not new_question or len(new_question.strip()) < 5:
                return False, "题目为空或过短", dimension
            return True, None, dimension

        if not self._check_position_relevance(new_question, target_position, position_ctx):
            return False, "岗位贴合度不足：题目未包含岗位关键词", dimension

        return True, None, dimension

    # ============================================================
    # 命令处理：start
    # ============================================================
    async def _handle_start(self, payload: dict):
        """开始面试：生成开场白 + self_intro 第一题（定制化）"""
        session_ctx = payload.get("session_ctx") or {}
        # 从 session_ctx 或 payload 读取岗位，禁用硬编码默认值
        target_position = (
            session_ctx.get("target_position")
            or payload.get("target_position")
            or ""
        )
        difficulty = payload.get("difficulty", "middle")
        # Phase 14 修复：target_company 优先从 session_ctx.user_assets 读取（全链路一致）
        # 避免依赖 payload 中的 company_name（可能因 planner 未透传而丢失）
        user_assets = session_ctx.get("user_assets", {}) or {}
        company_name = (
            user_assets.get("target_company")
            or session_ctx.get("target_company")  # 兜底：session_ctx 顶层
            or payload.get("company_name", "")
            or ""
        )
        company_id = (
            user_assets.get("target_company_id")
            or session_ctx.get("target_company_id")  # 兜底：session_ctx 顶层
            or payload.get("company_id", "")
            or ""
        )

        # Phase 14 调试日志：追踪公司信息传递链路
        import logging
        _logger = logging.getLogger(__name__)
        _logger.info(
            "[ Phase14 调试 _handle_start ] "
            "session_id=%s | target_position=%s | company_name=%s | company_id=%s | "
            "user_assets=%s | payload.company_name=%s | payload.company_id=%s | "
            "session_ctx.target_company=%s | session_ctx keys=%s",
            payload.get("session_id", ""),
            target_position,
            company_name,
            company_id,
            json.dumps(user_assets, ensure_ascii=False),
            payload.get("company_name", ""),
            payload.get("company_id", ""),
            session_ctx.get("target_company", ""),
            list(session_ctx.keys()),
        )

        # 持久化到 session_ctx 顶层，确保后续阶段可直接读取
        session_ctx["target_company"] = company_name
        session_ctx["target_company_id"] = company_id

        # 防御：如果会话已处于活跃状态，跳过重复初始化（防止重复出题）
        current_stage = session_ctx.get("current_stage", "init")
        if session_ctx.get("session_status") == "active" and current_stage not in ("init", "end"):
            yield self._meta_json(
                current_stage,
                current_stage,
                "面试已在进行中，请继续作答。",
                session_finished=False, note="已在面试中，跳过重复初始化",
                question_index=session_ctx.get("question_index", 0)
            )
            return

        # 初始化会话状态（清除上一场面试的全部状态，包括结束锁、待启动阶段标记）
        session_ctx["current_stage"] = "self_intro"
        session_ctx["question_index"] = 0
        session_ctx["question_records"] = []
        session_ctx["stage_scores"] = {}
        session_ctx["session_status"] = "active"
        session_ctx["completed_stages"] = []  # 追踪已完成的阶段，防止回归
        session_ctx["ended"] = False  # 清除结束锁，允许新面试正常推进
        session_ctx.pop("pending_stage_start", None)  # 清除待启动阶段标记
        session_ctx.pop("total_score", None)
        session_ctx.pop("section_scores", None)
        # Phase 13：清除追问状态（新一场面试开始时清空）
        session_ctx.pop("follow_up_state", None)
        # Phase 14 关键修复：清除上一场面试的对话历史
        # 根因：复用同一 session_id（基于 interview_id）重新开始面试时，history 中残留旧面试对话
        # （可能包含其他公司内容），这些旧对话通过 _llm_stream 的 history 参数传入 LLM，
        # 导致 LLM 被旧公司上下文污染，开场白出现非选定公司信息
        # 注意：handle_message 已在调用 agent 前 append 了 "开始面试" 的 user 消息，
        # 此处清空后需重新 append 当前用户输入，保持对话语义完整
        current_user_input = None
        if session_ctx.get("history"):
            # 保留最后一条用户消息（即本次"开始面试"指令）
            current_user_input = session_ctx["history"][-1]
        session_ctx["history"] = []
        if current_user_input:
            session_ctx["history"].append(current_user_input)
        # 初始化会话级已出题缓存库（新一场面试开始时清空缓存）
        self._init_question_cache(session_ctx)
        # 持久化岗位信息到 session_ctx，后续 _handle_chat 等从 session_ctx 读取
        session_ctx["target_position"] = target_position

        # 获取公司上下文（定制化出题）
        company_ctx = await self._fetch_company_context(company_name, company_id)
        position_ctx = self._classify_position(target_position)

        # Phase 14 调试日志：记录 company_ctx 实际值
        _logger.info(
            "[ Phase14 调试 _handle_start company_ctx ] "
            "company_name(传入)=%s | company_ctx.company_name=%s | company_ctx.has_company=%s | "
            "company_ctx keys=%s",
            company_name,
            (company_ctx or {}).get("company_name", ""),
            (company_ctx or {}).get("has_company", False),
            list((company_ctx or {}).keys()),
        )

        # 缓存公司上下文到 session_ctx，后续阶段复用
        session_ctx["company_ctx"] = company_ctx
        session_ctx["position_ctx"] = position_ctx
        # 确保岗位信息也直接存储在 session_ctx 顶层（_handle_chat 等从顶层读取）
        session_ctx["target_position"] = target_position

        # 生成开场白 + 自我介绍要求
        prompt = self._build_question_prompt(
            target_position, difficulty, "self_intro", 0, 1,
            is_first=True, company_ctx=company_ctx, position_ctx=position_ctx
        )
        # Phase 14 调试日志：记录 prompt 中是否包含公司名
        _logger.info(
            "[ Phase14 调试 _build_question_prompt ] "
            "prompt 包含公司名「%s」: %s | prompt 前200字符: %s",
            company_name,
            company_name in prompt if company_name else False,
            prompt[:200],
        )
        full_text = ""
        async for chunk in self._llm_stream(prompt, payload.get("dialogue_history", [])):
            full_text += chunk
            yield chunk

        # 记录开场题目到 question_records（answer 待用户回答后填入）
        question_records = session_ctx.get("question_records", [])
        question_records.append({
            "stage": "self_intro",
            "question": full_text.strip(),
            "answer": "",
            "review": "",
            "score": 0,
            "skipped": False,
        })
        session_ctx["question_records"] = question_records
        session_ctx["current_stage"] = "self_intro"
        session_ctx["question_index"] = 0
        # 将开场题目记录到会话级已出题缓存库（自我介绍题目维度为 None，不参与维度多样性校验）
        self._record_asked_question(full_text.strip(), None, "self_intro", session_ctx)

        # 推进到 self_intro 阶段
        yield self._meta_json(
            "self_intro", "self_intro", full_text,
            session_finished=False, note="开场 → 自我介绍",
            question_index=0
        )

    # ============================================================
    # 命令处理：chat（用户回答 → 评估 → 下一题）
    # ============================================================
    async def _handle_chat(self, payload: dict):
        """用户回答处理：评估 → 点评 → 推进下一题/阶段（自动流转）

        单轮单题原则：每次用户操作仅输出1条有效内容
        - 待启动阶段：输出新阶段第一题（reverse_qa 则处理用户提问）
        - 正常答题：点评 + 下一题（合并为一条消息）
        - 阶段末题：点评 + 阶段过渡语（不输出新题，下一轮再出题）
        - 反问环节：面试官回答 + 全局结束语
        """
        user_input = payload.get("user_input", "")
        session_ctx = payload.get("session_ctx") or {}
        target_position = (
            session_ctx.get("target_position")
            or payload.get("target_position")
            or ""
        )
        difficulty = payload.get("difficulty", "middle")

        current_stage = session_ctx.get("current_stage", "self_intro")
        question_index = session_ctx.get("question_index", 0)
        question_records = session_ctx.get("question_records", [])
        stage_scores = session_ctx.get("stage_scores", {})
        history = session_ctx.get("history", [])
        completed_stages = session_ctx.get("completed_stages", [])

        # === 硬上限校验：总答题数已达10题，禁止再出题 ===
        total_answered = sum(
            1 for r in question_records
            if r.get("answer") or r.get("skipped")
        )
        if total_answered >= TOTAL_QUESTIONS:
            if not session_ctx.get("ended"):
                session_ctx["ended"] = True
                session_ctx["session_status"] = "finished"
                session_ctx["current_stage"] = "end"
                yield "全部题目已完成，面试到这里就全部结束了，感谢你的分享，后续结果我们会在一周内通知你，祝你顺利。"
                yield self._meta_json(
                    current_stage, "end", "全部题目已完成",
                    session_finished=True, note="硬上限校验：10题已答完 → 强制结束",
                    question_index=0
                )
            return

        # === 待启动阶段检查：上一轮刚切换阶段，本轮输出新阶段第一题 ===
        pending_stage = session_ctx.get("pending_stage_start")
        if pending_stage:
            session_ctx.pop("pending_stage_start", None)
            session_ctx["current_stage"] = pending_stage
            session_ctx["question_index"] = 0
            current_stage = pending_stage
            question_index = 0

            if pending_stage == "reverse_qa":
                # 反问环节：用户的输入就是反向提问，直接处理
                async for chunk in self._handle_reverse_qa(
                    user_input, target_position, session_ctx, question_records,
                    stage_scores, completed_stages, history
                ):
                    yield chunk
                return
            else:
                # 其他阶段：输出第一题（双独立调用架构，用户输入仅作为触发，不记录为答题）
                config = QUESTION_BANK_CONFIG.get(pending_stage, {"count": 1})
                company_ctx = session_ctx.get("company_ctx")
                position_ctx = session_ctx.get("position_ctx")
                new_q_text = await self._generate_question_only(
                    target_position, difficulty, pending_stage, 0, config["count"],
                    history, company_ctx=company_ctx, position_ctx=position_ctx,
                    session_ctx=session_ctx
                )
                GUIDE_TEXT = "请结合你的实际经验回答以下问题。"
                full_output = f"{GUIDE_TEXT}\n\n{new_q_text}"
                full_output = self._dedupe_guide_phrases(full_output)
                full_output = self._dedupe_transition_phrases(full_output)
                yield full_output
                question_records.append({
                    "stage": pending_stage,
                    "question": new_q_text.strip(),
                    "answer": "",
                    "review": "",
                    "score": 0,
                    "skipped": False,
                })
                yield self._meta_json(
                    pending_stage, pending_stage, new_q_text,
                    session_finished=False,
                    note=f"新阶段启动 → {pending_stage} 第1/{config['count']}题",
                    question_index=0
                )
                return

        # === 阶段回归保护 ===
        if current_stage in completed_stages and question_index > 0:
            next_stage = self._get_next_stage(current_stage)
            logging.getLogger(__name__).warning(
                "阶段回归检测: %s 已完成且 question_index=%d，强制推进到 %s",
                current_stage, question_index, next_stage
            )
            if next_stage == "end":
                yield self._meta_json(
                    current_stage, "end", "面试已结束。",
                    session_finished=True, note="阶段回归保护 → 强制结束",
                    question_index=0
                )
                return
            current_stage = next_stage
            session_ctx["current_stage"] = current_stage
            session_ctx["question_index"] = 0
            question_index = 0

        # === 阶段第1题缺失防御（n-1 偏差根因修复）===
        # 场景：pending_stage_start 丢失（Redis 故障或文件恢复字段缺失）时，
        # 当前阶段没有第1题但 question_index=0，用户输入会被误当作"回答空题目"，
        # 导致该阶段少出1题。此处检测并补出第1题，用户输入仅作为触发。
        if (
            current_stage not in ("init", "end", "reverse_qa")
            and question_index == 0
            and not session_ctx.get("pending_stage_start")
        ):
            stage_has_question = any(
                r.get("stage") == current_stage and r.get("question")
                for r in question_records
            )
            if not stage_has_question:
                logging.getLogger(__name__).warning(
                    "阶段第1题缺失防御: %s 阶段无题目记录，补出第1题（用户输入仅作触发）",
                    current_stage
                )
                config = QUESTION_BANK_CONFIG.get(current_stage, {"count": 1})
                company_ctx = session_ctx.get("company_ctx")
                position_ctx = session_ctx.get("position_ctx")
                new_q_text = await self._generate_question_only(
                    target_position, difficulty, current_stage, 0, config["count"],
                    history, company_ctx=company_ctx, position_ctx=position_ctx,
                    session_ctx=session_ctx
                )
                GUIDE_TEXT = "请结合你的实际经验回答以下问题。"
                full_output = f"{GUIDE_TEXT}\n\n{new_q_text}"
                full_output = self._dedupe_guide_phrases(full_output)
                full_output = self._dedupe_transition_phrases(full_output)
                yield full_output
                question_records.append({
                    "stage": current_stage,
                    "question": new_q_text.strip(),
                    "answer": "",
                    "review": "",
                    "score": 0,
                    "skipped": False,
                })
                yield self._meta_json(
                    current_stage, current_stage, new_q_text,
                    session_finished=False,
                    note=f"缺失补出 → {current_stage} 第1/{config['count']}题",
                    question_index=0
                )
                return

        # === reverse_qa 特殊处理：用户提问，面试官回答 + 全局结束 ===
        if current_stage == "reverse_qa":
            async for chunk in self._handle_reverse_qa(
                user_input, target_position, session_ctx, question_records,
                stage_scores, completed_stages, history
            ):
                yield chunk
            return

        # === 正常答题流程 ===
        current_question = self._find_current_question(question_records, current_stage, question_index)

        # 检查是否处于追问模式（上一轮已点评+追问，本轮应推进到下一题）
        follow_up_state = session_ctx.get("follow_up_state") or {}
        pending_advance = follow_up_state.get("pending_advance_after_follow_up") is True

        # ① 调用1：纯点评生成（结构化JSON输出，强制字段拼接）
        # _generate_review_only 返回 (字段字典, 分数)，字段字典含 advantage/disadvantage/suggestion
        position_ctx = session_ctx.get("position_ctx")
        review_fields, score = await self._generate_review_only(
            target_position, difficulty, current_stage,
            current_question, user_input,
            position_ctx=position_ctx
        )
        # 拼接点评文本（后端固定模板，无任何AI生成话术）
        review = self._assemble_review_text(review_fields)

        # Phase 13 修复：追问回答合并到原题记录，不新增记录、不重复计入 stage_scores
        # 否则 _find_current_question 会因 stage_questions 列表多出一条相同题目而返回重复题
        if pending_advance:
            # 本轮是回答追问 → 合并到原题记录（追加 answer + 更新 review/score 取较高值）
            self._merge_follow_up_answer(
                question_records, current_stage, current_question,
                user_input, review, score
            )
            # 追问评分不单独计入 stage_scores（避免单题多次评分拉偏均分）
            # 仅在日志中记录，便于排查
            logging.getLogger(__name__).info(
                "追问回答已合并到原题记录 | stage=%s score=%d（不重复计入stage_scores）",
                current_stage, score
            )
        else:
            # 正常答题 → 新增/更新记录 + 计入 stage_scores
            self._record_answer(
                question_records, current_question, user_input, review, score, skipped=False,
                stage=current_stage
            )
            stage_scores.setdefault(current_stage, []).append(score)

        # ② 判断状态 → 输出单条内容
        config = QUESTION_BANK_CONFIG.get(current_stage)
        if not config:
            yield self._meta_json(current_stage, current_stage, "",
                                  session_finished=False, note="未知阶段")
            return

        # === Phase 13：追问机制 ===
        # 若当前阶段允许追问，且未追问过该题，则生成追问（不推进 question_index）
        # 下一轮用户回答追问后，pending_advance=True，直接推进到下一题
        follow_up_count_in_stage = follow_up_state.get(current_stage, {}).get("count", 0)
        if (
            not pending_advance
            and self._should_ask_follow_up(current_stage, question_index, follow_up_count_in_stage)
            and user_input.strip() != "跳过"
        ):
            follow_up_round = follow_up_count_in_stage + 1
            follow_up_q = await self._generate_follow_up_only(
                target_position, current_stage,
                current_question, user_input,
                follow_up_round
            )
            if follow_up_q:
                # 记录追问状态
                follow_up_state[current_stage] = {
                    "count": follow_up_round,
                    "last_question_index": question_index,
                }
                follow_up_state["pending_advance_after_follow_up"] = True
                follow_up_state["last_follow_up_question"] = follow_up_q
                session_ctx["follow_up_state"] = follow_up_state

                # 输出：点评 + 承接语 + 追问问题
                TRANSITION = "嗯，我们来深入一下这个点。"
                full_output = f"【点评】\n{review}\n\n{TRANSITION}\n\n{follow_up_q}"
                full_output = self._dedupe_guide_phrases(full_output)
                full_output = self._dedupe_transition_phrases(full_output)
                yield full_output
                # 追问不推进 question_index，META 仍保持当前题号
                yield self._meta_json(
                    current_stage, current_stage, follow_up_q,
                    session_finished=False,
                    note=f"追问第{follow_up_round}轮 → {current_stage} 第{question_index+1}/{config['count']}题（追问不推进题号）",
                    question_index=question_index,
                    is_follow_up=True,
                    follow_up_round=follow_up_round,
                )
                return
            else:
                # 追问生成失败，清空追问状态，正常推进
                logging.getLogger(__name__).info(
                    "追问生成失败，正常推进到下一题 | stage=%s q_index=%d",
                    current_stage, question_index
                )
                follow_up_state.pop("pending_advance_after_follow_up", None)
                session_ctx["follow_up_state"] = follow_up_state
        else:
            # 不需要追问，或追问已完成 → 清空追问状态
            if pending_advance:
                follow_up_state.pop("pending_advance_after_follow_up", None)
                session_ctx["follow_up_state"] = follow_up_state

        next_q_index = question_index + 1
        if next_q_index < config["count"]:
            # 场景1：阶段内推进 - 双独立调用 + 后端固定拼接
            # 调用1：生成纯点评（强制引用用户回答原文）
            # 调用2：生成纯题干（零引导零话术）
            # 后端硬编码拼接：【点评】+ 纯点评 + 承接语 + 引导语 + 纯题干
            company_ctx = session_ctx.get("company_ctx")
            position_ctx = session_ctx.get("position_ctx")

            # 调用2：生成纯题干（与调用1独立，互不感知上下文结构）
            new_q_text = await self._generate_question_only(
                target_position, difficulty, current_stage, next_q_index, config["count"],
                history, company_ctx=company_ctx, position_ctx=position_ctx,
                session_ctx=session_ctx
            )
            # Phase 13：自然承接语 - 根据是否追问过选择不同衔接
            if pending_advance:
                TRANSITION_TEXT = "好的，了解了。那我们再看下一个方向。"
            else:
                TRANSITION_TEXT = "嗯，我们继续。"
            # 后端硬编码引导语（仅1次）
            GUIDE_TEXT = "请结合你的实际经验回答以下问题。"
            # 后端固定拼接（场景1模板：点评+承接语+引导语+题干）
            full_output = f"【点评】\n{review}\n\n{TRANSITION_TEXT}\n\n{GUIDE_TEXT}\n\n{new_q_text}"
            # 全局去重：确保引导语、过渡语在完整输出中仅出现1次
            full_output = self._dedupe_guide_phrases(full_output)
            full_output = self._dedupe_transition_phrases(full_output)
            # 双层校验：内容清洗 + 结构校验
            is_valid, err_msg, warnings = self._run_double_layer_validation(
                full_output, "in_stage", current_stage, current_stage,
                review=review, user_answer=user_input
            )
            if not is_valid:
                logging.getLogger(__name__).warning(
                    "双层校验失败(场景1): %s | 输出: %s",
                    err_msg, full_output[:200]
                )
            elif warnings:
                logging.getLogger(__name__).info(
                    "双层校验告警(场景1): %s | 输出: %s",
                    "; ".join(warnings), full_output[:200]
                )
            # 一次性输出完整场景1内容
            yield full_output
            question_records.append({
                "stage": current_stage,
                "question": new_q_text.strip(),
                "answer": "",
                "review": "",
                "score": 0,
                "skipped": False,
            })
            session_ctx["question_index"] = next_q_index
            yield self._meta_json(
                current_stage, current_stage, new_q_text,
                session_finished=False, note=f"{current_stage} 第{next_q_index+1}/{config['count']}题",
                question_index=next_q_index
            )
        else:
            # 阶段结束（二级）：单轮完整输出
            # 固定结构：点评 + 过渡语 + 新阶段首题（或全局结束语）
            # 彻底消除「只有话术没有题目」的空转情况
            # question_index 是阶段内题号（0-based），+1 得到已输出题数
            questions_output = question_index + 1
            if questions_output < config["count"]:
                # 题量不足，补充生成当前阶段缺失题目（双独立调用架构）
                logging.getLogger(__name__).warning(
                    "题量校验: %s 阶段已出题 %d/%d，补充生成第 %d 题",
                    current_stage, questions_output, config["count"], questions_output + 1
                )
                # 场景1：题量补充 → 双独立调用 + 后端固定拼接
                company_ctx = session_ctx.get("company_ctx")
                position_ctx = session_ctx.get("position_ctx")
                new_q_text = await self._generate_question_only(
                    target_position, difficulty, current_stage, next_q_index, config["count"],
                    history, company_ctx=company_ctx, position_ctx=position_ctx,
                    session_ctx=session_ctx
                )
                TRANSITION_TEXT = "好的，了解了。那我们再看下一个方向。"
                GUIDE_TEXT = "请结合你的实际经验回答以下问题。"
                full_output = f"【点评】\n{review}\n\n{TRANSITION_TEXT}\n\n{GUIDE_TEXT}\n\n{new_q_text}"
                full_output = self._dedupe_guide_phrases(full_output)
                full_output = self._dedupe_transition_phrases(full_output)
                yield full_output
                question_records.append({
                    "stage": current_stage,
                    "question": new_q_text.strip(),
                    "answer": "",
                    "review": "",
                    "score": 0,
                    "skipped": False,
                })
                # 只有实际输出题目，才允许计数器+1
                session_ctx["question_index"] = next_q_index
                yield self._meta_json(
                    current_stage, current_stage, new_q_text,
                    session_finished=False,
                    note=f"题量补充 → {current_stage} 第{next_q_index+1}/{config['count']}题",
                    question_index=next_q_index
                )
                return

            # 题量已满，进入阶段切换（场景2/场景3）
            if current_stage not in completed_stages:
                completed_stages.append(current_stage)
            session_ctx["completed_stages"] = completed_stages

            next_stage = self._get_next_stage(current_stage)
            next_config = QUESTION_BANK_CONFIG.get(next_stage, {"count": 0})

            if next_stage == "end":
                # 场景3：全局面试结束 → 点评 + 全局结束语（无新题）
                # 全局结束语由后端硬编码，禁止 LLM 生成
                GLOBAL_END_TEXT = "面试到这里就全部结束了，感谢你的分享，后续结果我们会在一周内通知你，祝你顺利。"
                full_output = f"【点评】\n{review}\n\n{GLOBAL_END_TEXT}"
                # 双层校验：内容清洗 + 结构校验
                is_valid, err_msg, warnings = self._run_double_layer_validation(
                    full_output, "global_end", current_stage, "end",
                    review=review, user_answer=user_input
                )
                if not is_valid:
                    logging.getLogger(__name__).warning(
                        "双层校验失败(场景3): %s | 输出: %s",
                        err_msg, full_output[:200]
                    )
                elif warnings:
                    logging.getLogger(__name__).info(
                        "双层校验告警(场景3): %s | 输出: %s",
                        "; ".join(warnings), full_output[:200]
                    )
                yield full_output
                session_ctx["current_stage"] = "end"
                session_ctx["question_index"] = 0
                session_ctx["ended"] = True
                session_ctx["session_status"] = "finished"
                yield self._meta_json(
                    current_stage, "end", "",
                    session_finished=True,
                    note=f"全局结束 → {current_stage} 完成，面试结束",
                    question_index=0
                )
                return

            if next_stage == "reverse_qa":
                # 场景2特殊：反问环节 → 点评 + 过渡引导语（反问环节首题由用户提问触发）
                yield f"【点评】\n{review}\n\n"
                yield "我的问题问完了，现在你可以向我提问，你有什么想了解的吗？"
                session_ctx["current_stage"] = "reverse_qa"
                session_ctx["question_index"] = 0
                # 反问环节不计入出题计数，等待用户提问
                yield self._meta_json(
                    current_stage, "reverse_qa", "",
                    session_finished=False,
                    note=f"阶段完成 → {current_stage} → reverse_qa（等待用户提问）",
                    question_index=0
                )
                return

            # 场景2：阶段切换 → 双独立调用 + 后端固定拼接
            # 调用1：生成纯点评（已在上方 _evaluate_answer 完成）
            # 调用2：生成新阶段纯题干（零引导零话术）
            # Phase 12：后端硬编码拼接仅含 过渡语 + 纯题干，移除引导语（避免叠加重复）
            transition_text = self._build_stage_transition_text(next_stage, session_ctx)
            company_ctx = session_ctx.get("company_ctx")
            position_ctx = session_ctx.get("position_ctx")

            # 调用2：生成新阶段纯题干（与调用1独立，互不感知上下文结构）
            new_q_text = await self._generate_question_only(
                target_position, difficulty, next_stage, 0, next_config["count"],
                history, company_ctx=company_ctx, position_ctx=position_ctx,
                session_ctx=session_ctx
            )
            # Phase 12：场景B固定拼接（点评+过渡语+纯题干，无引导语）
            full_output = f"【点评】\n{review}\n\n{transition_text}\n\n{new_q_text}"
            # 全局去重：确保引导语、过渡语在完整输出中仅出现1次
            full_output = self._dedupe_guide_phrases(full_output)
            full_output = self._dedupe_transition_phrases(full_output)
            # 双层校验：内容清洗 + 结构校验
            is_valid, err_msg, warnings = self._run_double_layer_validation(
                full_output, "stage_switch", current_stage, next_stage,
                review=review, user_answer=user_input
            )
            if not is_valid:
                logging.getLogger(__name__).warning(
                    "双层校验失败(场景2): %s | 输出: %s",
                    err_msg, full_output[:200]
                )
            elif warnings:
                logging.getLogger(__name__).info(
                    "双层校验告警(场景2): %s | 输出: %s",
                    "; ".join(warnings), full_output[:200]
                )
            # 一次性输出完整场景2内容
            yield full_output

            # 记录新阶段首题（已出题计数=1，question_index=0 表示当前正在回答第1题）
            question_records.append({
                "stage": next_stage,
                "question": new_q_text.strip(),
                "answer": "",
                "review": "",
                "score": 0,
                "skipped": False,
            })
            session_ctx["current_stage"] = next_stage
            session_ctx["question_index"] = 0
            # 双层校验：内容清洗 + 结构校验（场景2阶段切换）
            is_valid, err_msg, warnings = self._run_double_layer_validation(
                full_output, "stage_switch", current_stage, next_stage
            )
            if not is_valid:
                logging.getLogger(__name__).warning(
                    "双层校验失败(场景2): %s | 输出: %s",
                    err_msg, full_output[:200]
                )
            elif warnings:
                logging.getLogger(__name__).info(
                    "双层校验告警(场景2): %s | 输出: %s",
                    "; ".join(warnings), full_output[:200]
                )
            yield self._meta_json(
                current_stage, next_stage, new_q_text,
                session_finished=False,
                note=f"阶段切换 → {current_stage} → {next_stage} 第1/{next_config['count']}题",
                question_index=0
            )

    # ============================================================
    # 命令处理：skip（跳过 → 无点评 → 下一题）
    # ============================================================
    async def _handle_skip(self, payload: dict):
        """跳过：不生成点评，直接下一题；阶段题目跳完则自动流转

        单轮单题原则与 _handle_chat 一致：
        - 待启动阶段：输出新阶段第一题
        - 正常跳过：直接下一题
        - 阶段末题：仅输出过渡语（不输出新题）
        """
        session_ctx = payload.get("session_ctx") or {}
        target_position = (
            session_ctx.get("target_position")
            or payload.get("target_position")
            or ""
        )
        difficulty = payload.get("difficulty", "middle")

        current_stage = session_ctx.get("current_stage", "self_intro")
        question_index = session_ctx.get("question_index", 0)
        question_records = session_ctx.get("question_records", [])
        stage_scores = session_ctx.get("stage_scores", {})
        history = session_ctx.get("history", [])
        completed_stages = session_ctx.get("completed_stages", [])

        # Phase 13：跳过时清理追问状态（避免跳过追问后状态错乱）
        follow_up_state = session_ctx.get("follow_up_state") or {}
        if follow_up_state.get("pending_advance_after_follow_up"):
            follow_up_state.pop("pending_advance_after_follow_up", None)
            session_ctx["follow_up_state"] = follow_up_state
            logging.getLogger(__name__).info(
                "跳过追问，清理 pending_advance_after_follow_up | stage=%s q_index=%d",
                current_stage, question_index
            )

        # === 硬上限校验 ===
        total_answered = sum(
            1 for r in question_records
            if r.get("answer") or r.get("skipped")
        )
        if total_answered >= TOTAL_QUESTIONS:
            if not session_ctx.get("ended"):
                session_ctx["ended"] = True
                session_ctx["session_status"] = "finished"
                session_ctx["current_stage"] = "end"
                yield "全部题目已完成，面试到这里就全部结束了，感谢你的分享，后续结果我们会在一周内通知你，祝你顺利。"
                yield self._meta_json(
                    current_stage, "end", "全部题目已完成",
                    session_finished=True, note="硬上限校验：10题已答完 → 强制结束",
                    question_index=0
                )
            return

        # === 待启动阶段检查 ===
        pending_stage = session_ctx.get("pending_stage_start")
        if pending_stage:
            session_ctx.pop("pending_stage_start", None)
            session_ctx["current_stage"] = pending_stage
            session_ctx["question_index"] = 0
            current_stage = pending_stage
            question_index = 0

            if pending_stage == "reverse_qa":
                # 反问环节跳过：直接结束面试
                async for chunk in self._handle_reverse_qa(
                    "", target_position, session_ctx, question_records,
                    stage_scores, completed_stages, history, skipped=True
                ):
                    yield chunk
                return
            else:
                # 输出第一题（双独立调用架构）
                config = QUESTION_BANK_CONFIG.get(pending_stage, {"count": 1})
                company_ctx = session_ctx.get("company_ctx")
                position_ctx = session_ctx.get("position_ctx")
                new_q_text = await self._generate_question_only(
                    target_position, difficulty, pending_stage, 0, config["count"],
                    history, company_ctx=company_ctx, position_ctx=position_ctx,
                    session_ctx=session_ctx
                )
                GUIDE_TEXT = "请结合你的实际经验回答以下问题。"
                full_output = f"{GUIDE_TEXT}\n\n{new_q_text}"
                full_output = self._dedupe_guide_phrases(full_output)
                full_output = self._dedupe_transition_phrases(full_output)
                yield full_output
                question_records.append({
                    "stage": pending_stage,
                    "question": new_q_text.strip(),
                    "answer": "",
                    "review": "",
                    "score": 0,
                    "skipped": False,
                })
                yield self._meta_json(
                    pending_stage, pending_stage, new_q_text,
                    session_finished=False,
                    note=f"跳过 → 新阶段启动 {pending_stage} 第1/{config['count']}题",
                    question_index=0
                )
                return

        # === 阶段回归保护 ===
        if current_stage in completed_stages and question_index > 0:
            next_stage = self._get_next_stage(current_stage)
            if next_stage == "end":
                yield self._meta_json(
                    current_stage, "end", "面试已结束。",
                    session_finished=True, note="阶段回归保护 → 强制结束",
                    question_index=0
                )
                return
            current_stage = next_stage
            session_ctx["current_stage"] = current_stage
            session_ctx["question_index"] = 0
            question_index = 0

        # === 阶段第1题缺失防御（n-1 偏差根因修复，与 _handle_chat 一致）===
        if (
            current_stage not in ("init", "end", "reverse_qa")
            and question_index == 0
            and not session_ctx.get("pending_stage_start")
        ):
            stage_has_question = any(
                r.get("stage") == current_stage and r.get("question")
                for r in question_records
            )
            if not stage_has_question:
                logging.getLogger(__name__).warning(
                    "阶段第1题缺失防御(skip): %s 阶段无题目记录，补出第1题",
                    current_stage
                )
                config = QUESTION_BANK_CONFIG.get(current_stage, {"count": 1})
                company_ctx = session_ctx.get("company_ctx")
                position_ctx = session_ctx.get("position_ctx")
                new_q_text = await self._generate_question_only(
                    target_position, difficulty, current_stage, 0, config["count"],
                    history, company_ctx=company_ctx, position_ctx=position_ctx,
                    session_ctx=session_ctx
                )
                GUIDE_TEXT = "请结合你的实际经验回答以下问题。"
                full_output = f"{GUIDE_TEXT}\n\n{new_q_text}"
                full_output = self._dedupe_guide_phrases(full_output)
                full_output = self._dedupe_transition_phrases(full_output)
                yield full_output
                question_records.append({
                    "stage": current_stage,
                    "question": new_q_text.strip(),
                    "answer": "",
                    "review": "",
                    "score": 0,
                    "skipped": False,
                })
                yield self._meta_json(
                    current_stage, current_stage, new_q_text,
                    session_finished=False,
                    note=f"跳过 → 缺失补出 {current_stage} 第1/{config['count']}题",
                    question_index=0
                )
                return

        # === reverse_qa 跳过：直接结束 ===
        if current_stage == "reverse_qa":
            async for chunk in self._handle_reverse_qa(
                "", target_position, session_ctx, question_records,
                stage_scores, completed_stages, history, skipped=True
            ):
                yield chunk
            return

        # === 正常跳过流程 ===
        current_question = self._find_current_question(question_records, current_stage, question_index)
        self._record_answer(
            question_records, current_question, "", "已跳过", 0, skipped=True,
            stage=current_stage
        )
        stage_scores.setdefault(current_stage, []).append(0)

        config = QUESTION_BANK_CONFIG.get(current_stage, {"count": 1})
        next_q_index = question_index + 1

        if next_q_index < config["count"]:
            # 场景1：单题跳过 → 双独立调用 + 后端固定拼接（无点评，因为跳过）
            # 调用2：生成纯题干（零引导零话术）
            company_ctx = session_ctx.get("company_ctx")
            position_ctx = session_ctx.get("position_ctx")
            new_q_text = await self._generate_question_only(
                target_position, difficulty, current_stage, next_q_index, config["count"],
                history, company_ctx=company_ctx, position_ctx=position_ctx,
                session_ctx=session_ctx
            )
            # 后端硬编码引导语（仅1次）
            GUIDE_TEXT = "请结合你的实际经验回答以下问题。"
            full_output = f"{GUIDE_TEXT}\n\n{new_q_text}"
            # 全局去重：确保引导语、过渡语在完整输出中仅出现1次
            full_output = self._dedupe_guide_phrases(full_output)
            full_output = self._dedupe_transition_phrases(full_output)
            # 一次性输出完整场景1内容
            yield full_output
            question_records.append({
                "stage": current_stage,
                "question": new_q_text.strip(),
                "answer": "",
                "review": "",
                "score": 0,
                "skipped": False,
            })
            session_ctx["question_index"] = next_q_index
            # 双层校验：内容清洗 + 结构校验（skip场景1阶段内推进，无点评）
            is_valid, err_msg, warnings = self._run_double_layer_validation(
                full_output, "skip_in_stage", current_stage, current_stage
            )
            if not is_valid:
                logging.getLogger(__name__).warning(
                    "双层校验失败(skip-场景1): %s | 输出: %s",
                    err_msg, full_output[:200]
                )
            elif warnings:
                logging.getLogger(__name__).info(
                    "双层校验告警(skip-场景1): %s | 输出: %s",
                    "; ".join(warnings), full_output[:200]
                )
            yield self._meta_json(
                current_stage, current_stage, new_q_text,
                session_finished=False, note=f"跳过 → {current_stage} 第{next_q_index+1}/{config['count']}题",
                question_index=next_q_index
            )
        else:
            # 阶段末题跳过：单轮完整输出（与 _handle_chat 一致的结构）
            # 固定结构：过渡语 + 新阶段首题（或全局结束语），无点评（跳过不点评）
            questions_output = question_index + 1
            if questions_output < config["count"]:
                # 题量不足，补充生成当前阶段缺失题目（双独立调用架构）
                logging.getLogger(__name__).warning(
                    "题量校验(skip): %s 阶段已出题 %d/%d，补充生成第 %d 题",
                    current_stage, questions_output, config["count"], questions_output + 1
                )
                company_ctx = session_ctx.get("company_ctx")
                position_ctx = session_ctx.get("position_ctx")
                new_q_text = await self._generate_question_only(
                    target_position, difficulty, current_stage, next_q_index, config["count"],
                    history, company_ctx=company_ctx, position_ctx=position_ctx,
                    session_ctx=session_ctx
                )
                # 后端硬编码引导语（仅1次）
                GUIDE_TEXT = "请结合你的实际经验回答以下问题。"
                full_output = f"{GUIDE_TEXT}\n\n{new_q_text}"
                full_output = self._dedupe_guide_phrases(full_output)
                full_output = self._dedupe_transition_phrases(full_output)
                yield full_output
                question_records.append({
                    "stage": current_stage,
                    "question": new_q_text.strip(),
                    "answer": "",
                    "review": "",
                    "score": 0,
                    "skipped": False,
                })
                session_ctx["question_index"] = next_q_index
                yield self._meta_json(
                    current_stage, current_stage, new_q_text,
                    session_finished=False,
                    note=f"跳过 → 题量补充 {current_stage} 第{next_q_index+1}/{config['count']}题",
                    question_index=next_q_index
                )
                return

            # 题量已满，进入阶段切换
            if current_stage not in completed_stages:
                completed_stages.append(current_stage)
            session_ctx["completed_stages"] = completed_stages

            next_stage = self._get_next_stage(current_stage)
            next_config = QUESTION_BANK_CONFIG.get(next_stage, {"count": 0})

            if next_stage == "end":
                # 场景3：全局结束（跳过版）→ 全局结束语（后端硬编码）
                GLOBAL_END_TEXT = "面试到这里就全部结束了，感谢你的分享，后续结果我们会在一周内通知你，祝你顺利。"
                yield GLOBAL_END_TEXT
                session_ctx["current_stage"] = "end"
                session_ctx["question_index"] = 0
                session_ctx["ended"] = True
                session_ctx["session_status"] = "finished"
                yield self._meta_json(
                    current_stage, "end", "",
                    session_finished=True,
                    note=f"跳过 → 全局结束 → {current_stage} 完成",
                    question_index=0
                )
                return

            if next_stage == "reverse_qa":
                # 场景2特殊：反问环节 → 过渡引导语
                yield "我的问题问完了，现在你可以向我提问，你有什么想了解的吗？"
                session_ctx["current_stage"] = "reverse_qa"
                session_ctx["question_index"] = 0
                yield self._meta_json(
                    current_stage, "reverse_qa", "",
                    session_finished=False,
                    note=f"跳过 → {current_stage} → reverse_qa（等待用户提问）",
                    question_index=0
                )
                return

            # 场景2：阶段切换 → 双独立调用 + 后端固定拼接（无点评，因为跳过不点评）
            # 调用2：生成新阶段纯题干（零引导零话术）
            # Phase 12：移除引导语，仅保留过渡文案 + 纯题干
            transition_text = self._build_stage_transition_text(next_stage, session_ctx)
            company_ctx = session_ctx.get("company_ctx")
            position_ctx = session_ctx.get("position_ctx")
            new_q_text = await self._generate_question_only(
                target_position, difficulty, next_stage, 0, next_config["count"],
                history, company_ctx=company_ctx, position_ctx=position_ctx,
                session_ctx=session_ctx
            )
            # Phase 12：场景B固定拼接（无引导语）
            if transition_text:
                full_output = f"{transition_text}\n\n{new_q_text}"
            else:
                full_output = f"{new_q_text}"
            # 全局去重
            full_output = self._dedupe_guide_phrases(full_output)
            full_output = self._dedupe_transition_phrases(full_output)
            yield full_output

            question_records.append({
                "stage": next_stage,
                "question": new_q_text.strip(),
                "answer": "",
                "review": "",
                "score": 0,
                "skipped": False,
            })
            session_ctx["current_stage"] = next_stage
            session_ctx["question_index"] = 0
            # 双层校验：内容清洗 + 结构校验（skip场景2阶段切换，无点评）
            is_valid, err_msg, warnings = self._run_double_layer_validation(
                full_output, "skip_stage_switch", current_stage, next_stage
            )
            if not is_valid:
                logging.getLogger(__name__).warning(
                    "双层校验失败(skip-场景2): %s | 输出: %s",
                    err_msg, full_output[:200]
                )
            elif warnings:
                logging.getLogger(__name__).info(
                    "双层校验告警(skip-场景2): %s | 输出: %s",
                    "; ".join(warnings), full_output[:200]
                )
            yield self._meta_json(
                current_stage, next_stage, new_q_text,
                session_finished=False,
                note=f"跳过 → 阶段切换 {current_stage} → {next_stage} 第1/{next_config['count']}题",
                question_index=0
            )

    # ============================================================
    # 反问环节处理：用户提问 → 面试官回答 → 全局结束
    # ============================================================
    async def _handle_reverse_qa(
        self, user_input: str, target_position: str,
        session_ctx: dict, question_records: list,
        stage_scores: dict, completed_stages: list,
        history: list, skipped: bool = False,
    ):
        """反问环节统一处理：面试官回答用户提问 + 触发全局结束

        触发条件（三重校验）：
        - 当前处于 reverse_qa 阶段
        - 用户已提交反向提问（或主动跳过）
        - 总答题数 >= 10
        """
        # 记录用户的反向提问（或跳过）
        current_question = self._find_current_question(question_records, "reverse_qa", 0)
        if current_question:
            self._record_answer(
                question_records, current_question, user_input,
                "用户反向提问" if not skipped else "已跳过",
                0, skipped=skipped, stage="reverse_qa"
            )
        stage_scores.setdefault("reverse_qa", []).append(0)

        # 面试官回答用户的问题（跳过时不回答）
        answer_text = ""
        if not skipped and user_input:
            yield "好的，非常感谢你的提问。\n\n"
            async for chunk in self._llm_stream(
                self._build_reverse_answer_prompt(target_position, user_input), history
            ):
                answer_text += chunk
                yield chunk
        else:
            answer_text = "（用户跳过反问环节）"

        # 记录面试官的回答
        question_records.append({
            "stage": "reverse_qa",
            "question": f"面试官回答：{answer_text.strip()[:100]}",
            "answer": user_input,
            "review": "反向提问已完成",
            "score": 0,
            "skipped": skipped,
        })

        # 标记 reverse_qa 完成
        if "reverse_qa" not in completed_stages:
            completed_stages.append("reverse_qa")
        session_ctx["completed_stages"] = completed_stages

        # === 计算最终评分（与 _handle_end 逻辑一致） ===
        # Phase 13 修复：基于 question_records 实际作答情况计算
        section_scores, total_score = self._calc_final_scores(
            question_records, stage_scores
        )
        session_ctx["total_score"] = total_score
        session_ctx["section_scores"] = section_scores

        # === 触发全局结束（设置结束锁，杜绝重复结束） ===
        session_ctx["ended"] = True
        session_ctx["current_stage"] = "end"
        session_ctx["question_index"] = 0
        session_ctx["session_status"] = "finished"
        session_ctx.pop("pending_stage_start", None)

        yield "\n\n"
        yield "面试到这里就全部结束了，感谢你的分享，后续结果我们会在一周内通知你，祝你顺利。"

        yield self._meta_json(
            "reverse_qa", "end", answer_text,
            session_finished=True,
            note="反向提问完成 → 面试结束（全部10题完成）",
            question_index=0,
            total_score=total_score,
            section_scores=section_scores
        )

    # ============================================================
    # 命令处理：end（结束汇总）
    # ============================================================
    async def _handle_end(self, payload: dict):
        """结束面试：计算5环节加权评分，保存到 session_ctx，由 ReviewAgent 统一生成复盘报告"""
        session_ctx = payload.get("session_ctx") or {}
        # 从 session_ctx 读取岗位，禁用硬编码默认值
        target_position = (
            session_ctx.get("target_position")
            or payload.get("target_position")
            or ""
        )

        # 结束状态锁：如果已经结束过，直接返回提示，不重复输出结束语
        if session_ctx.get("ended") or session_ctx.get("session_status") == "finished":
            yield "本场面试已结束，可前往面试复盘查看报告。"
            yield self._meta_json(
                "end", "end", "本场面试已结束，可前往面试复盘查看报告。",
                session_finished=True, note="结束锁保护，拒绝重复结束",
                question_index=0
            )
            return

        stage_scores = session_ctx.get("stage_scores", {})
        question_records = session_ctx.get("question_records", [])

        # Phase 13 修复：综合评分基于 question_records 实际作答情况计算
        # 避免追问重复评分、跳过题默认70分等导致的评分失真
        section_scores, total_score = self._calc_final_scores(
            question_records, stage_scores
        )

        # 将评分数据写入 session_ctx，供 ReviewAgent 使用
        session_ctx["total_score"] = total_score
        session_ctx["section_scores"] = section_scores
        session_ctx["session_status"] = "finished"
        # 设置结束锁，杜绝重复结束语
        session_ctx["ended"] = True
        session_ctx["current_stage"] = "end"

        # 输出结束语，不生成完整报告（由 ReviewAgent 统一负责）
        yield "面试到这里就全部结束了，感谢你的分享，后续结果我们会在一周内通知你，祝你顺利。"

        yield self._meta_json(
            session_ctx.get("current_stage", "reverse_qa"), "end",
            "面试到这里就全部结束了，感谢你的分享，后续结果我们会在一周内通知你，祝你顺利。",
            session_finished=True, note="面试结束，触发复盘",
            total_score=total_score,
            section_scores=section_scores
        )

    # ============================================================
    # LLM 调用封装
    # ============================================================
    async def _llm_stream(self, system_prompt: str, history: list):
        """流式调用 LLM

        保留完整对话历史，确保面试官的提问在结束面试前始终维持在上下文中。
        10题面试共20条消息（10条user + 10条interviewer），DeepSeek 32K 上下文足够容纳。

        异常处理：捕获 LLM 调用异常并记录后端日志，向上抛出标准化异常，
        由调用方（_handle_chat 等）的外层 try/except 统一兜底为友好提示，
        杜绝原始错误码/堆栈透传到前端对话区。
        """
        messages = [{"role": "system", "content": system_prompt}]
        # 移除 history[-10:] 限制，保留完整对话历史
        # 面试官需要看到之前所有问题才能避免重复出题、保持上下文连贯
        for h in history:
            role = "assistant" if h.get("role") == "interviewer" else "user"
            messages.append({"role": role, "content": h.get("content", "")})

        # 确保至少有一条 user 消息（部分 LLM API 拒绝纯 system 消息）
        if not any(m["role"] == "user" for m in messages):
            messages.append({"role": "user", "content": "请开始"})

        try:
            stream = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
                temperature=0.7,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta
                content = delta.content if delta and delta.content else None
                if content:
                    yield content
        except Exception as e:
            logging.getLogger(__name__).error(
                "LLM 流式调用失败 model=%s: %s", self.model, e, exc_info=True
            )
            raise RuntimeError("LLM 调用失败") from e

    async def _llm_complete(self, system_prompt: str, user_content: str) -> str:
        """非流式调用 LLM，返回完整文本

        异常处理：捕获 LLM 调用异常并记录后端日志，向上抛出标准化异常，
        由调用方的外层 try/except 统一兜底为友好提示。
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        try:
            resp = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            logging.getLogger(__name__).error(
                "LLM 非流式调用失败 model=%s: %s", self.model, e, exc_info=True
            )
            raise RuntimeError("LLM 调用失败") from e

    # ============================================================
    # Prompt 构造
    # ============================================================
    def _build_question_prompt(
        self, target_position: str, difficulty: str,
        stage: str, q_index: int, q_total: int,
        is_first: bool = False,
        company_ctx: Optional[dict] = None,
        position_ctx: Optional[dict] = None,
    ) -> str:
        """构造出题 prompt（支持公司+岗位定制化 + 多形式题库引导 + 自然话术）"""
        config = QUESTION_BANK_CONFIG.get(stage, {})
        q_type = config.get("type", "")
        diff_map = {
            "junior": "初级（1-3年经验）",
            "middle": "中级（3-5年经验）",
            "senior": "资深（5年以上经验）",
        }

        # 根据岗位类别动态生成 stage_hints，避免硬编码技术岗话术
        pos_category = (position_ctx or {}).get("category", "通用")
        if pos_category in ("产品", "运营"):
            stage_hints = {
                "self_intro": "请候选人做自我介绍，重点了解产品/运营经历和项目背景",
                "tech_qa": f"出第{q_index+1}/{q_total}道产品专业题，围绕「{target_position}」岗位核心能力（需求分析、产品设计、数据分析、用户研究等）",
                "star_qa": f"出第{q_index+1}/{q_total}道行为面试题，用STAR法则考察产品/运营情景应对",
                "project_qa": f"出第{q_index+1}/{q_total}道项目案例题，考察产品规划、项目推进和跨部门协作能力",
                "reverse_qa": "询问候选人是否有问题想了解公司或岗位",
            }
        elif pos_category in ("数据", "测试"):
            stage_hints = {
                "self_intro": "请候选人做自我介绍，重点了解数据/测试相关经历和技术背景",
                "tech_qa": f"出第{q_index+1}/{q_total}道专业题，围绕「{target_position}」岗位核心技能",
                "star_qa": f"出第{q_index+1}/{q_total}道行为面试题，用STAR法则考察情景应对",
                "project_qa": f"出第{q_index+1}/{q_total}道项目案例题，考察实战分析能力",
                "reverse_qa": "询问候选人是否有问题想了解公司或岗位",
            }
        else:
            # 技术类岗位（前端/后端/算法/客户端/全栈/安全等）
            stage_hints = {
                "self_intro": "请候选人做自我介绍，重点了解技术栈和项目经历",
                "tech_qa": f"出第{q_index+1}/{q_total}道专业技术题，围绕「{target_position}」岗位核心技能",
                "star_qa": f"出第{q_index+1}/{q_total}道行为面试题，用STAR法则考察情景应对",
                "project_qa": f"出第{q_index+1}/{q_total}道项目案例题，考察实战分析和架构设计能力",
                "reverse_qa": "询问候选人是否有问题想了解公司或岗位",
            }
        hint = stage_hints.get(stage, "")

        # Phase 13：多形式题库引导 - 按 q_index 提示不同考察方向
        question_angle_hint = ""
        angle_text = self._get_stage_question_angle(stage, q_index, target_position)
        if angle_text:
            question_angle_hint = f"""
【本题目考察方向 - 第{q_index+1}题专属】
{angle_text}

注意：本题为该阶段第{q_index+1}题，必须围绕上述方向出题，禁止与该阶段其他题目的考察角度重复。
"""

        first_line = "请简短开场问候，然后" if is_first else ""

        # 构建公司上下文段落
        # Phase 14 修复：公司名强绑定，即使数据库未查到详情，也必须透传公司名
        # 避免 LLM 因 prompt 中无公司信息而自由发挥编造其他公司（如宝洁、阿里巴巴）
        company_context_text = ""
        if company_ctx:
            c = company_ctx
            company_name_in_ctx = c.get('company_name', '') or ''
            if company_name_in_ctx:
                company_context_text = f"""
【目标公司】{company_name_in_ctx}
所属行业：{c.get('industry', '')}
主营业务：{c.get('business', '')}
企业文化：{c.get('culture', '')}
面试风格：{c.get('interview_style', '')}
面试流程：{c.get('interview_process', '')}
面试难度：{c.get('avg_difficulty', '')}
高频考点：{c.get('hiring_points', '')}
"""

        # 构建岗位上下文段落
        position_context_text = ""
        if position_ctx:
            position_context_text = f"""
【目标岗位】{target_position}（{position_ctx.get('category', '通用')}类）
核心考察点：{position_ctx.get('focus_points', '')}
"""

        # Phase 14 修复：开场白强绑定公司名
        # 只要 company_ctx 中有公司名（无论 has_company 是否为 True），就必须在开场白中提及
        # 避免 has_company=False 时 LLM 编造其他公司名
        company_name_for_opening = (company_ctx or {}).get('company_name', '') or ''
        opening_instruction = ""
        if is_first:
            if company_name_for_opening:
                # 确定公司详情是否可用（has_company=True 表示有完整公司信息）
                has_full_info = bool(company_ctx and company_ctx.get("has_company"))
                interview_process_ref = company_ctx.get('interview_process', '') if has_full_info else ''
                interview_style_ref = company_ctx.get('interview_style', '') if has_full_info else ''
                opening_instruction = f"""开场白必须包含以下要素：
1. 称呼候选人为「你好」
2. 【强制】明确提及公司名「{company_name_for_opening}」，这是本场面试的目标公司
3. 提及岗位名「{target_position or '通用岗位'}」
4. 简要介绍面试流程（参考：{interview_process_ref or '1-2轮技术面+HR面'}）
5. 提及公司面试风格（{interview_style_ref or '专业规范'}）
6. 严禁使用「欢迎参加本次面试」等通用模板句式
7. 【公司一致性强约束】开场白中只能出现「{company_name_for_opening}」这一家公司，
   绝对禁止出现其他任何公司名称（如宝洁、阿里巴巴、腾讯、字节跳动等），
   绝对禁止使用非「{company_name_for_opening}」的业务场景、企业文化、产品作为举例。"""
            elif target_position:
                opening_instruction = f"""开场白必须包含以下要素：
1. 称呼候选人为「你好」
2. 明确提及岗位名「{target_position}」
3. 简要介绍面试流程
4. 严禁使用「欢迎参加本次面试」等通用模板句式
5. 【公司一致性强约束】严禁在开场白中编造或提及任何具体公司名称。"""

        # 定制化出题指令
        custom_question_instruction = ""
        if company_ctx and company_ctx.get("has_company") and stage != "self_intro":
            custom_question_instruction = f"""
出题需结合公司背景：
- 公司业务场景：{company_ctx.get('business', '')}
- 高频考点：{company_ctx.get('hiring_points', '')}
- 面试风格：{company_ctx.get('interview_style', '')}
- 题目应体现该公司真实面试的特点，不要出通用题"""
        elif position_ctx and position_ctx.get("category") != "通用" and stage != "self_intro":
            custom_question_instruction = f"""
出题需贴合岗位属性：
- 岗位类别：{position_ctx.get('category', '')}
- 核心考察点：{position_ctx.get('focus_points', '')}
- 题目必须围绕该岗位的真实工作内容出题，不要出通用题"""

        # Phase 14 修复：面试官人设强绑定公司名
        # 原代码仅提岗位不提公司，导致 LLM 自由发挥编造公司
        interviewer_company_line = ""
        if company_name_for_opening:
            interviewer_company_line = f"你是「{company_name_for_opening}」的资深面试官，"
        else:
            interviewer_company_line = "你是资深面试官，"

        # Phase 14 修复：公司一致性全局约束
        company_consistency_constraint = ""
        if company_name_for_opening:
            company_consistency_constraint = f"""
10. 【公司一致性绝对约束 - 违规将被系统强制拦截】
   本场面试的目标公司是「{company_name_for_opening}」，全链路唯一公司上下文。
   - 你的身份是「{company_name_for_opening}」的面试官，不是其他公司的面试官
   - 所有输出内容（开场白、题目、场景设定、业务举例）只能围绕「{company_name_for_opening}」展开
   - 绝对禁止出现以下公司名称：宝洁、阿里巴巴、腾讯、字节跳动、百度、美团、京东、网易、华为、小米等
   - 绝对禁止使用非「{company_name_for_opening}」的业务场景、产品、企业文化作为题目背景
   - 若需举例，只能使用「{company_name_for_opening}」的业务场景；若不了解该公司详情，使用通用业务场景，不要套用其他公司"""

        return f"""你{interviewer_company_line}拥有8年招聘经验，正在面试「{target_position or '通用岗位'}」岗位。
难度等级: {diff_map.get(difficulty, difficulty)}
{company_context_text}
{position_context_text}
当前环节：{q_type}（第{q_index+1}/{q_total}题）
任务：{first_line}{hint}
{opening_instruction}
{custom_question_instruction}
{question_angle_hint}

规则:
1. 每次只问一个问题
2. 围绕岗位要求出题，不出超纲猎奇题
3. 语言简洁直接，符合真实面试官习惯
4. 不评价对错、不给答案、不教学
5. 不加'面试官：'前缀
6. 不同公司、不同岗位的开场白和题目应有明显差异，禁止使用通用模板
7. 【题目多样性强约束】同一阶段内不同题号必须考察不同维度/不同方向，禁止出同质化题目。
   例如 project_qa 阶段禁止连续两题都问"最有代表性的项目"；应分别考察：从0到1主导、失败项目反思、跨部门协作等不同方向。
8. 【自然语言风格】题目语言要口语化、自然流畅，像真实面试官现场发问。
   - 允许使用"嗯""好的""那我们""接下来"等自然衔接词
   - 禁止生硬的题库式表达（如"请详细描述..."过于书面化）
   - 示例：✅ "那我们来聊聊你的项目经历，分享一个你主导从0到1落地的项目吧，重点讲讲你的设计思路和推动过程"
9. 【权限边界强约束 - 违规内容将被系统强制删除】
   你（大模型）仅允许生成「单道题目的题干内容」，绝对禁止生成任何流程类话术。
   以下内容均由后端状态机唯一管控，LLM 严禁越权生成：
   - 全局结束话术：「面试全部结束」「面试到此结束」「整场面试结束」「今天面试就到这里」「感谢你的时间与分享」「后续结果会通知你」等
   - 阶段过渡话术：「XX环节到此结束」「接下来进入XX环节」「接下来聊聊」「进入下一环节」「聊下一部分」「本环节」「本阶段」「环节结束」「阶段结束」等
   - 点评/评估内容：「【点评】」「优点：」「不足：」「缺失：」「优化建议：」「改进建议：」「评分：」等
   - 多道题目：严禁一次输出2道及以上题目，仅输出当前第{q_index+1}题的题干
   理由：当前仍在「{q_type}」环节（第{q_index+1}/{q_total}题），整场面试共10题。
   阶段切换、全局结束、回答点评、题量计数均由后端状态机自动判定，与 LLM 无关。
   你只需输出第{q_index+1}题的题干，不要输出任何其他内容。
   违规输出的话术将被系统静默删除，可能导致题目内容不完整，请严格遵守。
{company_consistency_constraint}

请直接输出面试官话术（仅题干，无任何前缀和流程话术）。"""

    def _build_reverse_answer_prompt(
        self, target_position: str, user_questions: str,
    ) -> str:
        """构造反向提问回答 prompt：面试官回答候选人的问题"""
        return f"""你是拥有8年招聘经验的资深面试官，正在面试「{target_position or '通用岗位'}」岗位。

候选人向你提出了以下问题：
"{user_questions}"

请你以面试官的身份回答这些问题。要求：
1. 直接、坦诚地回答，不要打官腔
2. 如果涉及公司福利、团队规模、技术栈等，给出合理且有吸引力的回答
3. 如果涉及薪资、加班等敏感问题，给出合理范围但引导候选人关注成长空间
4. 回答控制在200字以内，简洁有力
5. 不加'面试官：'前缀

请直接回答。"""

    def _build_evaluate_prompt(
        self, target_position: str, difficulty: str,
        stage: str, question: str, answer: str,
        position_ctx: Optional[dict] = None,
    ) -> str:
        """构造回答评估 prompt（根据岗位类别动态调整评估维度）"""
        pos_category = (position_ctx or {}).get("category", "通用")

        # 根据岗位类别动态调整评估维度
        if pos_category in ("产品", "运营"):
            eval_dimensions = """请从4个维度评估：
1. 逻辑思维（0-25分）：需求分析是否清晰、逻辑是否严密
2. 用户意识（0-25分）：是否以用户为中心、是否有数据意识
3. 沟通表达（0-25分）：表达是否清晰、结构化
4. 落地能力（0-25分）：是否有可执行的方案、是否有量化成果"""
        elif pos_category in ("数据", "测试"):
            eval_dimensions = """请从4个维度评估：
1. 回答完整度（0-25分）：是否覆盖问题要点
2. 专业术语（0-25分）：是否包含相关专业术语和方法论
3. 逻辑条理（0-25分）：表达是否清晰、有层次
4. 量化成果（0-25分）：是否有具体数据、成果展示"""
        else:
            # 技术类岗位（前端/后端/算法/客户端/全栈/安全等）
            eval_dimensions = """请从4个维度评估：
1. 回答完整度（0-25分）：是否覆盖问题要点
2. 专业关键词（0-25分）：是否包含相关技术/专业术语
3. 逻辑条理（0-25分）：表达是否清晰、有层次
4. 量化成果（0-25分）：是否有具体数据、成果展示"""

        return f"""你是资深面试评估官，请评估候选人对以下问题的回答。

目标岗位：{target_position or '通用岗位'}（{pos_category}类）
难度：{difficulty}
环节：{QUESTION_BANK_CONFIG.get(stage, {}).get('type', stage)}
问题：{question}
候选人回答原文（必须100%基于此回答生成点评，禁止脱离原文）：
---
{answer}
---

{eval_dimensions}

【点评贴合度强制约束 - 违反则点评无效】
1. 所有点评内容必须100%基于上方「候选人回答原文」生成，禁止脱离原文输出通用套话。
2. 优点部分：必须明确引用候选人回答中的具体元素（项目方案/数据指标/方法论/业务逻辑/工具技术等），
   再说明该内容对应的优势。禁止只说"逻辑清晰"，必须说"你在回答中提到的XX分层方案，逻辑清晰且覆盖了XX场景"。
3. 不足部分：必须精准指出候选人回答中具体缺失的内容、表述模糊的环节、未覆盖的维度，
   对应回答的实际内容。禁止只说"缺乏数据支撑"，必须说"回答中提到了XX优化方案，但未补充对应的效果数据"。
4. 优化建议部分：必须针对候选人回答的具体不足给出可落地的补充方向，贴合回答场景。
   禁止给出与回答无关的通用建议。
5. 禁止使用"回答清晰""逻辑严谨""表达流畅"等空泛表述，必须引用回答中的具体内容做支撑。

输出格式（严格JSON，单答单评，仅输出1条点评）：
{{
  "review": "优点：...\\n不足：...\\n优化建议：...",
  "score": 75,
  "weak_points": ["薄弱点1", "薄弱点2"]
}}

点评结构强约束：
1. review 字段必须严格按「优点：...\\n不足：...\\n优化建议：...」三段式输出，禁止拆分为多条点评
2. 三要素缺一不可：优点（亮点与可取之处）、不足（问题与缺失点）、优化建议（针对性改进方向）
3. 严禁输出多个「优点：」「不足：」「优化建议：」标识，单条 review 中每个要素仅出现1次
4. 每个要素必须引用候选人回答中的具体内容做支撑，禁止通用套话

注意：score为0-100整数。评估标准必须与「{target_position or '通用岗位'}」岗位要求对齐，禁止用其他岗位标准评判。只输出JSON，不要其他文字。"""

    def _build_review_report_prompt(
        self, target_position: str, section_scores: dict,
        total_score: float, question_records: list,
        resume_summary: str, jd_summary: str,
    ) -> str:
        """构造复盘报告 prompt"""
        # 整理问答记录摘要
        qa_summary = ""
        for i, rec in enumerate(question_records, 1):
            status = "跳过" if rec.get("skipped") else f"得分{rec.get('score', 0)}"
            qa_summary += f"\n{i}. [{rec.get('stage','')}] Q: {rec.get('question','')[:80]} | A: {rec.get('answer','')[:80]} | {status}"

        return f"""你是面试复盘专家，请基于以下面试数据生成结构化复盘报告。

岗位：{target_position or '通用岗位'}
总分：{total_score}/100
各环节得分：{json.dumps(section_scores, ensure_ascii=False)}

问答记录摘要：
{qa_summary}

简历摘要：{resume_summary[:300]}
JD摘要：{jd_summary[:300]}

请输出以下内容（用markdown格式）：

## 面试复盘报告

### 一、各环节分项得分
（列出5个环节的得分和简评）

### 二、薄弱知识点清单
（列出3-5个需要加强的知识点）

### 三、标准高分回答模板
（针对每道题给出简短的高分回答参考）

### 四、简历/JD匹配度优化方案
（分析简历与岗位的匹配度，给出优化建议）

请直接输出报告内容。"""

    # ============================================================
    # 辅助方法
    # ============================================================
    async def _push_next_question(
        self, target_position: str, difficulty: str,
        stage: str, q_index: int, history: list,
        session_ctx: Optional[dict] = None,
    ):
        """推送下一题（含三层话术校验）

        校验顺序：
        1. _sanitize_agent_text：拦截非法全局结束话术
        2. _sanitize_question_text：拦截阶段过渡话术 + 点评内容（防止 LLM 越权）
        """
        config = QUESTION_BANK_CONFIG.get(stage, {"count": 1})
        company_ctx = (session_ctx or {}).get("company_ctx")
        position_ctx = (session_ctx or {}).get("position_ctx")
        prompt = self._build_question_prompt(
            target_position, difficulty, stage, q_index, config["count"],
            company_ctx=company_ctx, position_ctx=position_ctx
        )
        # 先累积完整文本，再过话术校验，最后一次性输出
        full_text = ""
        async for chunk in self._llm_stream(prompt, history):
            full_text += chunk
        # 第一层：拦截非法全局结束话术
        cleaned, _ = self._sanitize_agent_text(full_text, session_ctx or {})
        # 第二层：拦截阶段过渡话术 + 点评内容（防止 LLM 越权输出导致少题/重复点评）
        cleaned = self._sanitize_question_text(cleaned)
        yield cleaned

    async def _advance_to_stage(
        self, target_position: str, difficulty: str,
        next_stage: str, history: list,
        session_ctx: Optional[dict] = None,
    ):
        """推进到下一阶段：仅输出过渡语/引导语，不输出新阶段第一题

        严格分层（单轮单题原则）：
        - next_stage == "end"：仅输出全局结束语（由调用方保证已满足三级结束条件）
        - next_stage == "reverse_qa"：仅输出反问引导语，等待用户提问
        - 其他阶段：仅输出阶段过渡语，新阶段第一题在下一轮用户操作后输出
        - 设置 session_ctx["pending_stage_start"] = next_stage，供下一轮识别
        """
        if next_stage == "end":
            yield "面试到这里就全部结束了，感谢你的分享，后续结果我们会在一周内通知你，祝你顺利。"
            return

        # 设置待启动阶段标记，下一轮用户操作时输出新阶段第一题
        if session_ctx is not None:
            session_ctx["pending_stage_start"] = next_stage

        if next_stage == "reverse_qa":
            # 反问环节：仅输出引导语，等待用户提问
            yield "我的问题问完了，现在你可以向我提问，你有什么想了解的吗？"
            return

        # 其他阶段：仅输出过渡语，不输出第一题
        transition = self._build_stage_transition_text(next_stage, session_ctx)
        if transition:
            yield transition

    def _build_stage_transition_text(
        self, next_stage: str,
        session_ctx: Optional[dict] = None,
    ) -> str:
        """构建阶段过渡语文本（不 yield、不设置 pending）

        供单轮完整输出场景使用：阶段切换时，与点评+新阶段首题在同一轮输出。
        """
        if next_stage == "end":
            return "面试到这里就全部结束了，感谢你的分享，后续结果我们会在一周内通知你，祝你顺利。"
        if next_stage == "reverse_qa":
            return "我的问题问完了，现在你可以向我提问，你有什么想了解的吗？"

        company_ctx = (session_ctx or {}).get("company_ctx")
        if company_ctx and company_ctx.get("has_company"):
            cn = company_ctx["company_name"]
            transitions = {
                "tech_qa": f"自我介绍环节到此结束，接下来我们进入{cn}的专业技术环节。",
                "star_qa": f"技术问答环节到此结束，接下来聊聊{cn}常考的行为面试题。",
                "project_qa": f"行为面试环节到此结束，接下来进入项目案例环节，请结合实际项目经验作答。",
                "reverse_qa": "我的问题问完了，现在你可以向我提问，你有什么想了解的吗？",
            }
        else:
            transitions = {
                "tech_qa": "自我介绍环节到此结束，接下来我们进入专业技术环节。",
                "star_qa": "技术问答环节到此结束，接下来聊聊行为面试题。",
                "project_qa": "行为面试环节到此结束，接下来进入项目案例环节，请结合实际项目作答。",
                "reverse_qa": "我的问题问完了，现在你可以向我提问，你有什么想了解的吗？",
            }
        return transitions.get(next_stage, "")

    async def _evaluate_answer(
        self, target_position: str, difficulty: str,
        stage: str, question: str, answer: str, history: list,
        position_ctx: Optional[dict] = None,
    ) -> tuple:
        """评估回答，返回 (review_text, score)"""
        if not answer or not answer.strip():
            return "未作答", 0

        prompt = self._build_evaluate_prompt(
            target_position, difficulty, stage, question, answer,
            position_ctx=position_ctx
        )
        try:
            result = await self._llm_complete(prompt, "请评估")
            # 解析 JSON
            if result.startswith("```"):
                result = result.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            import re
            match = re.search(r'\{[\s\S]*\}', result)
            if match:
                data = json.loads(match.group(0))
                review = data.get("review", "评估完成")
                score = int(data.get("score", 70))
                return review, max(0, min(100, score))
        except Exception:
            pass
        return "评估完成", 70

    async def _generate_review_only(
        self, target_position: str, difficulty: str,
        stage: str, question: str, user_answer: str,
        position_ctx: Optional[dict] = None,
    ) -> tuple:
        """调用1：仅生成纯点评内容（结构化JSON输出 + 字段提取 + 原文锚定 + 岗位针对性）

        强制约束：
        1. 大模型必须返回标准JSON格式：{"comment":{"advantage":"...","disadvantage":"...","suggestion":"..."},"score":75}
        2. 非JSON格式、字段外文本全部丢弃，解析失败触发重试
        3. advantage/disadvantage 必须各引用至少1处用户回答原文关键词，否则触发重生成
        4. disadvantage 必须明确指出缺失的岗位能力维度
        5. 字段值禁止包含任何流程类、衔接类语句

        :return: (点评字段字典, 分数) 字典格式 {"advantage": "...", "disadvantage": "...", "suggestion": "..."}，分数 0-100
        """
        if not user_answer or not user_answer.strip():
            return {"advantage": "未作答", "disadvantage": "未作答", "suggestion": "建议补充完整回答"}, 0

        pos_category = (position_ctx or {}).get("category", "通用") if position_ctx else "通用"
        focus_points = (position_ctx or {}).get("focus_points", "综合能力") if position_ctx else "综合能力"
        dimensions = (position_ctx or {}).get("dimensions") or DEFAULT_DIMENSIONS

        # 构建岗位能力维度清单（用于点评时锚定缺失维度）
        dim_list_text = ""
        if dimensions:
            dim_lines = [f"- {d.get('dim','')}：{d.get('directions','')}" for d in dimensions]
            dim_list_text = "\n".join(dim_lines)

        # 根据岗位类别动态调整评估维度
        if pos_category in ("产品", "运营"):
            eval_dims = "逻辑思维、用户意识、沟通表达、落地能力"
        elif pos_category in ("数据", "测试"):
            eval_dims = "回答完整度、专业术语、逻辑条理、量化成果"
        elif pos_category == "设计":
            eval_dims = "设计思维、专业技法、用户视角、落地能力"
        else:
            eval_dims = "回答完整度、专业关键词、逻辑条理、量化成果"

        prompt = f"""你是资深面试评估官，请评估候选人对以下问题的回答。

目标岗位：{target_position or '通用岗位'}（{pos_category}类）
核心考察点：{focus_points}
难度：{difficulty}
环节：{QUESTION_BANK_CONFIG.get(stage, {}).get('type', stage)}
问题：{question}

候选人回答原文（必须100%基于此回答生成点评，禁止脱离原文）：
---
{user_answer}
---

【岗位能力维度清单（点评时需锚定候选人缺失的维度）】
{dim_list_text or '综合能力'}

评估维度：{eval_dims}（每维度0-25分，总分100）

【输出强约束 - 违反则点评无效】
1. **强制JSON格式**：仅输出标准JSON，禁止输出任何JSON以外的文本（无前缀、无后缀、无解释、无代码块标记）。
2. **强制原文锚定**：advantage、disadvantage 必须各引用至少1处用户回答中的具体表述（用短句直接对应原文内容）。
   - 正确示例："advantage": "你在回答中提到的分版本规划+对齐目标+权责拆分推进框架，逻辑清晰覆盖了三方诉求"
   - 错误示例："advantage": "逻辑清晰，有项目管理思维"（无对应原文支撑）
3. **岗位能力锚定**：disadvantage 必须明确指出候选人回答中缺失的岗位能力维度（参考上方「岗位能力维度清单」），并对应回答的实际内容。
   - 正确示例："disadvantage": "回答中提到了视觉风格定义，但未覆盖『设计体系建设』维度的组件库搭建经验"
   - 错误示例："disadvantage": "缺乏数据支撑"（无岗位维度锚定）
4. **字段纯内容**：每个字段仅写纯内容，禁止加"优点："、"不足："等前缀，禁止加任何衔接句、过渡句。
5. **零流程表述**：禁止出现"接下来、下面、请回答、以上点评、我们进入"等任何流程类、衔接类语句。
6. **精准对应**：suggestion 必须对应 disadvantage 给出可落地补充方向，贴合题目场景与岗位要求。
7. 禁止使用"回答清晰""逻辑严谨""表达流畅"等空泛表述，必须引用回答中的具体内容做支撑。
8. score 为 0-100 整数，必须与「{target_position or '通用岗位'}」岗位要求对齐。

【强制输出JSON结构】
{{
  "comment": {{
    "advantage": "纯优点内容，必须引用用户回答中的具体表述，无任何前缀后缀",
    "disadvantage": "纯不足内容，必须对应用户回答的具体缺失点+缺失的岗位能力维度，无任何前缀后缀",
    "suggestion": "纯优化建议内容，贴合不足+岗位要求给出方向，无任何前缀后缀"
  }},
  "score": 75
}}

直接输出JSON，不要代码块标记、不要解释："""

        max_retries = 2
        last_error = ""
        for attempt in range(max_retries + 1):
            try:
                result = await self._llm_complete(prompt, "请生成纯点评JSON")
                # 解析JSON
                parsed, score = self._parse_review_json(result)
                if parsed is None:
                    last_error = f"JSON解析失败：{result[:100]}"
                    logging.getLogger(__name__).warning(
                        "纯点评JSON解析失败(尝试%d/%d): %s",
                        attempt + 1, max_retries + 1, last_error
                    )
                    continue
                # Phase 12 三层贴合度校验
                # 1. 关键词命中校验：advantage/disadvantage 必须各含至少1个原文关键词
                if not self._validate_review_fields_relevance(parsed, user_answer):
                    last_error = "贴合度不足：advantage/disadvantage 未引用原文关键词"
                    logging.getLogger(__name__).warning(
                        "纯点评贴合度不足(尝试%d/%d): %s",
                        attempt + 1, max_retries + 1, last_error
                    )
                    continue
                # 2. 岗位相关性校验：点评必须包含目标岗位的专业术语/能力点
                if not self._validate_review_position_relevance(parsed, target_position, position_ctx):
                    last_error = "岗位相关性不足：点评未包含岗位专业术语/能力点"
                    logging.getLogger(__name__).warning(
                        "纯点评岗位相关性不足(尝试%d/%d): %s",
                        attempt + 1, max_retries + 1, last_error
                    )
                    continue
                # 3. 空泛套话拦截：仅出现「逻辑清晰、思路明确」等无支撑套话 → 重新生成
                if not self._validate_review_no_generic_phrases(parsed):
                    last_error = "空泛套话：点评仅含通用形容词无具体支撑"
                    logging.getLogger(__name__).warning(
                        "纯点评空泛套话(尝试%d/%d): %s",
                        attempt + 1, max_retries + 1, last_error
                    )
                    continue
                # 字段值清洗：过滤任何残留流程话术
                parsed = self._sanitize_review_fields(parsed)
                return parsed, score
            except Exception as e:
                last_error = f"调用异常: {e}"
                logging.getLogger(__name__).warning(
                    "纯点评生成异常(尝试%d/%d): %s",
                    attempt + 1, max_retries + 1, last_error
                )
        # 所有重试失败 → 返回兜底字段
        logging.getLogger(__name__).error(
            "纯点评生成全部失败，返回兜底字段 | 最后错误: %s", last_error
        )
        return {
            "advantage": "回答内容已收到",
            "disadvantage": "建议补充更多细节",
            "suggestion": "可结合具体场景补充实施步骤和量化指标"
        }, 70

    @staticmethod
    def _parse_review_json(result: str) -> tuple:
        """解析点评JSON，返回 (字段字典, 分数)

        支持以下格式：
        - 纯JSON: {"comment":{"advantage":"...","disadvantage":"...","suggestion":"..."},"score":75}
        - 代码块包裹: ```json ... ```
        - 混合文本: 提取首个完整JSON对象

        :return: (字段字典, 分数) 解析成功；失败返回 (None, 0)
        """
        if not result:
            return None, 0
        text = result.strip()
        # 去除代码块标记
        if text.startswith("```"):
            text = text.split("\n", 1)[-1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        # 去除非JSON前缀文本（提取首个 { 到末尾 }）
        import re as _re
        match = _re.search(r'\{[\s\S]*\}', text)
        if not match:
            return None, 0
        try:
            data = json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            return None, 0
        # 兼容两种结构：{comment:{...}} 或 直接 {...}
        comment = data.get("comment") if isinstance(data, dict) else None
        if comment and isinstance(comment, dict):
            advantage = comment.get("advantage", "").strip()
            disadvantage = comment.get("disadvantage", "").strip()
            suggestion = comment.get("suggestion", "").strip()
        else:
            advantage = data.get("advantage", "").strip() if isinstance(data, dict) else ""
            disadvantage = data.get("disadvantage", "").strip() if isinstance(data, dict) else ""
            suggestion = data.get("suggestion", "").strip() if isinstance(data, dict) else ""
        # 必须至少有 advantage 和 disadvantage
        if not advantage or not disadvantage:
            return None, 0
        # 提取分数（兼容多层结构）
        score = 70
        if isinstance(data, dict):
            raw_score = data.get("score")
            if raw_score is None and isinstance(comment, dict):
                raw_score = comment.get("score")
            if raw_score is not None:
                try:
                    score = max(0, min(100, int(raw_score)))
                except (ValueError, TypeError):
                    score = 70
        return {
            "advantage": advantage,
            "disadvantage": disadvantage,
            "suggestion": suggestion or "建议结合不足点补充具体内容",
        }, score

    @staticmethod
    def _validate_review_fields_relevance(review_fields: dict, user_answer: str) -> bool:
        """点评字段贴合度校验：advantage 和 disadvantage 必须各含至少1个原文关键词

        使用滑动窗口提取 2-4 字中文子串作为关键词，避免正则分词不匹配问题。

        :param review_fields: {"advantage":"...", "disadvantage":"...", "suggestion":"..."}
        :param user_answer: 用户回答原文
        :return: True=贴合，False=套话
        """
        if not user_answer or not review_fields:
            return True
        import re as _re
        # 提取用户回答中所有中文字符（去除标点、数字、英文）
        cn_only = _re.sub(r'[^\u4e00-\u9fa5]', '', user_answer)
        if len(cn_only) < 2:
            return True
        # 使用滑动窗口提取 2-4 字中文子串作为关键词
        keywords = set()
        for size in (4, 3, 2):
            for i in range(len(cn_only) - size + 1):
                keywords.add(cn_only[i:i+size])
        # 过滤通用词（仅过滤 2 字词）
        generic_words = {
            "回答", "问题", "这个", "一个", "我们", "你们", "他们",
            "可以", "可能", "应该", "需要", "进行", "通过", "这种",
            "方面", "情况", "内容", "方式", "方法", "过程",
            "采用", "明确", "具体", "细节", "数据", "建议",
        }
        keywords = {kw for kw in keywords if kw not in generic_words}
        if not keywords:
            return True
        # advantage 必须命中至少1个关键词
        advantage = review_fields.get("advantage", "")
        disadvantage = review_fields.get("disadvantage", "")
        adv_hit = any(kw in advantage for kw in keywords)
        dis_hit = any(kw in disadvantage for kw in keywords)
        return adv_hit and dis_hit

    @staticmethod
    def _validate_review_position_relevance(
        review_fields: dict, target_position: str, position_ctx: Optional[dict],
    ) -> bool:
        """Phase 12：点评岗位相关性校验

        点评内容必须包含目标岗位的专业术语/能力点，与岗位无关的泛化点评直接驳回。

        :param review_fields: {"advantage":..., "disadvantage":..., "suggestion":...}
        :param target_position: 目标岗位名
        :param position_ctx: 岗位上下文（含 category、focus_points、dimensions）
        :return: True=贴合岗位，False=泛化点评
        """
        if not review_fields:
            return True
        # 构建岗位关键词集合
        pos_keywords = set()
        import re as _re
        # 岗位名本身的关键词
        for cn_seg in _re.findall(r"[\u4e00-\u9fa5]+", target_position or ""):
            if len(cn_seg) >= 2:
                for size in (4, 3, 2):
                    for i in range(len(cn_seg) - size + 1):
                        pos_keywords.add(cn_seg[i:i+size])
        # 岗位类别 + focus_points + dimensions 关键词
        if position_ctx:
            for seg in [
                position_ctx.get("category", ""),
                position_ctx.get("focus_points", ""),
            ]:
                for cn_seg in _re.findall(r"[\u4e00-\u9fa5]+", seg):
                    if len(cn_seg) >= 2:
                        for size in (4, 3, 2):
                            for i in range(len(cn_seg) - size + 1):
                                pos_keywords.add(cn_seg[i:i+size])
            # 维度名 + 方向关键词
            for d in position_ctx.get("dimensions", []) or []:
                for seg in [d.get("dim", ""), d.get("directions", "")]:
                    for cn_seg in _re.findall(r"[\u4e00-\u9fa5]+", seg):
                        if len(cn_seg) >= 2:
                            for size in (4, 3, 2):
                                for i in range(len(cn_seg) - size + 1):
                                    pos_keywords.add(cn_seg[i:i+size])
        # 过滤通用词
        generic_words = {
            "岗位", "能力", "技术", "工作", "经验", "专业", "综合",
            "方面", "情况", "内容", "方式", "方法", "过程", "问题",
            "回答", "这个", "一个", "可以", "应该", "需要",
        }
        pos_keywords = {kw for kw in pos_keywords if kw not in generic_words}
        if not pos_keywords:
            return True  # 无岗位关键词时不校验
        # 拼接所有点评字段文本
        all_review_text = (
            review_fields.get("advantage", "") + review_fields.get("disadvantage", "")
            + review_fields.get("suggestion", "")
        )
        # 至少1个岗位关键词命中
        return any(kw in all_review_text for kw in pos_keywords)

    @staticmethod
    def _validate_review_no_generic_phrases(review_fields: dict) -> bool:
        """Phase 12：空泛套话拦截

        仅出现「逻辑清晰、思路明确、内容完整、表达流畅、回答清晰」等无支撑套话，
        判定为无效点评，必须重新生成。

        :param review_fields: {"advantage":..., "disadvantage":..., "suggestion":...}
        :return: True=有效（有具体内容），False=空泛套话
        """
        if not review_fields:
            return False
        # 空泛套话黑名单（仅这些短词构成点评 → 判定无效）
        generic_phrases = {
            "逻辑清晰", "思路明确", "思路清晰", "内容完整", "表达流畅",
            "回答清晰", "逻辑严谨", "条理清晰", "结构完整", "表述清楚",
            "重点突出", "层次分明", "论证有力", "言之有物",
            "缺乏数据", "缺乏细节", "缺乏支撑", "缺乏深度",
            "建议补充", "建议增加", "建议完善", "建议加强",
        }
        advantage = (review_fields.get("advantage") or "").strip()
        disadvantage = (review_fields.get("disadvantage") or "").strip()
        # 优点或不足为空 → 无效
        if not advantage or not disadvantage:
            return False
        # 优点字段仅由短套话组成（长度<15且包含套话）→ 无效
        if len(advantage) < 15:
            for phrase in generic_phrases:
                if phrase in advantage:
                    return False
        # 不足字段仅由短套话组成 → 无效
        if len(disadvantage) < 15:
            for phrase in generic_phrases:
                if phrase in disadvantage:
                    return False
        return True

    @staticmethod
    def _sanitize_review_fields(review_fields: dict) -> dict:
        """字段值二次清洗：删除残留的流程话术、引导语

        :param review_fields: {advantage, disadvantage, suggestion}
        :return: 清洗后的字段字典
        """
        if not review_fields:
            return review_fields
        def _clean_value(val: str) -> str:
            if not val:
                return val
            cleaned_lines = []
            for line in val.split("\n"):
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                # 删除流程话术行
                if any(pat in line_stripped for pat in STAGE_TRANSITION_PATTERNS):
                    continue
                # 删除引导语行
                if any(pat in line_stripped for pat in GUIDE_PHRASE_PATTERNS):
                    continue
                # 删除全局结束话术行
                if any(pat in line_stripped for pat in GLOBAL_END_PATTERNS):
                    continue
                cleaned_lines.append(line)
            return "\n".join(cleaned_lines).strip()
        return {
            "advantage": _clean_value(review_fields.get("advantage", "")),
            "disadvantage": _clean_value(review_fields.get("disadvantage", "")),
            "suggestion": _clean_value(review_fields.get("suggestion", "")),
        }

    @staticmethod
    def _assemble_review_text(review_fields: dict) -> str:
        """后端固定拼接点评文本（纯字段值硬拼接，无任何AI生成话术）

        拼接模板：
        优点：{advantage字段值}
        不足：{disadvantage字段值}
        优化建议：{suggestion字段值}

        :param review_fields: {advantage, disadvantage, suggestion}
        :return: 后端固定模板拼接的点评文本
        """
        if not review_fields:
            return "优点：未作答\n不足：未作答\n优化建议：建议补充完整回答"
        advantage = (review_fields.get("advantage") or "未作答").strip()
        disadvantage = (review_fields.get("disadvantage") or "未作答").strip()
        suggestion = (review_fields.get("suggestion") or "建议结合不足点补充具体内容").strip()
        return f"优点：{advantage}\n不足：{disadvantage}\n优化建议：{suggestion}"

    async def _generate_question_only(
        self, target_position: str, difficulty: str,
        stage: str, q_index: int, stage_count: int,
        history: list,
        company_ctx: Optional[dict] = None,
        position_ctx: Optional[dict] = None,
        session_ctx: Optional[dict] = None,
    ) -> str:
        """调用2：仅生成纯题干内容（结构化JSON输出 + 字段提取 + 三层清洗 + 三重校验）

        Phase 12 强制约束：
        1. 大模型必须返回标准JSON格式：{"question_title":"纯题目题干内容"}
        2. 非JSON格式、字段外文本全部丢弃，解析失败触发重试（最多3次）
        3. 字段值禁止包含引导语、前缀、过渡句、礼貌语
        4. 提取后执行三层清洗：正则删除引导词+语义过滤衔接句+去重校验
        5. 三重校验：语义去重(≥0.5) → 维度多样性 → 岗位贴合，未通过重新生成

        :param session_ctx: 会话上下文（用于已出题缓存和维度多样性校验）
        :return: 纯题干文本
        """
        # 初始化会话级缓存库
        if session_ctx is None:
            session_ctx = {}
        self._init_question_cache(session_ctx)

        # 构建已出题摘要（用于Prompt中提示LLM避免重复）
        asked_summary = ""
        cache = session_ctx.get("question_cache", {})
        asked_questions = cache.get("asked_questions", [])
        if asked_questions:
            asked_list = [f"- {item['question'][:60]}" for item in asked_questions[-6:]]
            asked_summary = "\n【已出题目（禁止重复出同语义题目）】\n" + "\n".join(asked_list)

        # 构建已考察维度摘要
        asked_dims_summary = ""
        asked_dims = cache.get("asked_dimensions", [])
        if asked_dims:
            asked_dims_summary = f"\n【已考察能力维度（禁止再出同维度题目）】{', '.join(asked_dims)}"

        # 构建当前可用维度提示
        available_dims = ""
        dimensions = (position_ctx or {}).get("dimensions") or DEFAULT_DIMENSIONS
        if dimensions:
            available_dims_list = []
            for d in dimensions:
                dim_name = d.get("dim", "")
                directions = d.get("directions", "")
                if dim_name not in asked_dims:
                    available_dims_list.append(f"- {dim_name}：{directions}")
            if available_dims_list:
                available_dims = "\n【本次可出题的能力维度（必须从中选择1个维度出题）】\n" + "\n".join(available_dims_list)

        base_prompt = self._build_question_prompt(
            target_position, difficulty, stage, q_index, stage_count,
            company_ctx=company_ctx, position_ctx=position_ctx
        )
        prompt = base_prompt + asked_summary + asked_dims_summary + available_dims + """

【输出强约束 - 违反则题目无效】
1. **强制JSON格式**：仅输出标准JSON，禁止输出任何JSON以外的文本（无前缀、无后缀、无解释、无代码块标记）。
2. **字段名固定**：必须使用 question_title 作为字段名（禁止用 question、content、title 等其他字段名）。
3. **字段纯内容**：question_title 字段仅保留题目核心设问，禁止加"请回答："、"请问："等前缀，禁止任何礼貌语。
4. **禁止引导语**：禁止出现"请结合实际经验作答"、"请针对题目给出解答方案"、"请作答"等任何引导句式。
5. **禁止过渡句**：禁止出现"接下来我们看"、"下面这道题"、"好的，那我们"等任何过渡、衔接类表述。
6. **单题输出**：question_title 字段仅包含1道完整题目，禁止多道题、禁止拆分小问题。
7. **题目多样性**：必须从「本次可出题的能力维度」中选择1个未考察的维度出题，禁止与已出题语义重复。
8. **岗位贴合**：题目必须紧扣目标岗位的日常工作场景与核心能力要求，禁止泛化题。

【强制输出JSON结构】
{
  "question_title": "纯题目核心设问，无任何前缀、引导语、过渡句、礼貌语"
}

直接输出JSON，不要代码块标记、不要解释："""

        max_retries = 3  # 三重校验需要更多重试机会
        last_error = ""
        for attempt in range(max_retries + 1):
            try:
                # 累积完整文本
                full_text = ""
                async for chunk in self._llm_stream(prompt, history):
                    full_text += chunk
                # 解析JSON
                question_text = self._parse_question_json(full_text)
                if question_text is None:
                    last_error = f"JSON解析失败：{full_text[:100]}"
                    logging.getLogger(__name__).warning(
                        "纯题干JSON解析失败(尝试%d/%d): %s",
                        attempt + 1, max_retries + 1, last_error
                    )
                    continue
                # 二次清洗：删除残留引导语、过渡句、多题目
                question_text = self._deep_clean_question_field(question_text)
                if not question_text or len(question_text.strip()) < 5:
                    last_error = f"清洗后题干为空或过短：{question_text}"
                    logging.getLogger(__name__).warning(
                        "纯题干清洗后无效(尝试%d/%d): %s",
                        attempt + 1, max_retries + 1, last_error
                    )
                    continue
                # 三重校验：语义去重 → 维度多样性 → 岗位贴合
                # Phase 12 修复：传入 stage 参数，project_qa/star_qa 等抽象阶段放宽岗位贴合校验
                is_valid, fail_reason, detected_dim = self._run_question_triple_check(
                    question_text, session_ctx, target_position, position_ctx, stage=stage
                )
                if not is_valid:
                    last_error = f"三重校验失败：{fail_reason}"
                    logging.getLogger(__name__).warning(
                        "纯题干三重校验失败(尝试%d/%d): %s | 题目: %s",
                        attempt + 1, max_retries + 1, fail_reason, question_text[:80]
                    )
                    continue
                # 三重校验通过 → 记录到缓存库
                self._record_asked_question(question_text, detected_dim, stage, session_ctx)
                logging.getLogger(__name__).info(
                    "题目生成成功 | 阶段: %s | 维度: %s | 题干: %s",
                    stage, detected_dim or "未匹配", question_text[:60]
                )
                return question_text
            except Exception as e:
                last_error = f"调用异常: {e}"
                logging.getLogger(__name__).warning(
                    "纯题干生成异常(尝试%d/%d): %s",
                    attempt + 1, max_retries + 1, last_error
                )
        # 所有重试失败 → 返回阶段具体兜底题干（必须是真实题目，禁止引导语）
        # Phase 12 修复：原兜底「请结合你的实际经验回答以下问题。」是引导语不是题干，
        # 导致用户看到只有话术没有题干的问题。改为按阶段返回具体真实题目。
        # Phase 14 修复：兜底题目按 q_index 选择多样化题目，避免重复出相同兜底题
        logging.getLogger(__name__).error(
            "纯题干生成全部失败，返回阶段具体兜底题干 | 最后错误: %s | 阶段: %s | q_index: %s",
            last_error, stage, q_index
        )
        fallback_q = self._get_stage_fallback_question(
            stage, target_position, q_index, session_ctx
        )
        self._record_asked_question(fallback_q, None, stage, session_ctx)
        return fallback_q

    @staticmethod
    def _get_stage_fallback_question(
        stage: str, target_position: str,
        q_index: int = 0, session_ctx: Optional[dict] = None,
    ) -> str:
        """按阶段返回具体兜底题干（真实题目，非引导语）

        当 LLM 题干生成全部失败时使用，确保用户始终能看到一道真实题目而非引导语。
        Phase 14 修复：按 q_index 选择多样化兜底题目，避免同阶段重复出相同兜底题。

        :param stage: 面试阶段
        :param target_position: 目标岗位
        :param q_index: 阶段内题号（0-based），用于选择多样化题目
        :param session_ctx: 会话上下文（用于检查已出题目，避免重复）
        :return: 阶段相关的具体兜底题目
        """
        pos = target_position or "目标岗位"

        # Phase 14：优先使用多样化题库（按 q_index 选择不同考察角度）
        angles = InterviewAgent._STAGE_QUESTION_ANGLES.get(stage, [])
        if angles and q_index < len(angles):
            candidate_q = angles[q_index].format(pos=pos)
        else:
            # q_index 超出范围或无多样化题库，使用固定兜底
            fallback_map = {
                "self_intro": f"请简单介绍一下你自己，重点说明你与{pos}岗位相关的经历和能力。",
                "tech_qa": f"请详细说明你在{pos}岗位中最熟悉的一项核心技术/专业技能，并举例说明你是如何应用的？",
                "star_qa": f"请描述一次你在工作中遇到的最大挑战，使用STAR法则说明情境、任务、行动和结果。",
                "project_qa": f"请详细描述你经历过的最有代表性的一个项目，说明你在其中的角色、承担的职责、解决的关键问题以及最终的量化成果。",
                "reverse_qa": "你有什么问题想了解关于这个岗位或公司的吗？",
            }
            candidate_q = fallback_map.get(stage, f"请结合你的{pos}岗位经验，详细说明一个你印象最深的工作经历。")

        # Phase 14 关键修复：检查兜底题目是否已出过，若已出过则选下一道未出过的
        if session_ctx:
            cache = session_ctx.get("question_cache", {}) or {}
            asked_questions = cache.get("asked_questions", [])
            asked_texts = [item.get("question", "") for item in asked_questions]

            # 如果当前候选题已出过，尝试从多样化题库中找未出过的
            if candidate_q in asked_texts and angles:
                for angle in angles:
                    alt_q = angle.format(pos=pos)
                    if alt_q not in asked_texts:
                        return alt_q

            # 如果所有多样化题目都已出过或没有多样化题库，尝试固定兜底题目中未出过的
            all_fallbacks = {
                "self_intro": [
                    f"请简单介绍一下你自己，重点说明你与{pos}岗位相关的经历和能力。",
                    f"请做一个自我介绍，突出你匹配{pos}岗位的核心优势。",
                ],
                "tech_qa": [
                    f"请详细说明你在{pos}岗位中最熟悉的一项核心技术/专业技能，并举例说明你是如何应用的？",
                    f"在{pos}领域，你认为最重要的技术趋势是什么？请结合你的实际经验说明。",
                    f"请描述你在{pos}工作中遇到的一个技术难题，以及你的解决过程。",
                ],
                "star_qa": [
                    f"请描述一次你在工作中遇到的最大挑战，使用STAR法则说明情境、任务、行动和结果。",
                    f"分享一次你在团队中发挥关键作用的经历，用STAR法则说明。",
                    f"描述一次你主动承担额外职责的经历，用STAR法则说明情境和成果。",
                ],
                "project_qa": [
                    f"请详细描述你经历过的最有代表性的一个项目，说明你在其中的角色、承担的职责、解决的关键问题以及最终的量化成果。",
                    f"描述一个你主导的从0到1落地的项目，重点讲讲你的方案设计思路和推动落地的关键动作。",
                    f"讲一个你推动跨部门协作落地的案例，重点描述你如何对齐不同方诉求并最终达成目标。",
                ],
                "reverse_qa": [
                    "你有什么问题想了解关于这个岗位或公司的吗？",
                    "关于这个岗位的日常工作或团队协作，你有什么想了解的？",
                ],
            }
            stage_fallbacks = all_fallbacks.get(stage, [candidate_q])
            for fb in stage_fallbacks:
                if fb not in asked_texts:
                    return fb
            # 全部都出过了，返回最后一个（极端情况）
            return stage_fallbacks[-1]

        return candidate_q

    # ============================================================
    # Phase 13：多形式题库 - 为 project_qa / star_qa / tech_qa 提供多样化题干方向
    # 每个阶段按 q_index 选择不同考察角度，避免"最有代表性的项目"类同质化题目
    # ============================================================
    _STAGE_QUESTION_ANGLES = {
        "project_qa": [
            # 第1题：从0到1的项目主导
            "描述一个你主导的从0到1落地的项目，重点讲讲你的方案设计思路和推动落地的关键动作。",
            # 第2题：失败项目反思
            "分享一个你参与过的最失败的项目，重点说明失败原因、你的反思和后续改进。",
            # 第3题：跨部门协作
            "讲一个你推动跨部门协作落地的案例，重点描述你如何对齐不同方诉求并最终达成目标。",
        ],
        "star_qa": [
            # 第1题：压力/挑战场景
            "分享一次你在紧迫时间或资源紧张情况下完成目标的经历，用STAR法则说明。",
            # 第2题：冲突/分歧处理
            "描述一次你在工作中与同事/上级产生分歧的经历，你是如何处理并推动问题解决的？",
        ],
        "tech_qa": [
            # 第1题：基础概念
            "你如何理解{pos}岗位中最核心的一项技术原理？请结合实际应用场景说明。",
            # 第2题：方案设计
            "给定一个典型业务场景，你会如何设计技术方案？请说明关键决策点和权衡依据。",
            # 第3题：性能/优化
            "请描述你做过的最具挑战性的一次性能优化或技术重构，包括定位问题的过程和最终效果。",
        ],
    }

    @staticmethod
    def _get_stage_question_angle(stage: str, q_index: int, target_position: str) -> str:
        """获取阶段内指定题号对应的多形式考察方向（用于 prompt 引导 LLM 出不同题）

        :param stage: 面试阶段
        :param q_index: 阶段内题号（0-based）
        :param target_position: 目标岗位
        :return: 考察方向描述；无对应返回空字符串
        """
        angles = InterviewAgent._STAGE_QUESTION_ANGLES.get(stage, [])
        if not angles or q_index >= len(angles):
            return ""
        pos = target_position or "目标岗位"
        return angles[q_index].format(pos=pos)

    # ============================================================
    # Phase 13：追问机制 - 候选人回答后基于回答内容生成1-2个追问
    # 追问不推进 question_index，下一轮才正式推进到新题
    # ============================================================
    def _build_follow_up_prompt(
        self, target_position: str, stage: str,
        question: str, user_answer: str,
        follow_up_round: int,
    ) -> str:
        """构造追问 prompt（基于候选人回答生成1个追问问题）"""
        return f"""你是拥有8年招聘经验的资深面试官，正在面试「{target_position or '通用岗位'}」岗位。
当前环节：{QUESTION_BANK_CONFIG.get(stage, {}).get('type', stage)}
面试官问题：{question}
候选人回答原文：
---
{user_answer}
---

任务：基于候选人的回答，生成1个追问问题，深挖候选人回答中的细节、数据、决策依据或潜在疑点。

【追问生成规则 - 违反则追问无效】
1. 仅输出1个追问问题，无任何前缀、无点评、无承接话术、无引导语。
2. 追问必须紧扣候选人回答中的具体内容（如候选人提到的方案/数据/决策/挑战）。
3. 优先深挖以下维度之一（按优先级）：
   - 若回答笼统：追问具体数据、具体动作、具体决策依据
   - 若回答有亮点：追问"当时为什么选择这个方案而不是其他？"
   - 若回答有疑点：追问"这里遇到的最大挑战是什么？你怎么解决的？"
4. 追问语言要自然口语化，像真实面试官的现场追问。
5. 追问禁止与原题重复，禁止简单复述原题。
6. 追问禁止包含"环节结束"、"接下来进入"、"面试结束"等流程话术。
7. 追问禁止包含"优点"、"不足"、"点评"、"评分"等评估性词汇。
8. 当前是第{follow_up_round}轮追问（最多2轮），追问应当比上一轮更具体、更深入。

【强制输出JSON结构】
{{
  "follow_up_question": "纯追问问题文本，无任何前缀和流程话术"
}}

直接输出JSON，不要代码块标记、不要解释："""

    def _parse_follow_up_json(self, result: str) -> Optional[str]:
        """解析追问 JSON，返回 follow_up_question 字段值"""
        if not result:
            return None
        text = result.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        import re as _re
        match = _re.search(r'\{[\s\S]*\}', text)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        follow_up = (data.get("follow_up_question") or "").strip()
        if not follow_up:
            return None
        # 清洗：移除可能残留的流程话术
        for pat in STAGE_TRANSITION_PATTERNS:
            if pat in follow_up:
                return None
        for pat in REVIEW_PATTERNS:
            if pat in follow_up:
                return None
        return follow_up

    async def _generate_follow_up_only(
        self, target_position: str, stage: str,
        question: str, user_answer: str,
        follow_up_round: int,
    ) -> Optional[str]:
        """生成单个追问问题（失败返回 None）"""
        if not user_answer or len(user_answer.strip()) < 5:
            return None
        prompt = self._build_follow_up_prompt(
            target_position, stage, question, user_answer, follow_up_round
        )
        try:
            full_text = ""
            async for chunk in self._llm_stream(prompt, []):
                full_text += chunk
            follow_up = self._parse_follow_up_json(full_text)
            if not follow_up or len(follow_up.strip()) < 5:
                return None
            return follow_up.strip()
        except Exception as e:
            logging.getLogger(__name__).warning(f"追问生成失败: {e}")
            return None

    def _should_ask_follow_up(
        self, stage: str, question_index: int,
        follow_up_count_in_stage: int,
    ) -> bool:
        """判断当前是否需要追问

        策略：
        - self_intro / reverse_qa 阶段不追问（开场和反问环节不深挖）
        - 其他阶段：每道正式题目最多追问1次（避免拖慢节奏）
        - 已追问1次则不再追问，下一轮直接推进到新题
        """
        if stage in ("self_intro", "reverse_qa", "init", "end"):
            return False
        return follow_up_count_in_stage < 1

    @staticmethod
    def _parse_question_json(result: str) -> Optional[str]:
        """解析题干JSON，返回 question_title 字段值

        Phase 12：强制使用 question_title 字段名（兼容回退 question 字段）
        支持以下格式：
        - 纯JSON: {"question_title":"..."} 或 {"question":"..."}
        - 代码块包裹: ```json ... ```
        - 混合文本: 提取首个完整JSON对象

        :return: 解析成功返回 question_title 字段值，失败返回 None
        """
        if not result:
            return None
        text = result.strip()
        # 去除代码块标记
        if text.startswith("```"):
            text = text.split("\n", 1)[-1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        # 去除非JSON前缀文本（提取首个 { 到末尾 }）
        import re as _re
        match = _re.search(r'\{[\s\S]*\}', text)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        # Phase 12：优先 question_title，兼容回退 question
        question = (data.get("question_title") or data.get("question") or "").strip()
        if not question:
            return None
        return question

    @staticmethod
    def _deep_clean_question_field(question: str) -> str:
        """题干字段三层清洗（Phase 12 架构级根治）

        执行三层清洗：
        1. 正则删除：删除所有以「请、请问、请你、请结合、请针对、请描述」开头的完整句子
        2. 语义过滤：删除所有引导作答、承接上下文的衔接句
        3. 去重校验：清洗后多题目仅保留第一道

        :param question: 从JSON中提取的 question_title 字段值
        :return: 清洗后的纯题干
        """
        if not question:
            return question
        import re as _re
        # === 第一层：正则删除引导词开头的完整句子 ===
        # 句子定义：以。！？!?.；;或换行结尾
        # 删除整句：以「请、请问、请你、请结合、请针对、请描述、请说明」开头
        # 但「请说明Vue3原理？」是合法题干 → 仅删除包含明确引导动词的句子
        guide_prefix_patterns = [
            r'请结合[^。！？!?.；;\n]*[。！？!?.；;\n]?',
            r'请针对[^。！？!?.；;\n]*[。！？!?.；;\n]?',
            r'请回答[^。！？!?.；;\n]*[。！？!?.；;\n]?',
            r'请作答[^。！？!?.；;\n]*[。！？!?.；;\n]?',
            r'请简要回答[^。！？!?.；;\n]*[。！？!?.；;\n]?',
            r'请详细回答[^。！？!?.；;\n]*[。！？!?.；;\n]?',
            r'请你[^。！？!?.；;\n]*[。！？!?.；;\n]?',
            r'请问[^。！？!?.；;\n]*[。！？!?.；;\n]?',
        ]
        cleaned = question
        for pat in guide_prefix_patterns:
            cleaned = _re.sub(pat, '', cleaned)

        # === 第二层：语义过滤（按行删除引导语/过渡话术/全局结束话术） ===
        cleaned_lines = []
        for line in cleaned.split("\n"):
            line_stripped = line.strip()
            if not line_stripped:
                continue
            # 删除过渡话术行
            if any(pat in line_stripped for pat in STAGE_TRANSITION_PATTERNS):
                continue
            # 删除引导语行（含 GUIDE_PHRASE_PATTERNS 整句模式）
            if any(pat in line_stripped for pat in GUIDE_PHRASE_PATTERNS):
                continue
            # 删除全局结束话术行
            if any(pat in line_stripped for pat in GLOBAL_END_PATTERNS):
                continue
            # 删除点评类话术行（题干中严禁出现点评）
            if any(pat in line_stripped for pat in REVIEW_PATTERNS):
                continue
            # 删除纯衔接句（如"好的，那我们来看下一题"、"以下是题目"等）
            transition_keywords = [
                "好的，", "以下是", "下面是", "题目如下", "题目是",
                "我们来看", "我们看下", "我们聊", "我们开始",
                "那么", "接下来", "下一步",
            ]
            if any(line_stripped.startswith(kw) for kw in transition_keywords):
                continue
            cleaned_lines.append(line)
        cleaned = "\n".join(cleaned_lines).strip()

        # === 第三层：去重校验（多题目仅保留第一道） ===
        question_marks = _re.findall(r"[？?]", cleaned)
        if len(question_marks) > 1:
            first_q_idx = cleaned.find("？") if "？" in cleaned else cleaned.find("?")
            if first_q_idx >= 0:
                end_idx = min(len(cleaned), first_q_idx + 21)
                next_newline = cleaned.find("\n", first_q_idx)
                if 0 < next_newline < end_idx:
                    end_idx = next_newline
                cleaned = cleaned[:end_idx].strip()

        # 清洗后为空则返回中性占位（非引导语，避免与后端模板叠加）
        if not cleaned:
            cleaned = "（请基于上述问题给出你的回答）"
        return cleaned

    async def _generate_review_report(
        self, target_position: str, section_scores: dict,
        total_score: float, question_records: list,
        resume_summary: str, jd_summary: str,
    ) -> str:
        """生成复盘报告"""
        prompt = self._build_review_report_prompt(
            target_position, section_scores, total_score,
            question_records, resume_summary, jd_summary
        )
        try:
            return await self._llm_complete(prompt, "请生成复盘报告")
        except Exception as e:
            logging.getLogger(__name__).error(
                "复盘报告生成失败: %s", e, exc_info=True
            )
            return "复盘报告生成中，请稍后重试。"

    def _find_current_question(self, records: list, stage: str, q_index: int) -> str:
        """找到当前阶段当前序号的题目"""
        stage_questions = [r for r in records if r.get("stage") == stage and not r.get("skipped")]
        if q_index < len(stage_questions):
            return stage_questions[q_index].get("question", "")
        # 兜底：取最近一条该阶段的题目
        for rec in reversed(records):
            if rec.get("stage") == stage and rec.get("question"):
                return rec.get("question", "")
        return ""

    def _record_answer(
        self, records: list, question: str, answer: str,
        review: str, score: int, skipped: bool,
        stage: str = "",
    ):
        """记录问答到 question_records

        匹配优先级：
        1. 同 stage + 同 question 文本 + 未作答 → 更新
        2. 任意未作答记录 + 同 question 文本 → 更新
        3. 新增记录（带 stage 字段）
        """
        # 1. 优先按 stage + question 精确匹配
        if stage:
            for rec in reversed(records):
                if (rec.get("stage") == stage
                        and rec.get("question") == question
                        and not rec.get("answer")):
                    rec["answer"] = answer
                    rec["review"] = review
                    rec["score"] = score
                    rec["skipped"] = skipped
                    return
        # 2. 按 question 文本匹配（兼容旧数据）
        for rec in reversed(records):
            if rec.get("question") == question and not rec.get("answer"):
                rec["answer"] = answer
                rec["review"] = review
                rec["score"] = score
                rec["skipped"] = skipped
                return
        # 3. 新增记录
        records.append({
            "stage": stage or "",
            "question": question,
            "answer": answer,
            "review": review,
            "score": score,
            "skipped": skipped,
        })

    def _merge_follow_up_answer(
        self, records: list, stage: str, question: str,
        follow_up_answer: str, follow_up_review: str, follow_up_score: int,
    ):
        """追问回答合并到原题记录（不新增记录，避免 _find_current_question 返回重复题）

        合并策略：
        1. 找到 stage + question 对应的原题记录
        2. 将追问回答追加到 answer 字段（用分隔符标注「追问回答」）
        3. review 字段追加追问点评
        4. score 取原题分与追问分的较高值（追问是对原题的深挖，取较高分更合理）
        """
        for rec in reversed(records):
            if (rec.get("stage") == stage
                    and rec.get("question") == question):
                # 追加追问回答（不覆盖原回答）
                orig_answer = rec.get("answer", "")
                rec["answer"] = (
                    f"{orig_answer}\n\n[追问回答] {follow_up_answer}"
                    if orig_answer else f"[追问回答] {follow_up_answer}"
                )
                # 追加追问点评
                orig_review = rec.get("review", "")
                rec["review"] = (
                    f"{orig_review}\n\n[追问点评] {follow_up_review}"
                    if orig_review else f"[追问点评] {follow_up_review}"
                )
                # 评分取较高值（追问深挖表现好则提升原题分）
                orig_score = rec.get("score", 0)
                rec["score"] = max(orig_score, follow_up_score)
                # 标记已追问
                rec["has_follow_up"] = True
                rec["follow_up_score"] = follow_up_score
                return
        # 未找到原题记录（异常情况）→ 新增一条记录
        logging.getLogger(__name__).warning(
            "追问合并未找到原题记录 | stage=%s question=%s → 新增记录",
            stage, question[:50]
        )
        records.append({
            "stage": stage,
            "question": question,
            "answer": f"[追问回答] {follow_up_answer}",
            "review": f"[追问点评] {follow_up_review}",
            "score": follow_up_score,
            "skipped": False,
            "has_follow_up": True,
        })

    @staticmethod
    def _calc_final_scores(
        question_records: list, stage_scores: dict
    ) -> tuple:
        """基于 question_records 实际作答情况计算各环节评分与综合总分

        Phase 13 修复：解决综合评分无法有效计算的问题
        - 旧逻辑：直接对 stage_scores 取均分，存在追问重复评分、跳过题默认70分等失真问题
        - 新逻辑：以 question_records 为准，按 stage 分组计算实际作答题目的均分

        评分规则：
        1. 跳过/未作答的题目：计 0 分（反映实际未作答情况，不默认给 70 分）
        2. 正常作答的题目：取 question_records 中的 score（已合并追问评分取较高值）
        3. 阶段均分 = 该阶段所有题目的评分之和 / 该阶段应有的题目数（QUESTION_BANK_CONFIG.count）
           - 分母用「应有题数」而非「实际作答题数」，跳过题拉低均分更合理
        4. 综合总分 = Σ(阶段均分 × 阶段权重)
        5. 若整场面试无任何作答记录，总分返回 0

        :return: (section_scores dict, total_score float)
        """
        # 按 stage 分组收集 question_records 中的评分
        stage_actual_scores = {}  # {stage: [score1, score2, ...]}
        for rec in question_records:
            stage = rec.get("stage", "")
            if not stage or stage in ("init", "end"):
                continue
            skipped = rec.get("skipped", False)
            answer = rec.get("answer", "").strip()
            # 跳过或未作答的题目计 0 分
            if skipped or not answer:
                stage_actual_scores.setdefault(stage, []).append(0)
            else:
                score = rec.get("score", 0)
                # 评分范围校验：0-100
                try:
                    score = max(0, min(100, int(score)))
                except (TypeError, ValueError):
                    score = 0
                stage_actual_scores.setdefault(stage, []).append(score)

        # 计算各阶段均分（分母用 QUESTION_BANK_CONFIG 中的应有题数）
        section_scores = {}
        for stage, weight in STAGE_WEIGHTS.items():
            expected_count = QUESTION_BANK_CONFIG.get(stage, {}).get("count", 1)
            actual_scores = stage_actual_scores.get(stage, [])
            if not actual_scores:
                # 该阶段无任何记录 → 0 分
                section_scores[stage] = 0
                continue
            # 分母用 expected_count（跳过题拉低均分）
            # 但若实际题数 > expected_count（异常情况），用实际题数
            denom = max(expected_count, len(actual_scores))
            # 分子：所有题目评分之和（跳过题为0）
            total = sum(actual_scores)
            section_scores[stage] = round(total / denom, 1)

        # 加权总分
        total = 0.0
        for stage, weight in STAGE_WEIGHTS.items():
            total += section_scores.get(stage, 0) * weight
        total_score = round(total, 1)

        # 日志记录评分明细，便于排查
        logging.getLogger(__name__).info(
            "综合评分计算完成 | section_scores=%s | total_score=%.1f | stage_actual=%s",
            section_scores, total_score,
            {k: v for k, v in stage_actual_scores.items()}
        )

        return section_scores, total_score

    @staticmethod
    def _get_next_stage(current: str) -> str:
        """获取下一阶段"""
        try:
            idx = STAGE_FLOW.index(current)
            if idx + 1 < len(STAGE_FLOW):
                return STAGE_FLOW[idx + 1]
        except ValueError:
            pass
        return "end"

    async def reset_session(self, session_id: str) -> dict:
        """重置面试会话：清空历史、进度、题目计数、上下文记忆

        - 清空 Redis 中该会话的全部对话历史
        - 重置面试阶段为初始状态
        - 清零题目计数、答题进度、已出题记录
        - 清空上一轮面试的全部上下文记忆
        - 重置后生成全新的面试题目，绝不复用上一会话的出题内容
        """
        if not self.redis:
            return {"success": False, "error": "Redis 未配置"}

        try:
            import time

            # 1. 删除 Redis 会话数据
            SESSION_PREFIX = "interview_session"
            await self.redis.delete(f"{SESSION_PREFIX}:{session_id}")

            # 2. 同时清理可能存在的其他关联 key
            # 尝试删除多种可能的 key 格式
            for prefix in ["interview", "session", "chat"]:
                try:
                    await self.redis.delete(f"{prefix}:{session_id}")
                except Exception:
                    pass

            # 3. 返回重置成功状态
            return {
                "success": True,
                "session_id": session_id,
                "message": "会话已重置，可开始新面试",
                "reset_time": int(time.time()),
                # 显式标注结束锁已清除，防止重置后仍被锁定
                "ended_cleared": True,
            }
        except Exception as e:
            logging.getLogger(__name__).error(f"重置会话失败: {e}", exc_info=True)
            return {"success": False, "error": "会话重置失败，请稍后重试"}

    def _meta_json(
        self, current_stage: str, next_stage: str, text: str,
        session_finished: bool = False, note: str = "",
        question_index: int = 0, **extra,
    ) -> str:
        """构造 META 控制信号（含全局进度信息，供前端进度条渲染）

        进度计算规则（严格对齐题号、进度条、阶段状态三者）：
        - 阶段切换场景（current_stage != next_stage）：current_stage 已答满，
          global_progress = STAGE_START_INDEX[next_stage] + question_index（通常为0）
          = 下一阶段起始题号 = 已完成阶段题数总和
        - 阶段内推进场景（current_stage == next_stage）：
          global_progress = STAGE_START_INDEX[current_stage] + question_index
          = 当前阶段起始题号 + 阶段内题号
        - end 阶段：global_progress = TOTAL_QUESTIONS = 10（100%）
        """
        config = QUESTION_BANK_CONFIG.get(next_stage, QUESTION_BANK_CONFIG.get(current_stage, {}))
        stage_total = config.get("count", 0)

        # 计算全局进度（基于阶段起始题号，杜绝进度错位）
        if next_stage == "end":
            global_completed = TOTAL_QUESTIONS
        elif next_stage != current_stage:
            # 阶段切换：当前阶段已答满，进度 = 下一阶段起始题号
            global_completed = STAGE_START_INDEX.get(next_stage, 0) + question_index
        else:
            # 阶段内推进：进度 = 当前阶段起始题号 + 阶段内题号
            global_completed = STAGE_START_INDEX.get(current_stage, 0) + question_index

        # 计数越界校验：避免计数溢出导致进度异常
        global_completed = max(0, min(global_completed, TOTAL_QUESTIONS))

        # question_index 用于前端显示 Q{index+1}/10，需限制在 0-9 范围
        #（end 状态时 global_completed=10，但显示应为 Q10/10 而非 Q11/10）
        display_question_index = min(global_completed, TOTAL_QUESTIONS - 1)

        meta = {
            "current_stage": current_stage,
            "next_stage": next_stage,
            "interviewer_say": text,
            "is_question": "?" in text or "？" in text,
            # question_index 使用全局题号(0-9)，解决阶段切换时前端显示 Q1/10 的问题
            # 内部 session_ctx 仍使用 stage-local，仅 META 输出转为 global
            "question_index": display_question_index,
            "stage_question_index": question_index,
            "stage_total": stage_total,
            "total_questions": TOTAL_QUESTIONS,
            "global_progress": global_completed,
            "global_progress_pct": round(global_completed / TOTAL_QUESTIONS * 100, 1) if TOTAL_QUESTIONS else 0,
            "need_follow_up": False,
            "session_finished": session_finished,
            "stage_note": note,
        }
        meta.update(extra)
        return "\n\n__META__" + json.dumps(meta, ensure_ascii=False)
