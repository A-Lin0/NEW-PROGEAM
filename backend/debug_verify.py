"""验证 _fetch_company_context 修复：向量库返回错误公司名时不应覆盖传入公司名"""
import asyncio
import json
import os
os.environ['PYTHONIOENCODING'] = 'utf-8'
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, '/')
from agent.core.interview_agent import InterviewAgent


class FakeVectorStore:
    """模拟向量库：查询华为时返回腾讯的文档（模拟 bug 场景）"""
    async def search(self, query_emb, top_k=1, filter_meta=None):
        return [{
            "content": "description: 腾讯社交平台\nculture: 用户为本\nculture: 瑞雪",
            "metadata": {
                "company_name": "腾讯",
                "company_id": "tencent-001",
                "industry": "互联网",
            }
        }]


class FakeEmbedder:
    async def embed_query(self, text):
        return [0.1] * 10


async def test():
    agent = InterviewAgent(
        vector_store=FakeVectorStore(),
        embedder=FakeEmbedder(),
        redis_client=None,
        db_session_factory=None,
        api_key="",
    )

    print("=" * 70)
    print("测试场景：用户选择「华为」，但向量库返回「腾讯」文档")
    print("=" * 70)
    ctx = await agent._fetch_company_context("华为", "")
    print(f"传入公司名: 华为")
    print(f"返回 company_name: {ctx['company_name']!r}")
    print(f"返回 has_company: {ctx['has_company']}")
    print()

    if ctx['company_name'] == '华为' and ctx['has_company'] == False:
        print(">>> PASS: 向量库返回错误公司名时，保持传入公司名不变，has_company=False")
    elif ctx['company_name'] == '腾讯':
        print(">>> FAIL: 严重错误！向量库返回的腾讯覆盖了传入的华为！")
    else:
        print(f">>> 未知结果: company_name={ctx['company_name']}")

    print()
    print("=" * 70)
    print("测试场景：用户选择「腾讯」，向量库返回「腾讯」文档（正常匹配）")
    print("=" * 70)
    ctx2 = await agent._fetch_company_context("腾讯", "")
    print(f"传入公司名: 腾讯")
    print(f"返回 company_name: {ctx2['company_name']!r}")
    print(f"返回 has_company: {ctx2['has_company']}")
    if ctx2['company_name'] == '腾讯' and ctx2['has_company'] == True:
        print(">>> PASS: 公司名匹配时正常使用向量库数据")
    else:
        print(f">>> FAIL: company_name={ctx2['company_name']}, has_company={ctx2['has_company']}")

    print()
    print("=" * 70)
    print("测试场景：无向量库和数据库时，保持传入公司名")
    print("=" * 70)
    agent2 = InterviewAgent(vector_store=None, embedder=None, redis_client=None, db_session_factory=None, api_key="")
    ctx3 = await agent2._fetch_company_context("比亚迪", "")
    print(f"传入公司名: 比亚迪")
    print(f"返回 company_name: {ctx3['company_name']!r}")
    print(f"返回 has_company: {ctx3['has_company']}")
    if ctx3['company_name'] == '比亚迪' and ctx3['has_company'] == False:
        print(">>> PASS: 无数据源时保持传入公司名，has_company=False")
    else:
        print(f">>> FAIL: company_name={ctx3['company_name']}")


asyncio.run(test())
