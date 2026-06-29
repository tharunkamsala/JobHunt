"""Strip HTML job descriptions to plain text for storage and search."""
from __future__ import annotations

import html
import re


def strip_html(text: str | None, *, max_len: int = 20000) -> str | None:
    if not text or not str(text).strip():
        return None
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", str(text), flags=re.I | re.S)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"</p\s*>", "\n\n", t, flags=re.I)
    t = re.sub(r"<li[^>]*>", "\n• ", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = re.sub(r"[ \t]{2,}", " ", t).strip()
    if not t:
        return None
    if len(t) > max_len:
        return t[: max_len - 1].rstrip() + "…"
    return t
