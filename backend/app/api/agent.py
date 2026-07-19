"""
Agent 接口（RESTful + SSE）

路由前缀: /api/agent

接口清单:
1. POST /api/agent/sync                同步执行单任务（检索/简历优化/复盘）
2. POST /api/agent/stream              SSE流式对话入口（面试模拟/流式简历优化）
3. GET  /api/agent/sessions            分页获取当前登录用户的所有会话列表
4. GET  /api/agent/sessions/{id}       获取指定会话详情与完整对话历史
5. POST /api/agent/sessions/{id}/end   手动结束会话，面试场景自动触发复盘
6. DELETE /api/agent/sessions/{id}     删除指定会话及关联对话记录
7. GET  /api/agent/health              Agent调度服务健康检查
"""

import json
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from ..db.session import get_db
from ..models.user import User
from ..api.auth import get_current_user
from ..schemas.agent import (
    AgentSyncRequest, AgentStreamRequest, SessionEndRequest,
    ApiResponse, AgentSessionOut, AgentSessionDetailOut,
    SyncResultData, HealthData,
)
from ..services.agent_service import (
    AgentService,
    ERR_ORCHESTRATOR_NOT_READY, ERR_SESSION_NOT_FOUND,
    ERR_SESSION_FORBIDDEN, ERR_AGENT_EXEC_FAILED,
)
from ..middleware.log import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/agent", tags=["Agent调度"])


# ==================== 依赖注入 ====================

def get_orchestrator(request: Request):
    """从 app.state 获取全局 orchestrator 实例"""
    orch = getattr(request.app.state, "orchestrator", None)
    if orch is None:
        raise HTTPException(
            status_code=503,
            detail=ApiResponse.error(ERR_ORCHESTRATOR_NOT_READY, "Agent 调度器未就绪").model_dump(),
        )
    return orch


def get_agent_service(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AgentService:
    """获取 AgentService（注入 orchestrator + db）"""
    orch = getattr(request.app.state, "orchestrator", None)
    return AgentService(db=db, orchestrator=orch)


# ==================== 1. 同步执行 ====================

@router.post("/sync", response_model=ApiResponse)
async def agent_sync(
    data: AgentSyncRequest,
    service: AgentService = Depends(get_agent_service),
    current_user: User = Depends(get_current_user),
):
    """同步执行单任务（检索/简历优化/复盘），一次性返回结果"""
    try:
        result: SyncResultData = await service.sync_execute(
            user=current_user,
            user_input=data.user_input,
            session_id=data.session_id,
            user_config=data.user_config,
        )
        return ApiResponse.success(data=result.model_dump())
    except RuntimeError as e:
        logger.error(f"同步执行失败: {e}", exc_info=True)
        return ApiResponse.error(
            code=ERR_AGENT_EXEC_FAILED, message=str(e),
            data={"session_id": data.session_id},
        )
    except Exception as e:
        logger.error(f"同步执行异常: {e}", exc_info=True)
        return ApiResponse.error(code=500, message=f"服务异常: {e}")


# ==================== 2. SSE 流式执行 ====================

@router.post("/stream")
async def agent_stream(
    data: AgentStreamRequest,
    service: AgentService = Depends(get_agent_service),
    current_user: User = Depends(get_current_user),
):
    """
    SSE 流式对话入口（面试模拟、流式简历优化）

    返回 text/event-stream，事件格式:
        data: {"type":"plan","plan":{...}}
        data: {"type":"task_start","task":"interview_agent","response_to_user":"..."}
        data: {"type":"data","content":"..."}
        data: {"type":"review_triggered","session_id":"..."}
        data: {"type":"done","session_id":"...","session_status":"..."}
    """
    async def event_generator():
        try:
            async for sse_str in service.stream_execute(
                user=current_user,
                user_input=data.user_input,
                session_id=data.session_id,
                user_config=data.user_config,
            ):
                # sse_str 形如 "data: {...}\n\n"，解析为 dict 交给 EventSourceResponse
                if sse_str.startswith("data: ") and sse_str.endswith("\n\n"):
                    payload = sse_str[len("data: "):-2]
                    yield {"event": "message", "data": payload}
                else:
                    yield {"event": "message", "data": sse_str}
        except Exception as e:
            err = json.dumps(
                {"type": "error", "message": f"流式执行异常: {e}"},
                ensure_ascii=False,
            )
            yield {"event": "error", "data": err}

    return EventSourceResponse(event_generator())


# ==================== 3. 会话列表 ====================

@router.get("/sessions", response_model=ApiResponse)
async def list_sessions(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    service: AgentService = Depends(get_agent_service),
    current_user: User = Depends(get_current_user),
):
    """分页获取当前登录用户的所有会话列表"""
    items, total = await service.list_sessions_by_user(current_user.id, skip, limit)
    return ApiResponse.success(data={
        "items": [service.to_session_out(s).model_dump() for s in items],
        "total": total,
        "skip": skip,
        "limit": limit,
    })


# ==================== 4. 会话详情 ====================

@router.get("/sessions/{session_id}", response_model=ApiResponse)
async def get_session_detail(
    session_id: str,
    service: AgentService = Depends(get_agent_service),
    current_user: User = Depends(get_current_user),
):
    """获取指定会话详情与完整对话历史"""
    session = await service.get_session_by_id(session_id)
    if not session:
        return ApiResponse.error(ERR_SESSION_NOT_FOUND, "会话不存在")
    if session.user_id != current_user.id:
        return ApiResponse.error(ERR_SESSION_FORBIDDEN, "无权访问此会话")
    detail = await service.to_session_detail_out(session)
    return ApiResponse.success(data=detail.model_dump())


# ==================== 5. 结束会话（面试场景触发复盘）====================

@router.post("/sessions/{session_id}/end", response_model=ApiResponse)
async def end_session(
    session_id: str,
    payload: SessionEndRequest,
    service: AgentService = Depends(get_agent_service),
    current_user: User = Depends(get_current_user),
):
    """手动结束会话，面试场景自动触发复盘 Agent"""
    result = await service.end_session(
        user=current_user, session_id=session_id,
        trigger_review=payload.trigger_review,
    )
    if not result.get("ok"):
        return ApiResponse.error(
            code=result.get("code", 500),
            message=result.get("message", "结束会话失败"),
        )
    return ApiResponse.success(
        data={"session_id": session_id, "review_result": result.get("review_result")},
        message="会话已结束",
    )


# ==================== 6. 删除会话 ====================

@router.delete("/sessions/{session_id}", response_model=ApiResponse)
async def delete_session(
    session_id: str,
    service: AgentService = Depends(get_agent_service),
    current_user: User = Depends(get_current_user),
):
    """删除指定会话及关联对话记录"""
    session = await service.get_session_by_id(session_id)
    if not session:
        return ApiResponse.error(ERR_SESSION_NOT_FOUND, "会话不存在")
    if session.user_id != current_user.id:
        return ApiResponse.error(ERR_SESSION_FORBIDDEN, "无权删除此会话")
    ok = await service.delete_session(session_id)
    if not ok:
        return ApiResponse.error(ERR_SESSION_NOT_FOUND, "会话已不存在")
    return ApiResponse.success(message="会话已删除")


# ==================== 7. 健康检查 ====================

@router.get("/health", response_model=ApiResponse)
async def health_check(
    service: AgentService = Depends(get_agent_service),
):
    """Agent 调度服务健康检查，返回各子 Agent 初始化状态"""
    data = service.health_check()
    return ApiResponse.success(data=data)
