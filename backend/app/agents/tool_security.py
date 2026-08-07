"""Tool-input security/validation guards — extracted from app/agents/tools.py
(AUDIT_Q_BATCH05_PERFORMANCE_ARCHITECTURE.md §10 "Modularity" — tools.py was
a 12,993-line god-module mixing all tool schemas/handlers together). These
8 functions are pure, self-contained guards with no dependency on anything
else in tools.py beyond the already-shared app.policy.engine checks, making
this a safe extraction. Behavior is unchanged — app.agents.tools re-exports
every name here for full backward compatibility with existing internal call
sites and app.agents.chat_agent's own direct
`from app.agents.tools import _is_dangerous_command, _is_protected_path`.
"""

from __future__ import annotations

import subprocess
from typing import Any

from app.policy.engine import check_command, check_path, check_path_in_worktree


def _is_dangerous_command(command: str) -> bool:
    """Delegates to the centralized policy engine denylist."""
    return not check_command(command, strict=False).allowed


def _ssrf_denial_reason(url: str) -> str | None:
    """SSRF guard for every agent-controlled outbound-fetch tool (audit_v1.md
    4.5/4.8, finding "fetch_url ... is SSRF-capable with no allowlist").

    Rejects non-http(s) schemes and resolves the hostname, denying if ANY
    resolved address falls in a private/loopback/link-local/reserved range
    (RFC1918, 127.0.0.0/8, 169.254.0.0/16 incl. the 169.254.169.254 cloud
    metadata endpoint, ::1, fc00::/7, etc.) — checking the resolved IP, not
    just the hostname string, so a DNS-rebinding or bare-IP URL is caught
    the same way a friendly hostname would be. Returns a denial reason, or
    None if the URL is safe to fetch.
    """
    import ipaddress
    import socket
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
    except Exception:
        return f"Could not parse URL: {url!r}"

    if parsed.scheme not in ("http", "https"):
        return f"URL scheme {parsed.scheme!r} is not allowed (only http/https)"

    hostname = parsed.hostname
    if not hostname:
        return f"URL has no hostname: {url!r}"

    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except Exception as e:
        return f"Could not resolve host {hostname!r}: {e}"

    if not addr_infos:
        return f"Could not resolve host {hostname!r}"

    for info in addr_infos:
        raw_addr = info[4][0]
        try:
            ip = ipaddress.ip_address(raw_addr)
        except ValueError:
            return f"Host {hostname!r} resolved to an unparseable address {raw_addr!r}"
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return (
                f"URL host {hostname!r} resolves to {raw_addr!r}, which is a "
                "private/loopback/link-local/reserved address — refusing to "
                "fetch (SSRF protection)"
            )
    return None


def _is_protected_path(path: str, worktree_path: str = "") -> bool:
    """Denylist + optional worktree containment check.

    Pass worktree_path (= repo_path in most handlers) to also block path
    traversal escapes like ../../../../tmp/pwned.txt.  Without worktree_path
    only the deny-list (.env, secrets, *.pem, etc.) is enforced.
    """
    if worktree_path:
        return not check_path_in_worktree(path, worktree_path).allowed
    return not check_path(path).allowed


def _extract_patch_target_paths(patch_content: str, strip: int) -> list[str]:
    """Extract real target file paths from unified-diff `+++`/`---` header
    lines, applying the same `-pN` leading-component strip that the `patch`
    CLI itself applies (see apply_patch, Blocker 1 in audit_v1.md 4.5/4.8).

    A unified diff's actual file targets live in these header lines (e.g.
    `+++ b/app/config.py`), not in any top-level "path" field — apply_patch's
    schema has none. `/dev/null` (used for pure adds/deletes) is skipped.
    """
    paths: list[str] = []
    for line in patch_content.splitlines():
        if not (line.startswith("+++ ") or line.startswith("--- ")):
            continue
        raw = line[4:].strip()
        raw = raw.split("\t", 1)[0].strip()  # drop optional diff timestamp
        if not raw or raw == "/dev/null":
            continue
        parts = raw.split("/")
        if strip > 0 and len(parts) > strip:
            raw = "/".join(parts[strip:])
        elif strip > 0:
            raw = parts[-1]
        if raw and raw not in paths:
            paths.append(raw)
    return paths


