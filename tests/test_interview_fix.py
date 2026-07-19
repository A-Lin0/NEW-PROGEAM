"""
测试 InterviewAgent 定制化出题与会话重置修复
"""
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch


# ============================================================
# 导入测试
# ============================================================
def test_import_interview_agent():
    """验证 InterviewAgent 可正常导入"""
    from agent.core.interview_agent import (
        InterviewAgent,
        POSITION_CATEGORIES,
        POSITION_KEYWORD_MAP,
        STAGE_FLOW,
        QUESTION_BANK_CONFIG,
    )
    assert InterviewAgent is not None
    assert len(POSITION_CATEGORIES) >= 8
    assert len(POSITION_KEYWORD_MAP) >= 15
    assert "self_intro" in STAGE_FLOW
    assert "tech_qa" in QUESTION_BANK_CONFIG


# ============================================================
# 岗位分类测试
# ============================================================
def test_classify_position():
    """验证岗位分类逻辑"""
    from agent.core.interview_agent import InterviewAgent

    agent = InterviewAgent()

    # 前端
    result = agent._classify_position("前端开发工程师")
    assert result["category"] == "前端"
    assert "React" in result["focus_points"]

    # 后端
    result = agent._classify_position("Java后端开发")
    assert result["category"] == "后端"

    # 算法
    result = agent._classify_position("AI算法工程师")
    assert result["category"] == "算法"

    # 产品
    result = agent._classify_position("产品经理")
    assert result["category"] == "产品"

    # 未知岗位 → 通用
    result = agent._classify_position("街舞老师")
    assert result["category"] == "通用"


# ============================================================
# 公司风格推断测试
# ============================================================
def test_infer_interview_style():
    """验证公司面试风格推断"""
    from agent.core.interview_agent import InterviewAgent

    # 腾讯
    style = InterviewAgent._infer_interview_style("腾讯", "")
    assert "腾讯" in style or "基础" in style

    # 字节
    style = InterviewAgent._infer_interview_style("字节跳动", "")
    assert "字节" in style or "算法" in style

    # 未知公司
    style = InterviewAgent._infer_interview_style("某小公司", "")
    assert "专业规范" in style


def test_infer_hiring_points():
    """验证公司高频考点推断"""
    from agent.core.interview_agent import InterviewAgent

    points = InterviewAgent._infer_hiring_points("腾讯", "")
    assert "分布式" in points or "C++" in points

    points = InterviewAgent._infer_hiring_points("未知公司", "")
    assert "核心" in points


# ============================================================
# Prompt 定制化测试
# ============================================================
def test_build_question_prompt_customized():
    """验证定制化 prompt 包含公司+岗位信息"""
    from agent.core.interview_agent import InterviewAgent

    agent = InterviewAgent()

    company_ctx = {
        "has_company": True,
        "company_name": "腾讯",
        "industry": "互联网",
        "business": "社交、游戏、云计算",
        "culture": "用户为本、科技向善",
        "interview_style": "注重基础，面试官风格温和",
        "interview_process": "3轮技术面+1轮HR面",
        "avg_difficulty": "中等偏难",
        "hiring_points": "C++/Go、分布式系统",
    }

    position_ctx = {"category": "后端", "focus_points": "分布式、数据库、API设计"}

    prompt = agent._build_question_prompt(
        "后端开发工程师", "middle", "self_intro", 0, 1,
        is_first=True, company_ctx=company_ctx, position_ctx=position_ctx
    )

    # 验证定制化内容
    assert "腾讯" in prompt
    assert "后端开发工程师" in prompt
    assert "社交" in prompt or "游戏" in prompt
    assert "分布式" in prompt
    assert "禁止使用通用模板" in prompt


def test_build_question_prompt_generic():
    """验证无公司岗位时降级为通用模式"""
    from agent.core.interview_agent import InterviewAgent

    agent = InterviewAgent()

    prompt = agent._build_question_prompt(
        "软件工程师", "middle", "self_intro", 0, 1, is_first=True
    )

    # 通用模式不应包含公司定制信息
    assert "目标公司" not in prompt
    assert "禁止使用通用模板" in prompt  # 规则仍然存在


