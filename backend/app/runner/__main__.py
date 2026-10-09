"""`python -m app.runner` — start the sandbox runner (see proxy.py)."""

import asyncio
import logging

from app.runner.proxy import serve

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
asyncio.run(serve())
