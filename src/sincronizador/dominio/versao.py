"""Regra de versão: toda mensagem leva `ciclo_iniciado_em`, o início do ciclo do
detector que a originou, e um ciclo posterior sempre descreve um estado mais novo do
i-Educar. Uma mensagem de um ciclo anterior ao último já tratado para a mesma
entidade está obsoleta (ex.: reprocessada da DLQ depois que uma mais nova passou) e
é descartada, para não desfazer o estado mais novo."""

from datetime import datetime


def obsoleta(ultimo_tratado: datetime | None, ciclo: datetime) -> bool:
    return ultimo_tratado is not None and ultimo_tratado > ciclo
