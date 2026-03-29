"""Build resources/istat_lookup.duckdb (table territorial_subdivisions) from CL_ITTER107 and ISTAT data.

Sources:
- CL_ITTER107: fetched via mcp__istat__get_codelist_description (cached in cache/cache.db)
- unit_territoriali.csv: resources/geo/unit_territoriali.csv (mapping cod_com → NUTS3 → cod_prov → cod_reg)
- ISTAT JSON: https://situas-servizi.istat.it/publish/reportspooljson?pfun=61&pdata=01/01/2048 (capoluogo flags)

Output columns (table: territorial_subdivisions):
- code: ISTAT territorial code (CL_ITTER107 for all levels; 6-digit numeric for comuni)
- name_it: Italian name
- level: italia | ripartizione | regione | provincia | comune
- nuts_level: 0 | 1 | 2 | 3 | 4
- parent_code: code of the parent territorial unit (NULL for Italia)
- capoluogo_provincia: True if the comune is a provincial/UTS capital (NULL for non-comuni)
- capoluogo_regione: True if the comune is a regional capital (NULL for non-comuni)
- cod_istat: numeric ISTAT code as string (COD_RIP for ripartizioni, COD_REG for regioni,
             COD_PROV_STORICO for province, PRO_COM_T for comuni; NULL for italia)
- den_rip: denominazione ripartizione geografica (Nord-ovest, Nord-est, Centro, Sud, Isole; NULL for italia)
- cod_rip: codice ripartizione geografica as string (1-5; NULL for italia)

Usage:
    python3 resources/build_territorial_subdivisions.py <itter107_json>
"""

import csv
import json
import re
import sys
import urllib.request
from pathlib import Path

import duckdb

# NUTS 2021 codes that DON'T follow simple ITH->ITD / ITI->ITE substitution
# Maps NUTS2021 NUTS3 code -> CL_ITTER107 code
NUTS2021_TO_ITTER_OVERRIDE = {
    'ITC4C': 'ITC45',  # Metro Milano -> Milano
    'ITC4D': 'IT108',  # Monza e della Brianza
    'ITI35': 'IT109',  # Fermo (must be before ITI->ITE rule)
    'ITF46': 'ITF41',  # Foggia
    'ITF47': 'ITF42',  # Bari / Citta Metropolitana
    'ITF48': 'IT110',  # Barletta-Andria-Trani
    'ITG2D': 'ITG25',  # Sassari
    'ITG2E': 'ITG26',  # Nuoro
    'ITG2F': 'ITG27',  # Cagliari
    'ITG2G': 'ITG28',  # Oristano
    'ITG2H': 'IT111',  # Sud Sardegna
}

# Special IT1XX province codes -> parent NUTS2 region code
IT1XX_PARENTS = {
    'IT108': 'ITC4',  # Monza e della Brianza -> Lombardia
    'IT109': 'ITE3',  # Fermo -> Marche
    'IT110': 'ITF4',  # Barletta-Andria-Trani -> Puglia
    'IT111': 'ITG2',  # Sud Sardegna -> Sardegna
    'IT113': 'ITG2',  # Gallura Nord-Est Sardegna -> Sardegna
    'IT119': 'ITG2',  # Sulcis Iglesiente -> Sardegna
}

ISTAT_DATA_URL = 'https://situas-servizi.istat.it/publish/reportspooljson?pfun=61&pdata=01/01/2048'
UNIT_TERR_CSV = Path(__file__).parent / 'geo' / 'unit_territoriali.csv'

# NUTS1 code → COD_RIP numeric string
NUTS1_TO_COD_RIP = {'ITC': '1', 'ITD': '2', 'ITE': '3', 'ITF': '4', 'ITG': '5'}

# NUTS1 code → denominazione ripartizione geografica
NUTS1_TO_DEN_RIP = {
    'ITC': 'Nord-ovest',
    'ITD': 'Nord-est',
    'ITE': 'Centro',
    'ITF': 'Sud',
    'ITG': 'Isole',
}

OUTPUT_PATH = Path(__file__).parent.parent / 'src' / 'istat_mcp_server' / 'resources' / 'istat_lookup.duckdb'


def nuts2021_to_itter(code: str) -> str:
    """Convert NUTS 2021 NUTS3 code to CL_ITTER107 equivalent."""
    if code in NUTS2021_TO_ITTER_OVERRIDE:
        return NUTS2021_TO_ITTER_OVERRIDE[code]
    if code.startswith('ITH'):
        return 'ITD' + code[3:]
    if code.startswith('ITI'):
        return 'ITE' + code[3:]
    return code


