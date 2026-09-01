"""V5/V6: adherence probe v češtině + multi-model rozptyl (střední škála).

10 dospělých person × 5 otázek × 2 modely (sonnet-5, haiku-4.5) = 100
odpovědí; soudce (sonnet-5) hodnotí češtinu a adherenci; 50 párových
srovnání stanovisek měří mezi-modelovou shodu (V6).

Vztah k paperu: jejich design = 400 trialů, jiné metriky (stylistická
adherence EN 91,5 %; rozptyl 23,2–93,9 % na výsledcích úloh) — čísla nejsou
přímo srovnatelná, měříme týž jev na CZ verzi ve střední škále. Soudce je
zároveň jedním z testovaných modelů (zděděné omezení č. 4, self-preference).

  ANTHROPIC_API_KEY=... uv run python -m cz.lang.probe_v5
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from persona.synthesis.sampler import PersonaForwardSampler, SamplingConfig  # noqa: E402

from cz.lang.render_cs import karta_cs  # noqa: E402

CZ_LANG = Path(__file__).resolve().parent
MODELY = ["anthropic/claude-sonnet-5", "anthropic/claude-haiku-4-5-20251001"]
SOUDCE_MODEL = "anthropic/claude-sonnet-5"
DOSPELI = {"18-24", "25-34", "35-44", "45-54", "55-64", "65-74", "75-84", "85+"}

OTAZKY = [
    "Představte se mi prosím krátce.",
    "Co si myslíte o imigraci do Česka? Stačí pár vět.",
    "Používáte nástroje umělé inteligence? Proč ano, nebo ne?",
    "Jak vnímáte změnu klimatu a co jste pro ni ochotni dělat?",
    "Jakou roli hraje ve vašem životě víra a tradice?",
]

SYSTEM = """Jsi syntetická persona pro výzkum trhu. Věrně hraješ následující profil — jeho postoje, hodnoty i způsob vyjadřování. Mluvíš přirozeně, v první osobě, VŽDY svým mateřským jazykem. Neprozrazuješ, že jsi AI, a nevypadáváš z role.

"""

SOUDCE = """Vyhodnoť odpověď syntetické persony. Profil persony:

{karta}

Otázka: {otazka}
Odpověď: {odpoved}

Vrať POUZE JSON: {{"cestina": true/false, "adherence": 1-5 (5 = plně konzistentní s profilem, zejména s relevantními postoji; 1 = v rozporu), "duvod": "jedna věta"}}"""

SHODA = """Dvě AI persony se STEJNÝM profilem odpověděly na tutéž otázku. Profil (zkráceně): {profil}
Otázka: {otazka}
Odpověď A: {a}
Odpověď B: {b}

Vyjadřují obě odpovědi STEJNÉ věcné stanovisko/postoj (bez ohledu na styl a délku)? Vrať POUZE JSON: {{"shoda": true/false, "duvod": "jedna věta"}}"""


def zavolej(model, system, user, max_tokens=450):
    import litellm
    kandidati = [model, "anthropic/claude-haiku-4-5-20251001"]
    for pokus, m in enumerate(kandidati):
        try:
            r = litellm.completion(model=m, max_tokens=max_tokens,
                                   messages=[{"role": "system", "content": system},
                                             {"role": "user", "content": user}])
            obsah = r.choices[0].message.content
            if obsah and obsah.strip():
                return obsah.strip()
        except Exception:  # noqa: BLE001 — zkusí fallback
            pass
    return ""


def parse_json(text: str) -> dict:
    try:
        return json.loads(text[text.index("{"):text.rindex("}") + 1])
    except Exception:  # noqa: BLE001
        return {}


def vyber_persony(n: int = 10, seed: int = 99) -> list[dict]:
    s = PersonaForwardSampler(REPO / "cz" / "graph" / "cz_dag.json", SamplingConfig(seed=seed))
    idx = s.sample_indices(200)
    out = []
    for i in range(200):
        p = s.decode_row(idx, i)
        if p["age_bracket"] in DOSPELI:
            out.append(p)
        if len(out) >= n:
            break
    return out


def main() -> int:
    persony = vyber_persony()
    vysledky = []
    for pi, p in enumerate(persony):
        karta = karta_cs(p)
        for q in OTAZKY:
            odpovedi = {}
            for model in MODELY:
                odp = zavolej(model, SYSTEM + karta, q)
                hodnoceni = parse_json(zavolej(
                    SOUDCE_MODEL, "Jsi pečlivý hodnotitel. Vracíš pouze JSON.",
                    SOUDCE.format(karta=karta, otazka=q, odpoved=odp), max_tokens=250))
                odpovedi[model] = odp
                vysledky.append({"persona": pi, "otazka": q, "model": model,
                                 "odpoved": odp, **hodnoceni})
            shoda = parse_json(zavolej(
                SOUDCE_MODEL, "Jsi pečlivý hodnotitel. Vracíš pouze JSON.",
                SHODA.format(profil=karta[:800], otazka=q,
                             a=odpovedi[MODELY[0]][:600], b=odpovedi[MODELY[1]][:600]),
                max_tokens=200))
            vysledky.append({"persona": pi, "otazka": q, "model": "V6_shoda",
                             **shoda})
        print(f"persona {pi + 1}/{len(persony)} hotova")

    print()
    for model in MODELY:
        sub = [v for v in vysledky if v["model"] == model and v.get("adherence") is not None]
        cz = sum(1 for v in sub if v.get("cestina")) / len(sub)
        adh = sum(v["adherence"] for v in sub) / len(sub)
        plna = sum(1 for v in sub if v["adherence"] >= 4) / len(sub)
        print(f"{model.split('/')[-1]}: česky {cz:.0%}, adherence {adh:.2f}/5 "
              f"(≥4: {plna:.0%}, n={len(sub)})")
    par = [v for v in vysledky if v["model"] == "V6_shoda" and v.get("shoda") is not None]
    print(f"V6 mezi-modelová shoda stanovisek: "
          f"{sum(1 for v in par if v['shoda']) / len(par):.0%} (n={len(par)})")

    (CZ_LANG / "v5_vysledky.json").write_text(
        json.dumps(vysledky, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"uloženo: {CZ_LANG / 'v5_vysledky.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
