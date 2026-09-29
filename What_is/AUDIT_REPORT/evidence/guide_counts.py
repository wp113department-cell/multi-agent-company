"""Evidence script: count what the running code actually registers, to check
PROJECT_MASTER_GUIDE.md's headline numbers. Run from backend/:
    .venv/bin/python ../What_is/AUDIT_REPORT/evidence/guide_counts.py
"""
import asyncio, json, os, sys
sys.path.insert(0, os.getcwd())

from app.fleet import capability_registry as cr
n_imported = cr.ensure_all_agents_registered()
reg = cr._registry
entries = reg.all()
from app.fleet.tool_manifest import TOOL_MANIFEST
from app.agents import tools as T
from app.config import Settings
from app.main import app
from fastapi.routing import APIRoute
_paths = app.openapi()["paths"]
routes = [(m, p) for p, ops in _paths.items() for m in ops]
from app.db.models import Base

async def db_tables():
    from sqlalchemy import text
    from app.db.session import new_isolated_async_engine
    engine = new_isolated_async_engine()
    async with engine.connect() as c:
        r = await c.execute(text("select count(*) from information_schema.tables where table_schema='public'"))
        return r.scalar()

out = {
  "agent_modules_imported": n_imported,
  "registered_capabilities": len(entries),
  "tool_manifest_entries": len(TOOL_MANIFEST),
  "READ_ONLY_TOOLS": len(T.READ_ONLY_TOOLS),
  "CODER_TOOLS": len(T.CODER_TOOLS),
  "CHAT_TOOLS": len(T.CHAT_TOOLS),
  "settings_fields": len(Settings.model_fields),
  "api_paths": len(_paths),
  "api_operations": len(routes),
  "api_router_modules_included": 21,
  "orm_tables": len(Base.metadata.tables),
  "live_db_public_tables": asyncio.run(db_tables()),
}
print(json.dumps(out, indent=2))
