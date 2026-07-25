"""验证复盘模块修复效果"""
import asyncio
import json
import os
os.environ['PYTHONIOENCODING'] = 'utf-8'
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, '/')
from agent.core.review_agent import ReviewAgent, LLM_TIMEOUT_SECONDS, LLM_MAX_RETRIES


async def test_fallback_report():
    """测试兜底报告生成"""
    agent = ReviewAgent(api_key="")  # 无 LLM，走兜底

    question_records = [
        {"stage": "self_intro", "question": "请介绍一下自己", "answer": "", "score": 0, "skipped": True},
        {"stage": "tech_qa", "question": "核心技术", "answer": "我熟悉Python", "score": 70, "skipped": False},
        {"stage": "tech_qa", "question": "技术趋势", "answer": "", "score": 0, "skipped": True},
    ]
    section_scores = {"self_intro": 0, "tech_qa": 23.3, "star_qa": 0, "project_qa": 0, "reverse_qa": 0}
    total_score = 7.0

    print("=" * 70)
    print("测试1: 兜底报告生成（无LLM）")
    print("=" * 70)
    report = agent._build_fallback_report(
        question_records, section_scores, total_score,
        "测试兜底", error=True
    )
    print(f"total_score: {report['total_score']}")
    print(f"section_scores: {report['section_scores']}")
    print(f"stage_analysis 数量: {len(report['stage_analysis'])}")
    print(f"question_by_question 数量: {len(report['question_by_question'])}")
    print(f"overall_problems: {report['overall_problems']}")
    print(f"improvement_plan: {report['improvement_plan']}")
    print(f"overall_comment: {report['overall_comment']}")

    checks = []
    checks.append(("total_score > 0", report['total_score'] > 0))
    checks.append(("section_scores 有5个阶段", len(report['section_scores']) == 5))
    checks.append(("stage_analysis 有5个阶段", len(report['stage_analysis']) == 5))
    checks.append(("question_by_question 有3题", len(report['question_by_question']) == 3))
    checks.append(("overall_problems 非空", len(report['overall_problems']) > 0))
    checks.append(("improvement_plan 有内容", len(report['improvement_plan']['short_term']) > 0))
    checks.append(("overall_comment 非空", bool(report['overall_comment'])))

    for name, result in checks:
        print(f"  {'PASS' if result else 'FAIL'}: {name}")


async def test_stream_with_meta():
    """测试 stream 方法发送 META 信号"""
    agent = ReviewAgent(api_key="")  # 无 LLM

    payload = {
        "interview_history": [],
        "question_records": [
            {"stage": "self_intro", "question": "介绍", "answer": "", "score": 0, "skipped": True},
        ],
        "section_scores": {"self_intro": 0, "tech_qa": 0, "star_qa": 0, "project_qa": 0, "reverse_qa": 0},
        "total_score": 0,
        "target_position": "测试岗位",
    }

    print()
    print("=" * 70)
    print("测试2: stream 方法发送 META 信号")
    print("=" * 70)
    chunks = []
    async for chunk in agent.stream(payload):
        chunks.append(chunk)

    has_meta = any("__META__" in c for c in chunks)
    has_done = any("[DONE]" in c for c in chunks)
    has_review_status = any("review_status" in c for c in chunks)

    print(f"chunks 数量: {len(chunks)}")
    print(f"包含 META 信号: {has_meta}")
    print(f"包含 [DONE]: {has_done}")
    print(f"包含 review_status: {has_review_status}")

    for name, result in [
        ("META 信号已发送", has_meta),
        ("[DONE] 已发送", has_done),
        ("review_status 已发送", has_review_status),
    ]:
        print(f"  {'PASS' if result else 'FAIL'}: {name}")


async def test_recalculate_scores():
    """测试评分重算"""
    print()
    print("=" * 70)
    print("测试3: 评分重算（跳过题计0分）")
    print("=" * 70)
    question_records = [
        {"stage": "self_intro", "question": "介绍", "answer": "我是张三", "score": 80, "skipped": False},
        {"stage": "tech_qa", "question": "技术1", "answer": "Python", "score": 70, "skipped": False},
        {"stage": "tech_qa", "question": "技术2", "answer": "", "score": 0, "skipped": True},
        {"stage": "tech_qa", "question": "技术3", "answer": "", "score": 0, "skipped": True},
    ]
    section_scores, total_score = ReviewAgent._recalculate_scores(question_records)
    print(f"section_scores: {section_scores}")
    print(f"total_score: {total_score}")

    checks = [
        ("self_intro 得分合理", section_scores['self_intro'] == 80.0),
        ("tech_qa 得分合理（70/3≈23.3）", 20 <= section_scores['tech_qa'] <= 25),
        ("total_score 合理（0.1*80+0.3*23.3≈15）", 10 <= total_score <= 20),
        ("所有阶段都有得分", len(section_scores) == 5),
    ]
    for name, result in checks:
        print(f"  {'PASS' if result else 'FAIL'}: {name}")


async def test_constants():
    """测试常量配置"""
    print()
    print("=" * 70)
    print("测试4: 常量配置")
    print("=" * 70)
    print(f"LLM_TIMEOUT_SECONDS: {LLM_TIMEOUT_SECONDS}")
    print(f"LLM_MAX_RETRIES: {LLM_MAX_RETRIES}")
    checks = [
        ("超时时间=60秒", LLM_TIMEOUT_SECONDS == 60),
        ("重试次数=2次", LLM_MAX_RETRIES == 2),
    ]
    for name, result in checks:
        print(f"  {'PASS' if result else 'FAIL'}: {name}")


async def main():
    await test_fallback_report()
    await test_stream_with_meta()
    await test_recalculate_scores()
    await test_constants()

asyncio.run(main())
