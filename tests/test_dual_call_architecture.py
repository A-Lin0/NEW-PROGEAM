"""双独立调用架构 + 双层校验机制 单元测试

验证范围：
1. _generate_review_only: 纯点评生成（无流程话术、强制引用原文）
2. _generate_question_only: 纯题干生成（无引导语、无过渡话术、单题输出）
3. _validate_review_relevance: 增强贴合度校验（≥2关键词 + 优点/不足两部分均含引用）
4. _validate_output_structure: 场景结构校验（in_stage/stage_switch/global_end/skip_*）
5. _run_double_layer_validation: 双层校验统一入口
"""
import asyncio
import sys
import os
import logging
from unittest.mock import AsyncMock, MagicMock, patch

# 添加项目根目录到 sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(level=logging.INFO)


def test_validate_review_relevance():
    """测试点评贴合度校验（双层强约束）"""
    from agent.core.interview_agent import InterviewAgent

    # 用例1：点评充分引用原文（优点+不足均含原文引用）→ 通过
    review_good = """优点：你在回答中提到的"分版本规划+对齐目标+权责拆分"推进框架，逻辑清晰覆盖了三方诉求。
不足：回答中提到的"分版本规划"未明确各版本的具体周期，权责拆分也缺少具体责任人分配。
优化建议：补充每个版本对应的转化率提升数据。"""
    answer = "我采用了分版本规划+对齐目标+权责拆分的推进框架，先对齐目标再拆分权责，覆盖了业务、产品、技术三方诉求。"
    assert InterviewAgent._validate_review_relevance(review_good, answer), \
        "用例1失败：点评充分引用原文应通过校验"

    # 用例2：点评套话，无原文引用 → 失败
    review_generic = """优点：逻辑清晰，有项目管理思维。
不足：缺乏数据支撑。
优化建议：增加量化指标。"""
    assert not InterviewAgent._validate_review_relevance(review_generic, answer), \
        "用例2失败：套话点评应不通过校验"

    # 用例3：优点有引用但不足无引用 → 失败（结构化引用约束）
    review_partial = """优点：你在回答中提到的"分版本规划"框架，逻辑清晰。
不足：缺乏数据支撑。
优化建议：增加量化指标。"""
    assert not InterviewAgent._validate_review_relevance(review_partial, answer), \
        "用例3失败：不足部分无原文引用应不通过校验"

    # 用例4：空回答 → 通过（跳过校验）
    assert InterviewAgent._validate_review_relevance("任意点评", ""), \
        "用例4失败：空回答应跳过校验"

    print("[OK] test_validate_review_relevance: 4/4 通过")


def test_validate_output_structure_in_stage():
    """测试场景1（阶段内推进）结构校验"""
    from agent.core.interview_agent import InterviewAgent

    # 合规输出
    output_ok = """【点评】优点：回答清晰\n不足：缺少数据\n优化建议：补充数据

请结合你的实际经验回答以下问题。

请说明 Vue3 的响应式原理？"""
    is_valid, err = InterviewAgent._validate_output_structure(
        output_ok, "in_stage", "tech_qa", "tech_qa"
    )
    assert is_valid, f"合规输出应通过校验，错误：{err}"

    # 引导语重复
    output_dup_guide = """【点评】优点：回答清晰\n不足：缺少数据

请结合你的实际经验回答以下问题。

请结合你的实际经验回答以下问题。

请说明 Vue3？"""
    is_valid, err = InterviewAgent._validate_output_structure(
        output_dup_guide, "in_stage", "tech_qa", "tech_qa"
    )
    assert not is_valid, "引导语重复应不通过校验"

    # 出现过渡话术
    output_with_transition = """【点评】优点：回答清晰

接下来进入下一环节。

请说明 Vue3？"""
    is_valid, err = InterviewAgent._validate_output_structure(
        output_with_transition, "in_stage", "tech_qa", "tech_qa"
    )
    assert not is_valid, "场景1出现过渡话术应不通过校验"

    # 缺少点评
    output_no_review = """请结合你的实际经验回答以下问题。

请说明 Vue3？"""
    is_valid, err = InterviewAgent._validate_output_structure(
        output_no_review, "in_stage", "tech_qa", "tech_qa"
    )
    assert not is_valid, "场景1缺少点评应不通过校验"

    print("[OK] test_validate_output_structure_in_stage: 4/4 通过")


def test_validate_output_structure_skip_scenarios():
    """测试 skip 场景结构校验（无点评）"""
    from agent.core.interview_agent import InterviewAgent

    # skip_in_stage 合规
    output_skip_ok = """请结合你的实际经验回答以下问题。

请说明 Vue3？"""
    is_valid, err = InterviewAgent._validate_output_structure(
        output_skip_ok, "skip_in_stage", "tech_qa", "tech_qa"
    )
    assert is_valid, f"skip_in_stage 合规输出应通过，错误：{err}"

    # skip_in_stage 误含点评
    output_skip_with_review = """【点评】优点：xxx

请结合你的实际经验回答以下问题。

请说明 Vue3？"""
    is_valid, err = InterviewAgent._validate_output_structure(
        output_skip_with_review, "skip_in_stage", "tech_qa", "tech_qa"
    )
    assert not is_valid, "skip_in_stage 误含点评应不通过"

    # skip_stage_switch 合规（Phase 12：移除引导语，仅过渡文案+题干）
    output_skip_switch = """技术问答环节到此结束，接下来聊聊行为面试题。

请描述一次你与团队成员意见不一致的经历？"""
    is_valid, err = InterviewAgent._validate_output_structure(
        output_skip_switch, "skip_stage_switch", "tech_qa", "star_qa"
    )
    assert is_valid, f"skip_stage_switch 合规输出应通过，错误：{err}"

    # skip_stage_switch 仍兼容带引导语版本（≤1次）
    output_skip_switch_with_guide = """技术问答环节到此结束，接下来聊聊行为面试题。

请针对题目给出你的解答方案。

请描述一次你与团队成员意见不一致的经历？"""
    is_valid, err = InterviewAgent._validate_output_structure(
        output_skip_switch_with_guide, "skip_stage_switch", "tech_qa", "star_qa"
    )
    assert is_valid, f"skip_stage_switch 兼容引导语版本应通过，错误：{err}"

    # skip_global_end 合规
    output_skip_end = "面试到这里就全部结束了，感谢你的分享，后续结果我们会在一周内通知你，祝你顺利。"
    is_valid, err = InterviewAgent._validate_output_structure(
        output_skip_end, "skip_global_end", "reverse_qa", "end"
    )
    assert is_valid, f"skip_global_end 合规输出应通过，错误：{err}"

    print("[OK] test_validate_output_structure_skip_scenarios: 4/4 通过")


