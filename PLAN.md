# MCP-сервер для AI-инструментов разработчика

Интеграция Claude Code / Codex с Camunda 7 через MCP (stdio) и REST-фасад на Litestar.

## Стек

- Python 3.12
- FastMCP (MCP-протокол, stdio-транспорт)
- Litestar (REST-фасад для не-AI клиентов и дашбордов)
- pydantic v2 + pydantic-settings
- httpx (async) + tenacity (retry / exponential backoff)
- structlog
- pytest + pytest-asyncio + respx + testcontainers
- ruff, mypy (strict)

## Структура репозитория

```
mcp-dev-tools/
├── pyproject.toml                    # uv/hatch, deps, ruff, pytest, mypy
├── src/mcp_dev_tools/
│   ├── __main__.py                   # entrypoints: stdio | rest | workers
│   ├── server/                       # FastMCP-сервер
│   │   ├── app.py                    # FastMCP instance, регистрация
│   │   ├── tools/
│   │   │   ├── dev.py                # read_file, search_code, run_tests
│   │   │   ├── process_control.py    # complete/correlate/signal
│   │   │   ├── process_admin.py      # modify/delete/retries (confirm-флаг)
│   │   │   ├── saga.py               # start_saga / compensate_saga
│   │   │   └── tasks.py              # user tasks, incidents
│   │   └── resources/                # saga://definitions/*, saga://instances/*
│   ├── rest/                         # Litestar-фасад
│   │   ├── app.py                    # Litestar(), OpenAPI, CORS, health
│   │   └── controllers/              # тонкие обёртки над sagas/ и clients/
│   ├── clients/
│   │   ├── base.py                   # RetryingAsyncClient (httpx + tenacity)
│   │   └── camunda.py                # C7 REST /engine-rest/*
│   ├── sagas/
│   │   ├── orchestrator.py           # старт/мониторинг/компенсация через message
│   │   ├── workers.py                # async External Task раннер (long-polling)
│   │   └── models.py                 # pydantic-модели saga-payload
│   ├── schemas/
│   │   ├── camunda.py                # CamundaVariable (typed vars)
│   │   └── ...
│   ├── config.py                     # pydantic-settings, env
│   └── logging.py                    # structlog
└── tests/
    ├── unit/                         # respx-моки
    ├── integration/                  # testcontainers: camunda/camunda-bpm-platform
    └── conftest.py
```

## Этапы

### Фаза 1 — скелет (1–2 дня)

- `pyproject.toml` с зависимостями: `fastmcp`, `litestar[standard]`, `httpx`, `pydantic>=2`, `pydantic-settings`, `tenacity`, `structlog`, `pytest`, `pytest-asyncio`, `respx`, `testcontainers`, `ruff`, `mypy`
- ruff (line-length 120, `select ALL` с разумными исключениями)
- mypy strict, pytest-asyncio `mode=auto`
- Pre-commit + CI (ruff, mypy, pytest)
- Три entrypoint'а: `mcp-dev-tools stdio`, `mcp-dev-tools rest`, `mcp-dev-tools workers`

### Фаза 2 — HTTP-слой (1 день)

- `RetryingAsyncClient` поверх `httpx.AsyncClient`:
  - `tenacity` с `wait_exponential(multiplier=0.5, max=30)`
  - `retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError))` с фильтрацией по 5xx/429
  - Таймауты: `connect=5`, `read=30`
  - Опционально circuit breaker
- Logging middleware (request-id, latency, status)
- Unit-тесты через `respx`

### Фаза 3 — MCP-сервер и tools (2–3 дня)

**Dev-инструменты:** `read_file`, `search_code`, `run_tests`

**Process control (штатное продвижение):**
- `complete_external_task(task_id, variables)`
- `complete_user_task(task_id, variables)`
- `correlate_message(message_name, business_key|correlation_keys, variables)` — `POST /message`
- `send_signal(signal_name, variables)` — `POST /signal`

**Process admin (ручное вмешательство, с `confirm=true`):**
- `resolve_incident(incident_id)`
- `set_job_retries(job_id, retries)`
- `modify_process_instance(instance_id, instructions)` — `POST /process-instance/{id}/modification` (startBefore/cancel/startAfter); обязательно `annotation`
- `set_variables(instance_id, variables)` — `PATCH /process-instance/{id}/variables`
- `suspend_process_instance` / `activate_process_instance`
- `delete_process_instance(id, reason, skipCustomListeners?)`

**Batch:**
- `create_batch_modification(query, instructions)`
- `create_batch_migration(source_def, target_def, query)`
- `get_batch(batch_id)`

