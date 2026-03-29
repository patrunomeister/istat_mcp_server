# Note su build_territorial_subdivisions.py

## Fonti dati

| Fonte | URL | Utilizzo |
|---|---|---|
| CL_ITTER107 | via MCP tool `get_codelist_description` (cache) | Codici NUTS e nomi per tutti i livelli |
| Comuni CSV | `https://www.istat.it/storage/codici-unita-amministrative/Elenco-comuni-italiani.csv` | Mapping cod6 → NUTS3 (via colonna NUTS3 2021) |
| ISTAT JSON | `https://situas-servizi.istat.it/publish/reportspooljson?pfun=61&pdata=01/01/2048` | Codici numerici ISTAT (`cod_istat`), flag capoluogo |

## Schema tabella output (`territorial_subdivisions`)

| Colonna | Tipo | Descrizione |
|---|---|---|
| `code` | VARCHAR | Codice NUTS (es. `ITG1`) o 6 cifre per comuni (es. `082053`) |
| `name_it` | VARCHAR | Nome italiano |
| `level` | VARCHAR | `italia` \| `ripartizione` \| `regione` \| `provincia` \| `comune` |
| `nuts_level` | TINYINT | 0–4 |
| `parent_code` | VARCHAR | Codice del livello padre (NULL per Italia) |
| `capoluogo_provincia` | BOOLEAN | True se capoluogo di provincia/UTS (solo comuni) |
| `capoluogo_regione` | BOOLEAN | True se capoluogo di regione (solo comuni) |
| `cod_istat` | VARCHAR | Codice numerico ISTAT (vedi sotto) |

### Valori di `cod_istat` per livello

| Livello | Fonte | Esempio |
|---|---|---|
| `ripartizione` | hardcoded (1–5) | `1` = Nord-ovest |
| `regione` | `COD_REG` dal JSON (intero) | `19` = Sicilia |
| `provincia` | `COD_PROV_STORICO` dal JSON (intero) | `82` = Palermo |
| `comune` | `PRO_COM_T` dal JSON | `082053` = Palermo |
| `italia` | — | `NULL` |

## Come si costruisce `cod_istat` per province e regioni

Il mapping viene derivato **a cascata dai comuni**:

1. Per ogni comune nel JSON: `PRO_COM_T` → `cod_prov` (intero di `COD_PROV_STORICO`)
2. La stessa `PRO_COM_T` viene usata per trovare il NUTS3 tramite `comune_to_nuts3` (dal CSV)
3. Si costruisce: `nuts3 → cod_prov` e `nuts2 → cod_reg`
4. I codici vengono assegnati alle province e regioni corrispondenti

## Problema noto: Sardegna

**Stato attuale**: solo 3 province abolite nel 2016 hanno `cod_istat = NULL` (dopo il fix).

**Causa**: dopo la riforma provinciale sarda del 2016, i codici comuni sono cambiati:

| Sistema | Sassari città |
|---|---|
| CSV ISTAT (col. 15) | `090064` (vecchia prov. 090) |
| JSON situas-servizi (`PRO_COM_T`) | `112050` (nuova prov. 112) |

I due sistemi usano **codici comuni diversi** per la Sardegna. Di conseguenza `comune_to_nuts3.get("112050")` restituisce `None` e il mapping `nuts3 → cod_prov` non si costruisce per le province sarde.

Province sarde senza `cod_istat`:

| NUTS3 | Nome | COD_PROV_STORICO atteso |
|---|---|---|
| ITG25 | Sassari | 112 |
| ITG26 | Nuoro | 114 |
| ITG27 | Cagliari | 118 |
| ITG28 | Oristano | 115 |
| IT111 | Sud Sardegna | 111 |
| ITG29 | Olbia-Tempio | — |
| ITG2A | Ogliastra | 116 |
| ITG2B | Medio Campidano | 117 |
| ITG2C | Carbonia-Iglesias | — |
| IT113 | Gallura Nord-Est Sardegna | 113 |
| IT119 | Sulcis Iglesiente | 119 |

**Fix implementato**: i codici delle province e della regione Sardegna vengono derivati tramite `unit_territoriali.csv`, che contiene i nomi e i codici correnti post-riforma. Restano `NULL` le 3 province abolite nel 2016 non presenti nel CSV corrente: `ITG29` (Olbia-Tempio), `ITG2C` (Carbonia-Iglesias), `IT111` (Sud Sardegna).
