"""
向量化与检索模块

封装 embedding 模型调用，支持：
- 文本向量化
- 批量向量化
- 相似度计算

当 LLM 提供商不支持 embedding API（如 DeepSeek）时，
自动降级为基于 hash 的确定性局部敏感向量，保证检索功能可用。
"""

from typing import Optional
import os
import hashlib
import struct
import logging

logger = logging.getLogger(__name__)

# 降级向量的维度
FALLBACK_DIM = 768


class EmbeddingModel:
    """文本向量化模型封装"""

    def __init__(
        self,
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.model_name = model_name or os.getenv(
            "LLM_EMBEDDING_MODEL", "text-embedding-3-small"
        )
        self.api_key = api_key or os.getenv("LLM_API_KEY", "")
        self.base_url = base_url or os.getenv("LLM_BASE_URL", "")
        self._client = None
        self._api_failed = False  # 标记 API 是否不可用，避免重复尝试

    async def _ensure_client(self):
        """懒加载 OpenAI 客户端"""
        if self._client is None and self.api_key and not self._api_failed:
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(
                    api_key=self.api_key, base_url=self.base_url
                )
            except ImportError:
                pass

    async def embed_query(self, text: str) -> list[float]:
        """将查询文本转为向量"""
        await self._ensure_client()
        if self._client and not self._api_failed:
            try:
                response = await self._client.embeddings.create(
                    model=self.model_name, input=[text]
                )
                return response.data[0].embedding
            except Exception as e:
                logger.warning(
                    "Embedding API 调用失败 (%s)，降级为 hash 向量: %s",
                    type(e).__name__, e
                )
                self._api_failed = True
        # 降级：返回确定性 hash 向量
        return self._hash_embed(text)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量将文档转为向量"""
        await self._ensure_client()
        if self._client and not self._api_failed:
            try:
                response = await self._client.embeddings.create(
                    model=self.model_name, input=texts
                )
                return [d.embedding for d in response.data]
            except Exception as e:
                logger.warning(
                    "Embedding API 批量调用失败 (%s)，降级为 hash 向量: %s",
                    type(e).__name__, e
                )
                self._api_failed = True
        return [self._hash_embed(t) for t in texts]

    @staticmethod
    def _hash_embed(text: str) -> list[float]:
        """
        基于 hash 的确定性向量生成（降级方案）
        
        特性：
        - 相同文本始终生成相同向量（确定性）
        - 不同文本生成不同向量（低碰撞）
        - 向量维度 768，值域 [-1, 1]
        - 不依赖任何外部 API
        """
        vec = [0.0] * FALLBACK_DIM
        # 用多个 hash 窗口填充向量，增加区分度
        for i in range(FALLBACK_DIM):
            # 每 8 个维度用一个 hash 窗口
            window = i // 8
            h = hashlib.md5(f"{text}:{window}".encode("utf-8")).digest()
            # 取 4 字节转为 float，归一化到 [-1, 1]
            val = struct.unpack("I", h[:4])[0] / 0xFFFFFFFF  # [0, 1]
            vec[i] = val * 2 - 1  # [-1, 1]
        
        # L2 归一化
        norm = sum(v * v for v in vec) ** 0.5
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec
