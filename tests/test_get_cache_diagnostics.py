"""Tests for get_cache_diagnostics tool handler."""

import json
import time
from unittest.mock import patch

import diskcache
import pytest
from mcp.types import TextContent


@pytest.mark.asyncio
async def test_get_cache_diagnostics_returns_text_content(tmp_path):
    """get_cache_diagnostics_handler must return list[TextContent], not a dict."""
    from istat_mcp_server.tools.get_cache_diagnostics import get_cache_diagnostics_handler

    with patch('istat_mcp_server.server.PERSISTENT_CACHE_DIR', str(tmp_path)):
        result = await get_cache_diagnostics_handler()

    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], TextContent)
    assert result[0].type == 'text'

    # The text must be valid JSON containing the expected keys
    data = json.loads(result[0].text)
    assert 'cache_path' in data
    assert 'cache_exists' in data


@pytest.mark.asyncio
async def test_get_cache_diagnostics_nonexistent_cache(tmp_path):
    """Handler returns TextContent even when the cache directory does not exist."""
    from istat_mcp_server.tools.get_cache_diagnostics import get_cache_diagnostics_handler

    nonexistent = str(tmp_path / 'does_not_exist')
    with patch('istat_mcp_server.server.PERSISTENT_CACHE_DIR', nonexistent):
        result = await get_cache_diagnostics_handler()

    assert isinstance(result, list)
    assert isinstance(result[0], TextContent)
    data = json.loads(result[0].text)
    assert data['cache_exists'] is False


@pytest.mark.asyncio
async def test_get_cache_diagnostics_excludes_expired_keys(tmp_path):
    """Expired keys must not appear in persistent_cache_keys."""
    from istat_mcp_server.tools.get_cache_diagnostics import get_cache_diagnostics_handler

    # Pre-populate cache with a key that expires in 1 second
    with diskcache.Cache(str(tmp_path)) as cache:
        cache.set('expired_key', 'value', expire=1)
        cache.set('valid_key', 'value', expire=3600)

    time.sleep(1.5)

    with patch('istat_mcp_server.server.PERSISTENT_CACHE_DIR', str(tmp_path)):
        result = await get_cache_diagnostics_handler()

    data = json.loads(result[0].text)
    assert 'expired_key' not in data['persistent_cache_keys']
    assert 'valid_key' in data['persistent_cache_keys']
    assert data['persistent_cache_size'] == 1
