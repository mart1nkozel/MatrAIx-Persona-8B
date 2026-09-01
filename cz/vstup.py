"""4D vstupní vrstva (Fáze 8: F1–F6) — zadání v přirozeném jazyce → filtry.

  ANTHROPIC_API_KEY=... uv run python -m cz.vstup "maminky na rodičovské z menších měst" \
      [--n 10000] [--spustit --out cz/kohorty/moje]

Metoda 4D (samostatná LLM vrstva, ne UI formulář — rozhodnutí backlogu):
1. Deconstruct — záměr, entity, kontext, omezení
2. Diagnose — mezery a nejednoznačnosti; VIDITELNÉ uživateli před generováním
3. Develop — volba přístupu (filtry vs. stratifikace, velikost)
4. Deliver — validovaný filtr pro cz.generate

Bez --spustit jen vypíše 4D rozklad (vč. otázek z Diagnose) a uloží
vstup_4d.json; s --spustit rovnou generuje a celý 4D výstup se propíše do
manifestu kohorty (F6, pole vstupni_4d). Ruční úprava filtru (F5): uprav
vstup_4d.json a spusť cz.generate s --vstup-4d.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

GRAPH = Path(__file__).resolve().parent / "graph" / "cz_dag.json"
MODEL = "anthropic/claude-sonnet-5"

# dimenze nabídnuté LLM vrstvě: kalibrované + geografie (filtry mají smysl)
FILTRO_DIMENZE = [
    "region", "cz_kraj", "age_bracket", "gender_identity", "highest_education",
    "demo_employment_status", "socioeconomic_band", "urbanicity", "primary_language",
    "english_proficiency", "political_lean", "demo_political_engagement", "religiosity",
    "demo_religion_affiliation", "trust_level", "att_immigration", "att_ai",
    "att_climate_action", "att_traditional_gender_roles", "tech_savviness",
    "lstyle_primary_social", "health_general_health", "demo_disability_status",
    "val_family", "val_spirituality_faith",
]

PROMPT = """Jsi vstupní vrstva generátoru syntetických českých person. Uživatel zadal use case v přirozeném jazyce. Rozlož ho metodou 4D a přelož na filtry nad schématem.

Dostupné dimenze a jejich PŘESNÉ hodnoty (filtr smí používat jen tyto):
{katalog}

Zadání uživatele: „{zadani}"

Vrať POUZE JSON:
{{
 "deconstruct": {{"zamer": "...", "entity": ["..."], "kontext": "...", "omezeni": ["..."]}},
 "diagnose": {{"mezery": ["co v zadání chybí nebo je nejednoznačné"], "otazky": ["otázka na uživatele"], "predpoklady": ["jaké předpoklady sis doplnil"]}},
 "develop": {{"pristup": "krátce: proč tyhle filtry/stratifikace", "stratifikovat": null nebo "dimenze"}},
 "deliver": {{"filtry": {{"dimenze": ["hodnota1", "hodnota2"]}}, "poznamka": "..."}}
}}

