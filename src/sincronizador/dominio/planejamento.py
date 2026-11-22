"""Decide os comandos para o Moodle a partir de um evento do i-Educar. Função pura:
recebe o evento e o estado anterior que importa, devolve um Plano. Quem busca o estado
anterior, publica os comandos e grava o estado novo é a camada de aplicação.

Os comandos descrevem o estado desejado ("este usuário deve existir assim", "este
aluno deve estar neste curso"), não uma ação. Por isso tratar o mesmo evento duas
vezes é inofensivo: gera os mesmos comandos.

O estado anterior só serve para saber o que REMOVER:
- os componentes da última versão da turma (componente que saiu → ocultar o curso);
- as inscrições já pedidas para o usuário (as que saíram → desinscrever).
"""

from dataclasses import dataclass, field

from sincronizador.dominio import regras


@dataclass(frozen=True)
class Comando:
    tipo: str  # ex.: moodle.usuario.sincronizar
    dados: dict


@dataclass
class Plano:
    comandos: list[Comando] = field(default_factory=list)
    # Estado a gravar depois de publicar os comandos.
    turma_gravar: dict | None = None
    turma_apagar: int | None = None
    inscricoes_adicionar: set[tuple[str, str, str]] = field(default_factory=set)
    inscricoes_remover: set[tuple[str, str, str]] = field(default_factory=set)


def planejar_turma(turma: dict, anterior: dict | None) -> Plano:
    """Turma ativa: um curso visível por componente. Componentes que saíram desde a
    versão anterior (ou todos, se a turma foi desativada ou removida): curso oculto."""
    plano = Plano()
    if turma["ativa"]:
        for curso in regras.cursos_da_turma(turma, visivel=True):
            plano.comandos.append(Comando("moodle.curso.sincronizar", curso))
        plano.turma_gravar = turma
    else:
        plano.turma_apagar = turma["turma_id"]
    if anterior:
        atuais = {c["id"] for c in turma["componentes"]} if turma["ativa"] else set()
        saiu = {
            **anterior,
            "componentes": [c for c in anterior["componentes"] if c["id"] not in atuais],
        }
        for curso in regras.cursos_da_turma(saiu, visivel=False):
            plano.comandos.append(Comando("moodle.curso.sincronizar", curso))
    return plano


def planejar_usuario(usuario: dict, papel: str, cursos: set[str], antes: set[str]) -> Plano:
    """O usuário como deve estar e as inscrições dele no papel: adiciona todas as
    desejadas (é idempotente) e remove as que estavam em `antes` e saíram."""
    plano = Plano(comandos=[Comando("moodle.usuario.sincronizar", usuario)])
    idnumber = usuario["idnumber"]
    for curso in sorted(cursos):
        plano.comandos.append(
            Comando(
                "moodle.inscricao.adicionar", {"usuario": idnumber, "curso": curso, "papel": papel}
            )
        )
        plano.inscricoes_adicionar.add((idnumber, curso, papel))
    for curso in sorted(antes - cursos):
        plano.comandos.append(
            Comando(
                "moodle.inscricao.remover", {"usuario": idnumber, "curso": curso, "papel": papel}
            )
        )
        plano.inscricoes_remover.add((idnumber, curso, papel))
    return plano


def entidade(tipo_evento: str, dados: dict) -> str:
    """Chave da entidade do evento: "turma:10", "servidor:7", "aluno:20"."""
    tipo = tipo_evento.split(".")[1]
    return f"{tipo}:{dados[f'{tipo}_id']}"
