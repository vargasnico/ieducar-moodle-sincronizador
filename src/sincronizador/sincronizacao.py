"""Transforma eventos do i-Educar em comandos para o Moodle.

Cada comando descreve o estado desejado ("este usuário deve existir assim", "este
aluno deve estar neste curso"), não uma ação. Por isso tratar o mesmo evento duas
vezes é inofensivo: gera os mesmos comandos, e aplicá-los de novo não muda nada.

O sincronizador guarda só o necessário para saber o que REMOVER:
- turma: os componentes da última versão (componente que saiu → ocultar o curso);
- inscricao: as inscrições que ele já pediu (as que saíram → desinscrever).

Ordem: publica os comandos e só depois grava o estado. Se cair entre os dois, o
RabbitMQ entrega o evento de novo e tudo é recalculado (cenário 4).
"""

import json
import logging
import sqlite3

from sincronizador import regras
from sincronizador.broker import Broker
from sincronizador.mensagem import Mensagem
from sincronizador.metricas import COMANDOS

log = logging.getLogger(__name__)


class Sincronizador:
    def __init__(self, db: sqlite3.Connection, broker: Broker) -> None:
        self.db = db
        self.broker = broker
        db.executescript("""
            CREATE TABLE IF NOT EXISTS turma (turma_id INTEGER PRIMARY KEY, dados TEXT);
            CREATE TABLE IF NOT EXISTS inscricao (
                usuario TEXT, curso TEXT, papel TEXT, PRIMARY KEY (usuario, curso, papel)
            );
        """)

    async def tratar(self, evento: Mensagem) -> None:
        self._evento = evento
        self._comandos: list[Mensagem] = []
        self._gravar: list[tuple[str, tuple]] = []
        d = evento.dados
        match evento.tipo:
            case "ieducar.turma.alterada":
                self._turma(d)
            case "ieducar.turma.removida":
                self._turma({"turma_id": d["turma_id"], "ativa": False, "componentes": []})
            case "ieducar.servidor.alterado":
                usuario, cursos = regras.professor(d)
                self._usuario(usuario, regras.EDITINGTEACHER, cursos)
            case "ieducar.servidor.removido":
                self._usuario(
                    {"idnumber": regras.usuario_servidor(d["servidor_id"]), "suspenso": True},
                    regras.EDITINGTEACHER,
                    set(),
                )
            case "ieducar.aluno.alterado":
                usuario, cursos = regras.aluno(d)
                self._usuario(usuario, regras.STUDENT, cursos)
            case "ieducar.aluno.removido":
                self._usuario(
                    {"idnumber": regras.usuario_aluno(d["aluno_id"]), "suspenso": True},
                    regras.STUDENT,
                    set(),
                )
            case _:
                log.warning("Evento desconhecido ignorado: %s", evento.routing_key)
        # 1º publica, 2º grava (ver docstring do módulo).
        for comando in self._comandos:
            await self.broker.publicar(comando)
            COMANDOS.labels(comando.routing_key).inc()
        with self.db:
            for sql, params in self._gravar:
                self.db.execute(sql, params)
        log.info("%s → %s comando(s)", evento.routing_key, len(self._comandos))

    def _comando(self, tipo: str, dados: dict) -> None:
        self._comandos.append(self._evento.derivar(tipo, dados))

    def _turma(self, turma: dict) -> None:
        linha = self.db.execute(
            "SELECT dados FROM turma WHERE turma_id = ?", (turma["turma_id"],)
        ).fetchone()
        anterior = json.loads(linha[0]) if linha else None
        atuais = {c["id"] for c in turma["componentes"]}
        if turma["ativa"]:
            for curso in regras.cursos_da_turma(turma, visivel=True):
                self._comando("moodle.curso.sincronizar", curso)
        if anterior:
            # Componentes que saíram (ou a turma inteira, se desativada): ocultar.
            saiu = {
                **anterior,
                "componentes": [
                    c
                    for c in anterior["componentes"]
                    if not turma["ativa"] or c["id"] not in atuais
                ],
            }
            for curso in regras.cursos_da_turma(saiu, visivel=False):
                self._comando("moodle.curso.sincronizar", curso)
        if turma["ativa"]:
            self._gravar.append(
                (
                    "INSERT OR REPLACE INTO turma VALUES (?, ?)",
                    (turma["turma_id"], json.dumps(turma)),
                )
            )
        else:
            self._gravar.append(("DELETE FROM turma WHERE turma_id = ?", (turma["turma_id"],)))

    def _usuario(self, usuario: dict, papel: str, cursos: set[str]) -> None:
        self._comando("moodle.usuario.sincronizar", usuario)
        idnumber = usuario["idnumber"]
        antes = {
            c
            for (c,) in self.db.execute(
                "SELECT curso FROM inscricao WHERE usuario = ? AND papel = ?", (idnumber, papel)
            )
        }
        for curso in sorted(cursos):
            self._comando(
                "moodle.inscricao.adicionar", {"usuario": idnumber, "curso": curso, "papel": papel}
            )
            self._gravar.append(
                ("INSERT OR IGNORE INTO inscricao VALUES (?, ?, ?)", (idnumber, curso, papel))
            )
        for curso in sorted(antes - cursos):
            self._comando(
                "moodle.inscricao.remover", {"usuario": idnumber, "curso": curso, "papel": papel}
            )
            self._gravar.append(
                (
                    "DELETE FROM inscricao WHERE usuario = ? AND curso = ? AND papel = ?",
                    (idnumber, curso, papel),
                )
            )
