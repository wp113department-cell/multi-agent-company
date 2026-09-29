"""Evidence script (Audit 05/08): construct the real Settings with production
profile + one bad value at a time; each must refuse to start.
Run from backend/: .venv/bin/python ../What_is/AUDIT_REPORT/evidence/prod_config_guards.py"""
import os, sys
sys.path.insert(0, os.getcwd())
from cryptography.fernet import Fernet
from app.config import Settings

GOOD = dict(deployment_env="production", jwt_auth_enabled=True, rbac_enabled=True,
            allow_legacy_role_header=False, default_admin_password="A-strong-admin-pw-123",
            credential_encryption_key=Fernet.generate_key().decode(),
            jwt_secret_key="x" * 48, anthropic_api_key="sk-ant-probe",
            worktrees_dir="/var/lib/gridiron/worktrees", repos_dir="/var/lib/gridiron/repos",
            bg_process_registry_path="/var/lib/gridiron/bg.json",
            database_url="postgresql+asyncpg://u:p@db:5432/gridiron")
CASES = {
  "baseline (all good)": {},
  "JWT disabled": {"jwt_auth_enabled": False},
  "RBAC disabled": {"rbac_enabled": False},
  "legacy role header on": {"allow_legacy_role_header": True},
  "default admin password": {"default_admin_password": "gridiron123"},
  "short admin password": {"default_admin_password": "short"},
  "no encryption key": {"credential_encryption_key": ""},
  "workspace under /tmp": {"worktrees_dir": "/tmp/gridiron-worktrees"},
  "empty JWT secret": {"jwt_secret_key": ""},
  "weak JWT secret": {"jwt_secret_key": "secret"},
}
for name, override in CASES.items():
    try:
        Settings(_env_file=None, **{**GOOD, **override})
        print(f"STARTS   {name}")
    except Exception as e:
        msg = [l.strip() for l in str(e).splitlines() if l.strip() and "errors.pydantic" not in l]
        print(f"REFUSED  {name}: {msg[-1][:120] if msg else type(e).__name__}")
