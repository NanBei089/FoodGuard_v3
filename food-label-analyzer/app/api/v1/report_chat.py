"""接口入口，只做参数接收、权限检查和响应返回，具体业务交给 service。"""


from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.common import ApiResponse, success_response
from app.schemas.report_chat import (
    ReportChatAskRequest,
    ReportChatSuggestionsResponse,
    ReportConversationResponse,
)
from app.services.report_chat_service import (
    get_or_generate_suggestions,
    get_report_conversation,
    stream_report_chat,
)

router = APIRouter()


@router.get(
    "/{report_id}/chat",
    response_model=ApiResponse[ReportConversationResponse | None],
    summary="获取报告专属问答会话",
    description="返回当前报告绑定的单线程对话记录；若会话尚未开始，则返回空数据。",
    responses={
        200: {"description": "查询成功"},
        401: {"description": "未认证"},
        404: {"description": "报告不存在"},
    },
)
async def get_chat(
    report_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ReportConversationResponse | None]:
    payload = await get_report_conversation(report_id, current_user.id, db)
    return success_response(payload)


@router.post(
    "/{report_id}/chat/suggestions",
    response_model=ApiResponse[ReportChatSuggestionsResponse],
    summary="获取报告专属快捷提问",
    description="返回当前报告的快捷提问；若尚未生成则按需调用模型生成。",
    responses={
        200: {"description": "查询成功"},
        401: {"description": "未认证"},
        404: {"description": "报告不存在"},
    },
)
async def get_chat_suggestions(
    report_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ReportChatSuggestionsResponse]:
    payload = await get_or_generate_suggestions(report_id, current_user.id, db)
    return success_response(payload)


@router.post(
    "/{report_id}/chat/stream",
    summary="流式生成报告专属问答回答",
    description="持久化用户问题后，以 SSE 形式流式返回当前报告专属助手的回答。",
    responses={
        200: {
            "description": "SSE stream",
            "content": {
                "text/event-stream": {
                    "schema": {"type": "string"}
                }
            },
        },
        401: {"description": "未认证"},
        404: {"description": "报告不存在"},
        422: {"description": "请求参数错误"},
        503: {"description": "大模型服务暂不可用"},
    },
)
async def stream_chat(
    report_id: UUID,
    request: ReportChatAskRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    stream = await stream_report_chat(report_id, current_user.id, request.message, db)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = ["router"]
