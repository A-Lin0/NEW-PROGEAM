# Debug Session: agents-functional-check

**Status**: [CLOSED]
**Started**: 2026-07-15
**Session ID**: agents-functional-check
**Completed**: 2026-07-16

## Objective
检查四个 Agent（简历优化、面试模拟、面试复盘、公司查询）的功能完善性和运行状态，生成检查报告。

## Hypotheses
| # | Hypothesis | Observation Point | Status |
|---|------------|------------------|--------|
| H1 | 简历优化 Agent 的 API 路由完整且可调用 | POST /api/resume/analyze | CONFIRMED（SSE 正常，ATS 评分 JSON 解析失败）|
| H2 | 面试模拟 Agent 的创建/对话/命令链路完整 | POST /api/interview/ + SSE | CONFIRMED（LLM 真实输出面试官话术）|
| H3 | 面试复盘 Agent 能根据面试记录生成报告 | POST /api/review/{id}/generate | CONFIRMED（400 错误：无问答记录）|
| H4 | 公司查询 Agent 能查询公司列表和详情 | GET /api/companies + POST /api/retrieve/ | CONFIRMED（双路检索正常）|
| H5 | LLM 配置缺失导致部分 Agent 降级运行 | .env LLM_API_KEY | REJECTED（LLM 已配置，调用成功）|

## Evidence Log

### 1. 公司查询 Agent
- **GET /api/companies/?skip=0&limit=5** → 200 OK，返回 1 条公司记录（腾讯）
- **POST /api/retrieve/**（query="腾讯", type="company_info"）→ 200 OK，has_result=True，3 条 detail_items
- 结论：RetrieverAgent 双路召回（DB + 向量库）正常工作

### 2. 简历优化 Agent
- **POST /api/resume/analyze**（content="张三，5年Java..."）→ 200 OK，SSE 流式响应
- 内容长度：46129 字节
- 首段输出：`[ATS 评分失败: Expecting value: line 1 column 1 (char 0)]`
- 后续流式输出简历分析报告正常
- **缺陷**：ATS 评分 prompt 让 LLM 返回 JSON，但 LLM 返回了非 JSON 内容，导致 `json.loads` 失败

### 3. 面试模拟 Agent
- **POST /api/interview/**（position="Java后端工程师"）→ 201 Created，返回 interview_id=e74a4fa9-...
- **POST /api/interview/{id}/command**（command="start"）→ 200 OK，SSE 流式响应
- LLM 真实输出："你好，欢迎参加今天的面试。请先做一下自我介绍，重点介绍你的技术栈、项目..."
- 结论：面试模拟 LLM 调用链路完全正常

### 4. 面试复盘 Agent
- **POST /api/review/{id}/generate** → 400 Bad Request
- 错误原因：`interview.questions_answers` 为空
- **根因**：`backend/app/api/interview.py` 第 99 行 `add_qa` 调用被注释：
  ```python
  # await service.add_qa(interview_id, question=..., answer=data.answer)
  ```
- InterviewService 提供了 `add_qa` 方法，但 API 层未调用，导致面试记录无法持久化
- ReviewAgent 本身代码完善（有 LLM 调用、JSON 输出、降级模式），但缺少数据输入

## Fixes Applied (2026-07-16)

### Fix 1: 面试问答记录持久化 (P0)
- **文件**: `backend/app/api/interview.py` (interview_chat 函数)
- **修改**: 取消 `add_qa` 注释，在 SSE 流结束后累积完整面试官话术并持久化 QA 记录
- **验证**: chat 接口 200 OK → review/generate 从 400 变为 200，返回结构化复盘 JSON

### Fix 2: ATS 评分 JSON 解析 (P1)
- **文件**: `agent/core/resume_agent.py` (_get_ats_score 方法)
- **修改**: 增加 markdown ```json 包裹剥离 + 正则兜底提取 JSON
- **验证**: /api/resume/analyze 首段返回有效 JSON `{"score": 45, "breakdown": {...}}`

### Fix 3: __META__ 异常输出 + 阶段误判
- **文件 A**: `agent/orchestrator.py` (handle_message)
  - **修改**: 检测到 `__META__` 信号后 `continue` 不 yield，避免透传给前端
- **文件 B**: `agent/core/interview_agent.py` (_decide_next_stage)
  - **修改**: 只在 reverse_qa 阶段检测结束信号，移除"今天的面试"等易误判短语
- **验证**: command=start 返回 `HAS_META: False`，面试官正常输出开场白不再误判为 end

## Execution Summary
1. ✅ 静态代码检查：四个 Agent 路由完整，依赖注入规范
2. ✅ 后端服务启动：健康检查通过，LLM 配置已加载
3. ✅ JWT 鉴权：注册/登录获取 token 成功
4. ✅ 公司查询 Agent：双路检索正常
5. ✅ 简历优化 Agent：SSE 正常，ATS 评分 JSON 解析成功（已修复）
6. ✅ 面试模拟 Agent：LLM 真实输出面试官话术，__META__ 不再透传（已修复）
7. ✅ 面试复盘 Agent：QA 记录已持久化，复盘报告生成成功（已修复）
