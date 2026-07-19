# Debug Session: interview-stage-loop

**Status**: [CLOSED - FIXED]
**Started**: 2026-07-16
**Session ID**: interview-stage-loop
**Completed**: 2026-07-16

## Symptom
面试模拟模块在"自我介绍"环节一直循环，无法推进到核心提问阶段。

## Root Cause (链路分析)

### 根因1：面试官话术未回填到 history
- `orchestrator.py` 的 `handle_message` 只在收到用户消息时 append `{"role":"user"}` 到 history
- 但从未 append `{"role":"interviewer"}`（面试官话术）到 history
- 结果：LLM 每次只看到 user 消息，看不到自己上一轮说过的话 → 重复输出自我介绍要求

### 根因2：_decide_next_stage 上次"保守策略"导致阶段永不推进
- 上次修复 __META__ 误判时，改成了"非 reverse_qa 阶段永不推进"
- 结果：self_intro → core_qa 完全没有推进路径

### 根因3：prompt 未明确告知 LLM 当前阶段行为
- 旧 prompt 只在末尾列出"当前阶段: {session_stage}"
- LLM 不理解 self_intro 阶段应该切入技术问题，继续要求自我介绍

## Fixes Applied

### Fix 1: 回填面试官话术到 history（根因1）
- **文件**: `agent/orchestrator.py` (handle_message)
- **修改**: 在 SSE 流结束后累积所有 chunks，append `{"role":"interviewer","content":...}` 到 session_ctx["history"]
- **验证**: Redis 显示 history 从 2 条（全是 user）变为 4 条（user+interviewer 交替）

### Fix 2: 阶段推进策略（根因2）
- **文件**: `agent/core/interview_agent.py` (_decide_next_stage)
- **修改**: 为每个阶段添加推进信号检测
  - init → self_intro: 检测"自我介绍"等开场白信号
  - self_intro → core_qa: 检测"下面""接下来""第一个问题"等过渡词
  - core_qa → reverse_qa: 检测"有什么想问""反问"等信号
  - reverse_qa → end: 检测明确结束信号
- **验证**: Redis current_stage 从 init → self_intro → core_qa 正常推进

### Fix 3: 增强 prompt 阶段行为指引（根因3）
- **文件**: `agent/core/interview_agent.py` (_build_interviewer_prompt)
- **修改**: 为每个阶段添加明确的 stage_instructions
  - init: "请简短问候并请候选人做自我介绍"
  - self_intro: "现在应该切入第一个技术/项目问题，不要再要求自我介绍"
  - core_qa: "每轮只问一个问题，等候选人回答后再出下一题"
- **验证**: LLM 输出"接下来我们进入技术环节。第一个问题..."，不再重复自我介绍要求

## Evidence (Pre-fix vs Post-fix)

### Pre-fix Redis state
```json
{"history": [
  {"role": "user", "content": "开始面试"},
  {"role": "user", "content": "我是张三..."}  // 全是 user，无 interviewer
], "current_stage": "self_intro"}  // 卡在 self_intro
```

### Post-fix Redis state
```json
{"history": [
  {"role": "user", "content": "开始面试"},
  {"role": "interviewer", "content": "你好，欢迎参加今天的面试..."},
  {"role": "user", "content": "我是张三..."},
  {"role": "interviewer", "content": "好的，感谢你的介绍。接下来我们进入技术环节..."}
], "current_stage": "core_qa"}  // 成功推进到 core_qa
```

## 结论
根因是面试官话术未回填到 history 导致 LLM 上下文断裂。修复后多轮对话上下文连贯，阶段按 init→self_intro→core_qa 正常推进。
