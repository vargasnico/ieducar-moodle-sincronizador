"""Adaptador de entrada HTTP: health check, métricas, consulta e reprocessamento da DLQ."""

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest


def criar_app(lifespan) -> FastAPI:
    app = FastAPI(title="Sincronizador i-Educar → Moodle", lifespan=lifespan)

    @app.get("/health", tags=["status"])
    def health(request: Request) -> JSONResponse:
        """O serviço está no ar e conectado ao RabbitMQ."""
        ok = request.app.state.broker.conectado
        return JSONResponse(
            {"status": "ok" if ok else "sem broker", "broker": ok}, status_code=200 if ok else 503
        )

    @app.get("/metrics", tags=["status"], include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/inscricoes", tags=["consulta"])
    async def inscricoes(request: Request) -> dict:
        """Quantas inscrições o sincronizador pediu, por papel."""
        return request.app.state.estado.contar_inscricoes()

    @app.post("/dlq/reprocessar", tags=["filas"])
    async def reprocessar_dlq(request: Request) -> dict:
        """Devolve à fila os eventos que foram para a DLQ."""
        return {"reprocessadas": await request.app.state.broker.reprocessar_dlq("sincronizador")}

    return app
