"""
公司业务逻辑层

负责公司信息的 CRUD 与智能问答
"""

from typing import Optional, List, Dict
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from ..models.company import Company
from ..schemas.company import CompanyCreate, CompanyQuery


class CompanyService:
    """公司信息服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: CompanyCreate) -> Company:
        """创建公司信息"""
        company = Company(**data.model_dump())
        self.db.add(company)
        await self.db.flush()
        await self.db.refresh(company)
        return company

    async def get(self, company_id: UUID) -> Optional[Company]:
        """获取公司详情"""
        result = await self.db.execute(
            select(Company).where(Company.id == company_id)
        )
        return result.scalar_one_or_none()

    async def list(
        self, keyword: Optional[str] = None, skip: int = 0, limit: int = 20
    ) -> List[Company]:
        """搜索/列表公司"""
        if keyword:
            stmt = (
                select(Company)
                .where(
                    or_(
                        Company.name.ilike(f"%{keyword}%"),
                        Company.industry.ilike(f"%{keyword}%"),
                        Company.description.ilike(f"%{keyword}%"),
                    )
                )
                .offset(skip)
                .limit(limit)
            )
        else:
            stmt = select(Company).offset(skip).limit(limit)

        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update(self, company_id: UUID, data: CompanyCreate) -> Optional[Company]:
        """更新公司信息"""
        company = await self.get(company_id)
        if not company:
            return None
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(company, key, value)
        await self.db.flush()
        await self.db.refresh(company)
        return company

    async def delete(self, company_id: UUID) -> bool:
        """删除公司"""
        company = await self.get(company_id)
        if company:
            await self.db.delete(company)
            await self.db.flush()
            return True
        return False

    async def search_smart(
        self, query: str, retriever=None, top_k: int = 5
    ) -> List[Dict]:
        """
        智能搜索：结合数据库和向量检索
        :param retriever: RetrieverAgent 实例（已注入 vector_store + embedder）
        """
        # 1. 数据库关键词匹配
        db_results = await self.list(keyword=query, limit=top_k)
        results = []
        for company in db_results:
            results.append({
                "id": str(company.id),
                "name": company.name,
                "description": company.description,
                "industry": company.industry,
                "location": company.location,
                "source": "database",
                "score": None,
            })

        # 2. 向量相似度检索（如果有 retriever）
        if retriever:
            # 调用 RetrieverAgent 的向量召回能力
            vector_results = await retriever._fetch_from_vector(
                query=query, company_name=query, target_position="", top_k=top_k
            )
            for vr in vector_results:
                content = vr.get("content", "")
                if not any(r["name"] == content[:50] for r in results):
                    results.append({
                        "id": vr.get("id", ""),
                        "name": content[:100],
                        "description": content,
                        "source": "vector",
                        "score": vr.get("score"),
                    })

        return results[:top_k]
