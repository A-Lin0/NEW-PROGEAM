# agent/core/retriever_agent.py
"""
信息检索 Agent

职责：基于本地向量知识库 + 公司结构化数据库，对用户求职类查询进行精准检索与结构化输出。
严格边界：绝不编造数据，所有结果必须有来源支撑；检索为空时如实告知。

支持双模式：
- keyword（关键词结构化查询）：保留原有所有逻辑，按 retrieve_type 分类输出结构化列表
- qa（自然语言语义问答）：向量召回 top-3 知识片段 → LLM 生成答案 → 结构化输出

输入 payload（由任务规划 Agent 透传）:
    query            : str  必填 用户原始查询
    query_type       : str  选填 keyword（默认）/ qa
    retrieve_type    : str  选填 company_info / interview_exp / salary_query / industry_analysis / mixed
    company_name     : str  选填 目标公司名称
    company_id       : str  选填 目标公司 ID（限定公司上下文问答）
    target_position  : str  选填 目标岗位
    top_k            : int  选填 默认5
    db_session       : AsyncSession  选填 结构化数据库会话（由后端注入）
    vector_store     : VectorStore    选填 向量库实例
    embedder         : EmbeddingModel 选填 嵌入模型实例

输出（非流式，直接 yield 单个 JSON 字符串）:

keyword 模式输出：
{
  "retrieve_type": "...",
  "has_result": bool,
  "summary": "...",
  "company_basic": {...},
  "detail_items": [...],
  "faq_list": [...],
  "empty_reason": "..."
}

qa 模式输出：
{
  "retrieve_type": "company_qa",
  "has_result": bool,
  "answer": "通顺的自然语言回答文本",
  "related_companies": [{"company_id": "...", "company_name": "...", "industry": "..."}],
  "detail_items": [...]  (保留兼容字段),
  "empty_reason": "..."
}
"""

import json
import logging
import os
import re
from typing import Optional, Any

from agent.knowledge.embeddings import EmbeddingModel
from agent.knowledge.vector_store import VectorStore, Document


# ---- 公司基础信息 JSON 兜底数据源（前端同源 companies.json） ----
# 优先级：DB 查询 > companies.json 兜底
_COMPANIES_JSON_CANDIDATES = [
    # 容器内：docker-compose 挂载的 companies.json
    "/app/data/companies.json",
    # 容器内：前端构建产物（若存在）
    "/app/frontend/pc-admin/public/data/companies.json",
    # 本地开发：项目根目录 frontend
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "frontend", "pc-admin", "public", "data", "companies.json"),
    # 本地开发：backend 同级根目录
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "companies.json"),
]


def _load_companies_json() -> list:
    """加载 companies.json 公司基础信息（兜底数据源）"""
    for path in _COMPANIES_JSON_CANDIDATES:
        try:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list) and data:
                        logging.getLogger(__name__).info(
                            "加载 companies.json 成功: %s, %d 家公司", path, len(data)
                        )
                        return data
        except Exception as e:
            logging.getLogger(__name__).warning("加载 companies.json 失败 %s: %s", path, e)
    return []


def _find_company_in_json(companies: list, company_id: str = "", company_name: str = "") -> Optional[dict]:
    """从 companies.json 列表中按 id 或 name 查找公司"""
    if not companies:
        return None
    # 按 id 精确匹配
    if company_id:
        for c in companies:
            if str(c.get("id", "")) == str(company_id):
                return c
    # 按名称精确/包含匹配
    if company_name:
        for c in companies:
            cname = c.get("name", "")
            if cname == company_name or company_name in cname:
                return c
    return None


# ---- 检索类型枚举 ----
TYPE_COMPANY_INFO = "company_info"
TYPE_INTERVIEW_EXP = "interview_exp"
TYPE_SALARY_QUERY = "salary_query"
TYPE_INDUSTRY_ANALYSIS = "industry_analysis"
TYPE_MIXED = "mixed"
TYPE_COMPANY_QA = "company_qa"

VALID_TYPES = {
    TYPE_COMPANY_INFO, TYPE_INTERVIEW_EXP, TYPE_SALARY_QUERY,
    TYPE_INDUSTRY_ANALYSIS, TYPE_MIXED, TYPE_COMPANY_QA,
}

# ---- 查询类型枚举 ----
QUERY_TYPE_KEYWORD = "keyword"
QUERY_TYPE_QA = "qa"

# ---- 已知公司名列表（用于从 query 中提取公司名） ----
KNOWN_COMPANY_NAMES = [
    "字节跳动", "阿里巴巴", "腾讯", "百度", "美团", "京东", "网易", "华为",
    "小米", "拼多多", "快手", "滴滴", "小红书", "哔哩哔哩", "B站",
    "蚂蚁集团", "蚂蚁金服", "携程", "大疆", "商汤", "旷视", "依图",
    "蔚来", "理想", "小鹏", "比亚迪", "宁德时代", "大华", "海康威视",
    "小红书", "知乎", "微博", "搜狐", "新浪", "360", "奇安信",
    "金山", "用友", "金蝶", "深信服", "中兴", "OPPO", "vivo",
    "荣耀", "联想", "IBM", "微软", "Google", "谷歌", "Apple", "苹果",
    "Amazon", "亚马逊", "Meta", "Facebook", "Netflix", "奈飞",
    "Shopee", "Grab", "Lazada", "Tokopedia",
    "SHEIN", "Temu", "Anker", "大疆创新",
]


