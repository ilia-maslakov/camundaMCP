# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
pip install -e ".[dev]"          # install with dev deps
python -m camunda_mcp             # run MCP server over stdio (needs env vars below)

pytest tests/unit                 # unit tests (respx, no Docker)
pytest tests/integration -m integration   # e2e against camunda/camunda-bpm-platform:run-7.21.0 via testcontainers; needs Docker
pytest tests/unit/test_tools.py::test_name -q   # single test

ruff check .                      # lint (config in pyproject.toml — `select = ["ALL"]`)
mypy src tests                    # strict mypy
```

Required runtime env (see `config.py`): `CAMUNDA_BASE_URL`, `CAMUNDA_USER`, `CAMUNDA_PASSWORD`, `MCP_ROLE` (`reader`/`operator`/`admin`). HTTP tuning vars use `HTTP_` prefix (`HTTP_CONNECT_TIMEOUT`, `HTTP_MAX_ATTEMPTS`, etc.).

## Architecture

**Single-transport MVP.** Only stdio is wired up; there is no REST façade, worker runner, or resources yet — `PLAN.md` describes a much broader target but only the MVP slice is implemented. Tool surface is exactly 5 tools: `get_process_status`, `list_incidents`, `start_process`, `complete_external_task`, `set_job_retries`.

**Request flow.** `__main__._serve` → `server.app.create_app` builds the `FastMCP` instance plus a shared `CamundaClient`, then `register_tools` closes over `(client, role)` to register tool stubs. Each stub calls its `*_impl` in `server/tools.py`, which (1) runs `authz.check_allowed(role, op)` *before* any network call, then (2) delegates to `CamundaClient`.

**Role gate is always first.** `authz.ROLE_ALLOWLIST` is the single source of truth for which role may call which tool. New tools must be added to the allowlist for every role that should see them — otherwise they fail with `PermissionDeniedError` before hitting Camunda. Tests assert this ordering (`test_rbac_denied_before_network`).

**`_impl` vs registered tool.** Keep business logic in `*_impl(client, role, ...)` module-level functions — unit and integration tests call these directly with a synthesized role. The `@mcp.tool()` closures inside `register_tools` are thin adapters and should stay that way.

**HTTP layer.** `http.build_retrying_client` builds an `httpx.AsyncClient` pinned to `{base_url}/engine-rest` with BasicAuth. `http.request_with_retry` wraps each call in `tenacity.AsyncRetrying` that retries transport errors plus HTTP `408/429/500/502/503/504` with exponential backoff up to `HTTP_MAX_ATTEMPTS`. `CamundaClient._request` then maps the remaining non-retryable HTTP statuses to typed exceptions (`NotFoundError`, `ConflictError`, `BadRequestError`, `CamundaError`). Anything adding a new Camunda call should go through `_request` to inherit both behaviours.

**Typed Camunda variables.** Camunda 7 requires `{"name": {"value": ..., "type": "Long"}}`. Keep tool signatures using native Python `dict[str, Any]` and convert at the boundary via `camunda.variables.to_camunda_vars` / `from_camunda_vars`. The converter maps `bool→Boolean`, `int→Long`, `float→Double`, `datetime→Date`, `str→String`, `dict|list→Json` (JSON-serialized with `valueInfo`). Extending the type map is the right place to add a new supported variable type.

**Idempotency convention for `start_process`.** `start_process_impl` first calls `CamundaClient.find_active_instance(definition_key, business_key)`; if an active instance exists it's returned with `reused=True` on the `ProcessInstance` model. `allow_duplicate=True` bypasses this check. Preserve this contract — `reused` is how callers distinguish a new start from a reuse.

**Pydantic models with Camunda aliases.** `camunda.models` uses `Field(alias="camelCase")` + `ConfigDict(extra="ignore")` so validation tolerates Camunda's evolving response shapes. Follow the same pattern for new models.

**Logging.** `configure_logging` sets up `structlog` writing JSON to **stderr** (stdio transport owns stdout — never log to stdout from server code).

## Testing Notes

- `tests/conftest.py` provides `settings`, `http_client`, `camunda_client` fixtures pinned to `http://camunda.test/engine-rest`. Unit tests use `respx` to mock httpx at that URL.
- `pytest-asyncio` runs in `mode=auto` — async test functions do not need `@pytest.mark.asyncio` for unit tests (integration tests still mark explicitly).
- Integration tests start a real Camunda container per module and deploy `tests/fixtures/simple_external_task.bpmn`; they are gated by the `integration` marker so they stay out of default `pytest` runs.