def load_itter107(path: str) -> dict[str, str]:
    """Load CL_ITTER107 codelist from a JSON file (MCP tool result format)."""
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    text = data[0]['text']
    entries = re.findall(r'\{[^{}]+\}', text)
    codes = {}
    for e in entries:
        cm = re.search(r'"code":\s*"([^"]+)"', e)
        di = re.search(r'"description_it":\s*"([^"]+)"', e)
        if cm and di:
            codes[cm.group(1)] = di.group(1)
    return codes


def _normalize_name(name: str) -> str:
    """Normalize province name for matching (escaped unicode, spaces, 'di ')."""
    import unicodedata
    s = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), name)
    s = unicodedata.normalize('NFC', s)
    s = re.sub(r'\s*/\s*', '/', s)       # "Bolzano / Bozen" → "Bolzano/Bozen"
    s = re.sub(r'\bdi\s+', '', s)         # "Reggio di Calabria" → "Reggio Calabria"
    return s.lower()


def build_mappings() -> tuple[dict, dict, dict, dict]:
    """Build all territorial mappings from unit_territoriali.csv.

    Returns:
        - comune_to_nuts3: cod_com (alfanumerico) → ITTER NUTS3
        - storico_to_nuts3: cod_prov_storico → ITTER NUTS3
        - name_to_cod_prov: normalized province name → cod_prov (int string)
        - nuts2_to_cod_reg: ITTER NUTS2 → cod_reg (int string)
    """
    comune_to_nuts3: dict[str, str] = {}
    storico_to_nuts3: dict[str, str] = {}
    name_to_cod_prov: dict[str, str] = {}
    nuts2_to_cod_reg: dict[str, str] = {}

    print(f'Reading {UNIT_TERR_CSV}...')
    with open(UNIT_TERR_CSV, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            cod_com = row['Codice Comune (alfanumerico)'].strip()
            nuts3_2024 = row['Codice NUTS3 2024'].strip()
            cod_prov = row['Codice Provincia (Storico)'].strip()
            cod_reg = row['Codice Regione'].strip()
            den_uts = row['Provincia/Uts'].strip()

            if nuts3_2024:
                itter = nuts2021_to_itter(nuts3_2024)
                comune_to_nuts3[cod_com] = itter
                storico_to_nuts3[cod_prov] = itter
                nuts2_to_cod_reg[itter[:4]] = str(int(cod_reg))
            if den_uts and cod_prov:
                name_to_cod_prov[_normalize_name(den_uts)] = str(int(cod_prov))

    print(f'  comuni: {len(comune_to_nuts3)} | storico: {len(storico_to_nuts3)} | prov_names: {len(name_to_cod_prov)} | reg: {len(nuts2_to_cod_reg)}')
    return comune_to_nuts3, storico_to_nuts3, name_to_cod_prov, nuts2_to_cod_reg


def download_istat_data() -> dict[str, dict]:
    """Download ISTAT comuni data from JSON endpoint.

    Returns:
        Dict mapping 6-digit comune code -> {
            'cap_prov': bool,
            'cap_reg': bool,
            'cod_reg': str,       # e.g. '19' for Sicilia
            'cod_prov': str,      # e.g. '82' (int of COD_PROV_STORICO)
            'cod_rip': str,       # e.g. '5'
            'pro_com_t': str,     # 6-digit PRO_COM_T code from JSON
        }
    """
    print(f'Downloading {ISTAT_DATA_URL}...')
    with urllib.request.urlopen(ISTAT_DATA_URL) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    result = {}
    for rec in data.get('resultset', []):
        raw_code = str(rec.get('PRO_COM_T', '')).strip()
        if not raw_code or not raw_code.isdigit():
            continue
        code = raw_code.zfill(6)
        try:
            cod_reg = str(int(rec['COD_REG']))
            cod_prov = str(int(rec['COD_PROV_STORICO']))
            cod_rip = str(rec['COD_RIP'])
        except (KeyError, ValueError, TypeError):
            continue
        result[code] = {
            'cap_prov': bool(rec.get('CC_UTS', 0)),
            'cap_reg': bool(rec.get('CC_REG', 0)),
            'cod_reg': cod_reg,
            'cod_prov': cod_prov,
            'cod_rip': cod_rip,
            'pro_com_t': code,
        }
    print(f'  Loaded ISTAT data for {len(result)} comuni')
    return result



def build_duckdb(codes: dict, comune_to_nuts3: dict, storico_to_nuts3: dict,
                 name_to_cod_prov: dict, nuts2_to_cod_reg: dict, istat_data: dict) -> None:
    """Build and write the DuckDB database."""
    # Province: standard NUTS3 + letter-suffix + IT1XX
    nuts3_codes = {k: v for k, v in codes.items() if re.match(r'^IT[A-Z][0-9]{2}$', k)}
    letter_suffix = {k: v for k, v in codes.items() if re.match(r'^IT[A-Z][0-9][A-Z]$', k)}
    it1xx = {k: v for k, v in codes.items() if re.match(r'^IT1[0-9]{2}$', k)}
    all_province_codes = {**nuts3_codes, **letter_suffix, **it1xx}

    # Helpers: NUTS1 code → den_rip / cod_rip
    def den_rip(nuts1: str | None) -> str | None:
        return NUTS1_TO_DEN_RIP.get(nuts1) if nuts1 else None

    def cod_rip(nuts1: str | None) -> str | None:
        return NUTS1_TO_COD_RIP.get(nuts1) if nuts1 else None

    rows = []

    rows.append(('IT', 'Italia', 'italia', 0, None, None, None, None, None, None))

    for k, v in {'ITC': 'Nord-ovest', 'ITD': 'Nord-est', 'ITE': 'Centro', 'ITF': 'Sud', 'ITG': 'Isole'}.items():
        rows.append((k, v, 'ripartizione', 1, 'IT', None, None, NUTS1_TO_COD_RIP.get(k), den_rip(k), cod_rip(k)))

    for k, v in codes.items():
        if re.match(r'^IT[A-Z][0-9]$', k):
            rows.append((k, v, 'regione', 2, k[:3], None, None, nuts2_to_cod_reg.get(k), den_rip(k[:3]), cod_rip(k[:3])))

    for k, v in all_province_codes.items():
        parent = IT1XX_PARENTS.get(k, k[:4])
        nuts1 = IT1XX_PARENTS.get(k, k)[:3]
        rows.append((k, v, 'provincia', 3, parent, None, None, name_to_cod_prov.get(_normalize_name(v)), den_rip(nuts1), cod_rip(nuts1)))

    no_parent = 0
    for k, v in codes.items():
        if re.match(r'^[0-9]{6}$', k):
            parent = comune_to_nuts3.get(k) or storico_to_nuts3.get(k[:3])
            if not parent:
                no_parent += 1
            rec = istat_data.get(k, {})
            cap_prov = rec.get('cap_prov', False)
            cap_reg = rec.get('cap_reg', False)
            nuts1 = parent[:3] if parent else None
            # IT1XX province parent: es. IT108 → ITC4 → nuts1=ITC
            if parent and re.match(r'^IT1', parent):
                nuts1 = IT1XX_PARENTS.get(parent, parent)[:3]
            cod_istat = rec.get('pro_com_t')
            rows.append((k, v, 'comune', 4, parent, cap_prov, cap_reg, cod_istat, den_rip(nuts1), cod_rip(nuts1)))

    # Remove existing db if present
    if OUTPUT_PATH.exists():
        OUTPUT_PATH.unlink()

    conn = duckdb.connect(str(OUTPUT_PATH))
    conn.execute('''
        CREATE TABLE territorial_subdivisions (
            code VARCHAR NOT NULL,
            name_it VARCHAR NOT NULL,
            level VARCHAR NOT NULL,
            nuts_level TINYINT,
            parent_code VARCHAR,
            capoluogo_provincia BOOLEAN,
            capoluogo_regione BOOLEAN,
            cod_istat VARCHAR,
            den_rip VARCHAR,
            cod_rip VARCHAR
        )
    ''')
    conn.executemany(
        'INSERT INTO territorial_subdivisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        rows,
    )
    conn.execute('CREATE INDEX idx_level ON territorial_subdivisions(level)')
    conn.execute('CREATE INDEX idx_parent ON territorial_subdivisions(parent_code)')
    conn.execute('CREATE INDEX idx_code ON territorial_subdivisions(code)')
    conn.close()

    size = OUTPUT_PATH.stat().st_size
    print(f'Written: {OUTPUT_PATH}')
    print(f'Rows: {len(rows)} | Size: {size:,} bytes ({size // 1024} KB)')
    print(f'Province: {len(all_province_codes)} | Comuni senza parent: {no_parent}')


if __name__ == '__main__':
    itter107_path = sys.argv[1] if len(sys.argv) > 1 else None

    if not itter107_path:
        print('Usage: python3 build_territorial_subdivisions.py <itter107_json>')
        print('  itter107_json: MCP tool result JSON for CL_ITTER107 codelist')
        sys.exit(1)

    print('Loading CL_ITTER107...')
    codes = load_itter107(itter107_path)
    print(f'  Loaded {len(codes)} codes')

    print('Building mappings from unit_territoriali.csv...')
    comune_to_nuts3, storico_to_nuts3, name_to_cod_prov, nuts2_to_cod_reg = build_mappings()

    print('Downloading ISTAT data (capoluogo flags)...')
    istat_data = download_istat_data()

    print('Building DuckDB...')
    build_duckdb(codes, comune_to_nuts3, storico_to_nuts3,
                 name_to_cod_prov, nuts2_to_cod_reg, istat_data)