def test_run_double_layer_validation():
    """测试双层校验统一入口"""
    from agent.core.interview_agent import InterviewAgent

    # 场景1：合规输出
    output_ok = """【点评】优点：你在回答中提到的"分版本规划"框架逻辑清晰\n不足：回答中未提及数据指标\n优化建议：补充数据

请结合你的实际经验回答以下问题。

请说明 Vue3 的响应式原理？"""
    answer = "我采用了分版本规划的框架，逻辑清晰"
    is_valid, err, warnings = InterviewAgent._run_double_layer_validation(
        output_ok, "in_stage", "tech_qa", "tech_qa",
        review="优点：你在回答中提到的分版本规划框架逻辑清晰\n不足：回答中未提及数据指标",
        user_answer=answer
    )
    assert is_valid, f"合规输出应通过双层校验，错误：{err}，告警：{warnings}"

    # 场景1：含非法全局结束语义 → 失败
    output_illegal_end = """【点评】优点：xxx

请结合你的实际经验回答以下问题。

面试全部结束了。请说明 Vue3？"""
    is_valid, err, warnings = InterviewAgent._run_double_layer_validation(
        output_illegal_end, "in_stage", "tech_qa", "tech_qa",
        review="优点：xxx", user_answer="我的回答"
    )
    assert not is_valid, "含非法全局结束语义应不通过双层校验"
    assert "全局结束" in err, f"错误信息应包含全局结束，实际：{err}"

    # 场景2：合规输出（Phase 12：移除引导语，仅点评+过渡文案+题干）
    output_s2_ok = """【点评】优点：回答清晰\n不足：缺少数据\n优化建议：补充数据

技术问答环节到此结束，接下来聊聊行为面试题。

请描述一次你与团队成员意见不一致的经历？"""
    is_valid, err, warnings = InterviewAgent._run_double_layer_validation(
        output_s2_ok, "stage_switch", "tech_qa", "star_qa"
    )
    assert is_valid, f"场景2合规输出应通过，错误：{err}，告警：{warnings}"

    # 场景3：合规输出
    output_s3_ok = """【点评】优点：回答清晰\n不足：缺少数据\n优化建议：补充数据

面试到这里就全部结束了，感谢你的分享，后续结果我们会在一周内通知你，祝你顺利。"""
    is_valid, err, warnings = InterviewAgent._run_double_layer_validation(
        output_s3_ok, "global_end", "reverse_qa", "end"
    )
    assert is_valid, f"场景3合规输出应通过，错误：{err}，告警：{warnings}"

    # 场景3：误含题目 → 失败
    output_s3_with_q = """【点评】优点：xxx

面试到这里就全部结束了。

请回答下一题？"""
    is_valid, err, warnings = InterviewAgent._run_double_layer_validation(
        output_s3_with_q, "global_end", "reverse_qa", "end"
    )
    assert not is_valid, "场景3误含题目应不通过校验"

    print("[OK] test_run_double_layer_validation: 5/5 通过")


def test_dedupe_guide_phrases():
    """测试引导语去重"""
    from agent.core.interview_agent import InterviewAgent

    # 主引导语重复
    text = """【点评】xxx

请结合你的实际经验回答以下问题。

请结合你的实际经验回答以下问题。

题目？"""
    result = InterviewAgent._dedupe_guide_phrases(text)
    assert result.count("请结合你的实际经验回答以下问题") == 1, \
        f"主引导语应仅1次，实际：{result.count('请结合你的实际经验回答以下问题')}"

    # 场景2引导语重复
    text2 = """过渡语

请针对题目给出你的解答方案。

请针对题目给出你的解答方案。

题目？"""
    result2 = InterviewAgent._dedupe_guide_phrases(text2)
    assert result2.count("请针对题目给出你的解答方案") == 1, \
        f"场景2引导语应仅1次，实际：{result2.count('请针对题目给出你的解答方案')}"

    print("[OK] test_dedupe_guide_phrases: 2/2 通过")


def test_deep_clean_content():
    """测试深度清洗"""
    from agent.core.interview_agent import InterviewAgent

    # 含过渡话术 + 引导语 + 多题
    dirty = """接下来进入下一环节。

请结合你的实际经验回答以下问题。

请说明 Vue3 原理？

请描述 React Hooks？"""
    cleaned = InterviewAgent._deep_clean_content(dirty)
    # 过渡话术应被删除
    assert "接下来进入" not in cleaned, f"过渡话术未删除：{cleaned}"
    # 引导语应被删除
    assert "请结合你的实际经验" not in cleaned, f"引导语未删除：{cleaned}"
    # 多题应仅保留第一道
    assert "React" not in cleaned, f"多题未截断：{cleaned}"
    assert "Vue3" in cleaned, f"第一题被误删：{cleaned}"

    print("[OK] test_deep_clean_content: 1/1 通过")


