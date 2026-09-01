"""Překlad katalogu dimenzí do češtiny (L2) přes upstream label-pack pipeline.

Krok 1: unikátní řetězce (labely + hodnoty) → LLM překlad (haiku, dávky),
        cache v cz/lang/translations_cs.json (commitovaná, reviewovatelná).
Krok 2: sestavení persona/schema/labels/sources/cs/{dimensions,meta,taxonomy}.json
Krok 3: uživatel spustí upstream build:
        uv run python persona/schema/labels/build_labels.py --locale cs

  ANTHROPIC_API_KEY=... uv run python -m cz.lang.translate_catalog

Řetězce bez písmen (číselné rozsahy jako "25-34") se nepřekládají. Hodnoty
změněné CZ vrstvou (okresy, kraje — už česky) řeší overlay
cz/lang/labels_cz_extra.json, ne tento katalog (pack je klíčovaný na
upstream dimensions.json).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

CZ_LANG = Path(__file__).resolve().parent
REPO = CZ_LANG.parents[1]
CACHE = CZ_LANG / "translations_cs.json"
SOURCES_CS = REPO / "persona" / "schema" / "labels" / "sources" / "cs"
MODEL = "anthropic/claude-haiku-4-5-20251001"
BATCH = 120

TAXONOMY_CS = {
    "background": "Zázemí",
    "behavior": "Chování a interakce",
    "capability": "Schopnosti",
    "career": "Kariéra",
    "culture": "Kultura a každodenní život",
    "decision_making": "Rozhodování",
    "demographics": "Demografie",
    "domains": "Obory",
    "education": "Vzdělání",
    "health": "Zdraví",
    "interaction_state": "Stav interakce",
    "interests": "Zájmy",
    "language": "Jazyk",
    "lifestyle": "Životní styl a zdraví",
    "other": "Ostatní",
    "personal_behavior": "Osobní chování",
    "personality": "Osobnost",
    "psychology": "Psychologie",
    "skills": "Dovednosti",
    "technology_use": "Používání technologií",
    "uncategorized": "Nezařazeno",
    "work_practices": "Pracovní návyky",
    "worldview": "Světonázor"
}

PROMPT = """Přelož následující krátké popisky z katalogu dimenzí syntetických person do češtiny.

Pravidla:
- Stručně, bez teček na konci, zachovej velikost prvního písmene podle originálu.
- Názvy jazyků jako hodnoty přelož (Czech→čeština, German→němčina).
- Odborné škály překládej přirozeně (Very high→Velmi vysoká, Passionate→Nadšený).
- Značky, zkratky a názvy produktů/technologií (ISCED, IT, Python, TikTok) nech být.
- Vrať POUZE validní JSON objekt {"anglický řetězec": "český překlad", ...} pro všechny vstupy.

Vstupy:
"""


def unikatni_retezce() -> list[str]:
    dims = json.loads((REPO / "persona" / "schema" / "dimensions.json").read_text())["dimensions"]
    out = set()
    for d in dims:
        out.add(d["label"])
        for v in d["values"]:
            out.add(str(v))
    return sorted(s for s in out if re.search(r"[A-Za-z]", s))


def prelozit_chybejici(retezce: list[str]) -> dict[str, str]:
    import litellm

    cache: dict[str, str] = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    chybi = [s for s in retezce if s not in cache]
    print(f"celkem {len(retezce)} řetězců, v cache {len(retezce) - len(chybi)}, překládám {len(chybi)}")
    for i in range(0, len(chybi), BATCH):
        davka = chybi[i:i + BATCH]
        r = litellm.completion(
            model=MODEL,
            max_tokens=8000,
            messages=[{"role": "user", "content": PROMPT + json.dumps(davka, ensure_ascii=False)}],
        )
        text = r.choices[0].message.content.strip()
        text = text[text.index("{"):text.rindex("}") + 1]
        preklady = json.loads(text)
        for s in davka:
            if s in preklady and isinstance(preklady[s], str) and preklady[s].strip():
                cache[s] = preklady[s].strip()
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True))
        print(f"  dávka {i // BATCH + 1}: +{len(davka)} (cache {len(cache)})")
    return cache


def sestavit_sources(cache: dict[str, str]) -> None:
    dims = json.loads((REPO / "persona" / "schema" / "dimensions.json").read_text())["dimensions"]
    out = {}
    for d in dims:
        zaznam = {"label": cache.get(d["label"], d["label"]), "values": {}}
        for v in d["values"]:
            v = str(v)
            if v in cache:
                zaznam["values"][v] = cache[v]
        out[d["id"]] = zaznam
    SOURCES_CS.mkdir(parents=True, exist_ok=True)
    (SOURCES_CS / "dimensions.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    (SOURCES_CS / "meta.json").write_text(
        json.dumps({"reviewStatus": "machine-assisted"}, indent=1), encoding="utf-8")
    (SOURCES_CS / "taxonomy.json").write_text(
        json.dumps(TAXONOMY_CS, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    print(f"sources/cs: {len(out)} dimenzí → {SOURCES_CS}")


def main() -> int:
    retezce = unikatni_retezce()
    cache = prelozit_chybejici(retezce)
    pokryti = sum(1 for s in retezce if s in cache) / len(retezce)
    print(f"pokrytí překladu: {pokryti:.1%}")
    sestavit_sources(cache)
    print("Teď spusť: uv run python persona/schema/labels/build_labels.py --locale cs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
