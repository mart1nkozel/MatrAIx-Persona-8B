# Fáze 7 — validace: tolerance, běh, definice v1

Stav k 2026-09-01. **Exit kritérium splněno**: existuje opakovatelný
validační běh (`uv run python -m cz.validate`), který projde, nebo jasně
ukáže, co neprošlo (report v `cz/validace/`).

## V1+V2 — marginály a formalizované tolerance

Jeden příkaz kontroluje všech 48 kalibrovaných uzlů proti referencím
uloženým v build_reportu (ČSÚ marginály, SLDB/ESS/EB kondicionály složené
přes věk/kraj/afiliaci):

| Kontrola | Tolerance (V2) | Zdůvodnění |
|---|---|---|
| marginály | max \|Δ\| ≤ **1,5 p. b.** na kategorii | šum vzorkování při n=200k ≤ ~0,3 p. b.; rezerva kryje kompozici CPT a vliv masek |
| CZ-survey a SLDB dimenze | srovnání na subpopulaci **18+** | reference měřené na 15+, bracket 13–17 nelze rozříznout |
| CZ konzistence (CZ1–CZ4) | **0** tvrdých rozporů | rodilý mluvčí⇒jazyk, kraj↔okres, Praha⇒město, monolingvní |
| upstream soft pravidla | ≤ **0,1 %** vzorku | životní fáze apod. (aktuálně 0,002 %) |
| determinismus | identické výstupy 2 běhů | pin seed+graf+snapshot |

Poslední běh: PASS — 48 uzlů, max Δ 1,26 p. b., 0 CZ rozporů, soft 0,002 %.

## V4 — pokrytí schématu (místo „míry nullů")

CZ verze nully nezavádí (rozhodnutí S4: world-default s explicitní
proveniencí místo null). Ekvivalentní metrika = podíl reálně CZ-kalibrovaných
dimenzí: **48 z 1 181 emitovaných (4,1 %)**; po kategoriích v JSON reportu.
Interpretace pro uživatele nástroje: demografické jádro, hodnoty a klíčové
postoje jsou CZ-grounded; zbylých ~96 % dimenzí (zájmy, osobnost, dovednosti)
nese světové priory — viditelné v registru provenience a v UI (F13) jako
„neověřeno pro ČR".

## V5/V6 — adherence probe v češtině a multi-model rozptyl

Střední škála (100 odpovědí + 50 párových srovnání; plných 400 trialů dle
paperu lze spustit týmž skriptem navýšením počtu person):
`uv run python -m cz.lang.probe_v5`. Výsledky v `cz/lang/v5_vysledky.json`.

Výsledky (2026-09-01, 10 person × 5 otázek × 2 modely):

| Model | Odpovědi česky | Adherence (1–5) | Adherence ≥4 |
|---|---|---|---|
| claude-sonnet-5 | 100 % | 4,85 | 100 % |
| claude-haiku-4.5 | 100 % | 4,70 | 100 % |

**V6 mezi-modelová shoda stanovisek: 89 %** (n=47 párů). Neshody (5) se
koncentrují tam, kde profil nechává prostor interpretaci — typicky míra
používání AI/technologií u person s protichůdnými signály (technický zájem
vs. nízká zběhlost). Potvrzuje zděděné omezení č. 2 v mírnější podobě:
volba modelu ovlivňuje odpovědi hlavně u nedourčených atributů — pro
screening použitelné, jeden běh ≠ jeden fakt.

Limity: soudce = sonnet-5 (self-preference, zděděné omezení č. 4);
metriky nejsou přímo srovnatelné s EN baseline paperu (jiný design).

## V7 — definice „v1 hotová"

**v1 = datové jádro + generátor + čeština + validace (Fáze 0–7).**
Front end (Fáze 8) je v1.1 — v1 je použitelná přes CLI.

| Kritérium | Stav |
|---|---|
| `cz.validate` PASS (marginály, konzistence, determinismus) | ✅ |
| kohorta 1M person < 2 min, deterministicky, manifest s pinem | ✅ (43 s) |
| filtry a stratifikace přes `cz.generate` | ✅ |
| karta persony česky, persony drží češtinu (≥ 95 % CZ odpovědí) | ✅ (100 %) |
| registr provenience úplný (žádná kalibrovaná dimenze bez zdroje) | ✅ |
| adherence probe naměřena a dokumentována | ✅ (střední škála) |
| dokumentace fází 0–7 v cz/docs | ✅ |

**v1 je tímto hotová.** Otevřené dovětky (nejsou blokery v1): NACE→domain
mapování ze ZAMG07, plná 400-trial probe, D8/D9 automatický refresh,
kurátorská revize strojových překladů.