class RetrieverAgent:
    """信息检索 Agent：结构化数据库 + 向量知识库 双路召回 + 语义问答"""

    def __init__(
        self,
        vector_store: Optional[VectorStore] = None,
        embedder: Optional[EmbeddingModel] = None,
        llm_api_key: Optional[str] = None,
        llm_base_url: Optional[str] = None,
        llm_model: str = "gpt-4o",
    ):
        self.store = vector_store or VectorStore()
        self.embedder = embedder or EmbeddingModel()
        self.llm_api_key = llm_api_key or os.getenv("LLM_API_KEY", "")
        self.llm_base_url = llm_base_url or os.getenv("LLM_BASE_URL", "")
        self.llm_model = llm_model
        self._llm_client = None

    async def _ensure_llm(self):
        """懒加载 LLM 客户端"""
        if self._llm_client is None and self.llm_api_key:
            try:
                from openai import AsyncOpenAI
                self._llm_client = AsyncOpenAI(
                    api_key=self.llm_api_key, base_url=self.llm_base_url
                )
            except ImportError:
                pass

    async def stream(self, payload: dict):
        """统一入口：yield 单个 JSON 字符串结果"""
        result = await self.retrieve(payload)
        yield json.dumps(result, ensure_ascii=False)

    async def retrieve(self, payload: dict) -> dict:
        """主检索流程：按 query_type 分发到 keyword 或 qa 模式"""
        query = (payload.get("query") or "").strip()
        query_type = payload.get("query_type", QUERY_TYPE_KEYWORD)
        retrieve_type = payload.get("retrieve_type", TYPE_MIXED)
        company_name = (payload.get("company_name") or "").strip()
        company_id = (payload.get("company_id") or "").strip()
        target_position = (payload.get("target_position") or "").strip()
        top_k = int(payload.get("top_k") or 5)
        db_session = payload.get("db_session")

        # 参数校验
        if not query:
            return self._empty_result(retrieve_type, "查询内容不能为空")

        # ---- qa 模式：自然语言语义问答 ----
        if query_type == QUERY_TYPE_QA:
            return await self._handle_qa_mode(
                query, company_name, company_id, top_k, db_session
            )

        # ---- keyword 模式：原有结构化查询（完全保留） ----
        if retrieve_type not in VALID_TYPES:
            return self._empty_result(TYPE_MIXED, f"不支持的检索类型: {retrieve_type}")

        # 双路召回
        db_info = await self._fetch_from_db(db_session, company_name, query) if db_session else None
        vector_docs = await self._fetch_from_vector(query, company_name, target_position, top_k)

        # 按 retrieve_type 整理输出
        if retrieve_type == TYPE_COMPANY_INFO:
            return self._format_company_info(company_name, db_info, vector_docs)
        elif retrieve_type == TYPE_INTERVIEW_EXP:
            return self._format_interview_exp(company_name, target_position, db_info, vector_docs)
        elif retrieve_type == TYPE_SALARY_QUERY:
            return self._format_salary(company_name, target_position, db_info, vector_docs)
        elif retrieve_type == TYPE_INDUSTRY_ANALYSIS:
            return self._format_industry(company_name, target_position, vector_docs)
        else:  # mixed
            return self._format_mixed(company_name, target_position, db_info, vector_docs)

    # ==================== 语义问答模式 ====================

    async def _handle_qa_mode(
        self,
        query: str,
        company_name: str,
        company_id: str,
        top_k: int,
        db_session,
    ) -> dict:
        """
        语义问答模式执行流程（三级兜底）：
        1. 向量召回 + DB查询 → LLM 生成精准回答（一级）
        2. 向量未命中但 DB 有公司信息 → 基于公司基础信息生成回答（二级）
        3. 完全无匹配 → 友好引导话术 + 推荐提问方向（三级）
        """
        # 0. 若未提供公司名，从 query 中智能提取
        if not company_name:
            extracted = self._extract_company_from_query(query)
            if extracted:
                company_name = extracted
                logging.getLogger(__name__).info("从query中提取公司名: %s", company_name)

        # 1. 向量召回 top-5 知识片段（增加召回条数）
        vector_docs = await self._fetch_from_vector_qa(query, company_name, company_id, top_k=5)

        # 2. 同时获取结构化数据库信息
        db_info = await self._fetch_from_db(db_session, company_name, query) if db_session else None

        # 3. 若指定了 company_id 但 db_info 为空，尝试用 company_id 查询
        if not db_info and company_id and db_session:
            db_info = await self._fetch_from_db_by_id(db_session, company_id)

        # 4. 收集关联公司信息
        related_companies = []
        if db_info:
            related_companies.append({
                "company_id": db_info.get("id", ""),
                "company_name": db_info.get("name", company_name),
                "industry": db_info.get("industry", ""),
                "scale": db_info.get("size", ""),
                "location": db_info.get("location", ""),
            })
        for doc in vector_docs:
            meta = doc.get("metadata", {}) or {}
            cid = meta.get("company_id", "")
            cname = meta.get("company_name", "")
            if cid and not any(c.get("company_id") == cid for c in related_companies):
                related_companies.append({
                    "company_id": cid,
                    "company_name": cname,
                    "industry": meta.get("industry", ""),
                })

        # ---- 一级兜底：知识库命中 → LLM 生成精准回答 ----
        if vector_docs:
            try:
                answer = await self._generate_answer_with_llm(query, vector_docs, db_info, company_name)
                # 组装 detail_items
                detail_items = self._build_detail_items(vector_docs, db_info)
                return {
                    "retrieve_type": TYPE_COMPANY_QA,
                    "has_result": True,
                    "answer": answer,
                    "related_companies": related_companies,
                    "detail_items": detail_items,
                    "empty_reason": "",
                }
            except Exception as e:
                logging.getLogger(__name__).warning("LLM生成答案失败，降级为模板回答: %s", e)
                answer = self._generate_answer_fallback(query, vector_docs, db_info, company_name)
                detail_items = self._build_detail_items(vector_docs, db_info)
                return {
                    "retrieve_type": TYPE_COMPANY_QA,
                    "has_result": True,
                    "answer": answer,
                    "related_companies": related_companies,
                    "detail_items": detail_items,
                    "empty_reason": "",
                }

        # ---- 二级兜底：向量未命中但 DB/基础信息有公司信息 → LLM 基于基础信息生成回答 ----
        if db_info:
            # 优先用 LLM 基于公司基础信息生成通顺回答
            try:
                answer = await self._generate_answer_with_llm(query, [], db_info, company_name)
                return {
                    "retrieve_type": TYPE_COMPANY_QA,
                    "has_result": True,
                    "answer": answer,
                    "related_companies": related_companies,
                    "detail_items": self._build_detail_items([], db_info),
                    "empty_reason": "",
                }
            except Exception as e:
                logging.getLogger(__name__).warning(
                    "二级兜底 LLM 生成失败，降级为模板回答: %s", e
                )
                answer = self._generate_db_fallback(query, db_info, company_name)
                return {
                    "retrieve_type": TYPE_COMPANY_QA,
                    "has_result": True,
                    "answer": answer,
                    "related_companies": related_companies,
                    "detail_items": self._build_detail_items([], db_info),
                    "empty_reason": "",
                }

        # ---- 三级兜底：完全无匹配 → 友好引导 + 推荐提问 ----
        return self._generate_friendly_empty(query, company_name, related_companies)

    @staticmethod
    def _extract_company_from_query(query: str) -> str:
        """从用户问题中智能提取公司名"""
        if not query:
            return ""
        # 按长度降序排列，优先匹配长名称（如"字节跳动"优先于"跳动"）
        sorted_names = sorted(KNOWN_COMPANY_NAMES, key=len, reverse=True)
        for name in sorted_names:
            if name in query:
                return name
        return ""

    async def _fetch_from_vector_qa(
        self, query: str, company_name: str, company_id: str, top_k: int
    ) -> list:
        """向量语义召回（QA 专用，支持公司范围过滤）"""
        # 构建增强查询
        search_query = query
        if company_name:
            search_query = f"{company_name} {query}"
        try:
            query_emb = await self.embedder.embed_query(search_query)
            # 若指定 company_id，则做元数据过滤
            filter_meta = None
            if company_id:
                filter_meta = {"company_id": company_id}
            docs = await self.store.search(query_emb, top_k=top_k, filter_meta=filter_meta)
            return docs or []
        except Exception:
            return []

    async def _generate_answer_with_llm(
        self,
        query: str,
        vector_docs: list,
        db_info: Optional[dict],
        company_name: str,
    ) -> str:
        """基于召回知识片段，调用 LLM 生成自然语言答案"""
        await self._ensure_llm()
        if not self._llm_client:
            raise RuntimeError("LLM 不可用")

        # 构建知识上下文
        context_parts = []
        if db_info:
            db_summary_parts = [f"【{db_info.get('name') or company_name}】"]
            if db_info.get("industry"):
                db_summary_parts.append(f"行业：{db_info['industry']}")
            if db_info.get("description"):
                db_summary_parts.append(f"业务：{db_info['description']}")
            if db_info.get("culture"):
                db_summary_parts.append(f"文化：{db_info['culture']}")
            if db_info.get("benefits"):
                db_summary_parts.append(f"福利：{db_info['benefits']}")
            if db_info.get("interview_process"):
                db_summary_parts.append(f"面试流程：{db_info['interview_process']}")
            if db_info.get("avg_salary"):
                db_summary_parts.append(f"平均薪资：{db_info['avg_salary']}")
            if db_info.get("avg_difficulty"):
                db_summary_parts.append(f"面试难度：{db_info['avg_difficulty']}")
            if db_info.get("size"):
                db_summary_parts.append(f"规模：{db_info['size']}")
            if db_info.get("location"):
                db_summary_parts.append(f"地点：{db_info['location']}")
            context_parts.append("；".join(db_summary_parts))

        for i, doc in enumerate(vector_docs):
            content = doc.get("content", "").strip()
            if content:
                context_parts.append(f"【参考片段{i+1}】{content}")

        knowledge = "\n\n".join(context_parts) if context_parts else "暂无相关数据"

        prompt = f"""你是一个求职辅助助手。请根据以下知识库信息，回答用户的问题。

用户问题：{query}

知识库参考信息：
{knowledge}

回答要求：
1. 基于知识库信息回答，不要编造数据
2. 如果知识库信息足以回答，请给出具体、详细的答案
3. 如果知识库信息不足以回答，请诚实说"根据现有资料无法确定"
4. 回答要通顺自然，控制在200字以内
5. 不要使用"根据知识库"等内部术语
6. 答案中不要提及"参考片段"等内部标识
7. 如果问及公司相关信息，务必先核实知识库中是否有该公司数据再回答"""

        try:
            response = await self._llm_client.chat.completions.create(
                model=self.llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=500,
            )
            return response.choices[0].message.content.strip()
        except Exception:
            raise

    def _generate_answer_fallback(
        self,
        query: str,
        vector_docs: list,
        db_info: Optional[dict],
        company_name: str,
    ) -> str:
        """降级模式：关键词匹配 + 模板化答案"""
        target = company_name or "该公司"
        msg = query.lower()

        # 按关键词匹配生成模板化答案
        if any(k in msg for k in ["加班", "工作强度", "累", "995", "996"]):
            if db_info and db_info.get("culture"):
                return f"根据现有信息，{target}的企业文化中提到：{db_info['culture']}。关于加班情况，建议结合具体部门和岗位进一步了解。"
            if vector_docs:
                return f"根据知识库资料，{target}的加班情况：{vector_docs[0].get('content', '')[:200]}"
            return f"关于{target}的加班情况，暂无详细资料，建议通过脉脉、知乎等社区了解真实员工反馈。"

        if any(k in msg for k in ["福利", "待遇", "薪资", "工资", "年薪"]):
            if db_info:
                parts = []
                if db_info.get("avg_salary"):
                    parts.append(f"平均薪资：{db_info['avg_salary']}")
                if db_info.get("benefits"):
                    parts.append(f"福利待遇：{db_info['benefits']}")
                if parts:
                    return f"{target}的待遇信息：{'；'.join(parts)}"
            if vector_docs:
                return f"关于{target}的薪资待遇：{vector_docs[0].get('content', '')[:200]}（信息来源于网络，仅供参考）"
            return f"暂无{target}的薪资待遇详细数据，建议通过招聘网站或社区了解。"

        if any(k in msg for k in ["面试", "面经", "难度", "难不难"]):
            if db_info:
                parts = []
                if db_info.get("interview_process"):
                    parts.append(f"面试流程：{db_info['interview_process']}")
                if db_info.get("avg_difficulty"):
                    parts.append(f"面试难度：{db_info['avg_difficulty']}")
                if parts:
                    return f"{target}的面试情况：{'；'.join(parts)}"
            if vector_docs:
                return f"关于{target}的面试经验：{vector_docs[0].get('content', '')[:200]}"
            return f"暂无{target}的面试经验资料，建议通过牛客网、面经社区等平台搜索。"

        if any(k in msg for k in ["文化", "氛围", "环境"]):
            if db_info and db_info.get("culture"):
                return f"{target}的企业文化：{db_info['culture']}"
            if vector_docs:
                return f"关于{target}的公司氛围：{vector_docs[0].get('content', '')[:200]}"
            return f"暂无{target}的企业文化详细资料。"

        # 通用降级：拼接知识片段
        if vector_docs:
            return f"关于「{query}」，根据现有资料：{vector_docs[0].get('content', '')[:300]}"
        if db_info and db_info.get("description"):
            return f"{target}：{db_info['description']}"
        return f"关于「{query}」，暂无相关资料可以回答，建议尝试更具体的查询。"

    @staticmethod
    def _empty_qa_result(query: str, company_name: str, related_companies: list) -> dict:
        """构造 QA 模式空结果"""
        target = company_name or "相关公司"
        return {
            "retrieve_type": TYPE_COMPANY_QA,
            "has_result": False,
            "answer": f"暂无关于「{query}」的相关资料，无法给出准确回答。",
            "related_companies": related_companies,
            "detail_items": [],
            "empty_reason": f"向量库与结构化数据库中均未找到{target}的相关信息",
        }

    # ==================== 三级兜底辅助方法 ====================

    async def _fetch_from_db_by_id(self, db_session, company_id: str) -> Optional[dict]:
        """按 company_id 精确查询公司信息（DB 优先 → companies.json 兜底）"""
        if not company_id:
            return None

        # 1. 先尝试 DB 查询（兼容容器内 app.* 与本地 backend.app.* 两种模块路径）
        if db_session:
            try:
                from sqlalchemy import select
                try:
                    from backend.app.models.company import Company
                except ImportError:
                    from app.models.company import Company

                stmt = select(Company).where(Company.id == company_id)
                result = await db_session.execute(stmt)
                company = result.scalar_one_or_none()
                if company:
                    return {
                        "id": str(company.id),
                        "name": company.name,
                        "industry": company.industry,
                        "size": company.size,
                        "location": company.location,
                        "description": company.description,
                        "culture": company.culture,
                        "benefits": company.benefits,
                        "website": company.website,
                        "interview_process": company.interview_process,
                        "avg_difficulty": company.avg_difficulty,
                        "avg_salary": company.avg_salary,
                    }
            except Exception as e:
                logging.getLogger(__name__).debug(
                    "DB 按 id 查询公司失败 (company_id=%s): %s", company_id, e
                )

        # 2. DB 未命中 → companies.json 兜底（支持 c001-c015 等前端短 ID）
        companies_json = _load_companies_json()
        c = _find_company_in_json(companies_json, company_id=company_id)
        if c:
            logging.getLogger(__name__).info(
                "companies.json 兜底命中: company_id=%s, name=%s", company_id, c.get("name")
            )
            return self._normalize_company_dict(c)
        return None

    @staticmethod
    def _normalize_company_dict(c: dict) -> dict:
        """将 companies.json 的公司 dict 规整为 db_info 同构 dict"""
        positions = c.get("positions") or []
        # 将岗位信息拼入 description，供 LLM 与兜底回答使用
        pos_text = ""
        if positions:
            pos_parts = []
            for p in positions[:6]:
                pos_parts.append(
                    f"{p.get('name','')}({p.get('department','')}, {p.get('salary','')})"
                )
            pos_text = "；招聘岗位：" + "、".join(pos_parts)
        return {
            "id": str(c.get("id", "")),
            "name": c.get("name", ""),
            "industry": c.get("industry", ""),
            "size": c.get("size", ""),
            "location": c.get("location", ""),
            "description": (c.get("description", "") or "") + pos_text,
            "culture": c.get("culture", ""),
            "benefits": c.get("benefits", ""),
            "website": c.get("website", ""),
            "interview_process": c.get("interview_process", ""),
            "avg_difficulty": c.get("avg_difficulty", ""),
            "avg_salary": "",
        }

    @staticmethod
    def _build_detail_items(vector_docs: list, db_info: Optional[dict]) -> list:
        """组装 detail_items（兼容原有字段）"""
        detail_items = []
        for doc in vector_docs:
            content = doc.get("content", "").strip()
            if content:
                detail_items.append({
                    "category": "知识库参考",
                    "content": content[:300],
                    "source": "向量知识库",
                    "reliability": "中",
                })
        if db_info:
            for field, category in [
                ("description", "业务介绍"),
                ("culture", "企业文化"),
                ("benefits", "福利待遇"),
                ("interview_process", "面试流程"),
            ]:
                if db_info.get(field):
                    detail_items.append({
                        "category": category,
                        "content": db_info[field],
                        "source": "结构化数据库",
                        "reliability": "高",
                    })
        return detail_items

    @staticmethod
    def _generate_db_fallback(query: str, db_info: dict, company_name: str) -> str:
        """二级兜底：基于公司基础信息生成针对性回答"""
        name = db_info.get("name") or company_name or "该公司"
        industry = db_info.get("industry") or ""
        size = db_info.get("size") or ""
        location = db_info.get("location") or ""
        description = db_info.get("description") or ""
        culture = db_info.get("culture") or ""
        benefits = db_info.get("benefits") or ""
        interview_process = db_info.get("interview_process") or ""
        avg_difficulty = db_info.get("avg_difficulty") or ""
        avg_salary = db_info.get("avg_salary") or ""

        msg = query.lower()

        # 按问题类型生成针对性回答
        if any(k in msg for k in ["面试", "面经", "难度", "流程", "难不难"]):
            parts = [f"关于{name}的面试信息："]
            if interview_process:
                parts.append(f"面试流程：{interview_process}")
            if avg_difficulty:
                parts.append(f"面试难度：{avg_difficulty}")
            if industry:
                parts.append(f"所属行业：{industry}，面试通常会考察行业相关知识。")
            if not interview_process and not avg_difficulty:
                parts.append(f"{name}是一家{industry}行业的公司，规模约{size}，位于{location}。建议通过牛客网、脉脉等平台了解更多面试经验。")
            return "；".join(parts)

        if any(k in msg for k in ["薪资", "待遇", "福利", "工资", "年薪"]):
            parts = [f"关于{name}的薪资待遇："]
            if avg_salary:
                parts.append(f"平均薪资：{avg_salary}")
            if benefits:
                parts.append(f"福利待遇：{benefits}")
            if not avg_salary and not benefits:
                parts.append(f"{name}是{industry}行业的公司，规模{size}。建议通过招聘网站查看具体岗位薪资范围。")
            return "；".join(parts)

        if any(k in msg for k in ["文化", "氛围", "环境", "怎么样"]):
            parts = [f"关于{name}："]
            if culture:
                parts.append(f"企业文化：{culture}")
            if description:
                parts.append(f"业务介绍：{description}")
            if industry:
                parts.append(f"所属行业：{industry}")
            if size:
                parts.append(f"公司规模：{size}")
            if location:
                parts.append(f"所在地：{location}")
            return "；".join(parts)

        # 通用回答：汇总公司基础信息
        parts = [f"关于{name}："]
        if industry:
            parts.append(f"所属行业：{industry}")
        if size:
            parts.append(f"公司规模：{size}")
        if location:
            parts.append(f"所在地：{location}")
        if description:
            parts.append(f"业务介绍：{description}")
        if culture:
            parts.append(f"企业文化：{culture}")
        if benefits:
            parts.append(f"福利待遇：{benefits}")
        if interview_process:
            parts.append(f"面试流程：{interview_process}")
        if not any([industry, size, location, description, culture, benefits, interview_process]):
            parts.append(f"建议通过官方渠道或招聘平台了解{name}的更多信息。")
        return "；".join(parts)

    @staticmethod
    def _generate_friendly_empty(query: str, company_name: str, related_companies: list) -> dict:
        """三级兜底：完全无匹配 → 友好引导话术 + 推荐提问方向"""
        target = company_name or "该公司"

        # 生成推荐提问
        suggestions = [
            f"{target}的面试流程是怎样的？",
            f"{target}的薪资待遇如何？",
            f"{target}的企业文化是什么？",
        ]

        answer = (
            f"关于「{query}」，我目前可以为您推荐以下更具针对性的提问方向，帮助您快速获取{target}的详细信息：\n\n"
        )
        for i, s in enumerate(suggestions, 1):
            answer += f"{i}. {s}\n"
        answer += "\n您也可以通过牛客网、脉脉、知乎等社区平台获取更多真实面经和公司评价。"

        return {
            "retrieve_type": TYPE_COMPANY_QA,
            "has_result": True,  # 有回答内容，不算空结果
            "answer": answer,
            "related_companies": related_companies,
            "detail_items": [],
            "empty_reason": "",
        }

    # ==================== 向量库数据同步方法 ====================

    async def sync_all_companies(self, companies_data: list[dict]) -> dict:
        """
        全量数据向量化写入
        :param companies_data: 公司数据列表，每条包含 company_id, name, industry, description 等字段
        :return: {"success": bool, "synced_count": int, "error": str}
        """
        try:
            documents = []
            for company in companies_data:
                company_id = str(company.get("company_id") or company.get("id", ""))
                if not company_id:
                    continue
                # 拼接公司文本用于向量化
                text_parts = []
                for field in ["name", "industry", "description", "culture", "benefits",
                               "interview_process", "location", "size"]:
                    val = company.get(field, "")
                    if val:
                        text_parts.append(f"{field}: {val}")
                content = "\n".join(text_parts)
                if not content.strip():
                    continue
                # 批量向量化
                doc = Document(
                    id=f"company_{company_id}",
                    content=content,
                    metadata={
                        "company_id": company_id,
                        "company_name": company.get("name", ""),
                        "industry": company.get("industry", ""),
                        "source": "structured",
                    },
                )
                documents.append(doc)

            if not documents:
                return {"success": True, "synced_count": 0, "error": ""}

            # 批量向量化
            contents = [d.content for d in documents]
            embeddings = await self.embedder.embed_documents(contents)
            for doc, emb in zip(documents, embeddings):
                doc.embedding = emb

            # 先清空旧数据再写入
            await self._clear_all_company_vectors()
            ids = await self.store.add_documents(documents)
            return {"success": True, "synced_count": len(ids), "error": ""}
        except Exception as e:
            return {"success": False, "synced_count": 0, "error": str(e)}

    async def sync_single_company(self, company: dict) -> dict:
        """
        单条公司数据新增/更新向量同步
        :param company: 公司数据 dict，必须包含 company_id 或 id
        :return: {"success": bool, "company_id": str, "error": str}
        """
        try:
            company_id = str(company.get("company_id") or company.get("id", ""))
            if not company_id:
                return {"success": False, "company_id": "", "error": "缺少 company_id"}

            # 拼接文本
            text_parts = []
            for field in ["name", "industry", "description", "culture", "benefits",
                           "interview_process", "location", "size"]:
                val = company.get(field, "")
                if val:
                    text_parts.append(f"{field}: {val}")
            content = "\n".join(text_parts)
            if not content.strip():
                return {"success": False, "company_id": company_id, "error": "无可向量化内容"}

            # 向量化
            embedding = await self.embedder.embed_query(content)

            doc = Document(
                id=f"company_{company_id}",
                content=content,
                embedding=embedding,
                metadata={
                    "company_id": company_id,
                    "company_name": company.get("name", ""),
                    "industry": company.get("industry", ""),
                    "source": "structured",
                },
            )

            # 先删除旧数据再写入（upsert 语义）
            await self.store.delete([f"company_{company_id}"])
            ids = await self.store.add_documents([doc])
            return {"success": True, "company_id": company_id, "error": ""}
        except Exception as e:
            return {"success": False, "company_id": company.get("id", ""), "error": str(e)}

    async def delete_single_company(self, company_id: str) -> dict:
        """
        删除单条公司向量数据
        :param company_id: 公司 ID
        :return: {"success": bool, "company_id": str, "error": str}
        """
        try:
            doc_id = f"company_{company_id}"
            await self.store.delete([doc_id])
            return {"success": True, "company_id": company_id, "error": ""}
        except Exception as e:
            return {"success": False, "company_id": company_id, "error": str(e)}

    async def _clear_all_company_vectors(self):
        """清空所有公司向量数据（内部方法）"""
        try:
            if self.store.store_type == "chroma" and self.store._store:
                collection = self.store._store.get_or_create_collection("documents")
                # 获取所有文档 ID 并删除
                all_ids = collection.get().get("ids", [])
                if all_ids:
                    collection.delete(ids=all_ids)
                    logging.getLogger(__name__).info("已清空 %d 条旧向量数据", len(all_ids))
        except Exception as e:
            logging.getLogger(__name__).warning("清空向量数据失败: %s", e)

    # ==================== 双路召回 ====================

    async def _fetch_from_db(self, db_session, company_name: str, query: str) -> Optional[dict]:
        """结构化数据库召回：按公司名精确/模糊匹配（DB 优先 → companies.json 兜底）"""
        if not company_name:
            return None

        # 1. 先尝试 DB 查询
        if db_session:
            try:
                from sqlalchemy import select
                try:
                    from backend.app.models.company import Company
                except ImportError:
                    from app.models.company import Company

                stmt = select(Company).where(Company.name.ilike(f"%{company_name}%")).limit(1)
                result = await db_session.execute(stmt)
                company = result.scalar_one_or_none()
                if company:
                    return {
                        "id": str(company.id),
                        "name": company.name,
                        "industry": company.industry,
                        "size": company.size,
                        "location": company.location,
                        "description": company.description,
                        "culture": company.culture,
                        "benefits": company.benefits,
                        "website": company.website,
                        "interview_process": company.interview_process,
                        "avg_difficulty": company.avg_difficulty,
                        "avg_salary": company.avg_salary,
                    }
            except Exception as e:
                logging.getLogger(__name__).debug(
                    "DB 按名称查询公司失败 (name=%s): %s", company_name, e
                )

        # 2. DB 未命中 → companies.json 按名称兜底
        companies_json = _load_companies_json()
        c = _find_company_in_json(companies_json, company_name=company_name)
        if c:
            logging.getLogger(__name__).info(
                "companies.json 兜底命中(按名称): name=%s", company_name
            )
            return self._normalize_company_dict(c)
        return None

    async def _fetch_from_vector(self, query: str, company_name: str,
                                  target_position: str, top_k: int) -> list:
        """向量知识库语义召回"""
        # 拼接增强查询：公司 + 岗位 + 原始query
        enhanced_query = " ".join(filter(None, [company_name, target_position, query]))
        try:
            query_emb = await self.embedder.embed_query(enhanced_query)
            docs = await self.store.search(query_emb, top_k=top_k)
            return docs or []
        except Exception:
            return []

    # ==================== 分场景格式化 ====================

    def _format_company_info(self, company_name, db_info: Optional[dict], vector_docs: list) -> dict:
        """公司信息查询输出"""
        detail_items = []
        company_basic = {"name": "", "industry": "", "scale": "", "location": ""}

        # 结构化数据库来源
        if db_info:
            company_basic = {
                "name": db_info.get("name") or company_name or "",
                "industry": db_info.get("industry") or "暂无公开数据",
                "scale": db_info.get("size") or "暂无公开数据",
                "location": db_info.get("location") or "暂无公开数据",
            }
            if db_info.get("description"):
                detail_items.append({
                    "category": "业务介绍",
                    "content": db_info["description"],
                    "source": "结构化数据库",
                    "reliability": "高",
                })
            if db_info.get("culture"):
                detail_items.append({
                    "category": "企业文化",
                    "content": db_info["culture"],
                    "source": "结构化数据库",
                    "reliability": "高",
                })
            if db_info.get("benefits"):
                detail_items.append({
                    "category": "福利待遇",
                    "content": db_info["benefits"],
                    "source": "结构化数据库",
                    "reliability": "高",
                })

        # 向量库来源（补充非结构化信息）
        for doc in vector_docs:
            content = doc.get("content", "").strip()
            if not content:
                continue
            detail_items.append({
                "category": "公司补充资料",
                "content": content,
                "source": "面经知识库" if "面试" in content or "面经" in content else "公开资料",
                "reliability": "中",
            })

        if not detail_items and not db_info:
            return self._empty_result(TYPE_COMPANY_INFO, f"暂无 {company_name or '该公司'} 的相关信息")

        summary = f"{company_basic['name'] or company_name}：{company_basic['industry']}，规模{company_basic['scale']}，总部{company_basic['location']}"
        return {
            "retrieve_type": TYPE_COMPANY_INFO,
            "has_result": True,
            "summary": summary,
            "company_basic": company_basic,
            "detail_items": detail_items,
            "faq_list": [],
            "empty_reason": "",
        }

    def _format_interview_exp(self, company_name, target_position, db_info: Optional[dict], vector_docs: list) -> dict:
        """面经检索输出"""
        detail_items = []
        company_basic = {"name": company_name or "", "industry": "", "scale": "", "location": ""}

        # 数据库中的面试流程
        if db_info:
            company_basic["name"] = db_info.get("name") or company_name
            company_basic["industry"] = db_info.get("industry") or ""
            if db_info.get("interview_process"):
                detail_items.append({
                    "category": "面试流程",
                    "content": db_info["interview_process"],
                    "source": "结构化数据库",
                    "reliability": "高",
                })

        # 向量库中的面经真题
        for doc in vector_docs:
            content = doc.get("content", "").strip()
            if not content:
                continue
            # 简单分类
            category = "面试真题"
            if "流程" in content or "轮次" in content:
                category = "面试流程"
            elif "经验" in content or "注意" in content:
                category = "面试经验"
            detail_items.append({
                "category": category,
                "content": content,
                "source": "面经知识库",
                "reliability": "中",
            })

        if not detail_items:
            pos = f"{target_position}岗位" if target_position else "该岗位"
            return self._empty_result(TYPE_INTERVIEW_EXP, f"暂无 {company_name or '该公司'} {pos} 的面经数据")

        summary = f"{company_name or '该公司'} {target_position or ''}面试：共召回{len(detail_items)}条面经资料"
        return {
            "retrieve_type": TYPE_INTERVIEW_EXP,
            "has_result": True,
            "summary": summary,
            "company_basic": company_basic,
            "detail_items": detail_items,
            "faq_list": [],
            "empty_reason": "",
        }

    def _format_salary(self, company_name, target_position, db_info: Optional[dict], vector_docs: list) -> dict:
        """薪资查询输出"""
        detail_items = []
        company_basic = {"name": company_name or "", "industry": "", "scale": "", "location": ""}

        # 数据库薪资字段
        if db_info:
            company_basic["name"] = db_info.get("name") or company_name
            if db_info.get("avg_salary"):
                detail_items.append({
                    "category": "薪资范围",
                    "content": f"平均薪资：{db_info['avg_salary']}",
                    "source": "结构化数据库",
                    "reliability": "高",
                })
            if db_info.get("benefits"):
                detail_items.append({
                    "category": "福利待遇",
                    "content": db_info["benefits"],
                    "source": "结构化数据库",
                    "reliability": "高",
                })

        # 向量库薪资数据
        for doc in vector_docs:
            content = doc.get("content", "").strip()
            if not content:
                continue
            detail_items.append({
                "category": "薪资补充资料",
                "content": content + "（信息来源于网络，仅供参考）",
                "source": "面经知识库",
                "reliability": "中",
            })

        if not detail_items:
            pos = f"{target_position}岗位" if target_position else "该岗位"
            return self._empty_result(TYPE_SALARY_QUERY, f"暂无 {company_name or '该公司'} {pos} 的薪资数据")

        summary = f"{company_name or '该公司'} {target_position or ''}薪资信息已召回（数据仅供参考）"
        return {
            "retrieve_type": TYPE_SALARY_QUERY,
            "has_result": True,
            "summary": summary,
            "company_basic": company_basic,
            "detail_items": detail_items,
            "faq_list": [],
            "empty_reason": "",
        }

    def _format_industry(self, company_name, target_position, vector_docs: list) -> dict:
        """行业与竞品分析输出"""
        detail_items = []
        for doc in vector_docs:
            content = doc.get("content", "").strip()
            if not content:
                continue
            detail_items.append({
                "category": "行业分析",
                "content": content,
                "source": "公开资料",
                "reliability": "中",
            })

        if not detail_items:
            return self._empty_result(TYPE_INDUSTRY_ANALYSIS, "暂无相关行业分析资料")

        return {
            "retrieve_type": TYPE_INDUSTRY_ANALYSIS,
            "has_result": True,
            "summary": f"已召回{len(detail_items)}条行业分析资料",
            "company_basic": {"name": company_name or "", "industry": "", "scale": "", "location": ""},
            "detail_items": detail_items,
            "faq_list": [],
            "empty_reason": "",
        }

    def _format_mixed(self, company_name, target_position, db_info: Optional[dict], vector_docs: list) -> dict:
        """混合检索：聚合公司信息 + 面经 + 薪资"""
        detail_items = []
        company_basic = {"name": company_name or "", "industry": "", "scale": "", "location": ""}

        if db_info:
            company_basic = {
                "name": db_info.get("name") or company_name or "",
                "industry": db_info.get("industry") or "",
                "scale": db_info.get("size") or "",
                "location": db_info.get("location") or "",
            }
            for field, category in [
                ("description", "业务介绍"),
                ("culture", "企业文化"),
                ("benefits", "福利待遇"),
                ("interview_process", "面试流程"),
            ]:
                if db_info.get(field):
                    detail_items.append({
                        "category": category,
                        "content": db_info[field],
                        "source": "结构化数据库",
                        "reliability": "高",
                    })

        for doc in vector_docs:
            content = doc.get("content", "").strip()
            if not content:
                continue
            detail_items.append({
                "category": "补充资料",
                "content": content,
                "source": "面经知识库",
                "reliability": "中",
            })

        if not detail_items:
            return self._empty_result(TYPE_MIXED, f"暂无 {company_name or '该主题'} 的相关资料")

        return {
            "retrieve_type": TYPE_MIXED,
            "has_result": True,
            "summary": f"已召回{len(detail_items)}条相关资料",
            "company_basic": company_basic,
            "detail_items": detail_items,
            "faq_list": [],
            "empty_reason": "",
        }

    # ==================== 工具方法 ====================

    @staticmethod
    def _empty_result(retrieve_type: str, reason: str) -> dict:
        """构造空结果响应"""
        return {
            "retrieve_type": retrieve_type,
            "has_result": False,
            "summary": "",
            "company_basic": {"name": "", "industry": "", "scale": "", "location": ""},
            "detail_items": [],
            "faq_list": [],
            "empty_reason": reason,
        }
