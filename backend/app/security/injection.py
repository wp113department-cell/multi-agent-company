"""Text that looks like an injected instruction (G2, 2026-10-09).

Shared by the agent loop (which flags such text in tool output and marks
external content as data) and memory curation (which refuses to store it,
so a poisoned README, web page or log can't become a "lesson" every later
agent is told to follow). Deliberately pattern-based and conservative:
flagging tool output never discards content, and memory only loses text
that reads as instructions to an AI rather than knowledge about code.
"""

from __future__ import annotations

import re

INJECTION_PATTERNS = [
    re.compile(r"(?im)^\s*(system|assistant)\s*:"),
    re.compile(r"(?i)ignore (all )?(previous|prior|above) instructions"),
    re.compile(r"<\|(system|assistant|im_start|im_end)\|>"),
    re.compile(r"(?im)^\s*#{1,3}\s*(system|instructions?)\s*$"),
    # B7 verification — the four patterns above caught one phrasing each; common
    # variants went through unflagged:
    re.compile(
        r"(?i)\b(disregard|forget|override)\b.{0,30}\b(previous|prior|above|earlier|all)\b"
        r".{0,30}\b(instructions?|rules?|prompts?|context)\b"
    ),
    re.compile(r"(?i)\byou are now\b"),
    re.compile(r"(?i)\bnew (system )?instructions?\s*:"),
    re.compile(r"(?i)</?(system|assistant|instructions?)>|\[/?INST\]|<<SYS>>"),
    re.compile(r"(?i)\bdo not (tell|inform|mention)\b.{0,20}\buser\b"),
    re.compile(
        r"(?i)\b(send|post|upload|exfiltrate|email)\b.{0,40}"
        r"\b(secrets?|credentials?|api[_ ]?keys?|tokens?|\.env)\b"
    ),
]


def looks_like_injection(text: str) -> bool:
    return any(p.search(text) for p in INJECTION_PATTERNS)
