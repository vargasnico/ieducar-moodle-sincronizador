"""Formato das mensagens trocadas pelos serviços: é o contrato entre eles.

O nome de uma mensagem é `<tipo>.v<versao>` (ex.: `ieducar.aluno.alterado.v1`) e é
também a routing key no RabbitMQ. O catálogo de mensagens fica no repositório de
orquestração (ieducar-moodle-integration, docs/architecture.md). Cada serviço tem a
sua cópia deste arquivo; uma mudança incompatível no formato vira uma versão nova.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


def agora() -> datetime:
    return datetime.now(UTC)


class Mensagem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tipo: str
    versao: int = 1
    # Identifica uma sincronização (um ciclo do detector) em todos os serviços.
    correlation_id: str
    # Quando o ciclo do detector começou: usado para medir o tempo de sincronização.
    ciclo_iniciado_em: datetime
    ocorrido_em: datetime = Field(default_factory=agora)
    dados: dict[str, Any]

    @property
    def routing_key(self) -> str:
        return f"{self.tipo}.v{self.versao}"

    def derivar(self, tipo: str, dados: dict[str, Any]) -> Mensagem:
        """Nova mensagem causada por esta, na mesma sincronização."""
        return Mensagem(
            tipo=tipo,
            correlation_id=self.correlation_id,
            ciclo_iniciado_em=self.ciclo_iniciado_em,
            dados=dados,
        )