_SHELL_METACHARS_RE = None  # set on first use — avoids a module-level `re` import


def _shell_metachar_reason(value: str, field: str) -> str | None:
    """Reject shell metacharacters in a value meant to be a literal CLI
    flag/arg (e.g. pytest/ruff/mypy flags), not an arbitrary shell fragment.

    Used for values that get f-string-interpolated into a `shell=True`
    command as multiple space-separated tokens, where shlex.quote() can't be
    applied to the whole string without collapsing it into one argument.
    Returns a denial reason string, or None if the value is safe.
    """
    global _SHELL_METACHARS_RE
    if _SHELL_METACHARS_RE is None:
        import re as _re

        _SHELL_METACHARS_RE = _re.compile(r"[;&|`$><(){}\n]")
    m = _SHELL_METACHARS_RE.search(value)
    if m:
        return f"{field} contains disallowed shell metacharacter {m.group()!r}"
    return None


_SECRET_NAME_RE = None
_SECRET_VALUE_RE = None


def _mask_secret_value(name: str, value: str) -> str:
    """Mask a value if it looks like a secret, showing only a short prefix.

    Triggers on secret-shaped env var names (KEY, SECRET, TOKEN, PASSWORD,
    PWD, CREDENTIAL, AUTH, PRIVATE) or values matching known secret shapes
    (sk-..., AKIA..., gh_-style tokens) or generic long opaque tokens.
    """
    global _SECRET_NAME_RE, _SECRET_VALUE_RE
    if _SECRET_NAME_RE is None:
        import re as _re

        _SECRET_NAME_RE = _re.compile(
            r"(KEY|SECRET|TOKEN|PASSWORD|PWD|CREDENTIAL|AUTH|PRIVATE)", _re.IGNORECASE
        )
        _SECRET_VALUE_RE = _re.compile(
            r"^(sk-|AKIA|gh[opsu]_|xox[baprs]-)", _re.IGNORECASE
        )
    if not value:
        return value
    looks_secret = bool(_SECRET_NAME_RE.search(name)) or bool(
        _SECRET_VALUE_RE.match(value)
    )
    if not looks_secret and len(value) > 20:
        import re as _re

        if _re.fullmatch(r"[A-Za-z0-9_\-./+=]{20,}", value):
            looks_secret = True
    if not looks_secret:
        return value
    prefix = value[:6]
    return f"{prefix}***REDACTED"


_SECRET_CONTENT_RE = None


