"""Serviço sincronizador: aplica as regras da integração aos eventos do i-Educar e
publica comandos para o Moodle. Não fala com nenhum sistema externo.

Dono do banco sincronizador.db (turmas e inscrições já pedidas).
"""

import os
import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI

from sincronizador.api import rotas_comuns
from sincronizador.broker import Broker
from sincronizador.logs import configurar_logs
from sincronizador.sincronizacao import Sincronizador


@asynccontextmanager
async def lifespan(app: FastAPI):
    configurar_logs("sincronizador")
    db = sqlite3.connect(os.environ.get("DATABASE_PATH", "data/sincronizador.db"))
    broker = Broker(
        os.environ.get("RABBITMQ_URL", "amqp://guest:guest@localhost/"), "sincronizador"
    )
    await broker.conectar()
    sincronizador = Sincronizador(db, broker)
    app.state.broker, app.state.db = broker, db
    # prefetch=1: um evento por vez, na ordem em que o detector publicou.
    await broker.consumir("sincronizador", "ieducar.#", sincronizador.tratar, prefetch=1)
    yield
    await broker.fechar()


app = FastAPI(title="Sincronizador i-Educar → Moodle", lifespan=lifespan)
rotas_comuns(app)


@app.get("/inscricoes", tags=["consulta"])
async def inscricoes() -> dict:
    """Quantas inscrições o sincronizador pediu, por papel."""
    linhas = app.state.db.execute("SELECT papel, COUNT(*) FROM inscricao GROUP BY papel")
    return dict(linhas.fetchall())


@app.post("/dlq/reprocessar", tags=["filas"])
async def reprocessar_dlq() -> dict:
    """Devolve à fila as mensagens que foram para a DLQ."""
    return {"reprocessadas": await app.state.broker.reprocessar_dlq("sincronizador")}
