# Fáze 4 — postojové dimenze z ESS: rozhodnutí a výsledky

Stav k 2026-08-31. **24 dimenzí kalibrováno z ESS10 CZ** (2 476 respondentů,
váženo `pspwght`), marginály PASS (max Δ 0,28 p. b. na 200k vzorku, srovnání
na subpopulaci 18+), audit konzistence beze změny (0 CZ rozporů).

## D3 — ESS konektor (a odpověď na otázku session cookie vs. userId)

Ověřeno reverzí frontendu a živým testem: oficiální API
`GET https://api.ess.sikt.no/v1/data/dataFile/{doiPrefix}/{doiSuffix}`
**nevyžaduje autentizaci** — `userId` v query je povinný, ale slouží jen ke
statistice užití (OpenAPI spec nemá security scheme; přihlášení chce jen
tlačítko v UI, které jde přes sso.nsd.no). Odpověď je 307 redirect na časově
podepsaný Azure blob. Použité parametry: `fileFormat=parquet`,
`recodeMissingValues=true` (missing kódy → NaN). userId žije v gitignorovaném
`cz/data/ess_user.json` (osobní identifikátor, nepatří do public repa).

## Klíčové skutečnosti

1. **ČR v ESS11 (2023) není** — poslední česká účast je Round 10 (2020/21).
   Health modul „Social inequalities in health" z R11 pro ČR neexistuje;
   jádrové položky (health, hlthhmp, stflife, happy) jsou v R10. Až ČR
   přibude do R11 integrovaného souboru, stačí změnit DOI v sources.yaml.
2. **ESS region = NUTS3 kraj**, ale ~175 respondentů/kraj ⇒ regionální
   podmínění počítáno **per NUTS2** (8 regionů, rozhodnutí „kraj/NUTS2")
   se shrinkage k národní distribuci (n/(n+50)); CPT řádky pro `cz_kraj`
   replikují NUTS2 hodnoty. Důsledek dle G7: kraje téhož NUTS2 mají
   identické postojové distribuce.
3. **Licence ESS: CC BY-NC-SA 4.0** — nekomerční užití (osobní účel projektu
   vyhovuje; při případném online provozu nutno revidovat).

## Mapování (S2) — 24 dimenzí

| Schema dimenze | ESS zdroj | Podmínění |
|---|---|---|
| trust_level | ppltrst | NUTS2 |
| health_general_health | health | NUTS2 |
| health_mental_health | stflife | NUTS2 |
| cog_optimism | happy | NUTS2 |
| topic_politics | polintr | NUTS2 |
| att_immigration | imwbcnt | NUTS2 |
| lstyle_social_battery | sclmeet | NUTS2 |
| tech_savviness | netusoft | NUTS2 |
| political_lean | lrscale (NaN→Apolitical) | NUTS2 |
| demo_political_engagement | vote×polintr | NUTS2 |
| demo_religion_affiliation | rlgblg×rlgdnm×rlgdgr | národní |
| religiosity | rlgdgr | **afiliace** (joint z téhož dotazníku) |
| demo_disability_status | hlthhmp (celkový podíl) + světový poměr typů | národní |
| health_mobility | hlthhmp | **disabilita** (deterministický joint) |
| schwartz_value_* (10) | PVQ 21 položek, MRAT centrování, vážené kvantily | národní |

## Dvě poučení o jointech z téhož dotazníku

1. **religiosity × afiliace**: nezávislé vzorkování + upstream maska
   „ateista ⇒ ne Observant" ořezaly Observant o 10 p. b. Řešení: CPT
   religiosity|afiliace přímo z ESS jointu (řádky s n≥30) — maska teď
   sedí s daty místo proti nim.
2. **health_mobility × disabilita**: obě odvozené z téže proměnné hlthhmp —
   nezávislé vzorkování by joint rozbilo. Řešení: mobilita deterministicky
   z disability statusu; marginál se skládá přesně na ESS hodnoty.

Obecné pravidlo pro další fáze: **dimenze odvozené ze stejné survey proměnné
nebo se známým jointem se nikdy nevzorkují nezávisle.**

## S4/S5 — politika pro nemapované dimenze + registr provenience

Rozhodnutí S4: nemapované postojové/lifestyle dimenze **ponechávají světový
prior** s explicitní proveniencí `world-default (neověřeno pro ČR)` —
dokumentované zkreslení. Null by persony degradoval a LLM by si hodnoty
stejně doplnil vlastními (anglofonními) předpoklady = nedokumentované
zkreslení (argument z pre-backlogu).

Registr (S5): `cz/graph/provenance_registry.csv` — všech 1 309 uzlů:

| Provenience | Počet |
|---|---|
| CZ-official (ČSÚ/Eurostat) | 9 |
| CZ-survey (ESS10) | 24 |
| world-default (neověřeno pro ČR) | 1 148 |
| hidden/latent (developer + interní) | 128 |

## Nepoužité ESS proměnné (S1 — pro budoucí rozšíření)

trstprl/trstlgl/trstplc/trstep/trstun (instituce — schéma nemá cílovou
dimenzi), gincdif (redistribuce), freehms (LGBT akceptace), euftf (EU),
aesfdrk (bezpečí po setmění), stfeco/stfgov/stfdem/stfedu/stfhlth
(spokojenost s institucemi) — kandidáti, pokud schéma dostane CZ dimenze.
`english_proficiency` zůstává světový (ESS jazykové proficiency neměří;
Eurobarometer bez GESIS přístupu — rozhodnutí uživatele „GESIS nic").
