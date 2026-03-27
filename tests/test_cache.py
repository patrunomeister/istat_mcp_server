"""Tests for cache functionality."""

import pytest

from istat_mcp_server.cache.manager import CacheManager
from istat_mcp_server.cache.memory import MemoryCache
from istat_mcp_server.cache.persistent import PersistentCache
from istat_mcp_server.utils.tool_helpers import METADATA_CACHE_TTL


def test_memory_cache_basic(memory_cache):
    """Test basic memory cache operations."""
    # Set and get
    memory_cache.set('key1', 'value1')
    assert memory_cache.get('key1') == 'value1'

    # Get nonexistent key
    assert memory_cache.get('nonexistent') is None

    # Delete
    memory_cache.delete('key1')
    assert memory_cache.get('key1') is None


def test_persistent_cache_basic(persistent_cache):
    """Test basic persistent cache operations."""
    # Set and get
    persistent_cache.set('key1', 'value1')
    assert persistent_cache.get('key1') == 'value1'

    # Get nonexistent key
    assert persistent_cache.get('nonexistent') is None

    # Delete
    persistent_cache.delete('key1')
    assert persistent_cache.get('key1') is None


def test_cache_manager_two_layer(cache_manager):
    """Test cache manager with two layers."""
    # Set in both layers
    cache_manager.set('key1', 'value1', persistent_ttl=3600)

    # Should retrieve from memory
    assert cache_manager.get('key1') == 'value1'

    # Clear memory cache
    cache_manager._memory.clear()

    # Should retrieve from persistent and populate memory
    assert cache_manager.get('key1') == 'value1'
    assert cache_manager._memory.get('key1') == 'value1'


@pytest.mark.asyncio
async def test_cache_manager_get_or_fetch(cache_manager):
    """Test get_or_fetch functionality."""
    fetch_count = 0

    async def fetch_func():
        nonlocal fetch_count
        fetch_count += 1
        return f'value_{fetch_count}'

    # First call - should fetch
    value1 = await cache_manager.get_or_fetch('key1', fetch_func, persistent_ttl=3600)
    assert value1 == 'value_1'
    assert fetch_count == 1

    # Second call - should use cache
    value2 = await cache_manager.get_or_fetch('key1', fetch_func, persistent_ttl=3600)
    assert value2 == 'value_1'
    assert fetch_count == 1  # Not incremented


def test_metadata_ttl_is_one_month():
    """METADATA_CACHE_TTL must equal 30 days (2592000 seconds)."""
    assert METADATA_CACHE_TTL == 30 * 24 * 3600


@pytest.mark.asyncio
async def test_get_or_fetch_serves_from_persistent_after_memory_clear(cache_manager):
    """After memory cache is cleared (simulating a restart), data is still served
    from the persistent cache without calling the fetch function again."""
    fetch_count = 0

    async def fetch_func():
        nonlocal fetch_count
        fetch_count += 1
        return 'expensive_value'

    # First call — fetches from source and caches in both layers
    value1 = await cache_manager.get_or_fetch(
        'test_key', fetch_func, persistent_ttl=METADATA_CACHE_TTL
    )
    assert value1 == 'expensive_value'
    assert fetch_count == 1

    # Simulate server restart by clearing memory cache
    cache_manager._memory.clear()

    # Second call — must be served from persistent cache, not re-fetched
    value2 = await cache_manager.get_or_fetch(
        'test_key', fetch_func, persistent_ttl=METADATA_CACHE_TTL
    )
    assert value2 == 'expensive_value'
    assert fetch_count == 1  # API not called again
