# GESIS zdroje (Fáze 4b) — lokální studie z ~/Desktop/gesis_studie

Stav k 2026-09-01. GESIS nemá volné API — uživatel stáhl ~110 studií
(1,7 GB, převážně Eurobarometry ZA78xx–ZA91xx + EVS/WVS). Konektor
`cz/data/gesis.py` čte lokální .dta, filtruje `isocntry=='CZ'` a do snapshotu
ukládá jen CZ výřezy (KB místo GB). Umístění složky lze změnit env `GESIS_DIR`.

## Integrováno (4 dimenze, vážení w1, universum 15+ ⇒ kontrola na 18+)

| Dimenze | Studie | Položka | CZ výsledek |
|---|---|---|---|
| english_proficiency | ZA8778 „Europeans and their languages" | d48a-d + q48f_1-3 | None 57 %, Basic 11 %, Intermediate 20 %, Fluent 11 %, Native 2 % |
| att_ai | ZA8904 (věda a technologie) | qa6a_9 | Positive 45 %, Skeptical 26 %, Enthusiast 16 % |
| att_vaccines | ZA8904 | qa6a_4 | — |
| att_automation | ZA8844 (roboti/AI v práci) | qb5 | — (Neutral=0, otázka nemá středovou kategorii) |

Tím je splacen dluh z Fáze 3/4: `english_proficiency` už není světový prior
(dřív ~22 % Native mezi bilingvními Čechy, teď 1,7 % celkem).

## Inventura — co dalšího složka nabízí (kandidáti dalších vln)

Metadatový sken všech .dta: `uv run python` skript viz git historie; shrnutí:

- **ZA7505 (EVS/WVS joint 2017–2022, 156k resp., CZ ✓)** — hodnoty
  (A001-A006 important in life → val_* dimenze), genderové role, národní
  hrdost, důvěra institucím. Největší nevytěžený zdroj.
- **ZA8929** — reálné POUŽÍVÁNÍ AI aplikací (q12/q13) + sociální platformy
  (q8) → lstyle_primary_social, AI adoption.
- **ZA9116** — postoj k použití AI (q6).
- **Standard EB 2024/25 (ZA9127-9130, ZA9144)** — klima (sd1), EU image
  (d78), důvěra médiím → att_climate_action, media dimenze.
- **ZA8853** — diskriminace/LGBTIQ (FRA) → citlivé, zvážit užití.
- **2018_2024_trendfile** — trendy důvěry EU; ActEU dataset; IRPD (potraty).
- Zbytek: tematické EB bez přímého mapování na schéma (zemědělství,
  antibiotika, …) — ponecháno.

## Postup přidání další studie

1. `sources.yaml` → sekce `gesis`: soubor, proměnné, cílové dimenze.
2. `uv run python -m cz.data.fetch` (vytvoří CZ výřez ve snapshotu).
3. Mapování do `cz/graph/gesis_mapping.py` (binování → hodnoty schématu).
4. `build_graph` + `check_marginals` + `check_consistency`.

Licence: GESIS/Eurobarometer data pro akademické/nekomerční užití dle
podmínek odsouhlasených při stažení; EVS dtto.
