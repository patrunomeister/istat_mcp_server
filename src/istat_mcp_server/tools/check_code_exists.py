"""Tool: check_code_exists - Check if dimension codes exist in a dataflow."""

import json
import logging
from typing import Any

from mcp.types import TextContent

from ..api.client import ApiClient
from ..cache.manager import CacheManager
from ..utils.tool_helpers import (
    format_json_response,
    get_cached_dataflows,
    get_cached_datastructure,
    find_dataflow_info,
    handle_tool_errors,
)

logger = logging.getLogger(__name__)


@handle_tool_errors
async def handle_check_code_exists(
    arguments: dict[str, Any],
    cache: CacheManager,
    api: ApiClient,
) -> list[TextContent]:
    """Check if codes exist for a given dimension in a dataflow.

    Uses codelist item query (~0.6s per code) instead of downloading all
    constraints (2+ minutes). Checks if the code exists in the dimension's
    codelist via GET /codelist/{agency}/{id}/{version}/{item_id}.

    Note: this verifies codelist membership, not dataflow constraint membership.
    A code in the codelist very likely has data, but if get_data returns empty,
    the user should be informed and exploration via search_constraint_values suggested.

    Args:
        arguments:
            'dataflow_id': Dataflow ID to check
            'dimension': Dimension ID to check (e.g., 'REF_AREA', 'AGE', 'SEX')
            'codes': List of codes to verify (e.g., ['082053', 'ITG12'])

    Returns:
        JSON: {dataflow_id, dimension, results: [{code, exists}]}
    """
    dataflow_id = arguments.get('dataflow_id', '').strip()
    dimension = arguments.get('dimension', '').strip().upper()
    codes = arguments.get('codes', [])

    if not dataflow_id:
        return format_json_response({'error': "Missing 'dataflow_id'"})
    if not dimension:
        return format_json_response({'error': "Missing 'dimension'"})
    if not codes:
        return format_json_response({'error': "Missing 'codes'"})

    if dimension == 'TIME_PERIOD':
        return format_json_response({
            'error': (
                "TIME_PERIOD is a range dimension and cannot be checked with this tool. "
                "Use get_constraints to retrieve the available StartPeriod/EndPeriod range."
            )
        })

    if isinstance(codes, str):
        try:
            codes = json.loads(codes)
        except (json.JSONDecodeError, ValueError):
            codes = [c.strip() for c in codes.split(',')]

    # Verify dataflow exists
    dataflows = await get_cached_dataflows(cache, api)
    dataflow_info = find_dataflow_info(dataflows, dataflow_id)
    if not dataflow_info:
        return format_json_response({'error': f'Dataflow not found: {dataflow_id}'})

    # Get datastructure to find the codelist for the requested dimension
    datastructure = await get_cached_datastructure(cache, api, dataflow_info.id_datastructure)
    dim_info = next(
        (d for d in datastructure.dimensions if d.dimension == dimension), None
    )
    if dim_info is None:
        available = [d.dimension for d in datastructure.dimensions]
        return format_json_response({
            'error': f"Dimension '{dimension}' not found in this dataflow",
            'available_dimensions': available,
        })

    codelist_id = dim_info.codelist
    if not codelist_id:
        return format_json_response({
            'error': f"No codelist found for dimension '{dimension}'",
        })

    # Check all codes in a single batch API call (~2s total)
    found_codes = await api.fetch_codelist_items(codelist_id, codes)
    results = [{'code': code, 'exists': code in found_codes} for code in codes]

    return format_json_response({
        'dataflow_id': dataflow_id,
        'dimension': dimension,
        'codelist': codelist_id,
        'note': 'Verified against codelist (not dataflow constraints). If get_data returns empty, try search_constraint_values to explore available codes.',
        'results': results,
    })
