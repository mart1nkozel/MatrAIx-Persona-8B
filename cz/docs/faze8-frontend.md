# Fáze 8 — front end (v1.1): stav a rozhodnutí

Stav k 2026-09-01. Hotové části: **segmentace + medoidy (F7–F11), 4D vstupní
vrstva (F1–F6), chat tří person (F16, F17, F19, F20)**. Zbývá: zobrazení dat
(F12–F15) a napojení na upstream Playground (F18) — viz Zbývá níže.

Celý tok funguje z CLI:
```bash
uv run python -m cz.vstup "mladé maminky z menších měst" --n 5000 --out cz/kohorty/maminky --spustit
uv run python -m cz.segmentace --kohorta cz/kohorty/maminky --k 4
uv run python -m cz.chat --kohorta cz/kohorty/maminky
```

## Segmentace a medoidy (F7–F11) — `cz/segmentace.py`

- **F7 dimenze**: výchozích 12 jádrových os (demografie × politika/hodnoty/
  technologie). Empirické zjištění: plná sada 45 kalibrovaných dimenzí dává
  siluetu ~0,01 — kvazi-nezávislé dimenze koncentrují Gower vzdálenosti
  (prokletí dimenzionality); 12 os dává 0,13–0,17. Geografie záměrně mimo
  (region je filtr, ne segmentační osa). `--dimenze plna` k dispozici.
- **F7 metoda**: k-medoids (k-medoids++ init, Voronoiho iterace) na Gower
  matici vzorku (F11, výchozí 4 000; O(n²)); celá kohorta pak přiřazena
  k nejbližšímu medoidu O(N·k). 20k kohorta ≈ 13 s.
- **F9 Gower**: ordinální dle pořadí hodnot ve schématu, nominální shodou,
  hodnoty mimo škálu (Apolitical, Prefer not to say, Nomadic) jako chybějící
  s přenormalizací jmenovatele — null-safe větev připravená i pro budoucí
  skutečné nully. **F10**: váhy uniformní (násobič připraven).
- Výstup: segmenty.json (podíly, medoidi, silueta, odlišující rysy s lifty)
  + prirazeni.parquet. Na plné populaci dominují osy věk×status (důchodci /
  děti / pracující) — psychografické štěpení vynikne na filtrovaných
  dospělých kohortách; dokumentováno.

## 4D vstupní vrstva (F1–F6) — `cz/vstup.py`

Samostatná LLM vrstva (sonnet-5), ne UI formulář (rozhodnutí backlogu).
Deconstruct → **Diagnose viditelná před generováním** (mezery, doplněné
předpoklady, otázky na uživatele — F2) → Develop → Deliver = filtry
validované proti schématu. `--spustit` volá cz.generate; **celý 4D výstup
se propisuje do manifestu kohorty (F6)**. Ruční úprava filtru (F5) =
editace vstup_4d.json + `cz.generate --vstup-4d`. Oprava cestou: stratum
se protíná s filtrem na téže dimenzi (jinak nesplnitelné kombinace).

## Chat (F16–F20) — `cz/chat.py`

Tři medoidní persony vedle sebe, každá **vlastní vlákno historie** (F16);
karta = klíčové atributy + segment + podíl populace (F17); **model viditelný
u každé odpovědi** (F19); `--porovnat` pustí tutéž personu pod druhým modelem
(F20). Přepis do chat-<ts>.json. Živé pozorování z testu: sonnet-5 drží
personu výrazně věrněji než haiku-4.5 (gramatika, konzistence s profilem) —
zděděné omezení č. 2 je v chatu vidět přímo; volba modelu je součást metodiky.

## Zbývá (v1.2)

- **F12–F15 zobrazení**: grafy rozložení, vizuální odlišení provenience
  (měřeno/odvozeno/simulováno — datový podklad je: registr + build_report),
  srovnávací pohled měřeno vs. odvozeno, rychlý náhled (F15; podklad =
  segmentace na vzorku).
- **F18 upstream Playground**: CZ kohorty jsou datově kompatibilní
  (persona YAML/manifest formát upstreamu) — integrace zvlášť.
