"""Regras e sincronizador, sem rede (broker falso)."""

import sqlite3
from datetime import UTC, datetime

import pytest

from sincronizador.mensagem import Mensagem
from sincronizador.sincronizacao import Sincronizador


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def msg(tipo: str, dados: dict) -> Mensagem:
    return Mensagem(
        tipo=tipo, correlation_id="c1", ciclo_iniciado_em=datetime.now(UTC), dados=dados
    )


class BrokerFalso:
    def __init__(self) -> None:
        self.publicadas: list[Mensagem] = []

    async def publicar(self, mensagem: Mensagem) -> None:
        self.publicadas.append(mensagem)

    def tipos(self) -> list[str]:
        return [m.tipo for m in self.publicadas]


TURMA = {
    "turma_id": 10,
    "nome": "1º ano A",
    "ano": 2026,
    "ativa": True,
    "componentes": [{"id": 1, "nome": "Português"}, {"id": 2, "nome": "Matemática"}],
}


def aluno(turmas: list) -> dict:
    return {"aluno_id": 20, "nome": "Carla Dias", "ativo": True, "turmas": turmas}


# --- Sincronizador -----------------------------------------------------------


@pytest.fixture
def sync():
    broker = BrokerFalso()
    return Sincronizador(sqlite3.connect(":memory:"), broker), broker  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_turma_vira_um_curso_por_componente(sync):
    s, broker = sync
    await s.tratar(msg("ieducar.turma.alterada", TURMA))
    assert [m.dados["idnumber"] for m in broker.publicadas] == [
        "ieducar-turma-10-componente-1",
        "ieducar-turma-10-componente-2",
    ]


@pytest.mark.anyio
async def test_componente_retirado_oculta_o_curso(sync):
    s, broker = sync
    await s.tratar(msg("ieducar.turma.alterada", TURMA))
    broker.publicadas.clear()
    await s.tratar(
        msg("ieducar.turma.alterada", {**TURMA, "componentes": TURMA["componentes"][:1]})
    )
    ocultos = [m.dados["idnumber"] for m in broker.publicadas if not m.dados["visivel"]]
    assert ocultos == ["ieducar-turma-10-componente-2"]


@pytest.mark.anyio
async def test_aluno_e_inscrito_e_desinscrito_ao_ganhar_dispensa(sync):
    s, broker = sync
    await s.tratar(msg("ieducar.aluno.alterado", aluno([{"turma_id": 10, "componentes": [1, 2]}])))
    assert broker.tipos().count("moodle.inscricao.adicionar") == 2
    broker.publicadas.clear()
    await s.tratar(msg("ieducar.aluno.alterado", aluno([{"turma_id": 10, "componentes": [1]}])))
    removidas = [
        m.dados["curso"] for m in broker.publicadas if m.tipo == "moodle.inscricao.remover"
    ]
    assert removidas == ["ieducar-turma-10-componente-2"]


@pytest.mark.anyio
async def test_aluno_removido_e_suspenso_e_desinscrito(sync):
    s, broker = sync
    await s.tratar(msg("ieducar.aluno.alterado", aluno([{"turma_id": 10, "componentes": [1]}])))
    broker.publicadas.clear()
    await s.tratar(msg("ieducar.aluno.removido", {"aluno_id": 20}))
    assert broker.publicadas[0].dados == {"idnumber": "ieducar-aluno-20", "suspenso": True}
    assert broker.tipos()[1:] == ["moodle.inscricao.remover"]


@pytest.mark.anyio
async def test_mesmo_evento_duas_vezes_gera_os_mesmos_comandos(sync):
    s, broker = sync
    evento = msg("ieducar.aluno.alterado", aluno([{"turma_id": 10, "componentes": [1, 2]}]))
    await s.tratar(evento)
    primeira = [m.dados for m in broker.publicadas]
    broker.publicadas.clear()
    await s.tratar(evento)
    assert [m.dados for m in broker.publicadas] == primeira


@pytest.mark.anyio
async def test_servidor_sem_turma_e_suspenso(sync):
    s, broker = sync
    servidor = {
        "servidor_id": 7,
        "nome": "Ana Souza",
        "cpf": "123",
        "email": "a@x",
        "ativo": True,
        "vinculos": [],
    }
    await s.tratar(msg("ieducar.servidor.alterado", servidor))
    assert broker.tipos() == ["moodle.usuario.sincronizar"]
    assert broker.publicadas[0].dados["suspenso"] is True


@pytest.mark.anyio
async def test_evento_antigo_reprocessado_da_dlq_e_descartado(sync):
    """O evento do ciclo 1 ficou na DLQ; o do ciclo 2 (aluno dispensado de Matemática)
    passou. Reprocessar o do ciclo 1 não pode reinscrever o aluno."""
    s, broker = sync
    ciclo1 = msg("ieducar.aluno.alterado", aluno([{"turma_id": 10, "componentes": [1, 2]}]))
    ciclo2 = msg("ieducar.aluno.alterado", aluno([{"turma_id": 10, "componentes": [1]}]))
    await s.tratar(ciclo2)
    broker.publicadas.clear()
    await s.tratar(ciclo1)
    assert broker.publicadas == []
    cursos = {c for (c,) in s.db.execute("SELECT curso FROM inscricao")}
    assert cursos == {"ieducar-turma-10-componente-1"}