async def test_generate_review_only_mock():
    """测试纯点评生成（Mock LLM - 强制JSON输出 + Phase 12 岗位相关性校验）"""
    from agent.core.interview_agent import InterviewAgent, POSITION_DIMENSIONS

    agent = InterviewAgent(api_key="fake-key", base_url="http://fake", model="fake")

    # Mock LLM 返回合规JSON（点评内容需含岗位关键词"前端"/"Vue3"等以通过岗位相关性校验）
    async def fake_complete(prompt, _):
        return """{
  "comment": {
    "advantage": "你在回答中提到的分版本规划+对齐目标+权责拆分推进框架，逻辑清晰覆盖了前端三方诉求",
    "disadvantage": "回答中提到的分版本规划未明确各版本的具体周期，权责拆分也缺少前端具体责任人分配",
    "suggestion": "补充每个版本对应的转化率提升数据和责任人名单"
  },
  "score": 75
}"""

    agent._llm_complete = fake_complete

    # Phase 12：必须传 position_ctx 才能通过岗位相关性校验
    position_ctx = {
        "category": "前端",
        "focus_points": "JavaScript/TypeScript、React/Vue框架、CSS布局、浏览器原理、性能优化、工程化",
        "dimensions": POSITION_DIMENSIONS["前端"],
    }

    review_fields, score = await agent._generate_review_only(
        "前端开发", "middle", "tech_qa",
        "请说明 Vue3 的响应式原理？",
        "我采用了分版本规划+对齐目标+权责拆分的推进框架，先对齐目标再拆分权责。",
        position_ctx=position_ctx,
    )
    # 应返回字典格式
    assert isinstance(review_fields, dict), f"应返回字典，实际：{type(review_fields)}"
    assert "advantage" in review_fields and "disadvantage" in review_fields and "suggestion" in review_fields, \
        f"字典应包含三个字段：{review_fields}"
    # 应不包含流程话术
    for pat in ["接下来", "请回答", "下面我们", "以上点评"]:
        for v in review_fields.values():
            assert pat not in v, f"字段值不应包含流程话术「{pat}」：{v}"
    # 应包含原文引用
    assert "分版本规划" in review_fields["advantage"] or "对齐目标" in review_fields["advantage"], \
        f"advantage 应引用原文关键词：{review_fields['advantage']}"
    assert "分版本规划" in review_fields["disadvantage"] or "权责拆分" in review_fields["disadvantage"], \
        f"disadvantage 应引用原文关键词：{review_fields['disadvantage']}"
    # 分数应有效
    assert 0 <= score <= 100, f"分数应在0-100范围：{score}"

    print("[OK] test_generate_review_only_mock: 1/1 通过")


async def test_generate_question_only_mock():
    """测试纯题干生成（Mock LLM - 强制JSON输出 + Phase 11 三重校验 + Phase 12 question_title 字段）"""
    from agent.core.interview_agent import InterviewAgent, POSITION_DIMENSIONS

    agent = InterviewAgent(api_key="fake-key", base_url="http://fake", model="fake")

    # Mock LLM 返回 question_title 字段（含残留引导语需三层清洗）
    async def fake_stream(prompt, history):
        yield '{"question_title": "请结合你的实际经验回答以下问题。\\n请说明前端 Vue3 的响应式原理？\\n请描述 React Hooks 的工作机制？"}'

    agent._llm_stream = fake_stream

    # 构造 session_ctx 与 position_ctx（Phase 11 三重校验必需）
    session_ctx = {}
    InterviewAgent._init_question_cache(session_ctx)
    position_ctx = {
        "category": "前端",
        "focus_points": "JavaScript/TypeScript、React/Vue框架、CSS布局、浏览器原理、性能优化、工程化",
        "dimensions": POSITION_DIMENSIONS["前端"],
    }

    q_text = await agent._generate_question_only(
        "前端开发", "middle", "tech_qa", 1, 3, [],
        position_ctx=position_ctx, session_ctx=session_ctx,
    )
    # 应不包含流程话术
    assert "接下来我们看" not in q_text, f"纯题干不应包含流程话术：{q_text}"
    # 应不包含引导语
    assert "请结合你的实际经验" not in q_text, f"纯题干不应包含引导语：{q_text}"
    # 应仅包含第一题（多题被截断）
    assert "React" not in q_text, f"多题未截断：{q_text}"
    assert "Vue3" in q_text, f"第一题被误删：{q_text}"

    print("[OK] test_generate_question_only_mock: 1/1 通过")


def test_parse_review_json():
    """测试点评JSON解析"""
    from agent.core.interview_agent import InterviewAgent

    # 用例1：标准JSON
    result1 = '{"comment":{"advantage":"引用原文","disadvantage":"缺失数据","suggestion":"补充数据"},"score":80}'
    parsed, score = InterviewAgent._parse_review_json(result1)
    assert parsed is not None, "标准JSON应解析成功"
    assert parsed["advantage"] == "引用原文"
    assert parsed["disadvantage"] == "缺失数据"
    assert parsed["suggestion"] == "补充数据"
    assert score == 80

    # 用例2：代码块包裹
    result2 = '```json\n{"comment":{"advantage":"引用","disadvantage":"缺失","suggestion":"补充"},"score":70}\n```'
    parsed, score = InterviewAgent._parse_review_json(result2)
    assert parsed is not None, "代码块JSON应解析成功"
    assert score == 70

    # 用例3：混合文本
    result3 = '好的，以下是点评：\n{"comment":{"advantage":"引用原文","disadvantage":"缺失细节","suggestion":"补充细节"},"score":75}\n以上是点评。'
    parsed, score = InterviewAgent._parse_review_json(result3)
    assert parsed is not None, "混合文本JSON应解析成功"
    assert parsed["advantage"] == "引用原文"
    assert score == 75

    # 用例4：扁平结构（无 comment 嵌套）
    result4 = '{"advantage":"引用","disadvantage":"缺失","suggestion":"补充","score":65}'
    parsed, score = InterviewAgent._parse_review_json(result4)
    assert parsed is not None, "扁平结构JSON应解析成功"
    assert score == 65

    # 用例5：缺关键字段 → 失败
    result5 = '{"comment":{"advantage":"引用"}}'
    parsed, score = InterviewAgent._parse_review_json(result5)
    assert parsed is None, "缺 disadvantage 应解析失败"

    # 用例6：非JSON文本 → 失败
    result6 = '这是一段普通文本，不是JSON'
    parsed, score = InterviewAgent._parse_review_json(result6)
    assert parsed is None, "非JSON文本应解析失败"

    # 用例7：分数越界 → 截断到100
    result7 = '{"comment":{"advantage":"引用","disadvantage":"缺失","suggestion":"补充"},"score":150}'
    parsed, score = InterviewAgent._parse_review_json(result7)
    assert score == 100, f"分数应截断到100，实际：{score}"

    print("[OK] test_parse_review_json: 7/7 通过")


