from __future__ import annotations

import asyncio

from .config import Settings
from .logging import configure_logging, get_logger
from .server.app import create_app


async def _serve() -> None:
    configure_logging()
    settings = Settings()
    log = get_logger(__name__)
    log.info("starting camunda-mcp", base_url=str(settings.camunda_base_url), role=settings.mcp_role.value)

    mcp, client = create_app(settings)
    try:
        await mcp.run_async(transport="stdio")
    finally:
        await client._http.aclose()  # noqa: SLF001


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
