"""Tool per diagnosticare lo stato della cache."""

from pathlib import Path

import diskcache
from mcp.types import TextContent

from ..utils.tool_helpers import format_json_response


async def get_cache_diagnostics_handler() -> list[TextContent]:
    """
    Restituisce informazioni diagnostiche sulla cache.

    Returns:
        List containing single TextContent with JSON-formatted diagnostics:
        - cache_path: path assoluto della directory cache
        - cache_exists: se la directory esiste
        - persistent_cache_size: numero di item in cache persistente
        - persistent_cache_keys: lista delle chiavi in cache
        - cache_writable: se la directory è scrivibile
        - errors: lista di errori (se presenti)
    """
    from ..server import PERSISTENT_CACHE_DIR

    cache_path = Path(PERSISTENT_CACHE_DIR).absolute()
    cache_exists = cache_path.exists()
    errors = []

    info = {
        "cache_path": str(cache_path),
        "cache_exists": cache_exists,
        "cache_writable": False,
        "persistent_cache_size": 0,
        "persistent_cache_keys": [],
    }

    if not cache_exists:
        return format_json_response(info)

    # Test scrittura
    try:
        test_file = cache_path / ".write_test"
        test_file.write_text("test")
        test_file.unlink()
        info["cache_writable"] = True
    except Exception as e:
        errors.append(f"Write test failed: {e}")

    # Ispezione cache persistente con context manager
    try:
        with diskcache.Cache(str(cache_path)) as cache:
            cache.expire()
            info["persistent_cache_size"] = len(cache)
            info["persistent_cache_keys"] = list(cache.iterkeys())
    except Exception as e:
        errors.append(f"Cache inspection failed: {e}")

    if errors:
        info["errors"] = errors

    return format_json_response(info)
