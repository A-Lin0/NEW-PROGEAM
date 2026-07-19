"""
知识库管理服务 (RAG)

负责：
- 文档导入与向量化
- 知识库查询
- 文档管理
"""

import os
from pathlib import Path
from typing import Optional

from ..config import settings


class RAGService:
    """知识库管理服务"""

    def __init__(self, vector_store=None, embedder=None):
        self.vector_store = vector_store
        self.embedder = embedder

    async def import_documents(
        self, directory: str, file_types: tuple = (".txt", ".md", ".pdf")
    ) -> dict:
        """从目录批量导入文档到知识库"""
        from agent.knowledge.vector_store import Document

        path = Path(directory)
        if not path.exists():
            return {"status": "error", "message": f"目录不存在: {directory}"}

        files = []
        for ext in file_types:
            files.extend(path.rglob(f"*{ext}"))

        imported = 0
        errors = []

        for file_path in files:
            try:
                content = self._read_file(file_path)
                if not content.strip():
                    continue

                # 生成文档 ID
                doc_id = str(hash(str(file_path)))

                # 向量化
                embedding = None
                if self.embedder:
                    embedding = await self.embedder.embed_documents([content])
                    embedding = embedding[0] if embedding else None

                # 创建文档
                doc = Document(
                    id=doc_id,
                    content=content,
                    metadata={
                        "source": str(file_path),
                        "filename": file_path.name,
                        "type": file_path.suffix[1:],
                    },
                    embedding=embedding,
                )

                # 存入向量库
                if self.vector_store:
                    await self.vector_store.add_documents([doc])

                imported += 1
            except Exception as e:
                errors.append({"file": str(file_path), "error": str(e)})

        return {
            "status": "success",
            "imported": imported,
            "total": len(files),
            "errors": errors,
        }

    async def search(self, query: str, top_k: int = 5) -> list[dict]:
        """知识库搜索"""
        if not self.embedder or not self.vector_store:
            return []
        query_embedding = await self.embedder.embed_query(query)
        return await self.vector_store.search(query_embedding, top_k=top_k)

    async def get_stats(self) -> dict:
        """获取知识库统计"""
        doc_count = 0
        if self.vector_store:
            doc_count = self.vector_store.count()
        return {
            "document_count": doc_count,
            "store_type": settings.VECTOR_STORE_TYPE,
        }

    def _read_file(self, file_path: Path) -> str:
        """读取文件内容"""
        suffix = file_path.suffix.lower()
        if suffix in (".txt", ".md"):
            return file_path.read_text(encoding="utf-8")
        elif suffix == ".pdf":
            try:
                import PyPDF2
                with open(file_path, "rb") as f:
                    reader = PyPDF2.PdfReader(f)
                    return "\n".join(
                        page.extract_text() or "" for page in reader.pages
                    )
            except ImportError:
                return f"[需要 PyPDF2 库来读取 PDF: {file_path.name}]"
        return ""
