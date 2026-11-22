# ieducar-moodle-sincronizador

Microsserviço da integração i-Educar → Moodle que **aplica as regras da integração**:
recebe os eventos do i-Educar e decide o que deve existir no Moodle (usuários,
cursos, inscrições), publicando comandos para o publicador. Não fala com nenhum
sistema externo.

Faz parte da integração montada em
[ieducar-moodle-integration](https://github.com/vargasnico/ieducar-moodle-integration).

## Regras

| i-Educar | Moodle |
|---|---|
| Servidor ativo com vínculo com turma no ano | Usuário `ieducar-servidor-<id>` (login pelo CPF), `editingteacher` nos cursos dos componentes do vínculo |
| Turma × componente curricular | Curso `ieducar-turma-<turma>-componente-<componente>` |
| Aluno ativo e enturmado | Usuário `ieducar-aluno-<código>`, `student` nos cursos dos componentes da série, menos os dispensados |

Ninguém é apagado: quem sai é suspenso e o curso de uma turma desativada é ocultado.
As regras estão em [`src/sincronizador/regras.py`](src/sincronizador/regras.py).

## Contrato

**Consome** a fila `sincronizador` (routing key `ieducar.#`), um evento por vez:
`ieducar.{turma,servidor,aluno}.{alterado,alterada,removido,removida}.v1`.

**Publica** na exchange `integracao` comandos de estado desejado:

| Routing key | `dados` |
|---|---|
| `moodle.usuario.sincronizar.v1` | `idnumber`, `username`, `firstname`, `lastname`, `email`, `suspenso` |
| `moodle.curso.sincronizar.v1` | `idnumber`, `shortname`, `fullname`, `ano`, `visivel` |
| `moodle.inscricao.adicionar.v1` | `usuario`, `curso`, `papel` |
| `moodle.inscricao.remover.v1` | `usuario`, `curso`, `papel` |

**Dados próprios:** `turma` (componentes da última versão, para ocultar cursos) e
`inscricao` (inscrições já pedidas, para saber o que remover) e `versao` (ciclo do
último evento tratado de cada turma, servidor e aluno).

## API

| Rota | Descrição |
|---|---|
| `GET /inscricoes` | Inscrições pedidas, por papel |
| `POST /dlq/reprocessar` | Devolve à fila os eventos da DLQ |
| `GET /health` · `GET /metrics` | Health check · `mensagens_total`, `sincronizador_comandos_total` |

## Resiliência

- Ack manual: um evento só sai da fila depois de tratado. Se o serviço cair, o
  evento é entregue de novo.
- Tratar o mesmo evento duas vezes gera os mesmos comandos (estado desejado), o que é
  inofensivo.
- Publica os comandos antes de gravar o estado.
- Evento que falha volta pela fila `sincronizador.retry` (10s); depois de 5 falhas
  vai para `sincronizador.dlq`.
- **Versão por entidade:** um evento de um ciclo anterior ao último tratado para a
  mesma entidade é descartado (`eventos_obsoletos_total`), então reprocessar a DLQ não
  desfaz uma alteração mais nova.

## Configuração

| Variável | Padrão |
|---|---|
| `RABBITMQ_URL` | `amqp://guest:guest@localhost/` |
| `DATABASE_PATH` | `data/sincronizador.db` |

## Estrutura (arquitetura hexagonal)

O domínio fica no centro e não conhece banco, broker nem HTTP; o caso de uso o usa
por meio das portas (interfaces), e os adaptadores as implementam. Trocar o SQLite
ou o RabbitMQ é trocar um adaptador; os testes usam versões em memória das portas.

```
src/sincronizador/
├── dominio/              regras puras, sem banco, rede nem framework
│   ├── regras.py         quem é professor, aluno, quais cursos (as regras do T1)
│   ├── planejamento.py   evento + estado anterior → comandos e estado novo (Plano)
│   └── versao.py         mensagem de um ciclo mais antigo é obsoleta
├── aplicacao/
│   └── tratar_evento.py  caso de uso: planeja, publica e só então grava o estado
├── portas.py             interfaces: EstadoSincronizacao, PublicadorDeComandos
├── adaptadores/          implementações das portas e entradas do serviço
│   ├── sqlite.py         porta EstadoSincronizacao (turmas, inscrições, versões)
│   ├── rabbitmq.py       entrada (consumo, retry, DLQ) e porta PublicadorDeComandos
│   └── api.py            entrada HTTP (/inscricoes, /dlq/reprocessar, /health, /metrics)
├── infra/                logs JSON, métricas
├── mensagem.py           formato das mensagens (o contrato com os outros serviços)
└── main.py               composição: cria os adaptadores e os injeta no caso de uso
```

## Desenvolvimento

```bash
uv sync
uv run pytest
mkdir -p data && RABBITMQ_URL=amqp://integracao:integracao@localhost:5672/ \
  PYTHONPATH=src uv run uvicorn sincronizador.main:app --port 8002
```

## Deploy

Cada tag `v*` roda o [CI](.github/workflows/ci.yml): testes e a imagem
`ghcr.io/<dono>/ieducar-moodle-sincronizador:<tag>`. No ambiente:
`docker compose up -d --build sincronizador`, sem mexer nos outros serviços.
