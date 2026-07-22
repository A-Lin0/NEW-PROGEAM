"""验证兜底题目去重修复"""
import asyncio
import os
os.environ['PYTHONIOENCODING'] = 'utf-8'
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, '/')
from agent.core.interview_agent import InterviewAgent

agent = InterviewAgent(vector_store=None, embedder=None, redis_client=None, db_session_factory=None, api_key="")

# 模拟已出过 tech_qa 第1题的 session_ctx
session_ctx = {
    "question_cache": {
        "asked_questions": [
            {"question": "请详细说明你在投资银行分析师岗位中最熟悉的一项核心技术/专业技能，并举例说明你是如何应用的？", "dimension": None, "stage": "tech_qa"},
        ],
        "asked_dimensions": [],
    }
}

print("=" * 70)
print("测试1: tech_qa 第2题兜底（已出过第1题，应返回不同题目）")
print("=" * 70)
q1 = InterviewAgent._get_stage_fallback_question("tech_qa", "投资银行分析师", 1, session_ctx)
print(f"返回: {q1}")
expected_old = "请详细说明你在投资银行分析师岗位中最熟悉的一项核心技术/专业技能"
if expected_old in q1:
    print(">>> FAIL: 返回了与第1题相同的兜底题目！")
else:
    print(">>> PASS: 返回了不同的兜底题目")

print()
print("=" * 70)
print("测试2: project_qa 第2题兜底（已出过第1题，应返回不同题目）")
print("=" * 70)
session_ctx2 = {
    "question_cache": {
        "asked_questions": [
            {"question": "请详细描述你经历过的最有代表性的一个项目，说明你在其中的角色、承担的职责、解决的关键问题以及最终的量化成果。", "dimension": None, "stage": "project_qa"},
        ],
        "asked_dimensions": [],
    }
}
q2 = InterviewAgent._get_stage_fallback_question("project_qa", "投资银行分析师", 1, session_ctx2)
print(f"返回: {q2}")
expected_old2 = "请详细描述你经历过的最有代表性的一个项目"
if expected_old2 in q2:
    print(">>> FAIL: 返回了与第1题相同的兜底题目！")
else:
    print(">>> PASS: 返回了不同的兜底题目")

print()
print("=" * 70)
print("测试3: tech_qa 第1题兜底（无已出题，应返回第1题）")
print("=" * 70)
q3 = InterviewAgent._get_stage_fallback_question("tech_qa", "投资银行分析师", 0, {})
print(f"返回: {q3}")
print(">>> PASS" if q3 else ">>> FAIL")

print()
print("=" * 70)
print("测试4: 连续3题兜底（模拟LLM全部失败的场景）")
print("=" * 70)
session_ctx4 = {"question_cache": {"asked_questions": [], "asked_dimensions": []}}
qs = []
for i in range(3):
    q = InterviewAgent._get_stage_fallback_question("tech_qa", "投资银行分析师", i, session_ctx4)
    qs.append(q)
    # 模拟记录到缓存
    session_ctx4["question_cache"]["asked_questions"].append({"question": q, "dimension": None, "stage": "tech_qa"})
    print(f"  第{i+1}题: {q[:60]}...")

# 检查是否有重复
unique_qs = set(qs)
if len(unique_qs) == 3:
    print(">>> PASS: 3题全部不同")
else:
    print(f">>> FAIL: 存在重复！唯一题目数: {len(unique_qs)}/3")

print()
print("=" * 70)
print("测试5: project_qa 连续3题兜底")
print("=" * 70)
session_ctx5 = {"question_cache": {"asked_questions": [], "asked_dimensions": []}}
qs5 = []
for i in range(3):
    q = InterviewAgent._get_stage_fallback_question("project_qa", "投资银行分析师", i, session_ctx5)
    qs5.append(q)
    session_ctx5["question_cache"]["asked_questions"].append({"question": q, "dimension": None, "stage": "project_qa"})
    print(f"  第{i+1}题: {q[:60]}...")

unique_qs5 = set(qs5)
if len(unique_qs5) == 3:
    print(">>> PASS: 3题全部不同")
else:
    print(f">>> FAIL: 存在重复！唯一题目数: {len(unique_qs5)}/3")
