# CZ vrstva

Lokalizační vrstva MatrAIx → ČR. Žije výhradně v adresáři `cz/` na větvi
`cz-main`, aby merge upstream updatů zůstal bezkonfliktní. Upstream kód se
nemění — sampler čte graf parametrem `--graph`, CZ graf bude drop-in.

## Struktura

| Cesta | Obsah |
|---|---|
| `cz/data/csu.py` | Konektor ČSÚ DataStat API (D1) |
| `cz/data/eurostat.py` | Konektor Eurostat JSON-stat (D2) |
| `cz/data/snapshots.py` | Verzované snapshoty + cache (D5, D6) |
| `cz/data/sources.yaml` | Registr zdrojových datasetů s proveniencí |
| `cz/data/fetch.py` | CLI: `uv run python -m cz.data.fetch` |
| `cz/data/snapshots/` | Stažená data (gitignored) |
| `cz/codelists/` | Číselníky a mapování ČSÚ → schéma (D7) |
| `cz/docs/` | Rozhodnutí a poznámky per fáze |

## Rychlý start

```bash
uv run python -m cz.data.fetch --dry-run   # co by se stáhlo
uv run python -m cz.data.fetch             # nový snapshot (stahuje jen změněné)
uv run python cz/data/csu.py SLD21A002     # probe: dimenze a ukazatele sady
uv run python -m cz.codelists.build_codelists
```

Snapshot ID (`snap-YYYYMMDD-HHMMSS`) je pin pro determinismus generování (E2):
manifest kohorty ponese ID snapshotu, z něhož byly postaveny priors.
