"""Versão por entidade: descarta mensagens mais antigas do que a última aplicada.

Toda mensagem leva `ciclo_iniciado_em`, o início do ciclo do detector que a originou.
Ele funciona como versão: um ciclo posterior sempre descreve um estado mais novo do
i-Educar. Para cada entidade guardamos o ciclo da última mensagem aplicada, e uma
mensagem de um ciclo anterior é descartada em vez de aplicada.

Isso torna seguro reprocessar a DLQ (uma mensagem que ficou lá enquanto uma mais nova
da mesma entidade passou não desfaz a mais nova) e resolve as mensagens que saem fora
de ordem pela fila de retry. Só o detector gera essa marca, então os horários vêm
sempre do mesmo relógio.
"""

import sqlite3
from datetime import datetime


class Versoes:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db
        db.execute("CREATE TABLE IF NOT EXISTS versao (chave TEXT PRIMARY KEY, ciclo TEXT)")

    def obsoleta(self, chave: str, ciclo: datetime) -> bool:
        """True se já foi aplicada uma mensagem de um ciclo posterior."""
        linha = self.db.execute("SELECT ciclo FROM versao WHERE chave = ?", (chave,)).fetchone()
        return linha is not None and datetime.fromisoformat(linha[0]) > ciclo

    def registrar(self, chave: str, ciclo: datetime) -> None:
        if not self.obsoleta(chave, ciclo):
            with self.db:
                self.db.execute(
                    "INSERT OR REPLACE INTO versao VALUES (?, ?)", (chave, ciclo.isoformat())
                )
