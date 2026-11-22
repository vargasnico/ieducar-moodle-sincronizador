"""Adaptador da porta EstadoSincronizacao sobre SQLite (o banco só deste serviço)."""

import json
import sqlite3
from datetime import datetime

from sincronizador.dominio.planejamento import Plano


class EstadoSqlite:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db
        db.executescript("""
            CREATE TABLE IF NOT EXISTS turma (turma_id INTEGER PRIMARY KEY, dados TEXT);
            CREATE TABLE IF NOT EXISTS inscricao (
                usuario TEXT, curso TEXT, papel TEXT, PRIMARY KEY (usuario, curso, papel)
            );
            CREATE TABLE IF NOT EXISTS versao (chave TEXT PRIMARY KEY, ciclo TEXT);
        """)

    def turma(self, turma_id: int) -> dict | None:
        linha = self.db.execute(
            "SELECT dados FROM turma WHERE turma_id = ?", (turma_id,)
        ).fetchone()
        return json.loads(linha[0]) if linha else None

    def cursos_inscritos(self, usuario: str, papel: str) -> set[str]:
        linhas = self.db.execute(
            "SELECT curso FROM inscricao WHERE usuario = ? AND papel = ?", (usuario, papel)
        )
        return {curso for (curso,) in linhas}

    def ultimo_ciclo(self, entidade: str) -> datetime | None:
        linha = self.db.execute("SELECT ciclo FROM versao WHERE chave = ?", (entidade,)).fetchone()
        return datetime.fromisoformat(linha[0]) if linha else None

    def gravar(self, plano: Plano, entidade: str, ciclo: datetime) -> None:
        with self.db:  # uma transação
            if plano.turma_gravar:
                t = plano.turma_gravar
                self.db.execute(
                    "INSERT OR REPLACE INTO turma VALUES (?, ?)", (t["turma_id"], json.dumps(t))
                )
            if plano.turma_apagar is not None:
                self.db.execute("DELETE FROM turma WHERE turma_id = ?", (plano.turma_apagar,))
            self.db.executemany(
                "INSERT OR IGNORE INTO inscricao VALUES (?, ?, ?)", plano.inscricoes_adicionar
            )
            self.db.executemany(
                "DELETE FROM inscricao WHERE usuario = ? AND curso = ? AND papel = ?",
                plano.inscricoes_remover,
            )
            self.db.execute(
                "INSERT INTO versao VALUES (?, ?) ON CONFLICT (chave) DO UPDATE"
                " SET ciclo = MAX(ciclo, excluded.ciclo)",
                (entidade, ciclo.isoformat()),
            )

    def contar_inscricoes(self) -> dict[str, int]:
        return dict(self.db.execute("SELECT papel, COUNT(*) FROM inscricao GROUP BY papel"))