Zásady: filtruj střídmě (jen co zadání opravdu implikuje — každý filtr zmenšuje kohortu); víc hodnot v seznamu = NEBO; neexistující omezení nevymýšlej, dej je do diagnose.predpoklady."""


def katalog() -> str:
    hodnoty = {n["id"]: n["values"] for n in json.loads(GRAPH.read_text())["nodes"]}
    radky = []
    for d in FILTRO_DIMENZE:
        vals = hodnoty.get(d, [])
        radky.append(f"- {d}: {' | '.join(str(v) for v in vals)}")
    return "\n".join(radky)


def _lenivy_json(text: str) -> dict:
    import re
    blok = text[text.index("{"):text.rindex("}") + 1]
    try:
        return json.loads(blok)
    except json.JSONDecodeError:
        oprava = re.sub(r",\s*([}\]])", r"\1", blok)  # trailing čárky
        return json.loads(oprava)


def rozloz(zadani: str) -> dict:
    import litellm
    zprava = PROMPT.format(katalog=katalog(), zadani=zadani)
    posledni = None
    for pokus in range(3):
        r = litellm.completion(
            model=MODEL, max_tokens=1500,
            messages=[{"role": "user", "content": zprava}]
            + ([{"role": "assistant", "content": str(posledni)[:500]},
                {"role": "user", "content": "Výstup nebyl validní JSON. Vrať POUZE opravený validní JSON."}]
               if posledni else []))
        text = r.choices[0].message.content or ""
        try:
            ctyrd = _lenivy_json(text)
            break
        except (ValueError, json.JSONDecodeError):
            posledni = text
    else:
        raise SystemExit("4D vrstva nevrátila validní JSON ani na 3 pokusy")
    # validace filtrů proti schématu
    hodnoty = {n["id"]: set(map(str, n["values"]))
               for n in json.loads(GRAPH.read_text())["nodes"]}
    chyby = []
    for dim, vals in (ctyrd.get("deliver", {}).get("filtry") or {}).items():
        if dim not in hodnoty:
            chyby.append(f"neznámá dimenze {dim}")
        else:
            spatne = [v for v in vals if str(v) not in hodnoty[dim]]
            if spatne:
                chyby.append(f"{dim}: neznámé hodnoty {spatne}")
    if chyby:
        raise SystemExit(f"4D vrstva vrátila nevalidní filtr: {chyby}\n{json.dumps(ctyrd, ensure_ascii=False, indent=1)}")
    ctyrd["zadani"] = zadani
    return ctyrd


def vypis(ctyrd: dict) -> None:
    d = ctyrd
    print(f"\n— Deconstruct: {d['deconstruct']['zamer']}")
    print(f"— Develop: {d['develop']['pristup']}")
    print("— DIAGNOSE (zkontroluj před generováním):")
    for m in d["diagnose"].get("mezery", []):
        print(f"    mezera: {m}")
    for p in d["diagnose"].get("predpoklady", []):
        print(f"    předpoklad: {p}")
    for o in d["diagnose"].get("otazky", []):
        print(f"    ❓ {o}")
    print("— Deliver (filtry):")
    for dim, vals in (d["deliver"].get("filtry") or {}).items():
        print(f"    {dim} = {' | '.join(map(str, vals))}")
    if d["develop"].get("stratifikovat"):
        print(f"    stratifikovat: {d['develop']['stratifikovat']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("zadani")
    ap.add_argument("--n", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--spustit", action="store_true",
                    help="rovnou generovat (jinak jen rozklad + vstup_4d.json)")
    args = ap.parse_args()

    ctyrd = rozloz(args.zadani)
    vypis(ctyrd)

    out = args.out or Path("cz/kohorty") / "4d-navrh"
    out.mkdir(parents=True, exist_ok=True)
    (out / "vstup_4d.json").write_text(
        json.dumps(ctyrd, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n4D rozklad → {out / 'vstup_4d.json'}")

    if not args.spustit:
        print("Spusť s --spustit, nebo uprav vstup_4d.json (F5) a použij: "
              f"uv run python -m cz.generate --n {args.n} --out {out} "
              f"--vstup-4d {out / 'vstup_4d.json'} …")
        return 0

    cmd = [sys.executable, "-m", "cz.generate", "--n", str(args.n), "--seed", str(args.seed),
           "--out", str(out), "--vstup-4d", str(out / "vstup_4d.json")]
    for dim, vals in (ctyrd["deliver"].get("filtry") or {}).items():
        cmd += ["--filtr", f"{dim}={'|'.join(map(str, vals))}"]
    if ctyrd["develop"].get("stratifikovat"):
        cmd += ["--stratifikovat", ctyrd["develop"]["stratifikovat"]]
    print("\n→ generuji:", " ".join(cmd[2:]))
    return subprocess.call(cmd, cwd=REPO)


if __name__ == "__main__":
    sys.exit(main())
