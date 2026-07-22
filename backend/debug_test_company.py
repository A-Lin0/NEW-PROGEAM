"""Phase 14 修复验证：模拟面试启动流程，检查公司名是否正确传递到 LLM prompt"""
import asyncio
import json
import sys
import os
import logging

# 配置日志输出
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

sys.path.insert(0, '/')

from agent.core.interview_agent import InterviewAgent


async def test_company_binding():
    """测试公司名是否正确绑定到 prompt"""

    # 模拟 Redis 客户端（使用 dict 模拟）
    class FakeRedis:
        def __init__(self):
            self.data = {}
        async def get(self, key):
            return self.data.get(key)
        async def setex(self, key, ttl, val):
            self.data[key] = val
        async def delete(self, key):
            self.data.pop(key, None)

    fake_redis = FakeRedis()

    # 创建 InterviewAgent 实例（不依赖向量库和数据库）
    agent = InterviewAgent(
        vector_store=None,
        embedder=None,
        redis_client=fake_redis,
        db_session_factory=None,
        api_key="",  # 不使用 LLM
        base_url="",
    )

    session_id = "test-company-binding-001"

    # 模拟 /command 接口写入的 user_assets（用户选了比亚迪）
    session_ctx = {
        "user_assets": {
            "target_position": "Java后端工程师",
            "target_company": "比亚迪",
            "target_company_id": "",
        },
        "session_status": "new",
        "current_stage": "init",
        "history": [
            {"role": "user", "content": "开始面试"}
        ],
    }

    # 模拟 _save_session
    fake_redis.data[f"session:{session_id}"] = json.dumps(session_ctx)

    # 模拟 _build_params_for_intent 构造的 payload
    payload = {
        "session_id": session_id,
        "session_ctx": session_ctx,
        "user_input": "开始面试",
        "session_stage": "init",
        "target_position": "Java后端工程师",
        "company_name": session_ctx["user_assets"].get("target_company", ""),
        "company_id": session_ctx["user_assets"].get("target_company_id", ""),
        "interview_type": "tech_1",
        "difficulty": "middle",
        "resume_summary": "",
        "jd_summary": "",
        "dialogue_history": session_ctx.get("history", []),
        "command": "start",
        "question_index": 0,
        "question_records": [],
        "stage_scores": {},
    }

    print("=" * 80)
    print("测试：用户选择「比亚迪」公司发起面试")
    print(f"payload.company_name = {payload['company_name']!r}")
    print(f"session_ctx.user_assets.target_company = {session_ctx['user_assets']['target_company']!r}")
    print()

    # 测试 _build_question_prompt（直接调用，不经过 LLM）
    company_ctx = await agent._fetch_company_context(
        payload["company_name"], payload["company_id"]
    )
    print(f"_fetch_company_context 返回:")
    print(f"  company_name = {company_ctx.get('company_name')!r}")
    print(f"  has_company = {company_ctx.get('has_company')!r}")
    print()

    position_ctx = agent._classify_position("Java后端工程师")

    prompt = agent._build_question_prompt(
        "Java后端工程师", "middle", "self_intro", 0, 1,
        is_first=True, company_ctx=company_ctx, position_ctx=position_ctx
    )

    print("=" * 80)
    print("生成的 prompt 内容（前500字符）：")
    print(prompt[:500])
    print()

    print("=" * 80)
    print("验证结果：")
    checks = [
        ("prompt 包含「比亚迪」", "比亚迪" in prompt),
        ("prompt 不包含「宝洁」", "宝洁" not in prompt or "绝对禁止出现宝洁" in prompt),
        ("prompt 包含面试官人设绑定", "你是「比亚迪」的资深面试官" in prompt),
        ("prompt 包含开场白强绑定", "明确提及公司名「比亚迪」" in prompt),
        ("prompt 包含公司一致性约束", "公司一致性绝对约束" in prompt),
        ("prompt 包含禁止其他公司", "绝对禁止出现以下公司名称" in prompt),
    ]
    all_pass = True
    for desc, result in checks:
        status = "✓ PASS" if result else "✗ FAIL"
        if not result:
            all_pass = False
        print(f"  {status} - {desc}")

    print()
    if all_pass:
        print(">>> 所有验证通过！公司名「比亚迪」已正确绑定到 prompt")
    else:
        print(">>> 部分验证失败！请检查上述 FAIL 项")


asyncio.run(test_company_binding())
