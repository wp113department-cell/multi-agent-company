"""Tool-input security/validation guards — extracted from app/agents/tools.py
(AUDIT_Q_BATCH05_PERFORMANCE_ARCHITECTURE.md §10 "Modularity" — tools.py was
a 12,993-line god-module mixing all tool schemas/handlers together). These
functions are pure, self-contained guards with no dependency on anything
else in tools.py beyond the already-shared app.policy.engine checks, making
this a safe extraction. Behavior is unchanged — app.agents.tools re-exports
every name here for full backward compatibility with existing internal call
sites and app.agents.chat_agent's own direct
`from app.agents.tools import _is_dangerous_command, _is_protected_path`.

`_ssrf_safe_opener()`/`_ssrf_safe_curl_fetch()` (2026-09-14, tool_enhance.md
productionization pass, tool #157) — a real, empirically-verified SSRF-via-
redirect bypass on EVERY tool that only calls `_ssrf_denial_reason()` once
on the caller-supplied URL and then follows redirects automatically
(`urllib.request.urlopen()`'s default redirect-following, or curl's `-L`):
the guard validates the FIRST URL only — a malicious (or compromised)
external server the first URL legitimately points to can issue an HTTP
redirect to any private/internal target (the cloud metadata endpoint
`169.254.169.254`, localhost, RFC1918 ranges), and the redirect is followed
completely unvalidated. Proved live against a real, public redirect
service (`https://httpbin.org/redirect-to?url=...`): both a raw
`curl -L` invocation and this codebase's own `http_request`/
`check_url_status` handlers (via `urllib.request.urlopen()`, which follows
redirects by default) genuinely attempted to connect to
`http://169.254.169.254/latest/meta-data/` after following the redirect —
in a real cloud deployment this would successfully exfiltrate real
instance-metadata credentials. This affected FOUR real tools: `fetch_url`
(tool #86), `check_url_status` (tool #126), `http_request` (tool #155,
all three already marked GREEN_FLAG before this discovery) and
`inspect_openapi_spec` (tool #157, the tool whose audit uncovered this).
Fixed once, here, and applied to all four: `_ssrf_safe_opener()` returns a
`urllib.request` opener whose redirect handler re-validates every hop
through `_ssrf_denial_reason()` before following it (`http_request`,
`check_url_status`); `_ssrf_safe_curl_fetch()` fetches via curl WITHOUT
`-L`, manually inspecting each response for a 3xx + `Location` header and
re-validating that target before following it, capped at 5 hops
(`fetch_url`, `inspect_openapi_spec`). Both were proved live to still
block the same malicious redirect AND to still correctly follow a
legitimate redirect to a real external site (`httpbin.org` →
`example.com`), so no real capability was lost.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

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


class _SsrfSafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-validates every redirect hop through `_ssrf_denial_reason()`
    before following it — closes the SSRF-via-redirect bypass
    `urlopen()`'s default redirect-following otherwise allows."""

    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Any:
        reason = _ssrf_denial_reason(newurl)
        if reason:
            raise urllib.error.HTTPError(
                newurl, code, f"Redirect blocked: {reason}", headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _ssrf_safe_opener() -> urllib.request.OpenerDirector:
    """A `urllib.request` opener for every `urlopen()`-based outbound
    fetch tool: the initial URL is still checked by the caller via
    `_ssrf_denial_reason()` before calling `.open()`, and this opener
    additionally re-validates every subsequent redirect hop the same
    way, so a malicious/compromised server the initial URL legitimately
    points to cannot use a redirect to reach a private/internal target."""
    return urllib.request.build_opener(_SsrfSafeRedirectHandler())


def _ssrf_safe_curl_fetch(
    url: str, timeout: int = 15, max_redirects: int = 5, max_chars: int = 10_000
) -> tuple[str, str | None]:
    """Fetches `url` via curl WITHOUT curl's own `-L` auto-redirect-
    following, manually validating and following each redirect hop
    through `_ssrf_denial_reason()` instead — closes the same
    SSRF-via-redirect bypass as `_ssrf_safe_opener()`, for the
    curl-subprocess-based outbound-fetch tools.

    Returns `(display_text, denial_reason)`. `denial_reason` is set
    ONLY for a real SSRF policy denial (the initial URL or a redirect
    hop) or a too-many-redirects abort — callers use this to return a
    `[POLICY DENIED] ...` response. For every other outcome
    (success, or an ordinary curl-level failure like a timeout or
    connection refusal), `denial_reason` is `None` and `display_text`
    already carries the right content to show the caller — the
    successful response body, or curl's own stderr (falling back to
    `[empty response]`) on failure, matching the exact fallback
    `fetch_url_handler` already used before this fix so no error
    information is silently lost. An empty status-line response (no
    headers written at all) is how a curl-level transport failure —
    as opposed to a legitimate empty-body HTTP response, which always
    has a status line — is distinguished here.

    B9 verification note: max_chars was previously a hardcoded 10_000, truncating the body
    BEFORE any caller got to look at it — fine as a display cap for arbitrary web page text
    (fetch_url's own default use), but wrong for a caller (inspect_openapi_spec) that must
    parse the ENTIRE document: a real OpenAPI spec is routinely well over 10KB, and cutting
    it mid-token corrupts the JSON/YAML so parsing fails with a confusing generic error
    instead of the content ever being examined. Proved live: a real public OpenAPI spec
    (~13.8KB) failed both the JSON and YAML parse after truncation, at exactly the 10,000-
    char boundary. Now parameterized — inspect_openapi_spec passes a much larger limit;
    fetch_url keeps its original 10_000 default, preserving its existing display behavior.
    """
    current_url = url
    for _ in range(max_redirects):
        reason = _ssrf_denial_reason(current_url)
        if reason:
            return "", reason

        fd, body_path = tempfile.mkstemp()
        os.close(fd)
        try:
            r = subprocess.run(
                [
                    "curl",
                    "-s",
                    "-D",
                    "-",
                    "-o",
                    body_path,
                    "--max-time",
                    str(timeout),
                    "--user-agent",
                    "Gridiron-Agent/1.0",
                    current_url,
                ],
                capture_output=True,
                text=True,
                timeout=timeout + 5,
            )
            headers = r.stdout
            body = Path(body_path).read_text(encoding="utf-8", errors="replace")
        finally:
            try:
                Path(body_path).unlink()
            except OSError:
                pass

        lines = headers.splitlines()
        status_line = lines[0] if lines else ""
        if not status_line:
            # curl never completed the request (DNS/connect/TLS/
            # timeout failure) — a real successful HTTP exchange
            # always writes at least a status line to -D.
            return body[:max_chars] or r.stderr or "[empty response]", None

        location: str | None = None
        for line in lines:
            if line.lower().startswith("location:"):
                location = line.split(":", 1)[1].strip()
                break

        is_redirect = any(
            f" {code} " in f" {status_line} "
            for code in ("301", "302", "303", "307", "308")
        )
        if is_redirect and location:
            current_url = urljoin(current_url, location)
            continue
        return body[:max_chars] or "[empty response]", None
    return "", f"Too many redirects (> {max_redirects})"


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
    # A 6-character prefix identifies a PROVIDER token (sk-ant-, ghp_16...) and is safe to
    # show; for a password or an arbitrary secret value it is 6 characters of the secret
    # (a 10-character password lost 60% of itself).
    prefix = value[:6] if _SECRET_VALUE_RE.match(value) else ""
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
                r"|gh[opsu]_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9\-]{10,}"
                # B6 verification: the shapes below went straight through — including
                # the platform's own ANTHROPIC_API_KEY (`sk-ant-...`: the hyphen after
                # "sk-ant" defeated the sk-[A-Za-z0-9]{16,} alternative).
                r"|sk-ant-[A-Za-z0-9_\-]{20,}|sk-(?:proj|svcacct|admin)-[A-Za-z0-9_\-]{20,}"
                r"|github_pat_[A-Za-z0-9_]{22,}|(?:sk|rk|pk)_live_[A-Za-z0-9]{16,}"
                r"|AIza[0-9A-Za-z_\-]{35}"
                r"|eyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,})"
            ),
            "bearer": _re.compile(r"(?i)\bbearer\s+([A-Za-z0-9._~+/=\-]{20,})"),
            "url_password": _re.compile(
                r"\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:([^\s@/]{3,})@"
            ),
            "pem_header": _re.compile(
                r"-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"
            ),
        }
    for line_no, line in enumerate(content.splitlines(), 1):
        m = _SECRET_CONTENT_RE["provider_token"].search(line)
        if m:
            return f"line {line_no} contains a value matching a known secret-token pattern ({m.group(1)[:6]}***REDACTED)"
        for extra in ("bearer", "url_password"):
            xm = _SECRET_CONTENT_RE[extra].search(line)
            if xm:
                return (
                    f"line {line_no} contains a credential ({extra}: "
                    f"{xm.group(1)[:4]}***REDACTED)"
                )
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
        # every token on the line (was: only the first — a second one leaked)
        for m in list(patterns["provider_token"].finditer(new_line)):
            token = m.group(1)
            new_line = new_line.replace(token, _mask_secret_value("TOKEN", token))
            found = True
        for extra in ("bearer", "url_password"):
            for m in list(patterns[extra].finditer(new_line)):
                new_line = new_line.replace(
                    m.group(1), _mask_secret_value("TOKEN", m.group(1))
                )
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


