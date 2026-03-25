"""Tool: discover_dataflows - Discover available dataflows from ISTAT SDMX API."""

import logging
from typing import Any

from mcp.types import TextContent

from ..api.client import ApiClient
from ..api.models import DiscoverDataflowsInput
from ..cache.manager import CacheManager
from ..utils.validators import validate_keywords
from ..utils.blacklist import DataflowBlacklist
from ..utils.tool_helpers import (
    format_json_response,
    get_cached_dataflows,
    handle_tool_errors,
)
from ..search import semantic as sem

logger = logging.getLogger(__name__)

EMBEDDINGS_CACHE_KEY = sem.EMBEDDINGS_CACHE_KEY
EMBEDDINGS_CACHE_TTL = 604800  # 7 days, same as dataflows


@handle_tool_errors
async def handle_discover_dataflows(
    arguments: dict[str, Any],
    cache: CacheManager,
    api: ApiClient,
    blacklist: DataflowBlacklist,
) -> list[TextContent]:
    """Handle discover_dataflows tool."""
    params = DiscoverDataflowsInput.model_validate(arguments)
    keywords = validate_keywords(params.keywords)
    max_results = getattr(params, 'max_results', 10)

    logger.info(f'discover_dataflows: keywords={keywords}')

    dataflows = await get_cached_dataflows(cache, api)
    dataflows = blacklist.filter_dataflows(dataflows)

    if keywords:
        query = ' '.join(keywords)

        if sem.is_available():
            cached_embeddings = cache.get(EMBEDDINGS_CACHE_KEY)
            matched, embeddings = sem.semantic_search(
                query=query,
                dataflows=dataflows,
                cached_embeddings=cached_embeddings,
                max_results=max_results,
            )
            cache.set(EMBEDDINGS_CACHE_KEY, embeddings, persistent_ttl=EMBEDDINGS_CACHE_TTL)
            dataflows = matched
            logger.info(f'Semantic search returned {len(dataflows)} dataflows')
        else:
            # Fallback: string matching (original behaviour)
            logger.info('sentence-transformers not installed, falling back to keyword matching')
            dataflows = [
                df for df in dataflows
                if any(kw in ' '.join([
                    df.id, df.name_it, df.name_en,
                    df.description_it, df.description_en, df.id_datastructure
                ]).lower() for kw in keywords)
            ]
            logger.info(f'Filtered to {len(dataflows)} dataflows')

    response = {
        'count': len(dataflows),
        'dataflows': [df.model_dump() for df in dataflows],
    }

    return format_json_response(response)
