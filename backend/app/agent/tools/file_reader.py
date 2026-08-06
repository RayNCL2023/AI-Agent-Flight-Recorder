"""Sandboxed file reader: only paths inside `file_reader_root` are allowed."""

from pathlib import Path
from typing import Any

from ...config import get_settings

_MAX_BYTES = 32_768


def run_file_reader(args: dict[str, Any], _seed: int) -> dict[str, Any]:
    rel = str(args.get("path", "")).strip()
    if not rel:
        raise ValueError("path is required")

    root = Path(get_settings().file_reader_root).resolve()
    target = (root / rel).resolve()
    if root not in target.parents and target != root:
        raise ValueError("path escapes the sandbox")
    if not target.is_file():
        available = sorted(
            str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()
        ) if root.is_dir() else []
        raise FileNotFoundError(
            f"file not found: {rel}. Available files: {', '.join(available) or '(none)'}"
        )

    data = target.read_bytes()[:_MAX_BYTES]
    return {
        "path": rel,
        "size_bytes": target.stat().st_size,
        "content": data.decode("utf-8", errors="replace"),
    }
