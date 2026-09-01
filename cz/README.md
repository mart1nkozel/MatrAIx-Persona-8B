# CZ vrstva — MatrAIx lokalizovaný na ČR

Kompletní workflow od dat po chat s personami. Vše žije v `cz/` na větvi
`cz-main`; upstream kód se nemění (graf je drop-in přes `--graph`).

## Workflow (v1)

```bash
# 1. Data: ČSÚ + Eurostat + ESS + GESIS → verzovaný snapshot
uv run python -m cz.data.fetch

# 2. Graf: CZ priory, hodnotové sady, CPT, masky → cz/graph/cz_dag.json
uv run python -m cz.graph.build_graph

# 3. Validace: marginály, konzistence, determinismus, pokrytí → PASS/FAIL
uv run python -m cz.validate

# 4. Kohorta ze zadání v přirozeném jazyce (4D vrstva, Diagnose viditelná)
uv run python -m cz.vstup "mladé maminky z menších měst" --n 5000 \
    --out cz/kohorty/maminky --spustit
#    …nebo přímo filtry:
uv run python -m cz.generate --n 5000 --out cz/kohorty/moje \
    --filtr "cz_kraj=Jihomoravský kraj" --filtr "age_bracket=25-34|35-44"

# 5. Segmenty a medoidní persony (Gower + k-medoids)
uv run python -m cz.segmentace --kohorta cz/kohorty/maminky --k 4

# 6. HTML report (rozložení, provenience měřeno/odvozeno, segmenty)
uv run python -m cz.report --kohorta cz/kohorty/maminky

# 7. Chat se třemi medoidními personami (česky; --porovnat = druhý model)
uv run python -m cz.chat --kohorta cz/kohorty/maminky

# 8. Export do upstream Playgroundu (dataset kompatibilní s jejich loaderem)
uv run python -m cz.export_playground --kohorta cz/kohorty/maminky
```

Kroky 4 (--spustit), 7 a překlady vyžadují `ANTHROPIC_API_KEY` v prostředí.
ESS vyžaduje `cz/data/ess_user.json` (gitignored), GESIS lokální složku
(`GESIS_DIR`, výchozí ~/Desktop/gesis_studie).

## Struktura

| Cesta | Obsah |
|---|---|
| `cz/data/` | konektory (csu, eurostat, ess, gesis), registr `sources.yaml`, snapshoty |
| `cz/graph/` | builder grafu, priory, ESS/GESIS mapování, kontroly, registr provenience |
| `cz/lang/` | čeština: label pack, render karty, L4/V5 proby |
| `cz/codelists/` | okresy, kraje+NUTS2, mapování číselníků |
| `cz/generate.py` | kohorty: filtry (clamp/rejection), stratifikace, manifest s pinem |
| `cz/vstup.py` | 4D vstupní vrstva (zadání → filtry) |
| `cz/segmentace.py` | Gower + k-medoids, medoidní persony |
| `cz/report.py` | HTML report s proveniencí |
| `cz/chat.py` | chat 3 person vedle sebe |
| `cz/export_playground.py` | export do upstream datasetu |
| `cz/validate.py` | validační běh V1–V4 |
| `cz/tests/` | unit testy (`uv run pytest cz/tests -q`) |
| `cz/docs/` | rozhodnutí a výsledky per fáze (faze1…faze8, gesis-zdroje) |

Snapshot ID + sha256 grafu = pin determinismu: stejný seed ⇒ bitově stejná
kohorta. Registr provenience (`cz/graph/provenance_registry.csv`): 49
kalibrovaných dimenzí (CZ-official/CZ-survey), zbytek world-default
(explicitně „neověřeno pro ČR"), developer dimenze skryté.

Účel dle pre-backlogu: screening a relativní srovnání, ne tvrdá čísla
o reálné populaci (zděděná omezení paperu platí).
