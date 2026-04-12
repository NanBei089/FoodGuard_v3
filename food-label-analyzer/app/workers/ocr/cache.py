from __future__ import annotations

import threading
from typing import Any, Callable

_ENGINE_CACHE: dict[str, Any] = {}
_engine_lock = threading.Lock()


def get_cached_engine(cache_key: str, builder: Callable[[], Any]) -> Any:
    if cache_key not in _ENGINE_CACHE:
        with _engine_lock:
            if cache_key not in _ENGINE_CACHE:
                _ENGINE_CACHE[cache_key] = builder()
    return _ENGINE_CACHE[cache_key]
