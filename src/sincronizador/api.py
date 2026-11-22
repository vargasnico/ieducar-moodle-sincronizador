"""Rotas comuns aos três serviços: health check e métricas."""

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest


def rotas_comuns(app: FastAPI) -> None:
    @app.get("/health", tags=["status"])
    def health(request: Request) -> JSONResponse:
        """O serviço está no ar e conectado ao RabbitMQ."""
        broker = request.app.state.broker
        ok = broker.conectado
        return JSONResponse(
            {"status": "ok" if ok else "sem broker", "broker": ok}, status_code=200 if ok else 503
        )

    @app.get("/metrics", tags=["status"], include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