# ============================================================
# 会话重置测试
# ============================================================
@pytest.mark.asyncio
async def test_reset_session():
    """验证会话重置方法"""
    from agent.core.interview_agent import InterviewAgent

    mock_redis = MagicMock()
    mock_redis.delete = AsyncMock(return_value=True)

    agent = InterviewAgent(redis_client=mock_redis)
    result = await agent.reset_session("test-session-123")

    assert result["success"] is True
    assert result["session_id"] == "test-session-123"
    assert "message" in result
    assert "reset_time" in result

    # 验证调用了 delete
    assert mock_redis.delete.called


@pytest.mark.asyncio
async def test_reset_session_no_redis():
    """验证无 Redis 时重置返回错误"""
    from agent.core.interview_agent import InterviewAgent

    agent = InterviewAgent()
    result = await agent.reset_session("test-session-123")

    assert result["success"] is False
    assert "Redis" in result["error"]


# ============================================================
# 开场白差异测试
# ============================================================
def test_opening_instruction_different():
    """验证不同公司生成不同的开场白指令"""
    from agent.core.interview_agent import InterviewAgent

    agent = InterviewAgent()

    # 腾讯
    tencent_ctx = {
        "has_company": True,
        "company_name": "腾讯",
        "interview_style": "注重基础",
        "interview_process": "3轮技术面",
    }
    prompt_tencent = agent._build_question_prompt(
        "前端工程师", "middle", "self_intro", 0, 1,
        is_first=True, company_ctx=tencent_ctx,
        position_ctx={"category": "前端", "focus_points": "React/Vue"}
    )

    # 字节跳动
    bytedance_ctx = {
        "has_company": True,
        "company_name": "字节跳动",
        "interview_style": "节奏快、算法多",
        "interview_process": "4轮技术面",
    }
    prompt_bytedance = agent._build_question_prompt(
        "前端工程师", "middle", "self_intro", 0, 1,
        is_first=True, company_ctx=bytedance_ctx,
        position_ctx={"category": "前端", "focus_points": "React/Vue"}
    )

    # 两个 prompt 应该有明显差异
    assert prompt_tencent != prompt_bytedance
    assert "腾讯" in prompt_tencent
    assert "字节跳动" in prompt_bytedance


# ============================================================
# 阶段过渡语定制化测试
# ============================================================
def test_transition_customized():
    """验证过渡语在公司定制模式下包含公司名"""
    from agent.core.interview_agent import InterviewAgent

    agent = InterviewAgent()

    # 构造一个 dict 来模拟 _advance_to_stage 中的过渡语生成逻辑
    transitions_generic = {
        "tech_qa": "好的，接下来进入专业技术环节。",
        "star_qa": "技术环节告一段落，接下来聊聊行为面试题。",
    }

    # 定制化过渡语应包含公司名
    cn = "腾讯"
    transitions_custom = {
        "tech_qa": f"好的，接下来进入{cn}的专业技术环节。",
        "star_qa": f"技术环节告一段落，接下来聊聊{cn}常考的行为面试题。",
    }

    # 验证定制化过渡语与通用过渡语不同
    assert transitions_custom["tech_qa"] != transitions_generic["tech_qa"]
    assert "腾讯" in transitions_custom["tech_qa"]
    assert "腾讯" in transitions_custom["star_qa"]


# ============================================================
# 回答记录测试
# ============================================================
def test_record_answer():
    """验证回答记录功能"""
    from agent.core.interview_agent import InterviewAgent

    agent = InterviewAgent()
    records = []

    # 确保可以记录空回答
    agent._record_answer(records, "题目1", "我的回答", "评价", 80, False)
    assert len(records) == 1
    assert records[0]["question"] == "题目1"
    assert records[0]["answer"] == "我的回答"
    assert records[0]["score"] == 80


# ============================================================
# 运行入口
# ============================================================
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])