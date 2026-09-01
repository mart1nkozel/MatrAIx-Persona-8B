"""Český render karty persony (L1/L2 — exit: „persona v promptu česky a čitelně").

Rozhodnutí L1: popisy person se generují přímo česky (ne EN + překlad) —
jednojazyčný prompt drží personu v češtině lépe a mechanismus label packů
překlad pokrývá. Jádro karty tvoří ručně psané české fráze; zbytek dimenzí
se skládá jako „Label: hodnota" z label packu cs (fallback EN, viz README
label packů — chybějící překlad nikdy neshodí render).

  uv run python -m cz.lang.render_cs --kohorta cz/kohorty/test-praha-zeny --index 0
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

CZ_LANG = Path(__file__).resolve().parent
REPO = CZ_LANG.parents[1]

_PACK = None
_EXTRA = None


def _labels() -> tuple[dict, dict]:
    global _PACK, _EXTRA
    if _PACK is None:
        _PACK = json.loads(
            (REPO / "persona" / "schema" / "labels" / "dimensions.labels.cs.json").read_text()
        )["dimensions"]
        _EXTRA = json.loads((CZ_LANG / "labels_cz_extra.json").read_text())
    return _PACK, _EXTRA


def hodnota(dim: str, val: str) -> str:
    pack, extra = _labels()
    if dim in extra and val in extra[dim]["values"]:
        return extra[dim]["values"][val]
    return pack.get(dim, {}).get("values", {}).get(val, val)


def label(dim: str) -> str:
    pack, extra = _labels()
    if dim in extra and extra[dim].get("label"):
        return extra[dim]["label"]
    return pack.get(dim, {}).get("label", dim)


VYNECHAT_HODNOTY = {"None", "Never used", "Not applicable", "Neutral", "Indifferent"}

SEKCE = [
    ("Hodnoty", ["schwartz_value_self_direction", "schwartz_value_stimulation",
                 "schwartz_value_hedonism", "schwartz_value_achievement", "schwartz_value_power",
                 "schwartz_value_security", "schwartz_value_conformity", "schwartz_value_tradition",
                 "schwartz_value_benevolence", "schwartz_value_universalism", "values_priority"]),
    ("Postoje a světonázor", ["political_lean", "demo_political_engagement", "topic_politics",
                              "att_immigration", "trust_level", "religiosity",
                              "demo_religion_affiliation", "cog_optimism", "lstyle_social_battery"]),
    ("Zdraví", ["health_general_health", "health_mental_health", "demo_disability_status",
                "health_mobility", "health_stress_level", "health_energy_level",
                "health_fitness_level", "health_sleep_quality"]),
    ("Technologie a média", ["tech_savviness", "netusoft_pozn", "lstyle_primary_social",
                             "att_social_media", "att_ai", "att_new_technology"]),
    ("Osobnost", ["dominant_trait", "mbti_type", "risk_tolerance", "decision_style",
                  "spending_style", "neurotype"]),
]


def _preferovane_zajmy(p: dict) -> list[str]:
    out = []
    for dim, val in p.items():
        if dim.startswith(("topic_", "hobby_", "interest_")) and val in ("Passionate", "Interested"):
            out.append(f"{label(dim).removeprefix('Téma: ').removeprefix('Zájem: ')}"
                       + (" (nadšeně)" if val == "Passionate" else ""))
    return out[:14]


def karta_cs(p: dict) -> str:
    rod_z = p.get("gender_identity") == "Woman"

    def ho(dim):
        return hodnota(dim, p.get(dim, ""))

    jazyk = ho("primary_language")
    veta1 = (f"{'Žena' if rod_z else 'Muž' if p.get('gender_identity') == 'Man' else ho('gender_identity')}, "
             f"{hodnota('age_bracket', p['age_bracket']).lower().replace('let', 'let věku') if p['age_bracket'] not in ('Under 5',) else 'do 5 let věku'}, "
             f"žije v okrese {p.get('region')}"
             + (f" ({p.get('cz_kraj')})" if p.get('cz_kraj') != p.get('region') else "")
             + f", prostředí: {ho('urbanicity').lower()}.")
    veta2 = (f"Mateřský jazyk: {jazyk}"
             + (f", angličtina: {ho('english_proficiency').lower()}" if p.get("english_proficiency") else "")
             + f". Vzdělání: {ho('highest_education').lower()}. "
             f"Ekonomický status: {ho('demo_employment_status').lower()}, "
             f"{ho('socioeconomic_band').lower()} pásmo.")
    radky = ["PROFIL PERSONY", veta1, veta2, ""]

    for nazev, dims in SEKCE:
        pary = []
        for d in dims:
            v = p.get(d)
            if v and v not in VYNECHAT_HODNOTY:
                pary.append(f"{label(d)}: {hodnota(d, v)}")
        if pary:
            radky.append(f"{nazev}: " + "; ".join(pary) + ".")

    zajmy = _preferovane_zajmy(p)
    if zajmy:
        radky.append("Zájmy: " + ", ".join(zajmy) + ".")
    return "\n".join(radky)


def nacti_personu(kohorta: Path, index: int) -> dict:
    soubory = sorted(list(kohorta.glob("*.jsonl.gz")) + list(kohorta.glob("*.jsonl")))
    if not soubory:
        raise SystemExit(f"V {kohorta} není žádný jsonl soubor")
    otevrit = gzip.open if soubory[0].suffix == ".gz" else open
    with otevrit(soubory[0], "rt", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i == index:
                return json.loads(line)
    raise SystemExit(f"Index {index} mimo rozsah")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kohorta", type=Path, required=True)
    ap.add_argument("--index", type=int, default=0)
    args = ap.parse_args()
    print(karta_cs(nacti_personu(args.kohorta, args.index)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
