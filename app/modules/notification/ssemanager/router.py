from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from app.modules.users.model import User
from app.shared.dependencies.auth import get_current_user

from .manager import SSEConnectionService, SSEService, notification_store

sse_connection_service = SSEConnectionService(notification_store)
sse_service_instance = SSEService(sse_connection_service)


def get_sse_service() -> SSEService:
    return sse_service_instance


router = APIRouter(prefix="/alerte_notifications", tags=["Alerte_Notifications"])


@router.get("/stream/")
async def notification_stream(
    request: Request,
    sse_service: SSEService = Depends(get_sse_service),
    current_user: User = Depends(get_current_user),
):
    # Ces en-têtes sont nécessaires derrière Nginx/Traefik/etc. : sans eux,
    # le proxy peut bufferiser les événements et ne les transmettre qu'à la
    # fermeture de la connexion, ce qui donne l'impression que le temps réel
    # ne fonctionne qu'après une reconnexion.
    return EventSourceResponse(
        sse_service.stream(current_user.id, request),
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
