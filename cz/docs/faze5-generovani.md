# Fáze 5 — on-demand generování: rozhodnutí a výsledky

Stav k 2026-09-01. **Exit kritérium splněno**: kohorta 1 000 000 person se
vygeneruje za ~43 s (4 workery, formát codes) a dva běhy se stejným seedem
a snapshotem dávají **bitově identické výstupy** (sha256 shoda všech souborů).

## Rozhraní (E1): `cz/generate.py`

```bash
uv run python -m cz.generate --n 10000 --seed 42 --out cz/kohorty/moje \
    --filtr "region=Hlavní město Praha" --filtr "age_bracket=25-34|35-44" \
    [--stratifikovat cz_kraj] [--format jsonl.gz|jsonl|codes] [--workers 4]
```

- **Filtry**: jednohodnotový filtr na kořenový uzel (region, age_bracket,
  gender_identity, …) se řeší **clampem** v sampleru — přesné podmínění bez
  režie (akceptace 100 %). Vícehodnotové filtry a filtry na odvozené uzly
  (cz_kraj, vzdělání, postoje) jedou **rejection samplingem** po dávkách
  s adaptivní velikostí dávky a pojistkou proti příliš restriktivním filtrům
  (limit akceptace 1e-4). Clamp na nekořenový uzel se záměrně nepoužívá —
  nebyl by to posterior (rodiče by se nepřepočítali).
- **Stratifikace**: `--stratifikovat dim` = rovnoměrné n na hodnotu dimenze,
  deterministické child seedy (seed·1000+i).
- Nefiltrovaný běh s `--format codes` se **deleguje na upstream paralelní
  sampler** (E3 streaming po dávkách, E4 shardování — hotové upstreamem).

## Determinismus (E2)

Manifest nese pin: `snapshot_id` (z metadat cz_dag) + **sha256 celého grafu**
+ seed. Dvě opravy, které determinismus vyžadoval:

1. gzip hlavička nese mtime → `.jsonl.gz` se zapisuje s `mtime=0`,
2. sidecar `codes.schema.json` ukládal absolutní cestu → normalizace na
   basename (bonus: adresář kohorty je přenositelný).

## Manifest kohorty (E5)

`manifest.json`: požadavek (n, seed, filtry, stratifikace) / graf (sha256,
cz verze, snapshot pin) / výsledek (skutečné n, per-stratum akceptační
poměry, sha256 každého souboru, trvání) / `vstupni_4d: null` — vyplní
vstupní LLM vrstva ve Fázi 8 (F6).

## Ověřeno

| Test | Výsledek |
|---|---|
| 1M codes, 2 běhy | identické sha256, 43 s |
| Clamp: Praha × žena × 25-34, n=5000 | akceptace 100 %, kraj/urbanicita koherentní (Dense urban 100 %) |
| Rejection: JMK × VŠ (Master's/Doctorate), n=2000 | akceptace 1,4 % (≈ 11 % kraj × 13 % VŠ ✓), deterministické |
| Stratifikace cz_kraj, 14×100 | OK |
| Render z codes (E6) | upstream render_personas.py čte kohortu beze změn |

## Nechané na později

- E7 (cache hotových person) — P3, zatím netřeba (1M/43 s).
- Rychlost filtrovaného běhu (~300 person/s) limituje per-řádkový decode —
  pro Fázi 8 (rychlý náhled F15) případně vektorizovat filtr nad indexy.
- Formát codes nepodporuje filtry (jen jsonl) — pro filtrované milionové
  kohorty by se přidal filtr nad codes streamem.