**Saga и задачи:**
- `start_saga(process_key, business_key, variables)` → `processInstance.id`
- `get_saga_status(instance_id)` → activities, incidents, variables
- `compensate_saga(business_key, reason)` → корреляция message
- `list_user_tasks(assignee?, process_key?)` / `list_incidents(process_key?)`

**Ресурсы:**
- `saga://definitions/{bpmn_id}` — BPMN XML
- `saga://instances/{key}/history` — элементы процесса

### Фаза 4 — интеграция с Camunda 7 (3–4 дня)

**REST-клиент** `clients/camunda.py` — всё через `/engine-rest/*`:
- `POST /process-definition/key/{key}/start` — старт
- `GET /process-instance/{id}` + `/history/process-instance/{id}` — статус/история
- `POST /external-task/fetchAndLock`, `/external-task/{id}/complete|failure|bpmnError`
- `POST /message`, `POST /signal`
- `GET /incident` + `PUT /incident/{id}/resolve`
- `POST /process-instance/{id}/modification`, `POST /modification`, `POST /migration`

**External Task раннер** (`sagas/workers.py`):
- Собственный async на httpx long-polling (fetchAndLock с `asyncResponseTimeout`), не sync-обёртка над `camunda-external-task-client-python3`
- Декоратор `@worker.topic("charge-payment")` для регистрации handler'ов
- Обработка ошибок:
  - бизнес → `bpmnError` (триггер compensation boundary event)
  - техническая → `failure` с `retries` и `retryTimeout` (backoff на стороне Camunda)
- Живёт как отдельный entrypoint `mcp-dev-tools workers`

**Саги — BPMN-путь (рекомендация):**
- BPMN с compensation boundary events + compensation throw event
- `compensate_saga` → `POST /message` `messageName=CompensateSaga` + `businessKey`
- Альтернатива (orchestrator в коде) — только если BPMN недоступен

**Переменные процесса:**
- C7 требует typed variables: `{"amount": {"value": 100, "type": "Long"}}`
- `schemas/camunda.py` — `CamundaVariable` с сериализатором; tool'ы принимают обычные Python-типы, клиент конвертирует

### Фаза 5 — Litestar REST-фасад (1–2 дня)

- Те же use-case'ы, что MCP-tools, через REST (для дашбордов/не-AI клиентов)
- OpenAPI автогенерация, CORS, `/health` и `/ready`
- Контроллеры — тонкая обёртка; бизнес-логика в `clients/` и `sagas/`

### Фаза 6 — тесты и наблюдаемость (2 дня)

**Unit:**
- `respx` для мока httpx
- Прямой вызов tool-функций для FastMCP

**Integration (testcontainers):**
- `camunda/camunda-bpm-platform:run-latest` (H2 in-memory достаточно)
- Деплой тестового BPMN через `POST /deployment/create` в фикстуре
- Сценарии:
  - start → fetchAndLock → complete → assert history
  - happy-path компенсации через `bpmnError`
  - "процесс застрял на incident → `resolve_incident` → токен пошёл"
  - `modify_process_instance`: cancel + startBefore другого activity

**E2E:**
- Запуск stdio-сервера, прогон "start → worker → complete → compensate"

**Наблюдаемость:**
- OpenTelemetry traces (httpx + Litestar + FastMCP-хуки)

## Принципы дизайна tool'ов

- **Read-only vs mutating:** `get_*`/`list_*` — без подтверждений; mutating (`modify_*`, `delete_*`, `set_job_retries`) — возвращают preview по умолчанию, реальное применение через параметр `confirm=true`. Защита от "Claude передвинул токен в проде"
- **`modify_process_instance`** — самый опасный; обязательный `annotation` (сохраняется в history), логирование caller/reason
- **Authz:** прокидывать `X-Authorization-Username` (C7 identity service) или завести отдельных engine-users per-role, чтобы audit log был осмысленным
- **Idempotency:** для `correlate_message` и `start_saga` требовать `business_key` и проверять существование — иначе при ретрае будут дубли

## Открытые вопросы

- Транспорт MCP: только stdio, или добавить SSE/HTTP для удалённого использования?
- Источник правды по saga-state: только Camunda, или дублировать в локальный Postgres для быстрых запросов?
- Политика прав: один admin-user движка или per-role с проксированием identity от MCP-клиента?

## MVP (первые PR)

1. Скелет проекта + CI (Фаза 1)
2. `RetryingAsyncClient` + `CamundaClient` с основными endpoints (Фаза 2 + часть Фазы 4)
3. MCP tools: `start_saga`, `get_saga_status`, `correlate_message`, `complete_external_task` (Фаза 3, минимум)
4. Async External Task раннер + один demo-topic (Фаза 4)
5. Integration-тесты с testcontainers для happy-path (Фаза 6)