def test_parse_question_json():
    """测试题干JSON解析（Phase 12：question_title 优先，兼容 question 回退）"""
    from agent.core.interview_agent import InterviewAgent

    # 用例1：标准JSON（Phase 12 新字段名 question_title）
    result1 = '{"question_title": "请说明 Vue3 的响应式原理？"}'
    parsed = InterviewAgent._parse_question_json(result1)
    assert parsed == "请说明 Vue3 的响应式原理？", f"question_title 解析错误：{parsed}"

    # 用例2：代码块包裹
    result2 = '```json\n{"question_title": "请描述 React Hooks？"}\n```'
    parsed = InterviewAgent._parse_question_json(result2)
    assert parsed == "请描述 React Hooks？", f"代码块JSON解析错误：{parsed}"

    # 用例3：混合文本
    result3 = '好的，题目如下：\n{"question_title": "请说明 Vue3 原理？"}\n请作答。'
    parsed = InterviewAgent._parse_question_json(result3)
    assert "Vue3" in parsed, f"混合文本JSON解析错误：{parsed}"

    # 用例4：兼容旧字段 question（向后兼容）
    result4 = '{"question": "请说明 Vue3 原理？"}'
    parsed = InterviewAgent._parse_question_json(result4)
    assert parsed == "请说明 Vue3 原理？", f"兼容 question 字段解析错误：{parsed}"

    # 用例5：同时存在两个字段 → 优先 question_title
    result5 = '{"question": "旧字段", "question_title": "新字段"}'
    parsed = InterviewAgent._parse_question_json(result5)
    assert parsed == "新字段", f"应优先 question_title 字段：{parsed}"

    # 用例6：缺 question_title 和 question 字段 → 失败
    result6 = '{"content": "Vue3 原理"}'
    parsed = InterviewAgent._parse_question_json(result6)
    assert parsed is None, "缺 question_title/question 字段应解析失败"

    # 用例7：空 question_title → 失败
    result7 = '{"question_title": ""}'
    parsed = InterviewAgent._parse_question_json(result7)
    assert parsed is None, "空 question_title 应解析失败"

    print("[OK] test_parse_question_json: 7/7 通过")


def test_assemble_review_text():
    """测试点评字段拼接（后端固定模板）"""
    from agent.core.interview_agent import InterviewAgent

    # 用例1：完整字段
    fields1 = {
        "advantage": "引用原文逻辑清晰",
        "disadvantage": "缺失数据支撑",
        "suggestion": "补充转化率数据"
    }
    result1 = InterviewAgent._assemble_review_text(fields1)
    assert "优点：引用原文逻辑清晰" in result1, f"优点拼接错误：{result1}"
    assert "不足：缺失数据支撑" in result1, f"不足拼接错误：{result1}"
    assert "优化建议：补充转化率数据" in result1, f"优化建议拼接错误：{result1}"
    # 应为三段式固定结构
    assert result1.count("优点：") == 1, f"优点应仅1次：{result1}"
    assert result1.count("不足：") == 1, f"不足应仅1次：{result1}"
    assert result1.count("优化建议：") == 1, f"优化建议应仅1次：{result1}"

    # 用例2：空字段 → 使用兜底值
    fields2 = {}
    result2 = InterviewAgent._assemble_review_text(fields2)
    assert "未作答" in result2, f"空字段应使用兜底值：{result2}"

    # 用例3：None → 兜底
    result3 = InterviewAgent._assemble_review_text(None)
    assert "未作答" in result3, f"None 应使用兜底值：{result3}"

    print("[OK] test_assemble_review_text: 3/3 通过")


def test_validate_review_fields_relevance():
    """测试点评字段贴合度校验（advantage/disadvantage 分别校验）"""
    from agent.core.interview_agent import InterviewAgent

    answer = "我采用了分版本规划+对齐目标+权责拆分的推进框架，先对齐目标再拆分权责。"

    # 用例1：两部分均引用原文 → 通过
    fields1 = {
        "advantage": "你在回答中提到的分版本规划框架逻辑清晰",
        "disadvantage": "回答中提到的权责拆分未明确具体责任人",
        "suggestion": "补充责任人名单"
    }
    assert InterviewAgent._validate_review_fields_relevance(fields1, answer), \
        "用例1失败：两部分均引用原文应通过"

    # 用例2：仅 advantage 有引用 → 失败
    fields2 = {
        "advantage": "你在回答中提到的分版本规划框架逻辑清晰",
        "disadvantage": "缺乏数据支撑",
        "suggestion": "补充数据"
    }
    assert not InterviewAgent._validate_review_fields_relevance(fields2, answer), \
        "用例2失败：disadvantage 无引用应不通过"

    # 用例3：仅 disadvantage 有引用 → 失败
    fields3 = {
        "advantage": "逻辑清晰",
        "disadvantage": "回答中提到的权责拆分未明确具体责任人",
        "suggestion": "补充责任人"
    }
    assert not InterviewAgent._validate_review_fields_relevance(fields3, answer), \
        "用例3失败：advantage 无引用应不通过"

    # 用例4：两部分均无引用 → 失败
    fields4 = {
        "advantage": "逻辑清晰",
        "disadvantage": "缺乏数据",
        "suggestion": "补充数据"
    }
    assert not InterviewAgent._validate_review_fields_relevance(fields4, answer), \
        "用例4失败：两部分均无引用应不通过"

    # 用例5：空回答 → 通过（跳过校验）
    assert InterviewAgent._validate_review_fields_relevance(fields1, ""), \
        "用例5失败：空回答应跳过校验"

    print("[OK] test_validate_review_fields_relevance: 5/5 通过")


def test_deep_clean_question_field():
    """测试题干字段三层清洗（Phase 12：正则+语义+去重）"""
    from agent.core.interview_agent import InterviewAgent

    # 用例1：含引导语 + 多题
    dirty1 = "请结合你的实际经验回答以下问题。\n请说明 Vue3 原理？\n请描述 React Hooks？"
    cleaned1 = InterviewAgent._deep_clean_question_field(dirty1)
    assert "请结合你的实际经验" not in cleaned1, f"引导语未删除：{cleaned1}"
    assert "React" not in cleaned1, f"多题未截断：{cleaned1}"
    assert "Vue3" in cleaned1, f"第一题被误删：{cleaned1}"

    # 用例2：含过渡话术
    dirty2 = "接下来进入下一环节。\n请说明 Vue3 原理？"
    cleaned2 = InterviewAgent._deep_clean_question_field(dirty2)
    assert "接下来进入" not in cleaned2, f"过渡话术未删除：{cleaned2}"
    assert "Vue3" in cleaned2, f"题目被误删：{cleaned2}"

    # 用例3：合法题干（含"请说明"前缀，但不是引导语）
    dirty3 = "请说明 Vue3 的响应式原理？"
    cleaned3 = InterviewAgent._deep_clean_question_field(dirty3)
    assert "Vue3" in cleaned3, f"合法题干被误删：{cleaned3}"

    # 用例4（Phase 12 新增）：含"请针对"、"请回答"开头的引导句应被删除
    dirty4 = "请针对题目给出你的解答方案。\n请说明你如何定义产品的视觉风格？"
    cleaned4 = InterviewAgent._deep_clean_question_field(dirty4)
    assert "请针对" not in cleaned4, f"Phase 12 应删除「请针对」开头引导句：{cleaned4}"
    assert "视觉风格" in cleaned4, f"题干被误删：{cleaned4}"

    # 用例5（Phase 12 新增）：含"请回答"开头的引导句应被删除
    dirty5 = "请回答以下问题。\n请描述前端 Vue3 的 Diff 算法？"
    cleaned5 = InterviewAgent._deep_clean_question_field(dirty5)
    assert "请回答" not in cleaned5, f"Phase 12 应删除「请回答」开头引导句：{cleaned5}"
    assert "Diff" in cleaned5, f"题干被误删：{cleaned5}"

    print("[OK] test_deep_clean_question_field: 5/5 通过")


