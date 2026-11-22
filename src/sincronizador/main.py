"""Serviço sincronizador: aplica as regras da integração aos eventos do i-Educar e
publica comandos para o Moodle. Não fala com nenhum sistema externo.

Este arquivo só compõe as peças (arquitetura hexagonal):

    adaptadores/rabbitmq.py ──evento──▶ aplicacao/tratar_evento.py ──▶ dominio/
                                              │ portas.py
                         adaptadores/sqlite.py ◀┘└▶ adaptadores/rabbitmq.py (comandos)
"""

import os
import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI

from sincronizador.adaptadores.api import criar_app
from sincronizador.adaptadores.rabbitmq import Broker
from sincronizador.adaptadores.sqlite import EstadoSqlite
from sincronizador.aplicacao.tratar_evento import TratarEvento
from sincronizador.infra.logs import configurar_logs


@asynccontextmanager
async def lifespan(app: FastAPI):
    configurar_logs("sincronizador")
    estado = EstadoSqlite(sqlite3.connect(os.environ.get("DATABASE_PATH", "data/sincronizador.db")))
    broker = Broker(
        os.environ.get("RABBITMQ_URL", "amqp://guest:guest@localhost/"), "sincronizador"
    )
    await broker.conectar()
    tratar_evento = TratarEvento(estado, publicador=broker)
    app.state.broker, app.state.estado = broker, estado
    # prefetch=1: um evento por vez, na ordem em que o detector publicou.
    await broker.consumir("sincronizador", "ieducar.#", tratar_evento, prefetch=1)
    yield
    await broker.fechar()


app = criar_app(lifespan)
