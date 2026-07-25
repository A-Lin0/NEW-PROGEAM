"""验证 RAG 智能问答修复效果"""
import asyncio
import os
os.environ['PYTHONIOENCODING'] = 'utf-8'
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, '/')
from agent.core.retriever_agent import RetrieverAgent

# 模拟向量库文档（包含字段名裸露的旧数据）
class FakeDoc:
    def __init__(self, content, metadata=None):
        self.content = content
        self.metadata = metadata or {}


class FakeVectorStore:
    async def search(self, query_emb, top_k=1, filter_meta=None):
        # 模拟旧数据：字段名裸露
        return [
            FakeDoc(
                content="name: 字节跳动\nindustry: 互联网\ndescription: 字节跳动是一家科技公司\ninterview_process: 笔试+技术面+HR面",
                metadata={"company_id": "c001", "company_name": "字节跳动", "industry": "互联网"}
            )
        ]


class FakeEmbedder:
    async def embed_query(self, text):
        return [0.1] * 10


async def test():
    # 测试无 LLM 场景（降级模板）
    agent = RetrieverAgent(
        vector_store=FakeVectorStore(),
        embedder=FakeEmbedder(),
        llm_api_key="",  # 无 LLM，走降级
    )

    db_info = {
        "id": "c001",
        "name": "字节跳动",
        "industry": "互联网",
        "size": "10000+",
        "location": "北京",
        "description": "字节跳动是一家全球化的科技公司",
        "culture": "务实敢为",
        "benefits": "免费三餐",
        "interview_process": "笔试+技术面+HR面",
        "avg_difficulty": "中等偏上",
        "avg_salary": "30K",
    }

    print("=" * 70)
    print("场景1: 提问「字节跳动面试流程是怎样的」（仅输出面试相关）")
    print("=" * 70)
    answer1 = agent._generate_db_fallback("字节跳动面试流程是怎样的", db_info, "字节跳动")
    print(f"回答: {answer1}")
    has_field = any(f in answer1 for f in ["name:", "industry:", "description:", "interview_process:"])
    print(f">>> {'FAIL' if has_field else 'PASS'}: {'存在字段名裸露' if has_field else '无字段名裸露'}")

    print()
    print("=" * 70)
    print("场景2: 输入「你好」问候语（友好回应，不堆砌全量信息）")
    print("=" * 70)
    answer2 = agent._generate_db_fallback("你好", db_info, "字节跳动")
    print(f"回答: {answer2}")
    is_short = len(answer2) < 80
    no_pile = "笔试" not in answer2 and "免费三餐" not in answer2
    print(f">>> {'PASS' if is_short and no_pile else 'FAIL'}: 简短且不堆砌全量信息")

    print()
    print("=" * 70)
    print("场景3: 提问偏门问题「字节跳动的股票代码」（兜底正常）")
    print("=" * 70)
    answer3 = agent._generate_db_fallback("字节跳动的股票代码", db_info, "字节跳动")
    print(f"回答: {answer3}")
    has_field = any(f in answer3 for f in ["name:", "industry:", "description:"])
    print(f">>> {'FAIL' if has_field else 'PASS'}: {'存在字段名裸露' if has_field else '无字段名裸露'}")

    print()
    print("=" * 70)
    print("场景4: _clean_raw_fields 清洗字段名测试")
    print("=" * 70)
    dirty = "name: 字节跳动\nindustry: 互联网\n根据【参考片段1】显示 description: 科技公司"
    cleaned = RetrieverAgent._clean_raw_fields(dirty)
    print(f"原始: {dirty}")
    print(f"清洗后: {cleaned}")
    has_field = any(f in cleaned for f in ["name:", "industry:", "description:", "【参考"])
    print(f">>> {'FAIL' if has_field else 'PASS'}: {'仍存在字段名' if has_field else '字段名已清除'}")

    print()
    print("=" * 70)
    print("场景5: _is_greeting 问候识别测试")
    print("=" * 70)
    greetings = ["你好", "您好", "hi", "在吗", "你是谁", "你能做什么"]
    non_greetings = ["字节跳动面试流程", "腾讯薪资怎么样", "阿里巴巴文化"]
    for g in greetings:
        result = RetrieverAgent._is_greeting(g)
        print(f"  '{g}' → {result} {'PASS' if result else 'FAIL'}")
    for g in non_greetings:
        result = RetrieverAgent._is_greeting(g)
        print(f"  '{g}' → {result} {'PASS' if not result else 'FAIL'}")

    print()
    print("=" * 70)
    print("场景6: _build_detail_items 使用中文类别名")
    print("=" * 70)
    docs = [FakeDoc(content="name: 腾讯\nindustry: 互联网")]
    items = RetrieverAgent._build_detail_items(docs, db_info)
    for item in items:
        print(f"  category={item['category']} | content={item['content'][:50]}")
    has_english_field = any("name:" in item["content"] or "industry:" in item["content"] for item in items)
    print(f">>> {'FAIL' if has_english_field else 'PASS'}: detail_items {'仍含字段名' if has_english_field else '已使用中文类别名'}")


asyncio.run(test())