# ---------------------------------------------------------------------------
# AUDIT_Q_BATCH18 §54/55/56 gap-closure (2026-08-12) — "Refuse to invent
# APIs/files/functions/classes" was scored NO, not PARTIAL: every real
# no-hallucination mechanism this audit found (VerificationConfig.
# blocking_until, _quality_gate, the model-context-limit gate, ...)
# constrains what an agent may DO, none of them checks what an agent's own
# final CLAIM says — several of this codebase's own agent role prompts
# already demand a citation discipline ("each finding must cite file:line
# read this run", security_reviewer.py; "each with file:line evidence",
# architecture_reviewer.py) but nothing ever verified a submitted citation
# against the real repo. A citation regex is a legitimate first pass here
# (same class of extraction _scan_content_for_secrets already uses) — the
# actual verification is a real filesystem check (file exists, line number
# is within the file's real line count), never another regex pretending to
# confirm correctness.
_FILE_LINE_CITATION_RE = re.compile(
    r"([A-Za-z0-9_][A-Za-z0-9_./-]*\."
    r"(?:py|ts|tsx|js|jsx|go|rs|java|kt|rb|php|c|cpp|h|hpp|cs|"
    r"md|yml|yaml|json|toml|txt|sql|sh|html|css))"
    r":(\d+)(?:-\d+)?"
)


