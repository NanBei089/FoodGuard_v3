"""接口入口，只做参数接收、权限检查和响应返回，具体业务交给 service。"""


from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.metrics import get_metrics_snapshot
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.common import ApiResponse, success_response
from app.schemas.metrics import MetricsSnapshotResponse

router = APIRouter()


@router.get(
    "",
    response_model=ApiResponse[MetricsSnapshotResponse],
    summary="Get current process metrics snapshot",
    description=(
        "Return the current process histogram and counter snapshot for backend "
        "observability and debugging."
    ),
    responses={
        200: {"description": "Metrics snapshot fetched successfully"},
        401: {"description": "Authentication required"},
    },
)
async def get_metrics(
    _: User = Depends(get_current_user),
) -> ApiResponse[MetricsSnapshotResponse]:
    payload = MetricsSnapshotResponse.model_validate(get_metrics_snapshot())
    return success_response(payload)


__all__ = ["router"]
