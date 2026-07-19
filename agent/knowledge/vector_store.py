"""
向量数据库接口

支持 FAISS / Chroma 两种后端：
- 文档入库（分块、向量化、存储）
- 相似性搜索
- 元数据过滤
"""

import os
import json
from typing import Optional
from dataclasses import dataclass, field


@dataclass
class Document:
    """文档对象"""
    id: str
    content: str
    metadata: dict = field(default_factory=dict)
    embedding: Optional[list[float]] = None


class VectorStore:
    """向量数据库抽象层"""

    def __init__(
        self,
        store_type: str = "chroma",
        persist_dir: str = "./data/chroma_db",
    ):
        self.store_type = store_type
        self.persist_dir = persist_dir
        self._store = None
        self._documents: list[Document] = []

    async def initialize(self):
        """初始化向量存储后端"""
        if self.store_type == "chroma":
            await self._init_chroma()
        elif self.store_type == "faiss":
            await self._init_faiss()
        else:
            await self._init_memory()

    async def _init_chroma(self):
        try:
            import chromadb
            from chromadb.config import Settings

            os.makedirs(self.persist_dir, exist_ok=True)
            self._store = chromadb.PersistentClient(
                path=self.persist_dir,
                settings=Settings(anonymized_telemetry=False),
            )
        except ImportError:
            self._store = None

    async def _init_faiss(self):
        try:
            import faiss
            import numpy as np
            self._faiss = faiss
            self._np = np
            self._index = None
        except ImportError:
            self._store = None

    async def _init_memory(self):
        """纯内存存储（降级方案）"""
        self._documents = []

    async def add_documents(self, documents: list[Document]) -> list[str]:
        """添加文档到向量库"""
        ids = []
        if self.store_type == "chroma" and self._store:
            ids = await self._add_to_chroma(documents)
        elif self.store_type == "faiss" and hasattr(self, "_faiss"):
            ids = await self._add_to_faiss(documents)
        else:
            for doc in documents:
                if not doc.id:
                    import uuid
                    doc.id = str(uuid.uuid4())
                self._documents.append(doc)
                ids.append(doc.id)
        return ids

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        filter_meta: Optional[dict] = None,
    ) -> list[dict]:
        """向量相似性搜索"""
        if self.store_type == "chroma" and self._store:
            return await self._search_chroma(query_embedding, top_k, filter_meta)
        elif self.store_type == "faiss" and hasattr(self, "_faiss"):
            return await self._search_faiss(query_embedding, top_k)
        else:
            return self._search_memory(query_embedding, top_k)

    async def delete(self, doc_ids: list[str]):
        """删除文档"""
        if self.store_type == "chroma" and self._store:
            try:
                collection = self._store.get_or_create_collection("documents")
                collection.delete(ids=doc_ids)
            except Exception:
                pass
        else:
            self._documents = [
                d for d in self._documents if d.id not in doc_ids
            ]

    def count(self) -> int:
        """返回文档总数"""
        if self.store_type == "chroma" and self._store:
            try:
                collection = self._store.get_or_create_collection("documents")
                return collection.count()
            except Exception:
                return 0
        return len(self._documents)

    # ---- Chroma 实现 ----
    async def _add_to_chroma(self, documents: list[Document]) -> list[str]:
        ids = []
        try:
            collection = self._store.get_or_create_collection("documents")
            for doc in documents:
                if not doc.id:
                    import uuid
                    doc.id = str(uuid.uuid4())
                # 确保 metadata 不含 None 值（Chroma 要求值为 str/int/float/bool）
                clean_meta = {}
                for k, v in (doc.metadata or {}).items():
                    if v is not None:
                        clean_meta[k] = str(v) if not isinstance(v, (str, int, float, bool)) else v
                collection.add(
                    ids=[doc.id],
                    embeddings=[doc.embedding] if doc.embedding else None,
                    documents=[doc.content],
                    metadatas=[clean_meta],
                )
                ids.append(doc.id)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Chroma add_documents 失败: %s", e)
        return ids

    async def _search_chroma(
        self, query_embedding, top_k: int, filter_meta=None
    ) -> list[dict]:
        try:
            collection = self._store.get_or_create_collection("documents")
            # 构建 Chroma where 过滤条件
            where_clause = None
            if filter_meta:
                # Chroma 的 where 语法：{"field": "value"} 或 {"$and": [...]}
                conditions = []
                for k, v in filter_meta.items():
                    if v is not None:
                        conditions.append({k: str(v)})
                if len(conditions) == 1:
                    where_clause = conditions[0]
                elif len(conditions) > 1:
                    where_clause = {"$and": conditions}

            query_kwargs = {
                "query_embeddings": [query_embedding],
                "n_results": top_k,
            }
            if where_clause:
                query_kwargs["where"] = where_clause

            results = collection.query(**query_kwargs)
            docs = []
            if results["ids"] and results["ids"][0]:
                for i, doc_id in enumerate(results["ids"][0]):
                    doc = {
                        "id": doc_id,
                        "content": results["documents"][0][i] if results["documents"] else "",
                        "score": results["distances"][0][i] if results.get("distances") else 0,
                    }
                    # 返回元数据（关键：前端需要 company_id 等字段做数据隔离）
                    if results.get("metadatas") and results["metadatas"][0]:
                        doc["metadata"] = results["metadatas"][0][i] or {}
                    else:
                        doc["metadata"] = {}
                    docs.append(doc)
            return docs
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Chroma search 失败: %s", e)
            return []

    # ---- FAISS 实现 ----
    async def _add_to_faiss(self, documents: list[Document]) -> list[str]:
        ids = []
        embeddings = []
        for doc in documents:
            if not doc.id:
                import uuid
                doc.id = str(uuid.uuid4())
            if doc.embedding:
                embeddings.append(doc.embedding)
                ids.append(doc.id)
                self._documents.append(doc)

        if embeddings:
            emb_array = self._np.array(embeddings, dtype="float32")
            if self._index is None:
                dim = emb_array.shape[1]
                self._index = self._faiss.IndexFlatIP(dim)
            self._index.add(emb_array)
        return ids

    async def _search_faiss(
        self, query_embedding, top_k: int
    ) -> list[dict]:
        if self._index is None:
            return []
        q = self._np.array([query_embedding], dtype="float32")
        scores, indices = self._index.search(q, top_k)
        docs = []
        for i, idx in enumerate(indices[0]):
            if idx >= 0 and idx < len(self._documents):
                doc = self._documents[idx]
                docs.append({
                    "id": doc.id,
                    "content": doc.content,
                    "score": float(scores[0][i]),
                    "metadata": doc.metadata,
                })
        return docs

    # ---- 内存实现 ----
    def _search_memory(self, query_embedding, top_k: int) -> list[dict]:
        results = []
        for doc in self._documents:
            if doc.embedding:
                sim = self._cosine_similarity(query_embedding, doc.embedding)
                results.append({
                    "id": doc.id,
                    "content": doc.content,
                    "score": sim,
                    "metadata": doc.metadata,
                })
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x ** 2 for x in a) ** 0.5
        norm_b = sum(y ** 2 for y in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