def _extract_file_line_citations(text: str) -> list[tuple[str, int]]:
    return [
        (m.group(1), int(m.group(2))) for m in _FILE_LINE_CITATION_RE.finditer(text)
    ]


def _collect_strings(value: Any) -> list[str]:
    """Recursively pulls every string leaf out of a submit_* tool's raw
    input dict (which may nest lists of dicts — e.g. architecture_reviewer's
    risks[].evidence) so citation extraction doesn't need one traversal
    written per agent's own result schema."""
    strings: list[str] = []
    if isinstance(value, str):
        strings.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            strings.extend(_collect_strings(v))
    elif isinstance(value, list):
        for v in value:
            strings.extend(_collect_strings(v))
    return strings


def verify_file_line_citations(
    repo_root: str, raw_result: dict[str, Any]
) -> dict[str, Any]:
    """Extracts every `path/to/file.ext:NNN` citation from a submit_*
    result's string fields and checks each against the real repo: does the
    file exist, and is the line number within that file's actual line
    count. Returns {checked, unverified} — `unverified` holds human-
    readable reasons, capped at 20 entries so a result with many bad
    citations doesn't blow up the response size.

    Deliberately non-blocking (flags, doesn't reject) — same "a false
    positive here should be visible, not lose real content" rationale
    _flag_suspicious_tool_output already applies to injection-pattern
    detection: a citation-shaped string that isn't really a file
    reference (a ratio, a timestamp, a version string) is a real risk this
    regex can't fully rule out, so silently blocking a real submission on
    one would be worse than the gap this closes. Never raises: a repo_root
    that doesn't exist, or an unreadable file, becomes an "unverified"
    entry, not an exception.
    """
    import os

    if not repo_root or not os.path.isdir(repo_root):
        return {"checked": 0, "unverified": []}

    strings = _collect_strings(raw_result)
    seen: set[tuple[str, int]] = set()
    unverified: list[str] = []
    checked = 0
    for text in strings:
        for rel_path, line in _extract_file_line_citations(text):
            key = (rel_path, line)
            if key in seen:
                continue
            seen.add(key)
            checked += 1
            abs_path = os.path.realpath(os.path.join(repo_root, rel_path))
            root_real = os.path.realpath(repo_root)
            if abs_path != root_real and not abs_path.startswith(root_real + os.sep):
                # a citation like `x/../../etc/hosts.txt:1` must not turn this into a
                # probe of files outside the repo (exists / how many lines)
                if len(unverified) < 20:
                    unverified.append(f"{rel_path}:{line} — outside the repo")
                continue
            if not os.path.isfile(abs_path):
                if len(unverified) < 20:
                    unverified.append(f"{rel_path}:{line} — file not found in repo")
                continue
            try:
                with open(abs_path, encoding="utf-8", errors="replace") as f:
                    total_lines = sum(1 for _ in f)
            except OSError:
                if len(unverified) < 20:
                    unverified.append(f"{rel_path}:{line} — could not read file")
                continue
            if line < 1 or line > max(total_lines, 1):
                if len(unverified) < 20:
                    unverified.append(
                        f"{rel_path}:{line} — file has only {total_lines} line(s)"
                    )

    return {"checked": checked, "unverified": unverified}


