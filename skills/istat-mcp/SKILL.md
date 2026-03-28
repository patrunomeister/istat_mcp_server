---
name: istat-mcp
description: >
  Workflow guide for querying Italian ISTAT statistical data via this MCP server.
  Use this skill whenever working with ISTAT data, SDMX dataflows, Italian statistics,
  regional/provincial data, unemployment, population, GDP, agriculture, or any other
  ISTAT indicator — even when the user doesn't explicitly mention ISTAT or SDMX.
  Triggers on requests like "trova dati ISTAT su X", "disoccupazione per regione",
  "dati popolazione Italia", "statistiche agricoltura", or any query that could be
  answered with official Italian statistical data.
license: MIT
compatibility: Requires the ISTAT MCP server (mcp__istat__* tools).
metadata:
  author: ondata
  version: "1.3"
---

# ISTAT MCP Server — Query Workflow

This MCP server exposes 10 tools to access Italian ISTAT statistical data via the SDMX REST API.
Always follow the **3-step workflow** below. Never skip steps.

---

## The 3-Step Workflow

### Step 1 — `discover_dataflows`

Search for relevant dataflows. The tool performs **keyword search** across dataflow IDs, names,
descriptions, and data structure IDs, returning results in compact TOON (Token-Oriented Object
Notation) text format: one dataflow per line with `id`, `name_it`, `description_it`.

Your job: read the results and pick the most relevant dataflow ID for the user's request.
Prefer dataflows whose `name_it` directly matches the topic.

```
discover_dataflows(keywords="disoccupazione,regioni")
```

Parameters:
- `keywords`: comma-separated terms, Italian or English — each token is matched independently against all fields

#### Fallback — when results are not relevant

If the results don't match the user's topic,
**do not stop** — try `discover_dataflows` again with different keywords before concluding that
data doesn't exist. Strategies to try, in order:

1. **Synonyms or related terms** — e.g., if "olio oliva" fails, try "olive", "oleario", "grassi vegetali"
2. **Switch language** — if Italian keywords fail, try English (or vice versa)
3. **Broader category** — e.g., if "olio d'oliva" fails, try "agricoltura", "prodotti alimentari", "agroalimentare"
4. **Different keywords** — think about how ISTAT might classify the topic (e.g., by sector ATECO, by transport mode, by price index)

Only after 2–3 failed `discover_dataflows` attempts with diverse keywords should you conclude
that the data is not available in this MCP server and suggest alternative sources.

#### Generic vs specific dataflow IDs

`discover_dataflows` may return both a **generic ID** (e.g., `29_317`) and one or more **specific IDs**
with a `_DF_` suffix (e.g., `29_317_DF_DCIS_POPSTRCIT1_1`).

**Always prefer the specific `_DF_` variant.** Generic IDs are parent containers that aggregate many
series — calling `get_constraints` or `get_data` on them causes timeouts (180s+).

If only a generic ID appears in the results, run `discover_dataflows` again with more specific keywords
to surface the concrete `_DF_` variant before proceeding.

#### Granularity signals in dataflow names

The dataflow name often contains a suffix that reveals its territorial granularity.
**Read this before selecting a dataflow** — high-granularity dataflows will almost always
timeout when queried at national level.

| Name suffix | Granularity | Timeout risk |
|---|---|---|
| `- comuni` | Municipality-level | Very high — avoid for national queries |
| `- prov.` or `- province` | Province-level | High — use only when provincial detail is needed |
| `- reg.` or `- regioni` | Regional-level | Medium — acceptable for regional breakdowns |
| `Italia, regioni, province` | Multi-level (includes national) | Low — safe for national queries |
| *(no suffix)* | Usually national | Low |

**Rule:** if the user asks for national or aggregate data, always prefer a dataflow whose name
contains "Italia" or has no territorial suffix over one ending in "- comuni" or "- prov.".
When both options appear in `discover_dataflows` results, pick the less granular one first.

### Step 2 — Verify codes before fetching data

This step has two paths depending on what you need to verify. **Always take the fastest path first.**

#### Step 2a — Territorial codes: `get_territorial_codes` + `check_code_exists`

> **Mandatory rule:** whenever the user asks for data at a specific geographic level
> (city, province, region), **immediately call `get_territorial_codes(level=..., name=...)`**
> to obtain the correct territorial code. Do this **before** any `search_constraint_values`
> call on the dataflow.

```
# Get code at the RIGHT level (infer from user context)
get_territorial_codes(level="provincia", name="Palermo")
# → {"code": "ITG12", "name_it": "Palermo"}

# Verify code exists in the dataflow's codelist (~2s, batch)
check_code_exists(dataflow_id="...", dimension="REF_AREA", codes=["ITG12", "ITF52"])
# → results: [{code: "ITG12", exists: true}, {code: "ITF52", exists: true}]
```

`check_code_exists` uses a **codelist item query** (~2s for any number of codes in a single batch).
It verifies that the code exists in the dimension's codelist, not in the dataflow's constraint set.
This is almost always sufficient: if a territorial code is in the codelist, it very likely has data.