def test_init_question_cache():
    """测试会话级题目缓存初始化"""
    from agent.core.interview_agent import InterviewAgent

    # 用例1：空 session_ctx → 初始化缓存
    ctx1 = {}
    InterviewAgent._init_question_cache(ctx1)
    assert "question_cache" in ctx1, "缓存键应被创建"
    assert ctx1["question_cache"]["asked_questions"] == [], "asked_questions 应为空列表"
    assert ctx1["question_cache"]["asked_dimensions"] == [], "asked_dimensions 应为空列表"

    # 用例2：已有缓存 → 不覆盖
    ctx2 = {
        "question_cache": {
            "asked_questions": [{"question": "测试题"}],
            "asked_dimensions": ["视觉设计能力"],
        }
    }
    InterviewAgent._init_question_cache(ctx2)
    assert len(ctx2["question_cache"]["asked_questions"]) == 1, "已有缓存不应被覆盖"
    assert ctx2["question_cache"]["asked_dimensions"] == ["视觉设计能力"], "已有维度不应被覆盖"

    print("[OK] test_init_question_cache: 2/2 通过")


def test_extract_question_keywords():
    """测试题目关键词提取（滑动窗口 + 通用词过滤）"""
    from agent.core.interview_agent import InterviewAgent

    # 用例1：中文题目（含通用词过滤）
    q1 = "请说明 Vue3 的响应式原理？"
    kws1 = InterviewAgent._extract_question_keywords(q1)
    assert isinstance(kws1, list), "应返回列表"
    # 应包含英文术语 vue
    assert "vue" in [k.lower() for k in kws1], f"应包含 vue 关键词：{kws1}"
    # 应包含核心中文词
    kw_lower = [k.lower() for k in kws1]
    assert any("响应" in k for k in kw_lower) or any("原理" in k for k in kw_lower), \
        f"应包含 响应/原理 关键词：{kws1}"
    # 不应包含通用词
    assert "请说" not in kws1, f"通用词「请说」应被过滤：{kws1}"

    # 用例2：空字符串
    assert InterviewAgent._extract_question_keywords("") == [], "空字符串应返回空列表"
    assert InterviewAgent._extract_question_keywords(None) == [], "None 应返回空列表"

    # 用例3：含数字
    q3 = "请描述 Vue3 的 3 种组件通信方式？"
    kws3 = InterviewAgent._extract_question_keywords(q3)
    assert "vue" in [k.lower() for k in kws3], f"应包含 vue：{kws3}"

    print("[OK] test_extract_question_keywords: 3/3 通过")


def test_calculate_similarity():
    """测试题目语义相似度计算（Jaccard 系数）"""
    from agent.core.interview_agent import InterviewAgent

    # 用例1：完全相同 → 1.0
    q = "请说明 Vue3 的响应式原理？"
    sim1 = InterviewAgent._calculate_similarity(q, q)
    assert sim1 == 1.0, f"完全相同应=1.0，实际：{sim1}"

    # 用例2：完全无关 → 0.0
    sim2 = InterviewAgent._calculate_similarity(
        "请说明 Vue3 的响应式原理？",
        "你如何处理跨部门协作的冲突？"
    )
    assert sim2 < 0.6, f"无关题目相似度应<0.6，实际：{sim2}"

    # 用例3：高度相似（仅个别词不同）→ 应≥0.6
    sim3 = InterviewAgent._calculate_similarity(
        "请说明 Vue3 的响应式原理？",
        "请说明 Vue3 的响应式原理与实现？"
    )
    assert sim3 >= 0.6, f"高度相似应≥0.6，实际：{sim3}"

    # 用例4：空字符串 → 0.0
    assert InterviewAgent._calculate_similarity("", "题目") == 0.0, "空字符串应=0.0"
    assert InterviewAgent._calculate_similarity("题目", "") == 0.0, "空字符串应=0.0"

    print("[OK] test_calculate_similarity: 4/4 通过")


def test_check_question_duplicate():
    """测试题目重复检测（会话级缓存）"""
    from agent.core.interview_agent import InterviewAgent

    # 用例1：空缓存 → 不重复
    ctx1 = {}
    InterviewAgent._init_question_cache(ctx1)
    is_dup, dup_with = InterviewAgent._check_question_duplicate(
        "请说明 Vue3 原理？", ctx1
    )
    assert not is_dup, "空缓存不应判重"

    # 用例2：与缓存中题目完全相同 → 重复
    ctx2 = {}
    InterviewAgent._init_question_cache(ctx2)
    InterviewAgent._record_asked_question("请说明 Vue3 的响应式原理？", None, "tech_qa", ctx2)
    is_dup, dup_with = InterviewAgent._check_question_duplicate(
        "请说明 Vue3 的响应式原理？", ctx2
    )
    assert is_dup, "完全相同应判重"
    assert "Vue3" in dup_with, f"应返回重复题目：{dup_with}"

    # 用例3：与缓存中题目高度相似 → 重复
    ctx3 = {}
    InterviewAgent._init_question_cache(ctx3)
    InterviewAgent._record_asked_question("请说明 Vue3 的响应式原理？", None, "tech_qa", ctx3)
    is_dup, dup_with = InterviewAgent._check_question_duplicate(
        "请说明 Vue3 的响应式原理与实现？", ctx3
    )
    assert is_dup, "高度相似应判重"

    # 用例4：与缓存中题目无关 → 不重复
    ctx4 = {}
    InterviewAgent._init_question_cache(ctx4)
    InterviewAgent._record_asked_question("请说明 Vue3 的响应式原理？", None, "tech_qa", ctx4)
    is_dup, dup_with = InterviewAgent._check_question_duplicate(
        "你如何处理跨部门协作冲突？", ctx4
    )
    assert not is_dup, "无关题目不应判重"

    print("[OK] test_check_question_duplicate: 4/4 通过")