def _scan_content_for_secrets(content: str) -> str | None:
    """Pre-commit content scanner (audit_v1.md 4.5, finding #9: "No
    secret-content scanner before commit; only filename-pattern denylist").

    check_path()/_is_protected_path() only ever inspected file *paths*
    (.env, secrets/, *.pem, id_rsa) — a real credential embedded inside an
    otherwise-ordinary source file (e.g. a hardcoded AWS key in a .py file)
    sailed straight through to a real `git commit`. This scans file
    *content* line-by-line for the same secret shapes _mask_secret_value
    already recognizes (KEY=value/KEY: value pairs whose name looks secret,
    or standalone tokens matching known provider prefixes), plus PEM
    private-key headers. Returns a denial reason for the first match found,
    or None if the content looks clean.
    """
    global _SECRET_CONTENT_RE
    if _SECRET_CONTENT_RE is None:
        import re as _re

        _SECRET_CONTENT_RE = {
            "assignment": _re.compile(
                r"(?im)^[^\S\n]*[\w.\-]*(KEY|SECRET|TOKEN|PASSWORD|PWD|CREDENTIAL|AUTH|PRIVATE)[\w.\-]*"
                r"\s*[:=]\s*['\"]?([A-Za-z0-9_\-./+=]{8,})['\"]?\s*$"
            ),
            "provider_token": _re.compile(
                # AUDIT_Q_BATCH11 §96 "Secret scanning" — the AWS access-key-id
                # prefix list was widened from AKIA-only to every real AWS key
                # type (root/user/temp-session/etc.) while consolidating the
                # two separately-maintained repo-wide `secrets_scan` tool
                # implementations (app/agents/tools.py) onto this one shared
                # pattern set instead of three independently-drifting regex
                # lists.
                r"\b(sk-[A-Za-z0-9]{16,}|(?:AKIA|AGPA|AROA|AIPA|ANPA|ANVA|ASIA)[0-9A-Z]{12,}"
                r"|gh[opsu]_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9\-]{10,})\b"
            ),
            "pem_header": _re.compile(
                r"-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"
            ),
        }
    for line_no, line in enumerate(content.splitlines(), 1):
        m = _SECRET_CONTENT_RE["provider_token"].search(line)
        if m:
            return f"line {line_no} contains a value matching a known secret-token pattern ({m.group(1)[:6]}***REDACTED)"
        if _SECRET_CONTENT_RE["pem_header"].search(line):
            return f"line {line_no} contains a private key header (-----BEGIN ... PRIVATE KEY-----)"
        am = _SECRET_CONTENT_RE["assignment"].match(line)
        if am:
            value = am.group(2)
            # Plausible placeholder/test values shouldn't hard-block a
            # commit — only flag values that are actually secret-shaped
            # (long, high-entropy-looking), matching _mask_secret_value's
            # own generic-token heuristic.
            if len(value) >= 12 and value.lower() not in (
                "changeme",
                "placeholder",
                "your_key_here",
                "your-key-here",
                "xxxxxxxxxxxx",
            ):
                return (
                    f"line {line_no} assigns a secret-shaped value to a "
                    f"credential-looking name ({value[:4]}***REDACTED)"
                )
    return None


_REPO_SCAN_SKIP_DIRS = frozenset(
    {".git", "__pycache__", ".venv", "venv", "node_modules", ".next", "dist", "build"}
)
_REPO_SCAN_SKIP_EXTS = frozenset(
    {
        ".pyc",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".woff",
        ".woff2",
        ".zip",
        ".pdf",
        ".lock",
    }
)


def _scan_directory_for_secrets(
    root: Any, directory: str = "", *, max_hits: int = 50
) -> str:
    """Repo-wide secret scan, reusing _scan_content_for_secrets's canonical
    pattern set (assignment-style + provider-token + PEM headers) instead of
    a third, independently-maintained regex list.

    AUDIT_Q_BATCH11 §96 "Secret scanning" — two separate `secrets_scan` tool
    implementations existed in app/agents/tools.py (sec_secrets_scan, used
    by make_security_reviewer_handlers, and secrets_scan, used by
    make_coder_handlers), each maintaining its OWN independent regex list —
    different again from this module's own _scan_content_for_secrets (the
    pre-commit content scanner). All three now share this one canonical
    detector, so a future improvement to secret-shape detection applies
    everywhere at once instead of needing three synchronized edits (the
    exact kind of narrow-coverage drift this audit finding is about).

    `root` is a pathlib.Path (repo root); typed Any here to avoid importing
    pathlib into this otherwise dependency-light module for a type hint
    only — every real caller already has a real Path.
    """
    scan_root = (root / directory) if directory else root
    hits: list[str] = []
    for fp in scan_root.rglob("*"):
        if len(hits) >= max_hits:
            break
        if fp.is_dir() or any(part in _REPO_SCAN_SKIP_DIRS for part in fp.parts):
            continue
        if fp.suffix.lower() in _REPO_SCAN_SKIP_EXTS:
            continue
        try:
            content = fp.read_text(encoding="utf-8", errors="replace")
        except (OSError, PermissionError):
            continue
        reason = _scan_content_for_secrets(content)
        if reason:
            try:
                rel = fp.relative_to(root)
            except ValueError:
                rel = fp
            hits.append(f"{rel}: {reason}")
    if not hits:
        return "✅ No hardcoded secrets detected."
    return f"⚠️  {len(hits)} potential secret(s):\n" + "\n".join(hits[:max_hits])