**If `check_code_exists` returns false:** the dataflow may not have data at that geographic level.
Try a different level:

```
# Municipality code not found? Try province level
get_territorial_codes(level="provincia", name="Torino")
check_code_exists(dataflow_id="...", dimension="REF_AREA", codes=["ITC11"])
# Inform user: "data available at province level, not municipality"
```

**If code exists but `get_data` returns empty:** the code is in the codelist but has no data in
this specific dataflow. Inform the user and suggest `search_constraint_values` to explore what
territorial levels actually have data.

**Always pass `level=` explicitly** when searching by name. Do not call
`get_territorial_codes(name="Roma")` without `level=` — the multi-level results
make it ambiguous which code to pick.

| User says | Intended level | Call |
|---|---|---|
| "città", "comune", specific city name | `comune` | `get_territorial_codes(level="comune", name="Roma")` |
| "provincia", "province of…" | `provincia` | `get_territorial_codes(level="provincia", name="Roma")` |
| "regione", "region" | `regione` | `get_territorial_codes(level="regione", name="Lazio")` |

> **Anti-pattern — never use `search_constraint_values` to discover territorial codes by name.**
> It returns whatever codes are *in the dataflow* that match, often at the wrong geographic level.

#### Step 2b — Discovering dimension codes: `get_constraints`

> **Skip this when territorial codes are already known.** Go directly to Step 3.

Use `get_constraints` only when you need to discover unknown dimension codes (AGE groups,
DATA_TYPE values, etc.). **Always pass only the dimensions you need** — fetching all dimensions
on complex dataflows causes timeouts (180s+).

```
# Only need AGE codes
get_constraints(dataflow_id="29_7_DF_DCIS_POPSTRRES1_1", dimensions=["AGE"])
```

Skip dimensions with well-known defaults (`SEX`, `FREQ`, `TIME_PERIOD`) — apply their safe
defaults directly in `get_data`.

#### Step 2c — When you don't know dimension codes and `get_constraints` times out

Use the **safe preview pattern** from Step 3 instead: call `get_data` with maximum filters
and `last_n_observations=1` to discover dimension codes from actual data. See Step 3 for details.

### Step 3 — `get_data`

Fetch actual data. **Always use the narrowest-first strategy**: start with maximum filters,
then expand only if needed.

#### CRITICAL: Understanding `last_n_observations`

`last_n_observations=1` returns the **most recent observation per series**, NOT 1 total row.
A dataflow with 100 provinces × 14 age groups × 3 sexes × 4 result types = 16,800 series.
With `last_n_observations=1`, you still get 16,800 rows (one per series).

**The only way to reduce rows is to close dimensions with filters.** `last_n_observations`
only helps when you've already filtered down to a small number of series.

#### The narrowest-first strategy

**Always filter ALL dimensions you can.** Every open dimension multiplies the number of series.

**Phase 1 — Maximum filters, single territory, `last_n_observations=1`:**

```
get_data(
  id_dataflow="41_270_DF_DCIS_MORTIFERITISTR1_1",
  dimension_filters={
    "REF_AREA": ["IT"],          # national total
    "FREQ": ["A"],               # annual
    "SEX": ["9"],                # both sexes
    "MONTH": ["99"]              # annual total (not monthly)
  },
  last_n_observations=1
)
```

This first call reveals the **actual dimension codes** in the response (DATA_TYPE values,
RESULT codes, AGE classes, etc.). Read them from the output before building the real query.

**Phase 2 — Targeted query with all dimensions closed:**

```
# Now you know from Phase 1: RESULT has M (morti), F (feriti), 9 (totale)
get_data(
  id_dataflow="41_270_DF_DCIS_MORTIFERITISTR1_1",
  dimension_filters={
    "REF_AREA": ["ITG12", "ITF52"],   # Palermo + Matera provinces
    "FREQ": ["A"],
    "SEX": ["9"],
    "RESULT": ["M"],                   # solo morti — from Phase 1
    "PERSON_CLASS": ["9"],             # totale
    "AGE": ["TOTAL"],
    "MONTH": ["99"],
    "DATA_TYPE": ["KILLINJ"],          # from Phase 1
    "ACCIDENT_LOCALIZATON": ["9"],
    "TY_ROAD_ACCIDENT": ["9"],
    "INTERSECTION": ["1"]
  },
  start_period="2020-01-01",
  end_period="2024-12-31"
)
```

**Phase 3 — If Phase 1 times out, close even more dimensions:**

Some dataflows are inherently slow on ISTAT's server (60–120s even for 1 series). If Phase 1
times out:
1. Add more safe defaults: `AGE: ["TOTAL"]`, `PERSON_CLASS: ["9"]`, `RESULT: ["9"]`
2. Use `start_period` and `end_period` to restrict to a single year
3. If still timing out, the dataflow may be too heavy — try a different, less granular dataflow

#### Safe defaults when the user hasn't specified a breakdown

