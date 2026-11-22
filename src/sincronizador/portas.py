"""Portas: o que o caso de uso precisa do mundo externo, sem saber como é feito.

Os adaptadores (adaptadores/sqlite.py, adaptadores/rabbitmq.py) as implementam; os
testes usam versões em memória.
"""

from datetime import datetime
from typing import Protocol

from sincronizador.dominio.planejamento import Plano
from sincronizador.mensagem import Mensagem


class EstadoSincronizacao(Protocol):
    """O que o sincronizador lembra entre um evento e outro."""

    def turma(self, turma_id: int) -> dict | None:
        """Última versão tratada da turma."""
        ...

    def cursos_inscritos(self, usuario: str, papel: str) -> set[str]:
        """Cursos em que já foi pedida a inscrição do usuário no papel."""
        ...

    def ultimo_ciclo(self, entidade: str) -> datetime | None:
        """Ciclo do último evento tratado da entidade."""
        ...

    def gravar(self, plano: Plano, entidade: str, ciclo: datetime) -> None:
        """Grava o estado do plano e a versão da entidade, numa transação."""
        ...


class PublicadorDeComandos(Protocol):
    async def publicar(self, mensagem: Mensagem) -> None: ...
