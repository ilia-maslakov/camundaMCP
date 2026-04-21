# camunda-mcp

MCP server for Camunda 7 over stdio. Exposes 5 tools to start and operate BPMN processes.

## Install

```
pip install -e ".[dev]"
```

## Run

```
CAMUNDA_BASE_URL=http://localhost:8080 \
CAMUNDA_USER=demo \
CAMUNDA_PASSWORD=demo \
MCP_ROLE=operator \
python -m camunda_mcp
```

## Tools

| Tool | Role |
|------|------|
| `get_process_status` | reader+ |
| `list_incidents` | reader+ |
| `start_process` | operator+ |
| `complete_external_task` | operator+ |
| `set_job_retries` | admin |

## Environment

| Var | Default | Notes |
|-----|---------|-------|
| `CAMUNDA_BASE_URL` | — | e.g. `http://localhost:8080` |
| `CAMUNDA_USER` | — | basic auth user |
| `CAMUNDA_PASSWORD` | — | basic auth password |
| `MCP_ROLE` | `reader` | `reader` / `operator` / `admin` |
| `HTTP_CONNECT_TIMEOUT` | `5.0` | seconds |
| `HTTP_READ_TIMEOUT` | `30.0` | seconds |
| `HTTP_WRITE_TIMEOUT` | `30.0` | seconds |
| `HTTP_MAX_ATTEMPTS` | `4` | tenacity retries |

## Tests

```
pytest tests/unit
pytest tests/integration -m integration
```

Integration tests spin up `camunda/camunda-bpm-platform:run-7.21.0` via testcontainers and require Docker.
