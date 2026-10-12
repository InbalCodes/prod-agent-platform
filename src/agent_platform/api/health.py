"""Liveness and readiness probes.

- live:  "is the process alive?" Never checks dependencies — if the DB is down,
         restarting every API container does not fix the DB, it just adds an outage.
- ready: "should the load balancer send me traffic?" False until startup has
         finished; later it will also check critical dependencies.
"""

from fastapi import APIRouter, Request, Response, status

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request, response: Response) -> dict[str, str]:
    if not request.app.state.ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready"}
    return {"status": "ready"}
