"""Caso de uso: tratar um evento do i-Educar.

1. Descarta o evento se já foi tratada uma versão mais nova da mesma entidade.
2. Busca o estado anterior que o domínio precisa e pede o plano a ele.
3. Publica os comandos e SÓ DEPOIS grava o estado. Se o serviço cair entre os dois, o
   RabbitMQ entrega o evento de novo e tudo é recalculado (cenário 4); o contrário
   (gravar e não publicar) perderia comandos.
"""

import logging

from sincronizador.dominio import regras, versao
from sincronizador.dominio.planejamento import (
    Plano,
    entidade,
    planejar_turma,
    planejar_usuario,
)
from sincronizador.infra.metricas import COMANDOS, OBSOLETOS
from sincronizador.mensagem import Mensagem
from sincronizador.portas import EstadoSincronizacao, PublicadorDeComandos

log = logging.getLogger(__name__)


class TratarEvento:
    def __init__(self, estado: EstadoSincronizacao, publicador: PublicadorDeComandos) -> None:
        self.estado = estado
        self.publicador = publicador

    async def __call__(self, evento: Mensagem) -> None:
        chave = entidade(evento.tipo, evento.dados)
        if versao.obsoleta(self.estado.ultimo_ciclo(chave), evento.ciclo_iniciado_em):
            log.warning(
                "%s de %s descartado: já foi tratada uma versão mais nova",
                evento.routing_key,
                chave,
            )
            OBSOLETOS.labels(evento.routing_key).inc()
            return
        plano = self._planejar(evento)
        for comando in plano.comandos:
            mensagem = evento.derivar(comando.tipo, comando.dados)
            await self.publicador.publicar(mensagem)
            COMANDOS.labels(mensagem.routing_key).inc()
        self.estado.gravar(plano, chave, evento.ciclo_iniciado_em)
        log.info("%s → %s comando(s)", evento.routing_key, len(plano.comandos))

    def _planejar(self, evento: Mensagem) -> Plano:
        d = evento.dados
        match evento.tipo:
            case "ieducar.turma.alterada":
                return planejar_turma(d, self.estado.turma(d["turma_id"]))
            case "ieducar.turma.removida":
                removida = {"turma_id": d["turma_id"], "ativa": False, "componentes": []}
                return planejar_turma(removida, self.estado.turma(d["turma_id"]))
            case "ieducar.servidor.alterado":
                usuario, cursos = regras.professor(d)
                return self._usuario(usuario, regras.EDITINGTEACHER, cursos)
            case "ieducar.servidor.removido":
                suspenso = {"idnumber": regras.usuario_servidor(d["servidor_id"]), "suspenso": True}
                return self._usuario(suspenso, regras.EDITINGTEACHER, set())
            case "ieducar.aluno.alterado":
                usuario, cursos = regras.aluno(d)
                return self._usuario(usuario, regras.STUDENT, cursos)
            case "ieducar.aluno.removido":
                suspenso = {"idnumber": regras.usuario_aluno(d["aluno_id"]), "suspenso": True}
                return self._usuario(suspenso, regras.STUDENT, set())
        log.warning("Evento desconhecido ignorado: %s", evento.routing_key)
        return Plano()

    def _usuario(self, usuario: dict, papel: str, cursos: set[str]) -> Plano:
        antes = self.estado.cursos_inscritos(usuario["idnumber"], papel)
        return planejar_usuario(usuario, papel, cursos, antes)
