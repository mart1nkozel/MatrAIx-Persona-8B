"""L4: drží LLM personu v češtině stejně dobře jako v angličtině? (mini probe)

Smoke-scale měření (4 persony × 2 varianty karty × 3 české otázky = 24
odpovědí + 24 soudcovských hodnocení), NE plná replikace 400-trial designu
z paperu — ta je V5 (Fáze 7). Soudce = stejný model jako persona → platí
zděděné omezení č. 4 (self-preference), dokumentováno.

  ANTHROPIC_API_KEY=... uv run python -m cz.lang.l4_test
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from cz.lang.render_cs import karta_cs, nacti_personu

CZ_LANG = Path(__file__).resolve().parent
REPO = CZ_LANG.parents[1]
MODELY = ["anthropic/claude-sonnet-5", "anthropic/claude-haiku-4-5-20251001"]

PERSONY = [
    ("cz/kohorty/test-praha-zeny", 0),
    ("cz/kohorty/test-praha-zeny", 2),
    ("cz/kohorty/test-jmk-vs", 0),
    ("cz/kohorty/test-jmk-vs", 3),
]

OTAZKY = [
    "Představte se mi prosím krátce.",
    "Co si myslíte o imigraci do Česka? Stačí pár vět.",
    "Jak moc používáte internet a sociální sítě? K čemu hlavně?",
]

SYSTEM_CS = """Jsi syntetická persona pro výzkum trhu. Věrně hraješ následující profil — jeho postoje, hodnoty i způsob vyjadřování. Mluvíš přirozeně, v první osobě, VŽDY svým mateřským jazykem. Neprozrazuješ, že jsi AI, a nevypadáváš z role.

"""

SYSTEM_EN = """You are a synthetic persona for market research. Faithfully play the following profile — its attitudes, values and manner of speaking. Speak naturally, in the first person, ALWAYS in your persona's native language. Never reveal you are an AI or break character.

"""

SOUDCE = """Vyhodnoť odpověď syntetické persony. Profil persony:

{karta}

Otázka: {otazka}
Odpověď persony: {odpoved}

Vrať POUZE JSON: {{"cestina": true/false (je odpověď česky?), "adherence": 1-5 (5 = plně konzistentní s profilem, zejména s relevantními postoji; 1 = v rozporu), "duvod": "jedna věta"}}"""


def karta_en(p: dict) -> str:
    dims = {d["id"]: d for d in json.loads(
        (REPO / "persona" / "schema" / "dimensions.json").read_text())["dimensions"]}
    vyber = ["gender_identity", "age_bracket", "region", "cz_kraj", "urbanicity",
             "primary_language", "english_proficiency", "highest_education",
             "demo_employment_status", "socioeconomic_band", "political_lean",
             "demo_political_engagement", "att_immigration", "trust_level", "religiosity",
             "demo_religion_affiliation", "cog_optimism", "lstyle_social_battery",
             "tech_savviness", "health_general_health", "health_mental_health",
             "dominant_trait", "mbti_type", "risk_tolerance",
             "schwartz_value_tradition", "schwartz_value_security", "schwartz_value_benevolence"]
    radky = ["PERSONA PROFILE"]
    for d in vyber:
        if p.get(d):
            lbl = dims[d]["label"] if d in dims else d
            radky.append(f"{lbl}: {p[d]}")
    return "\n".join(radky)


def zavolej(messages, system, max_tokens=450):
    import litellm
    posledni = None
    for model in MODELY:
        try:
            r = litellm.completion(model=model, max_tokens=max_tokens,
                                   messages=[{"role": "system", "content": system}] + messages)
            return r.choices[0].message.content.strip(), model
        except Exception as e:  # noqa: BLE001 — fallback na starší model
            posledni = e
    raise posledni


def main() -> int:
    vysledky = []
    for cesta, idx in PERSONY:
        p = nacti_personu(REPO / cesta, idx)
        for varianta, karta, system in [("cs", karta_cs(p), SYSTEM_CS),
                                        ("en", karta_en(p), SYSTEM_EN)]:
            for otazka in OTAZKY:
                odpoved, model = zavolej([{"role": "user", "content": otazka}], system + karta)
                text, judge_model = zavolej(
                    [{"role": "user", "content": SOUDCE.format(
                        karta=karta_cs(p), otazka=otazka, odpoved=odpoved)}],
                    "Jsi pečlivý hodnotitel. Vracíš pouze JSON.", max_tokens=250)
                try:
                    hodnoceni = json.loads(text[text.index("{"):text.rindex("}") + 1])
                except Exception:  # noqa: BLE001
                    hodnoceni = {"cestina": None, "adherence": None, "duvod": "PARSE FAIL"}
                vysledky.append({
                    "persona": f"{cesta}#{idx}", "varianta": varianta, "otazka": otazka,
                    "odpoved": odpoved, "model": model, "judge_model": judge_model,
                    **hodnoceni,
                })
                print(f"  {cesta.split('/')[-1]}#{idx} [{varianta}] "
                      f"cestina={hodnoceni.get('cestina')} adherence={hodnoceni.get('adherence')}")

    for varianta in ("cs", "en"):
        sub = [v for v in vysledky if v["varianta"] == varianta and v["adherence"] is not None]
        cz = sum(1 for v in sub if v["cestina"]) / len(sub)
        adh = sum(v["adherence"] for v in sub) / len(sub)
        print(f"\nkarta {varianta.upper()}: odpovědi česky {cz:.0%}, adherence {adh:.2f}/5 (n={len(sub)})")

    out = CZ_LANG / "l4_vysledky.json"
    out.write_text(json.dumps(vysledky, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nuloženo: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
