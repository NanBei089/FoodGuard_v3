"""接口入口，只做参数接收、权限检查和响应返回，具体业务交给 service。"""


from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.analysis import router as analysis_router
from app.api.v1.auth import router as auth_router
from app.api.v1.metrics import router as metrics_router
from app.api.v1.preferences import router as preferences_router
from app.api.v1.report_chat import router as report_chat_router
from app.api.v1.reports import router as reports_router
from app.api.v1.users import router as users_router

api_router = APIRouter()
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(analysis_router, prefix="/analysis", tags=["analysis"])
api_router.include_router(reports_router, prefix="/reports", tags=["reports"])
api_router.include_router(report_chat_router, prefix="/reports", tags=["reports"])
api_router.include_router(users_router, prefix="/users", tags=["users"])
api_router.include_router(metrics_router, prefix="/metrics", tags=["metrics"])
api_router.include_router(
    preferences_router, prefix="/preferences", tags=["preferences"]
)


__all__ = ["api_router"]
