from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from src.bot.services.routerai_client import RouterAIClient


@dataclass
class NotebookDigest:
    title: str
    content_hash: str
    compact_context: str
    tokens_estimate: int


def extract_text_from_ipynb(raw_bytes: bytes) -> tuple[str, str]:
    try:
        payload = json.loads(raw_bytes.decode("utf-8-sig"))
    except Exception as exc:
        raise ValueError("Invalid .ipynb JSON content") from exc
    cells = payload.get("cells", [])
    chunks: list[str] = []
    for cell in cells:
        source = cell.get("source", [])
        if isinstance(source, list):
            text = "".join(source)
        else:
            text = str(source)
        text = text.strip()
        if text:
            chunks.append(text)
    all_text = "\n\n".join(chunks)
    title = chunks[0].split("\n")[0][:100] if chunks else "Notebook lesson"
    return title, all_text


async def build_notebook_digest(raw_bytes: bytes, llm: RouterAIClient) -> NotebookDigest:
    title, raw_text = extract_text_from_ipynb(raw_bytes)
    content_hash = hashlib.sha256(raw_bytes).hexdigest()
    compact_context = await llm.summarize_lesson(raw_text)
    tokens_estimate = max(1, len(compact_context) // 4)
    return NotebookDigest(
        title=title,
        content_hash=content_hash,
        compact_context=compact_context[:20000],
        tokens_estimate=tokens_estimate,
    )
