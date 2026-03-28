---
name: istat-mcp
description: >
  Workflow guide for querying Italian ISTAT statistical data via this MCP server.
  Use this skill whenever working with ISTAT data, SDMX dataflows, Italian statistics,
  regional/provincial data, unemployment, population, GDP, agriculture, or any other
  ISTAT dataset. Guides the discover -> constraints -> data workflow step by step.
license: MIT
compatibility: Requires the istat MCP server to be running (provides 7 tools for ISTAT SDMX API access).
metadata:
  author: ondata
  version: "1.0"
---

# ISTAT MCP Server - Workflow Guide

## Quick Start

Always follow this 3-step workflow:

1. **Discover** the dataflow with `discover_dataflows`
2. **Get metadata** with `get_constraints` (one call returns dimensions + valid codes + descriptions)
3. **Fetch data** with `get_data` using the codes from step 2

## Available Tools

| # | Tool | Purpose |
|---|------|---------|
| 1 | `discover_dataflows` | Find datasets by keywords (with blacklist filtering) |
| 2 | `get_constraints` | Retrieve constraints + structure + descriptions in one call |
| 3 | `get_structure` | Retrieve dimensions and codelists definitions |
| 4 | `get_codelist_description` | Retrieve IT/EN descriptions for codelist values |
| 5 | `get_concepts` | Retrieve semantic definitions of SDMX concepts |
| 6 | `get_data` | Retrieve statistical observations |
| 7 | `get_cache_diagnostics` | Debug tool to inspect cache status |

## Detailed Workflow

### Step 1: Identify Dataflows

Use `discover_dataflows` with comma-separated keywords (Italian or English).

```json
{ "keywords": "employment,labour,work" }
```

Output: list of dataflows with ID, names (IT/EN), and descriptions.

Note: dataflows in the blacklist (env var `DATAFLOW_BLACKLIST`) are automatically excluded.

### Step 2: Retrieve Constraints and Descriptions

Use `get_constraints` with the dataflow ID from step 1. This is the **recommended** approach - one call instead of many.

```json
{ "dataflow_id": "101_1015_DF_DCSP_COLTIVAZIONI_1" }
```

This internally calls `get_structure` + `get_codelist_description` for each dimension. Everything is cached for 1 month.

Output includes:
- Dimension names and order
- Valid codes for each dimension (only values available for that dataflow)
- Italian and English descriptions for each code
- Codelist IDs

**Alternative manual approach**: call `get_structure` first, then `get_codelist_description` for each codelist you need.

### Step 3: Fetch Data

Use `get_data` with dimension filters built from step 2 output.

```json
{
  "id_dataflow": "149_577_DF_DCSC_OROS_1_1",
  "dimension_filters": {
    "FREQ": ["Q"],
    "REF_AREA": ["IT"],
    "DATA_TYPE": ["FT_EMPL_1"],
    "ADJUSTMENT": ["N"],
    "ECON_ACTIVITY_NACE_2007": ["0011", "0013", "0015"]
  },
  "start_period": "2020-01-01",
  "end_period": "2023-12-31"
}
```

Key rules for `get_data`:
- **Dimension order** must follow the order from `get_constraints`
- **Multiple codes** for the same dimension: use an array `["0011", "0013"]`
- **No filter** on a dimension: omit it from `dimension_filters`
- **Default behavior**: if no time range is specified, only the latest available year is returned
- **Rate limit**: the ISTAT API allows max 3 calls per minute (handled automatically)

## Best Practices

1. **Always start with `get_constraints`** before `get_data` - it gives you correct dimension order and valid codes
2. **Start with fewer filters** and add constraints progressively to avoid empty datasets
3. **Omit time range** for a quick latest-year pull; specify full ranges for historical analysis
4. **Inspect codelist values** to pick exact, valid codes
5. **Cache is your friend**: metadata cached 1 month, dataflows 7 days, data 1 hour

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Dataset too large | Add more dimension filters or reduce time range |
| No data returned | Verify codes exist in the codelist and are compatible |
| Wrong dimension order | Check `get_constraints` output for correct order |
| 404 errors | Ensure all dimensions are present in correct order |