def test_detect_question_dimension():
    """测试题目维度检测（关键词匹配）"""
    from agent.core.interview_agent import InterviewAgent, POSITION_DIMENSIONS

    # 用例1：UI设计师岗位 - 视觉设计维度
    design_dims = POSITION_DIMENSIONS["设计"]
    q1 = "请说明你如何定义产品的视觉风格和品牌视觉适配？"
    dim1 = InterviewAgent._detect_question_dimension(q1, design_dims)
    assert dim1 is not None, f"应检测到维度：{dim1}"
    assert "视觉" in dim1 or "视觉设计" in dim1, f"应匹配视觉设计维度：{dim1}"

    # 用例2：UI设计师岗位 - 跨角色协作维度
    q2 = "你如何与产品经理和开发对齐设计走查结果？"
    dim2 = InterviewAgent._detect_question_dimension(q2, design_dims)
    assert dim2 is not None, f"应检测到维度：{dim2}"

    # 用例3：空题目或空维度
    assert InterviewAgent._detect_question_dimension("", design_dims) is None, "空题目应返回 None"
    assert InterviewAgent._detect_question_dimension("题目", []) is None, "空维度应返回 None"

    print("[OK] test_detect_question_dimension: 3/3 通过")


def test_check_dimension_diversity():
    """测试维度多样性校验（同维度单会话最多1道）"""
    from agent.core.interview_agent import InterviewAgent, POSITION_DIMENSIONS

    design_dims = POSITION_DIMENSIONS["设计"]

    # 用例1：空缓存 → 不重复
    ctx1 = {}
    InterviewAgent._init_question_cache(ctx1)
    dim, is_dup = InterviewAgent._check_dimension_diversity(
        "请说明你如何定义产品的视觉风格？", ctx1, design_dims
    )
    assert not is_dup, "空缓存维度不应重复"

    # 用例2：已含视觉设计维度题目 → 再出视觉题应判重
    ctx2 = {}
    InterviewAgent._init_question_cache(ctx2)
    InterviewAgent._record_asked_question(
        "请说明你如何定义产品的视觉风格？", "视觉设计能力", "tech_qa", ctx2
    )
    dim, is_dup = InterviewAgent._check_dimension_diversity(
        "请描述你的品牌视觉适配流程？", ctx2, design_dims
    )
    # 若检测到同为视觉设计维度，应判重
    if dim == "视觉设计能力":
        assert is_dup, f"同维度应判重：{dim}"

    # 用例3：已含视觉设计维度 → 出交互题不应判重
    ctx3 = {}
    InterviewAgent._init_question_cache(ctx3)
    InterviewAgent._record_asked_question(
        "请说明你如何定义产品的视觉风格？", "视觉设计能力", "tech_qa", ctx3
    )
    dim, is_dup = InterviewAgent._check_dimension_diversity(
        "请描述你如何优化用户路径和易用性设计？", ctx3, design_dims
    )
    # 交互题不应判重（即便检测失败也不应误判为重复）
    if dim and dim != "视觉设计能力":
        assert not is_dup, f"不同维度不应判重：检测到={dim}"

    print("[OK] test_check_dimension_diversity: 3/3 通过")


def test_check_position_relevance():
    """测试岗位贴合度校验"""
    from agent.core.interview_agent import InterviewAgent

    # 用例1：UI设计师题目贴合 → 通过
    pos_ctx1 = {
        "category": "设计",
        "focus_points": "视觉设计、交互设计、设计体系、用户研究、跨角色协作、项目落地",
    }
    q1 = "请说明你如何定义产品的视觉风格和品牌视觉适配？"
    assert InterviewAgent._check_position_relevance(q1, "UI设计师", pos_ctx1), \
        "UI设计师题目应贴合岗位"

    # 用例2：题目完全无关 → 失败
    q2 = "请说明 Linux 内核的进程调度算法？"
    assert not InterviewAgent._check_position_relevance(q2, "UI设计师", pos_ctx1), \
        "Linux 内核题目不应贴合 UI设计师"

    # 用例3：空题目 → 失败
    assert not InterviewAgent._check_position_relevance("", "UI设计师", pos_ctx1), \
        "空题目应不通过"

    # 用例4：无岗位关键词（空岗位+空ctx）→ 默认通过（不校验）
    assert InterviewAgent._check_position_relevance("任意题目", "", None), \
        "无岗位关键词时应默认通过"

    print("[OK] test_check_position_relevance: 4/4 通过")


def test_record_asked_question():
    """测试已出题记录到缓存"""
    from agent.core.interview_agent import InterviewAgent

    ctx = {}
    InterviewAgent._init_question_cache(ctx)

    # 记录第一道题
    InterviewAgent._record_asked_question(
        "请说明 Vue3 的响应式原理？", "框架原理", "tech_qa", ctx
    )
    assert len(ctx["question_cache"]["asked_questions"]) == 1, "应记录1道题"
    assert ctx["question_cache"]["asked_questions"][0]["dimension"] == "框架原理"
    assert "框架原理" in ctx["question_cache"]["asked_dimensions"], "维度应被记录"

    # 记录第二道题（同维度）
    InterviewAgent._record_asked_question(
        "请描述 React 的 Diff 算法？", "框架原理", "tech_qa", ctx
    )
    assert len(ctx["question_cache"]["asked_questions"]) == 2, "应记录2道题"
    # 维度去重
    assert ctx["question_cache"]["asked_dimensions"].count("框架原理") == 1, \
        "同维度应去重记录"

    # 记录第三道题（不同维度）
    InterviewAgent._record_asked_question(
        "请说明浏览器的事件循环机制？", "浏览器与网络", "tech_qa", ctx
    )
    assert len(ctx["question_cache"]["asked_dimensions"]) == 2, "应有2个不同维度"

    print("[OK] test_record_asked_question: 3/3 通过")