| Dimension | Safe default | Meaning |
|---|---|---|
| `REF_AREA` | `["IT"]` | Italy total |
| `SEX` | `["9"]` | Both sexes combined |
| `FREQ` | `["A"]` | Annual |
| `MONTH` | `["99"]` | Annual total (not monthly) |
| `AGE` | `["TOTAL"]` | All ages combined |

**Default territory:** if the user does not specify a territory, use `REF_AREA: ["IT"]` silently.

> **Warning — `IT` is not universal.** Some dataflows use `ITTOT` or other codes for the
> national total. If `get_data` returns 404 or empty, run
> `search_constraint_values(dataflow_id="...", dimension="REF_AREA")` to find the correct code.

**Default period:** if the user does not specify a time range, use the previous calendar year
(e.g., if today is 2026, use `start_period="2025-01-01"`, `end_period="2025-12-31"`).

---

## Rate Limiting

**Never make more than one ISTAT API call every 12 seconds.**

The server has a built-in rate limiter that enforces this pause automatically — if you call
two tools back-to-back, the second one will block until 12 seconds have elapsed since the first.
This is expected behavior, not an error.

**Minimize API calls:** `check_code_exists` checks all codes in a single batch call (~2s).
A typical workflow (discover → territorial_codes → check_code_exists → get_data) uses 4 API
calls = ~36s of rate limiting wait.

Do not retry a call that appears to be hanging — it is likely queued behind the rate limiter.

---

## Large Responses

`get_data` returns a TSV. When the result set is large, the server truncates the output
and includes a note with the total row count. If truncation occurs:
- The data returned is still valid — just the first N rows
- Ask the user if they want a narrower filter to get the complete dataset
- The full data is cached server-side and can be re-fetched with tighter filters

---

## Supporting Tools

| Tool | When to use |
|---|---|
| `check_code_exists(dataflow_id, dimension, codes)` | Verify known codes exist — batch codelist query, ~2s |
| `search_constraint_values(dataflow_id, dimension, search)` | Discover codes when unknown, or search by name |
| `get_structure(id_datastructure)` | Get the full list of dimensions for a dataflow |
| `get_codelist_description(codelist_id)` | Get human-readable descriptions for codes in a codelist |
| `get_concepts` | Explore concept schemes (rare) |
| `get_cache_diagnostics` | Debug cache state (not for normal queries) |

---

## Common Patterns

### Provincial data for specific cities

```
# 1. Find dataflow
discover_dataflows(keywords="incidenti stradali,morti")

# 2. Get territorial codes + verify
get_territorial_codes(level="provincia", name="Palermo")   # → ITG12
get_territorial_codes(level="provincia", name="Matera")     # → ITF52
check_code_exists(dataflow_id="41_270_DF_...", dimension="REF_AREA", codes=["ITG12", "ITF52"])

# 3. Preview with maximum filters to discover dimension codes
get_data(
  id_dataflow="41_270_DF_...",
  dimension_filters={"REF_AREA": ["ITG12"], "FREQ": ["A"], "SEX": ["9"], "MONTH": ["99"]},
  last_n_observations=1
)
# → Read RESULT, DATA_TYPE, PERSON_CLASS codes from response

# 4. Targeted query with ALL dimensions closed
get_data(
  id_dataflow="41_270_DF_...",
  dimension_filters={
    "REF_AREA": ["ITG12", "ITF52"], "FREQ": ["A"], "SEX": ["9"],
    "RESULT": ["M"], "MONTH": ["99"], "AGE": ["TOTAL"],
    "DATA_TYPE": ["KILLINJ"], "PERSON_CLASS": ["9"],
    "ACCIDENT_LOCALIZATON": ["9"], "TY_ROAD_ACCIDENT": ["9"], "INTERSECTION": ["1"]
  },
  start_period="2020-01-01", end_period="2024-12-31"
)
```

### Regional data for all Italy

```
1. discover_dataflows(keywords="tasso disoccupazione,regionale")
2. get_territorial_codes(level="regione")  # all 21 region codes
3. get_data(id_dataflow="...", dimension_filters={
     "REF_AREA": ["ITC1","ITC2","ITC3","ITC4","ITD1","ITD2","ITD3","ITD4","ITD5",
                  "ITE1","ITE2","ITE3","ITE4","ITF1","ITF2","ITF3","ITF4","ITF5","ITF6",
                  "ITG1","ITG2"],
     "SEX": ["9"], "FREQ": ["A"]
   })
```

### Filter by sex and age

```
# From get_constraints or preview: SEX: 1=maschi, 2=femmine, 9=totale
#                                   AGE: Y15-74, Y15-64, Y20-64
get_data(..., dimension_filters={"SEX": ["2"], "AGE": ["Y15-74"]})
```

### Annual vs quarterly data

```
# FREQ: A=annuale, Q=trimestrale, M=mensile
get_data(..., dimension_filters={"FREQ": ["A"]}, start_period="2015-01-01")
```
