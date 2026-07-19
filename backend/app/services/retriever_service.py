"""
RAG 检索服务层

：
- 全量/单条公司数据向量化同步
- 单条向量数据删除
- 调用 RetrieverAgent 执行语义问答
"""

import json
import logging
from typing import Optional, Dict, Any, List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..models.company import Company
from ..config import settings

logger = logging.getLogger(__name__)


class RetrieverService:
    """RAG 检索业务服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ============================================================
    # 语义问答
    # ============================================================

    async def qa_answer(
        self,
        query: str,
        vector_store,
        db_session: AsyncSession,
        company_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        语义问答：调用 RetrieverAgent 执行自然语言检索
        """
        from agent.core.retriever_agent import RetrieverAgent
        from agent.knowledge.embeddings import EmbeddingModel

        try:
            embedder = EmbeddingModel()
            agent = RetrieverAgent(vector_store=vector_store, embedder=embedder)

            payload = {
                "query": query,
                "retrieve_type": "mixed",
                "company_name": None,
                "target_position": None,
                "top_k": 5,
                "db_session": db_session,
            }

            if company_id:
                company = await self.db.get(Company, UUID(company_id))
                if company:
                    payload["company_name"] = company.name

            result = await agent.retrieve(payload)

            # 提取关联公司
            related_companies = []
            if result.get("company_basic", {}).get("name"):
                related_companies.append({
                    "id": result.get("company_basic", {}).get("id", ""),
                    "name": result["company_basic"]["name"],
                    "industry": result["company_basic"].get("industry", ""),
                    "location": result["company_basic"].get("location", ""),
                    "avg_difficulty": result["company_basic"].get("avg_difficulty", 0.0),
                    "relevance": "直接匹配",
                })

            return {
                "code": 0,
                "message": "",
                "data": {
                    "answer": result.get("summary", ""),
                    "related_companies": related_companies,
                    "detail_items": result.get("detail_items", []),
                    "has_result": result.get("has_result", True),
                },
            }
        except Exception as e:
            logger.error(f"语义问答失败: {e}", exc_info=True)
            return {
                "code": 500,
                "message": f"问答服务异常: {str(e)}",
                "data": {
                    "answer": "",
                    "related_companies": [],
                    "has_result": False,
                },
            }

    # ============================================================
    # 向量库同步
    # ============================================================

    async def vector_init_all(self, vector_store, embedder) -> Dict[str, Any]:
        """
        全量初始化：读取所有公司数据，批量向量化写入向量库
        """
        try:
            result = await self.db.execute(select(Company))
            companies = list(result.scalars().all())

            if not companies:
                return {"code": 0, "message": "数据库中没有公司数据", "data": {"synced": 0}}

            from agent.knowledge.vector_store import Document

            synced = 0
            errors = []
            documents = []

            for company in companies:
                try:
                    text = self._company_to_text(company)
                    if not text.strip():
                        continue

                    embedding = None
                    if embedder:
                        embedding = await embedder.embed_documents([text])
                        embedding = embedding[0] if embedding else None

                    doc = Document(
                        id=str(company.id),
                        content=text,
                        metadata={
                            "source": "company_db",
                            "company_id": str(company.id),
                            "company_name": company.name,
                        },
                        embedding=embedding,
                    )
                    documents.append(doc)
                except Exception as e:
                    errors.append({"company": company.name, "error": str(e)})

            if documents and vector_store:
                await vector_store.add_documents(documents)
                synced = len(documents)

            logger.info(f"向量库全量初始化完成: {synced}/{len(companies)} 条")
            return {
                "code": 0,
                "message": f"全量同步完成: {synced}/{len(companies)} 条",
                "data": {"synced": synced, "total": len(companies), "errors": errors},
            }
        except Exception as e:
            logger.error(f"向量库全量初始化失败: {e}", exc_info=True)
            return {"code": 500, "message": f"初始化失败: {str(e)}", "data": {"synced": 0}}

    async def vector_sync_one(
        self, company_id: str, vector_store, embedder
    ) -> Dict[str, Any]:
        """
        单条公司数据同步到向量库
        """
        try:
            company = await self.db.get(Company, UUID(company_id))
            if not company:
                return {"code": 404, "message": "公司不存在", "data": None}

            text = self._company_to_text(company)
            if not text.strip():
                return {"code": 0, "message": "公司数据为空，跳过同步", "data": None}

            from agent.knowledge.vector_store import Document

            embedding = None
            if embedder:
                embedding = await embedder.embed_documents([text])
                embedding = embedding[0] if embedding else None

            doc = Document(
                id=str(company.id),
                content=text,
                metadata={
                    "source": "company_db",
                    "company_id": str(company.id),
                    "company_name": company.name,
                },
                embedding=embedding,
            )

            if vector_store:
                await vector_store.add_documents([doc])

            logger.info(f"向量同步完成: {company.name} ({company.id})")
            return {
                "code": 0,
                "message": f"已同步: {company.name}",
                "data": {"company_id": str(company.id), "company_name": company.name},
            }
        except Exception as e:
            logger.error(f"向量同步失败: {e}", exc_info=True)
            return {"code": 500, "message": f"同步失败: {str(e)}", "data": None}

    async def vector_delete_one(self, company_id: str, vector_store) -> Dict[str, Any]:
        """
        删除单条向量数据
        """
        try:
            if vector_store:
                await vector_store.delete([company_id])

            logger.info(f"向量删除完成: {company_id}")
            return {
                "code": 0,
                "message": f"已删除向量数据: {company_id}",
                "data": {"company_id": company_id},
            }
        except Exception as e:
            logger.error(f"向量删除失败: {e}", exc_info=True)
            return {"code": 500, "message": f"删除失败: {str(e)}", "data": None}

    # ============================================================
    # 辅助方法
    # ============================================================

    @staticmethod
    def _company_to_text(company: Company) -> str:
        """将公司对象转换为向量化文本"""
        parts = []
        if company.name:
            parts.append(f"公司名称: {company.name}")
        if company.industry:
            parts.append(f"行业: {company.industry}")
        if company.size:
            parts.append(f"规模: {company.size}")
        if company.location:
            parts.append(f"地点: {company.location}")
        if company.description:
            parts.append(f"业务描述: {company.description}")
        if company.culture:
            parts.append(f"企业文化: {company.culture}")
        if company.benefits:
            parts.append(f"福利待遇: {company.benefits}")
        if company.interview_process:
            parts.append(f"面试流程: {company.interview_process}")
        if company.avg_salary:
            parts.append(f"平均薪资: {company.avg_salary}")
        return "\n".join(parts)