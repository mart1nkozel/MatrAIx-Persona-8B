# Fáze 1 — datová vrstva: rozhodnutí a poznatky

Stav k 2026-08-31. Exit kritérium splněno: kompletní sada vstupních dat pro
demografické jádro se stahuje jedním příkazem, cachuje a snapshot má verzi.

## D1 — rozhodnutí: DataStat API (primárně)

Zvolena kombinace s jasnou dělbou: **DataStat REST API** pro všechna tabulková
data (umí filtrovaný výběr — poslední období, úroveň okresů — v jednom
requestu, vrací číselníkové kódy NUTS/LAU přímo v CSV, bez autentizace),
**opendata katalog** jen jako záloha pro případné bulk soubory, které API
nepokryje. Zatím nebyl potřeba.

### Poznatky o API, které nejsou v dokumentaci

1. Pseudo-dimenze ukazatelů se v těle POST jmenuje `IndicatorType`
   (dokumentace uvádí `#UKAZATEL`, deployované API ho nezná).
2. `casovaDimenze.typAktualizacePolozek=POSLEDNICH_N` server odmítá;
   funguje jen explicitní výčet položek v `filtr.zobrazitPolozky`.
3. Pokud filtrované období nemá v sadě data, API nevrátí prázdný výsledek,
   ale **HTTP 400 „No dimensions for filter“** — konektor to řeší
   automatickým posunem okna zpět (`fetch_csv_s_posunem`).
4. Číselníky času sahají do budoucnosti (projekce do 2040) — builder
   filtruje položky podle `casOd`.
5. Poslední publikovaný rok mívá jen agregáty (např. OBY02B 2026: jen
   „Celkem“ bez jednotek věku) — proto `posledni_obdobi: 2` a výběr
   plného roku až při stavbě priors.
6. Export celé sady bez filtru na velkých sadách selže (sync limit CSV).
7. Validaci těla výběru umí `POST /api/katalog/v1/sady/{kod}/vybery/validace`
   s wrapperem `{"obsahVyberu": ...}` — hodí se na debugging.

## Praha a „77 okresů“

Číselník okresů (109) má **76 položek — Praha okresem není**, je krajem
(CZ010) i obcí. Proto OBY02B stahujeme přes hierarchickou územní variantu
`Uz0123h2` (stát+region+kraj+okres, 99 jednotek) a Praha se do okresní
hodnotové sady schématu doplní z krajské úrovně. Číselník
`cz/codelists/okresy.csv` už Prahu obsahuje (77 řádků, LAU1 `CZ0100`,
převzato z varianty UZ023H2U, kterou používá např. registr nezaměstnanosti).

## Ověření dat (snapshot snap-20260831-140958)

| Kontrola | Výsledek |
|---|---|
| ČSÚ populace ČR k 1. 1. 2025 (OBY02B) | 10 909 500 |
| Eurostat demo_r_pjangrp3, součet 14 NUTS3 | 10 909 500 — **přesná shoda** |
| Součet okresů = součet přes věky | sedí (9 511 620 bez Prahy + 1 397 880 Praha) |
| SLDB 2021 populace 15+ | ~8,83 M (ČR řádek) |
| Registrovaná nezaměstnanost ČR 2024 | 4,1 % |

## D10 — licence

- ČSÚ otevřená data: **CC BY 4.0** — povinnost uvádět zdroj („Zdroj: ČSÚ“).
- Eurostat: reuse povolen s uvedením zdroje (rozhodnutí Komise 2011/833/EU).
- Obojí kompatibilní s osobním užitím i případným pozdějším online provozem;
  do UI patří atribuce u každého čísla kategorie „měřeno“ (F13 to pokryje).

## Co ve Fázi 1 záměrně není

- **D3/D4 (ESS CZ, Eurobarometer CZ)**: oba zdroje vyžadují registraci
  (ESS Data Portal, GESIS) — stažení dat je ruční krok uživatele, konektor
  pak zpracuje lokální soubory. Potřeba až pro Fázi 4 (postojové dimenze).
- **D8/D9 (automatický refresh + alerty)**: P2; cache klíč zatím invaliduje
  jen změna definice sady (`casZmenyDefinice`), detekci změn samotných dat
  doplní scheduler v D8.
- **NACE / CZ-ISCO číselníky**: doplní se se sadami zaměstnání
  (SLD21A045/SLD21A058) ve Fázi 2/3.