# Stage 4 Tier 3 (2026-08-05, answer2.md Q17) — real, bounded structured
# pattern-detection over raw docker_logs output (previously returned
# completely unparsed, per that finding). Mirrors this same codebase's own
# established analyze_error() convention exactly (real pattern list,
# "=== X Analysis ===" formatted summary prepended to the real content, not
# replacing it). Docker containers run arbitrary applications with no fixed
# log schema, so this is deliberately pattern/keyword detection, not a
# claim of full structured (e.g. JSON) log parsing for every possible
# container.
#
# tool_enhance.md productionization pass, tool #108 (2026-08-25) —
# relocated here from app/agents/tools.py so both `docker_logs` (this
# tool) and `diagnose_deployment_failure` (tool #106, which also needs
# it) can import it from a neutral, lower-level module without either
# creating a circular import or resorting to a lazy in-function import.
# tools.py re-exports this name for backward compatibility with any
# other existing reference.
_DOCKER_LOG_ERROR_PATTERNS = (
    "error",
    "exception",
    "fatal",
    "panic",
    "traceback",
    "failed",
)
_DOCKER_LOG_WARNING_PATTERNS = ("warn",)
_DOCKER_LOG_CRASH_PATTERNS = (
    "oomkilled",
    "out of memory",
    "sigkill",
    "sigsegv",
    "segmentation fault",
    "core dumped",
    "exit code 1",
    "exit code 137",
)


def _summarize_docker_log_patterns(raw_log: str) -> str:
    lines = raw_log.splitlines()
    error_lines = [
        ln for ln in lines if any(p in ln.lower() for p in _DOCKER_LOG_ERROR_PATTERNS)
    ]
    warning_lines = [
        ln
        for ln in lines
        if any(p in ln.lower() for p in _DOCKER_LOG_WARNING_PATTERNS)
        and ln not in error_lines
    ]
    crash_lines = [
        ln for ln in lines if any(p in ln.lower() for p in _DOCKER_LOG_CRASH_PATTERNS)
    ]

    if not error_lines and not warning_lines and not crash_lines:
        return ""

    parts = ["=== Docker Log Analysis ==="]
    if crash_lines:
        parts.append(f"Crash/OOM signatures ({len(crash_lines)}):")
        parts.extend(f"  {ln.strip()}" for ln in crash_lines[:5])
    if error_lines:
        parts.append(f"Error/exception lines ({len(error_lines)}):")
        parts.extend(f"  {ln.strip()}" for ln in error_lines[:5])
    if warning_lines:
        parts.append(f"Warning lines ({len(warning_lines)}):")
        parts.extend(f"  {ln.strip()}" for ln in warning_lines[:5])
    parts.append("--- raw log below ---\n")
    return "\n".join(parts)
