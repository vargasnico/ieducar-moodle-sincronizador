"""Métricas do sincronizador (Prometheus), expostas em /metrics."""

from prometheus_client import Counter

MENSAGENS = Counter(
    "mensagens_total",
    "Eventos consumidos, por resultado (sucesso, retry ou dlq)",
    ["tipo", "resultado"],
)
COMANDOS = Counter("sincronizador_comandos_total", "Comandos publicados para o Moodle", ["tipo"])
