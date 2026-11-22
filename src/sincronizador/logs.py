"""Logs estruturados (JSON, uma linha por evento) com o correlation ID corrente.

O correlation ID fica numa ContextVar: o consumidor de mensagens o define ao começar
a tratar cada mensagem, e todo log emitido dali em diante o carrega.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_servico = "?"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        linha = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "nivel": record.levelname,
            "servico": _servico,
            "msg": record.getMessage(),
            "correlation_id": correlation_id.get(),
        }
        if record.exc_info:
            linha["erro"] = self.formatException(record.exc_info)
        return json.dumps(linha, ensure_ascii=False)


def configurar_logs(servico: str) -> None:
    global _servico
    _servico = servico
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    for ruidoso in ("httpx", "aiormq", "aio_pika", "uvicorn.access"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)
