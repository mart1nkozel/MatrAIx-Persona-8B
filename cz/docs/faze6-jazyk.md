# Fáze 6 — jazyková a textová vrstva: rozhodnutí a výsledky

Stav k 2026-09-01. **Exit kritérium splněno**: karta persony se renderuje
česky a čitelně; L4 má naměřený výsledek (smoke scale).

## L1 — rozhodnutí: čeština přímo

Popisy person se generují **přímo česky**, ne anglicky s překladem.
Jednojazyčný prompt drží personu v jazyce lépe, mechanismus label packů
překlad katalogu unese a systémový prompt upstreamu stejně velí „mluv svým
mateřským jazykem". L4 měření volbu podpořilo (viz níže).

## L2 — lokalizace katalogu a render

- **Label pack cs** přes upstream pipeline: 2 519 unikátních řetězců
  přeloženo LLM (haiku, dávky po 120), cache v reviewovatelném
  `cz/lang/translations_cs.json`, ~75 klíčových řetězců ručně kurátorováno
  (Observant→Praktikující, Primary→Základní, …). Vygenerováno
  `persona/schema/labels/sources/cs/` + `dimensions.labels.cs.json`,
  prošlo upstream validací (`build_labels.py --locale cs --check`),
  `reviewStatus: machine-assisted`.
- **CZ overlay** `cz/lang/labels_cz_extra.json` pro dimenze změněné CZ
  vrstvou (okres, kraj, CZ sada jazyků) — pack je klíčovaný na upstream
  katalog, tyhle hodnoty v něm nejsou.
- **Renderer** `cz/lang/render_cs.py`: ručně psané české jádro karty
  (pohlaví, věk, okres+kraj, prostředí, jazyk, vzdělání, status, pásmo)
  + sekce Hodnoty / Postoje / Zdraví / Technologie / Osobnost / Zájmy
  z label packu. Chybějící překlad padá na EN (nikdy neshodí render).

## L4 — drží LLM personu v češtině? (mini probe)

4 persony × 2 varianty karty (CS/EN) × 3 české otázky; persona i soudce
claude-sonnet-5 (pár judge callů fallback haiku). Výsledky
(`cz/lang/l4_vysledky.json`):

| Varianta karty | Odpovědi česky | Adherence (1–5) |
|---|---|---|
| česká | 100 % | 5,00 |
| anglická | 100 % | 4,91 |

Čeština drží v obou variantách (instrukce „mluv mateřským jazykem" stačí
i nad anglickou kartou); česká karta je na adherenci nepatrně lepší.
**Limity měření**: smoke scale (22 platných hodnocení, 2 parse faily),
soudce = model persony (zděděné omezení č. 4 — self-preference),
stropový efekt (skoro samé 5/5 ⇒ shovívavý soudce). Plná replikace
400-trial adherence probe = V5 (Fáze 7).

## L3 — task instrukce a verifiery (rozhodnutí, P2)

Lokalizují se až s konkrétními use casy (Fáze 8 chat; survey tasky podle
potřeby) — upstream tasky zůstávají anglicky, persona odpovídá česky
nezávisle na jazyce instrukce (ověřeno L4 EN kartou).

## Známé nedokonalosti

- Strojové překlady mají místy špatný rod/pád („Nízké" u ženských
  substantiv) — `machine-assisted`; kurátorská revize průběžně přes
  `translations_cs.json` (po editaci přegenerovat pack).
- Karta záměrně nezahrnuje world-default dimenze mimo vybrané sekce —
  plný render všech 1 181 dimenzí česky je možný, ale pro chat prompt
  zbytečně dlouhý (a world-default obsah je stejně neověřený pro ČR).
