import os
import json
import asyncio
from typing import Any, Dict

# Simple async JSON storage with per-file locks to avoid race conditions

_locks: Dict[str, asyncio.Lock] = {}


def _ensure_dir(path: str):
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)


def _get_lock(path: str) -> asyncio.Lock:
    if path not in _locks:
        _locks[path] = asyncio.Lock()
    return _locks[path]


async def load_json(path: str, default: Any) -> Any:
    lock = _get_lock(path)
    async with lock:
        try:
            if not os.path.exists(path):
                return default
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return default


async def save_json(path: str, data: Any) -> None:
    lock = _get_lock(path)
    async with lock:
        try:
            _ensure_dir(path)
            tmp = path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception:
            # Best-effort; ignore write errors to avoid crashing scheduled loops
            pass
