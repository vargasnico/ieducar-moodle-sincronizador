"""RabbitMQ: publicação e consumo com retry e dead-letter queue.

Todos os serviços publicam na exchange "integracao" (topic), com a routing key
`<tipo>.v<versao>`. Cada consumidor declara só a PRÓPRIA fila, com duas auxiliares:

    F        fila principal, ligada à exchange pelas routing keys que interessam
    F.retry  sem consumidor; a mensagem espera ATRASO_RETRY segundos (TTL) e volta
             para F. Assim uma mensagem que falhou sai da frente e as outras seguem.
    F.dlq    mensagens que falharam MAX_TENTATIVAS vezes. Ficam lá até alguém
             reprocessá-las (POST /dlq/reprocessar).

Este arquivo é igual nos três serviços (cada repositório tem a sua cópia): o que os
serviços compartilham é o formato das mensagens, não código.
"""

import logging
from collections.abc import Awaitable, Callable

import aio_pika
from aio_pika.abc import AbstractIncomingMessage

from sincronizador.logs import correlation_id
from sincronizador.mensagem import Mensagem
from sincronizador.metricas import MENSAGENS

log = logging.getLogger(__name__)

EXCHANGE = "integracao"
MAX_TENTATIVAS = 5
ATRASO_RETRY = 10  # segundos


class Broker:
    def __init__(self, url: str, servico: str) -> None:
        self.url = url
        self.servico = servico
        self.conexao: aio_pika.abc.AbstractRobustConnection | None = None

    async def conectar(self) -> None:
        # connect_robust reconecta sozinho se o RabbitMQ cair.
        self.conexao = await aio_pika.connect_robust(self.url)
        # publisher_confirms: publish() só retorna depois que o broker gravou a mensagem.
        self.canal = await self.conexao.channel(publisher_confirms=True)
        self.exchange = await self.canal.declare_exchange(
            EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
        )

    @property
    def conectado(self) -> bool:
        return self.conexao is not None and not self.conexao.is_closed

    async def fechar(self) -> None:
        if self.conexao:
            await self.conexao.close()

    async def publicar(self, mensagem: Mensagem) -> None:
        await self.exchange.publish(_amqp(mensagem), routing_key=mensagem.routing_key)

    async def declarar_fila(self, fila: str, routing_key: str) -> None:
        """Fila do consumidor, com retry e DLQ. Idempotente: se já existe (o RabbitMQ
        do ambiente sobe com ela, ver definitions.json), não muda nada."""
        q = await self.canal.declare_queue(fila, durable=True)
        await q.bind(self.exchange, routing_key)
        await self.canal.declare_queue(
            f"{fila}.retry",
            durable=True,
            arguments={
                "x-message-ttl": ATRASO_RETRY * 1000,
                "x-dead-letter-exchange": "",
                "x-dead-letter-routing-key": fila,
            },
        )
        await self.canal.declare_queue(f"{fila}.dlq", durable=True)

    async def consumir(
        self,
        fila: str,
        routing_key: str,
        tratar: Callable[[Mensagem], Awaitable[None]],
        prefetch: int = 10,
    ) -> None:
        """Ack manual: a mensagem só sai da fila depois de tratada (ou de ir para retry
        ou DLQ). Se o serviço cair no meio, o RabbitMQ a entrega de novo; por isso
        todo tratador precisa ser idempotente."""
        assert self.conexao
        await self.declarar_fila(fila, routing_key)
        canal = await self.conexao.channel()
        await canal.set_qos(prefetch_count=prefetch)
        queue = await canal.get_queue(fila)

        async def ao_receber(amqp: AbstractIncomingMessage) -> None:
            mensagem = Mensagem.model_validate_json(amqp.body)
            correlation_id.set(mensagem.correlation_id)
            tentativa = int((amqp.headers or {}).get("tentativa", 0)) + 1
            try:
                await tratar(mensagem)
                resultado = "sucesso"
            except Exception as exc:
                if tentativa < MAX_TENTATIVAS:
                    resultado, destino = "retry", f"{fila}.retry"
                    log.warning(
                        "%s falhou (tentativa %s de %s), nova tentativa em %ss: %r",
                        mensagem.routing_key,
                        tentativa,
                        MAX_TENTATIVAS,
                        ATRASO_RETRY,
                        exc,
                    )
                else:
                    resultado, destino = "dlq", f"{fila}.dlq"
                    log.error(
                        "%s falhou %s vezes, enviada à DLQ: %r",
                        mensagem.routing_key,
                        tentativa,
                        exc,
                    )
                headers = {"tentativa": tentativa, "erro": repr(exc)[:500]}
                await self.canal.default_exchange.publish(
                    _amqp(mensagem, headers), routing_key=destino
                )
            await amqp.ack()
            MENSAGENS.labels(mensagem.routing_key, resultado).inc()

        await queue.consume(ao_receber)

    async def reprocessar_dlq(self, fila: str) -> int:
        """Devolve à fila principal as mensagens da DLQ, com as tentativas zeradas."""
        assert self.conexao
        canal = await self.conexao.channel()
        dlq = await canal.get_queue(f"{fila}.dlq")
        movidas = 0
        while amqp := await dlq.get(fail=False):
            mensagem = Mensagem.model_validate_json(amqp.body)
            await self.canal.default_exchange.publish(_amqp(mensagem), routing_key=fila)
            await amqp.ack()
            movidas += 1
        await canal.close()
        return movidas


def _amqp(mensagem: Mensagem, headers: dict | None = None) -> aio_pika.Message:
    return aio_pika.Message(
        body=mensagem.model_dump_json().encode(),
        content_type="application/json",
        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,  # sobrevive a um reinício do broker
        message_id=mensagem.id,
        correlation_id=mensagem.correlation_id,
        type=mensagem.routing_key,
        headers=headers or {},
    )