def test_run_question_triple_check():
    """测试题目三重校验（去重 → 多样性 → 贴合）"""
    from agent.core.interview_agent import InterviewAgent, POSITION_DIMENSIONS

    design_dims = POSITION_DIMENSIONS["设计"]
    pos_ctx = {
        "category": "设计",
        "focus_points": "视觉设计、交互设计、设计体系、用户研究、跨角色协作、项目落地",
        "dimensions": design_dims,
    }
    target_position = "UI设计师"

    agent = InterviewAgent(api_key="fake-key", base_url="http://fake", model="fake")

    # 用例1：空缓存 + 贴合题 → 通过
    ctx1 = {}
    InterviewAgent._init_question_cache(ctx1)
    q1 = "请说明你如何定义产品的视觉风格和品牌视觉适配？"
    is_valid, fail_reason, dim = agent._run_question_triple_check(
        q1, ctx1, target_position, pos_ctx
    )
    assert is_valid, f"空缓存+贴合题应通过，失败原因：{fail_reason}"

    # 用例2：与已出题高度相似 → 失败（语义重复）
    ctx2 = {}
    InterviewAgent._init_question_cache(ctx2)
    InterviewAgent._record_asked_question(
        "请说明你如何定义产品的视觉风格和品牌视觉适配？",
        "视觉设计能力", "tech_qa", ctx2
    )
    q2 = "请说明你如何定义产品的视觉风格与品牌视觉适配？"
    is_valid, fail_reason, dim = agent._run_question_triple_check(
        q2, ctx2, target_position, pos_ctx
    )
    assert not is_valid, "高度相似题应判失败"
    assert "语义重复" in fail_reason or "维度重复" in fail_reason, \
        f"失败原因应含语义重复或维度重复：{fail_reason}"

    # 用例3：题目不贴合岗位 → 失败
    ctx3 = {}
    InterviewAgent._init_question_cache(ctx3)
    q3 = "请说明 Linux 内核的进程调度算法？"
    is_valid, fail_reason, dim = agent._run_question_triple_check(
        q3, ctx3, target_position, pos_ctx
    )
    assert not is_valid, "不贴合岗位题应判失败"
    assert "岗位贴合" in fail_reason, f"失败原因应含岗位贴合：{fail_reason}"

    # 用例4：空缓存 + 不贴合题 → 失败（第三重校验拦截）
    ctx4 = {}
    InterviewAgent._init_question_cache(ctx4)
    q4 = "请解释量子力学的基本原理？"
    is_valid, fail_reason, dim = agent._run_question_triple_check(
        q4, ctx4, target_position, pos_ctx
    )
    assert not is_valid, "量子力学题对UI设计师应判失败"

    print("[OK] test_run_question_triple_check: 4/4 通过")


def test_classify_position_with_dimensions():
    """测试岗位分类返回 dimensions 字段"""
    from agent.core.interview_agent import InterviewAgent, POSITION_DIMENSIONS, DEFAULT_DIMENSIONS

    # 用例1：UI设计师 → 设计类
    result1 = InterviewAgent._classify_position("UI设计师")
    assert result1["category"] == "设计", f"UI设计师应分类为设计：{result1['category']}"
    assert "dimensions" in result1, "应包含 dimensions 字段"
    assert result1["dimensions"] == POSITION_DIMENSIONS["设计"], "应返回设计维度列表"

    # 用例2：前端开发 → 前端类
    result2 = InterviewAgent._classify_position("前端开发工程师")
    assert result2["category"] == "前端", f"前端开发应分类为前端：{result2['category']}"
    assert result2["dimensions"] == POSITION_DIMENSIONS["前端"]

    # 用例3：未匹配岗位 → 通用类
    result3 = InterviewAgent._classify_position("xxx不存在的岗位yyy")
    assert result3["category"] == "通用", f"未匹配应分类为通用：{result3['category']}"
    assert result3["dimensions"] == DEFAULT_DIMENSIONS

    # 用例4：空岗位 → 通用类
    result4 = InterviewAgent._classify_position("")
    assert result4["category"] == "通用", "空岗位应分类为通用"

    print("[OK] test_classify_position_with_dimensions: 4/4 通过")


def test_validate_review_position_relevance():
    """Phase 12：点评岗位相关性校验"""
    from agent.core.interview_agent import InterviewAgent, POSITION_DIMENSIONS

    pos_ctx = {
        "category": "设计",
        "focus_points": "视觉设计、交互设计、设计体系、用户研究、跨角色协作、项目落地",
        "dimensions": POSITION_DIMENSIONS["设计"],
    }

    # 用例1：点评包含岗位关键词（视觉/设计/交互）→ 通过
    fields1 = {
        "advantage": "你提到的视觉风格定义体现了扎实的设计基础",
        "disadvantage": "未覆盖交互体验设计维度的用户路径优化",
        "suggestion": "补充交互设计相关的可用性测试经验"
    }
    assert InterviewAgent._validate_review_position_relevance(fields1, "UI设计师", pos_ctx), \
        "用例1失败：点评包含岗位关键词应通过"

    # 用例2：点评完全无关岗位（讲Linux内核）→ 失败
    # 注意：避免使用"数据"等UI岗位维度中的关键词
    fields2 = {
        "advantage": "你提到的进程调度算法逻辑清晰",
        "disadvantage": "缺乏内核链表的实现细节",
        "suggestion": "补充内核编译相关经验"
    }
    assert not InterviewAgent._validate_review_position_relevance(fields2, "UI设计师", pos_ctx), \
        "用例2失败：点评与UI设计师岗位无关应不通过"

    # 用例3：空岗位+空ctx → 默认通过（不校验）
    fields3 = {"advantage": "任意内容", "disadvantage": "任意", "suggestion": "任意"}
    assert InterviewAgent._validate_review_position_relevance(fields3, "", None), \
        "用例3失败：无岗位关键词时应默认通过"

    # 用例4：空字段 → 通过（不校验）
    assert InterviewAgent._validate_review_position_relevance({}, "UI设计师", pos_ctx), \
        "用例4失败：空字段应通过"

    print("[OK] test_validate_review_position_relevance: 4/4 通过")


