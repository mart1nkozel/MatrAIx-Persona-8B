"""Chat se třemi medoidními personami vedle sebe (Fáze 8: F16–F20).

  ANTHROPIC_API_KEY=... uv run python -m cz.chat --kohorta cz/kohorty/demo-cr
      [--segmenty 0,2,3] [--model anthropic/claude-sonnet-5]
      [--porovnat anthropic/claude-haiku-4-5-20251001]

- F16: tři persony = tři samostatná vlákna konverzace (každá má vlastní historii)
- F17: karta persony — klíčové atributy, který segment reprezentuje a jeho podíl
- F19: u každé odpovědi je vidět model, který personu hraje
- F20: --porovnat pustí tutéž personu i pod druhým modelem (sekundární výstup)
- F18 (napojení na upstream Playground) je v1.2 — viz docs

Zprávy se čtou ze stdin (interaktivně i pipe), `konec` ukončí. Přepis se
ukládá do <kohorta>/chat-<timestamp>.json.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from cz.lang.render_cs import karta_cs  # noqa: E402

SYSTEM = """Jsi syntetická persona pro výzkum trhu. Věrně hraješ následující profil — jeho postoje, hodnoty i způsob vyjadřování. Mluvíš přirozeně, v první osobě, VŽDY svým mateřským jazykem. Odpovídáš stručně a konkrétně (3–6 vět, pokud se nehodí víc). Neprozrazuješ, že jsi AI, a nevypadáváš z role.

"""


def zavolej(model: str, system: str, historie: list[dict]) -> str:
    import litellm
    r = litellm.completion(model=model, max_tokens=600,
                           messages=[{"role": "system", "content": system}] + historie)
    return (r.choices[0].message.content or "").strip()


def hlavicka_persony(seg: dict) -> str:
    m = seg["medoid"]
    return (f"{m.get('gender_identity')}, {m.get('age_bracket')}, {m.get('region')} — "
            f"{m.get('highest_education')}, {m.get('demo_employment_status')}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kohorta", type=Path, required=True)
    ap.add_argument("--segmenty", help="čárkami indexy segmentů (výchozí: 3 největší)")
    ap.add_argument("--model", default="anthropic/claude-sonnet-5")
    ap.add_argument("--porovnat", help="druhý model pro F20 srovnání (volitelné)")
    args = ap.parse_args()

    seg_soubor = args.kohorta / "segmenty.json"
    if not seg_soubor.exists():
        raise SystemExit(f"{seg_soubor} neexistuje — nejdřív spusť cz.segmentace")
    data = json.loads(seg_soubor.read_text())
    segmenty = sorted(data["segmenty"], key=lambda s: -s["podil"])
    if args.segmenty:
        chtene = [int(x) for x in args.segmenty.split(",")]
        segmenty = [s for s in data["segmenty"] if s["segment"] in chtene]
    segmenty = segmenty[:3]

    print("=" * 72)
    for s in segmenty:
        print(f"PERSONA {s['segment']} — segment {s['segment']} "
              f"({s['podil']:.0%} populace kohorty)")
        print(f"  {hlavicka_persony(s)}")
        for r in s["odlisujici_rysy"][:3]:
            print(f"  typické: {r['dimenze']}={r['hodnota']} ({r['segment']:.0%} vs {r['populace']:.0%})")
    print(f"model: {args.model}" + (f" | srovnání: {args.porovnat}" if args.porovnat else ""))
    print("=" * 72)

    vlakna = {s["segment"]: [] for s in segmenty}   # F16: oddělené historie
    vlakna_b = {s["segment"]: [] for s in segmenty}
    prepis = {"kohorta": str(args.kohorta), "model": args.model,
              "porovnani": args.porovnat, "segmenty": [s["segment"] for s in segmenty],
              "zpravy": []}

    print("Piš zprávy (ukonči 'konec'):")
    for radek in sys.stdin:
        zprava = radek.strip()
        if not zprava:
            continue
        if zprava.lower() in ("konec", "exit", "quit"):
            break
        for s in segmenty:
            karta = karta_cs(s["medoid"])
            vlakna[s["segment"]].append({"role": "user", "content": zprava})
            odp = zavolej(args.model, SYSTEM + karta, vlakna[s["segment"]])
            vlakna[s["segment"]].append({"role": "assistant", "content": odp})
            print(f"\n[persona {s['segment']} | {s['podil']:.0%} | {args.model.split('/')[-1]}]")
            print(f"  {odp}")
            zaznam = {"segment": s["segment"], "zprava": zprava,
                      "model": args.model, "odpoved": odp}
            if args.porovnat:
                vlakna_b[s["segment"]].append({"role": "user", "content": zprava})
                odp_b = zavolej(args.porovnat, SYSTEM + karta, vlakna_b[s["segment"]])
                vlakna_b[s["segment"]].append({"role": "assistant", "content": odp_b})
                print(f"  [srovnání | {args.porovnat.split('/')[-1]}]: {odp_b}")
                zaznam["odpoved_porovnani"] = odp_b
            prepis["zpravy"].append(zaznam)
        print("\n> ", end="", flush=True)

    ts = time.strftime("%Y%m%d-%H%M%S")
    out = args.kohorta / f"chat-{ts}.json"
    out.write_text(json.dumps(prepis, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\npřepis → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
