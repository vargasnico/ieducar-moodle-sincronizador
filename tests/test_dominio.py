"""Domínio puro: regras e planejamento, sem banco nem broker."""

from sincronizador.dominio import regras, versao
from sincronizador.dominio.planejamento import entidade, planejar_turma, planejar_usuario

TURMA = {
    "turma_id": 10,
    "nome": "1º ano A",
    "ano": 2026,
    "ativa": True,
    "componentes": [{"id": 1, "nome": "Português"}, {"id": 2, "nome": "Matemática"}],
}


def test_professor_precisa_de_vinculo():
    servidor = {
        "servidor_id": 7,
        "nome": "Ana Souza",
        "cpf": "123",
        "email": None,
        "ativo": True,
        "vinculos": [{"turma_id": 10, "componentes": [1]}],
    }
    usuario, cursos = regras.professor(servidor)
    assert usuario["username"] == "123" and not usuario["suspenso"]
    assert cursos == {"ieducar-turma-10-componente-1"}
    usuario, cursos = regras.professor({**servidor, "vinculos": []})
    assert usuario["suspenso"] and cursos == set()


def test_turma_desativada_oculta_todos_os_cursos_anteriores():
    plano = planejar_turma({**TURMA, "ativa": False, "componentes": []}, anterior=TURMA)
    assert [c.dados["visivel"] for c in plano.comandos] == [False, False]
    assert plano.turma_apagar == 10


def test_usuario_remove_so_o_que_saiu():
    plano = planejar_usuario({"idnumber": "u"}, "student", {"c1"}, antes={"c1", "c2"})
    assert [c.tipo for c in plano.comandos] == [
        "moodle.usuario.sincronizar",
        "moodle.inscricao.adicionar",
        "moodle.inscricao.remover",
    ]
    assert plano.inscricoes_remover == {("u", "c2", "student")}


def test_entidade_e_versao():
    from datetime import UTC, datetime

    assert entidade("ieducar.aluno.alterado", {"aluno_id": 20}) == "aluno:20"
    antes, depois = datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC)
    assert versao.obsoleta(depois, antes) and not versao.obsoleta(antes, depois)
    assert not versao.obsoleta(None, antes)