def _redact_secrets_in_text(content: str) -> tuple[str, bool]:
    """Non-blocking counterpart to _scan_content_for_secrets — redacts every
    line matching the same secret shapes in place and returns
    (redacted_content, any_found), instead of a single denial reason for
    the first match. Built for LLM-generated *output* (a chat reply, an
    agent's submitted summary) that already exists and must still reach the
    user in some form — unlike a `git commit`, there's no "refuse the whole
    thing" option that makes sense here.

    AUDIT_Q_BATCH11 §21 "Data leakage prevention" — _mask_secret_value only
    ever ran on read_env_var_h's own output and _scan_content_for_secrets
    only ever ran pre-commit; neither covered arbitrary agent output/chat
    text, so a secret the agent encountered via read_file and then quoted
    back in its own reply sailed straight through to the user unredacted.
    """
    if not content:
        return content, False
    if _SECRET_CONTENT_RE is None:
        _scan_content_for_secrets("")  # populate the shared compiled patterns

    patterns = _SECRET_CONTENT_RE
    assert patterns is not None
    found = False
    out_lines: list[str] = []
    for line in content.splitlines():
        new_line = line
        m = patterns["provider_token"].search(new_line)
        if m:
            token = m.group(1)
            new_line = new_line.replace(token, _mask_secret_value("TOKEN", token))
            found = True
        if patterns["pem_header"].search(new_line):
            new_line = "[REDACTED: private key header]"
            found = True
        am = patterns["assignment"].match(new_line)
        if am:
            value = am.group(2)
            if len(value) >= 12 and value.lower() not in (
                "changeme",
                "placeholder",
                "your_key_here",
                "your-key-here",
                "xxxxxxxxxxxx",
            ):
                new_line = new_line.replace(
                    value, _mask_secret_value(am.group(1), value)
                )
                found = True
        out_lines.append(new_line)
    return "\n".join(out_lines), found


_SENSITIVE_HOST_MOUNT_PATHS = (
    "/etc",
    "/root",
    "/var/run/docker.sock",
    "/proc",
    "/sys",
    "/home",
    "/boot",
)


def _docker_container_risk_reason(container: str) -> str | None:
    """Inspect a running container for host-escape surface before allowing
    docker_exec into it: --privileged, --pid=host, dangerous added
    capabilities, or a bind-mount of a sensitive host path (including a
    bare '/'). Returns a denial reason, or None if nothing suspicious was
    found. Fails closed (denies) if the container can't be inspected at
    all — safer than executing blind into an unverifiable target.

    Scope note: this only examines a container's *existing* configuration.
    It cannot stop a caller who can also create containers (e.g. via
    `docker compose up` against a compose file it just wrote) from first
    building a privileged one — that's a container-*creation* control,
    not an exec-time one, and needs to be enforced separately wherever
    container creation is reachable.
    """
    import json as _json

    try:
        r = subprocess.run(
            ["docker", "inspect", container],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as e:
        return f"could not inspect container {container!r} before exec: {e}"
    if r.returncode != 0:
        detail = (r.stderr or r.stdout).strip()[:200]
        return f"could not inspect container {container!r} before exec: {detail}"
    try:
        data = _json.loads(r.stdout)
    except Exception as e:
        return f"could not parse docker inspect output for {container!r}: {e}"
    if not data:
        return f"docker inspect returned no data for container {container!r}"

    info = data[0]
    host_config = info.get("HostConfig") or {}

    if host_config.get("Privileged"):
        return f"container {container!r} is running with --privileged"

    if host_config.get("PidMode") == "host":
        return f"container {container!r} shares the host PID namespace (--pid=host)"

    cap_add = [str(c).upper() for c in (host_config.get("CapAdd") or [])]
    if "ALL" in cap_add or "SYS_ADMIN" in cap_add:
        return f"container {container!r} has dangerous added capabilities: {cap_add}"

    for m in info.get("Mounts") or []:
        src = str(m.get("Source", ""))
        if not src:
            continue
        if src == "/" or any(
            src == p or src.startswith(p + "/") for p in _SENSITIVE_HOST_MOUNT_PATHS
        ):
            return (
                f"container {container!r} has a sensitive host mount: "
                f"{src!r} -> {m.get('Destination')!r}"
            )

    return None