def test_validate_review_no_generic_phrases():
    """Phase 12：空泛套话拦截"""
    from agent.core.interview_agent import InterviewAgent

    # 用例1：点评有具体内容（>15字）→ 通过
    fields1 = {
        "advantage": "你在回答中提到的分版本规划+对齐目标+权责拆分推进框架，逻辑清晰覆盖了三方诉求",
        "disadvantage": "回答中提到的分版本规划未明确各版本的具体周期和责任人分配",
        "suggestion": "补充每个版本对应的转化率提升数据和责任人名单"
    }
    assert InterviewAgent._validate_review_no_generic_phrases(fields1), \
        "用例1失败：有具体内容的点评应通过"

    # 用例2：优点仅含短套话（<15字）→ 失败
    fields2 = {
        "advantage": "逻辑清晰",
        "disadvantage": "回答中提到的分版本规划未明确具体周期",
        "suggestion": "补充数据"
    }
    assert not InterviewAgent._validate_review_no_generic_phrases(fields2), \
        "用例2失败：优点仅含短套话应不通过"

    # 用例3：不足仅含短套话（<15字）→ 失败
    fields3 = {
        "advantage": "你在回答中提到的分版本规划框架逻辑清晰",
        "disadvantage": "缺乏数据",
        "suggestion": "补充数据"
    }
    assert not InterviewAgent._validate_review_no_generic_phrases(fields3), \
        "用例3失败：不足仅含短套话应不通过"

    # 用例4：空字段 → 失败
    assert not InterviewAgent._validate_review_no_generic_phrases({}), \
        "用例4失败：空字段应不通过"

    # 用例5：advantage 为空 → 失败
    fields5 = {"advantage": "", "disadvantage": "有内容", "suggestion": "建议"}
    assert not InterviewAgent._validate_review_no_generic_phrases(fields5), \
        "用例5失败：advantage 为空应不通过"

    print("[OK] test_validate_review_no_generic_phrases: 5/5 通过")


def test_question_similarity_threshold_lowered():
    """Phase 12：相似度阈值下调到 0.5"""
    from agent.core.interview_agent import InterviewAgent, QUESTION_SIMILARITY_THRESHOLD

    # 验证常量值
    assert QUESTION_SIMILARITY_THRESHOLD == 0.5, \
        f"Phase 12 阈值应为 0.5，实际：{QUESTION_SIMILARITY_THRESHOLD}"

    # 验证：相似度 0.5-0.6 之间的题目现在应被判定为重复
    # 构造两个题目，关键词部分重合，相似度在 0.5-0.6 之间
    # 用相同关键词较多但略有差异的题目
    ctx = {}
    InterviewAgent._init_question_cache(ctx)
    InterviewAgent._record_asked_question(
        "请说明前端 Vue3 的响应式原理与组件设计？", None, "tech_qa", ctx
    )
    # 同高度相似题（仅个别词不同）
    is_dup, _ = InterviewAgent._check_question_duplicate(
        "请说明前端 Vue3 的响应式原理与组件设计模式？", ctx
    )
    # 在新阈值0.5下，高度相似题应被判定为重复
    # （具体相似度取决于关键词重合度，这里测试整体判定逻辑）
    assert is_dup, f"Phase 12 阈值0.5下，高度相似题应判重"

    print("[OK] test_question_similarity_threshold_lowered: 2/2 通过")


def test_scene_B_no_guide_text():
    """Phase 12：场景B（阶段切换）输出不应包含引导语"""
    from agent.core.interview_agent import InterviewAgent

    # 场景B合规输出（无引导语）
    output_no_guide = """【点评】优点：回答清晰\n不足：缺少数据\n优化建议：补充数据

技术问答环节到此结束，接下来聊聊行为面试题。

请描述一次你与团队成员意见不一致的经历？"""
    is_valid, err = InterviewAgent._validate_output_structure(
        output_no_guide, "stage_switch", "tech_qa", "star_qa"
    )
    assert is_valid, f"Phase 12 场景B无引导语应通过，错误：{err}"

    # 双层校验也应通过
    is_valid, err, warnings = InterviewAgent._run_double_layer_validation(
        output_no_guide, "stage_switch", "tech_qa", "star_qa"
    )
    assert is_valid, f"Phase 12 场景B双层校验应通过，错误：{err}，告警：{warnings}"

    # 场景B重复引导语 → 仍应失败（≤1次约束）
    output_dup_guide = """【点评】优点：xxx

技术问答环节到此结束，接下来聊聊行为面试题。

请针对题目给出你的解答方案。

请针对题目给出你的解答方案。

请描述一次经历？"""
    is_valid, err = InterviewAgent._validate_output_structure(
        output_dup_guide, "stage_switch", "tech_qa", "star_qa"
    )
    assert not is_valid, "Phase 12 场景B引导语重复仍应失败"

    print("[OK] test_scene_B_no_guide_text: 3/3 通过")


def main():
    """主测试入口"""
    print("=" * 60)
    print("结构化JSON输出 + 后端字段拼接 单元测试")
    print("=" * 60)

    # 同步测试 - 基础校验
    test_validate_review_relevance()
    test_validate_output_structure_in_stage()
    test_validate_output_structure_skip_scenarios()
    test_run_double_layer_validation()
    test_dedupe_guide_phrases()
    test_deep_clean_content()

    # 同步测试 - JSON解析与字段拼接
    test_parse_review_json()
    test_parse_question_json()
    test_assemble_review_text()
    test_validate_review_fields_relevance()
    test_deep_clean_question_field()

    # Phase 11 同步测试 - 题目去重+多样性+贴合度
    test_init_question_cache()
    test_extract_question_keywords()
    test_calculate_similarity()
    test_check_question_duplicate()
    test_detect_question_dimension()
    test_check_dimension_diversity()
    test_check_position_relevance()
    test_record_asked_question()
    test_run_question_triple_check()
    test_classify_position_with_dimensions()

    # Phase 12 同步测试 - 架构级根治
    test_validate_review_position_relevance()
    test_validate_review_no_generic_phrases()
    test_question_similarity_threshold_lowered()
    test_scene_B_no_guide_text()

    # 异步测试 - Mock LLM 调用
    asyncio.run(test_generate_review_only_mock())
    asyncio.run(test_generate_question_only_mock())

    print("=" * 60)
    print("全部测试通过 [OK]")
    print("=" * 60)


if __name__ == "__main__":
    main()
