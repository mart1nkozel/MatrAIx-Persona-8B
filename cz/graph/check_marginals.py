"""Kontrola marginálů vygenerované kohorty vs. ČSÚ priory (exit Fáze 2).

Porovnává vzorek z cz_dag.json s referencí v build_report.json. U vzdělání a
zaměstnaneckého statusu se srovnává subpopulace 18+ (reference ČSÚ je 15+ a
kompatibilní masky záměrně ohýbají dětské kategorie; bracket 13-17 nelze
rozříznout na 15). Tolerance: max |rozdíl| ≤ 1,5 p. b. na kategorii
(předběžná definice V2, finalizace ve Fázi 7).

  uv run python -m cz.graph.check_marginals /cesta/vzorek.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent
TOLERANCE_PB = 1.5

DOSPELI_18 = {"18-24", "25-34", "35-44", "45-54", "55-64", "65-74", "75-84", "85+"}
JEN_DOSPELI = {"highest_education", "demo_employment_status"}


def _jen_dospeli(nid: str, info: dict) -> bool:
    """ESS reference jsou měřené na populaci 15+ — srovnávat subpopulaci 18+."""
    if nid in JEN_DOSPELI:
        return True
    zdroj = str((info.get("provenance") or {}).get("zdroj", ""))
    return zdroj.startswith("ess10")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("sample", type=Path)
    args = ap.parse_args()

    report = json.loads((OUT_DIR / "build_report.json").read_text())
    recs = [json.loads(l) for l in args.sample.open(encoding="utf-8")]
    n = len(recs)
    print(f"vzorek: {n:,} person | snapshot: {report['snapshot']} | tolerance ±{TOLERANCE_PB} p.b.\n")

    celkove_ok = True
    for nid, info in report["nodes"].items():
        # Uzly podmíněné věkem se srovnávají proti očekávanému marginálu 18+
        # (vážený průměr CPT řádků věkovým priorem), ostatní proti prioru.
        ref = info.get("reference_18plus") or info["prior"]
        dospeli = _jen_dospeli(nid, info)
        zdroj = [r for r in recs if r["age_bracket"] in DOSPELI_18] if dospeli else recs
        cnt = Counter(r[nid] for r in zdroj)
        m = len(zdroj)
        max_diff, max_kat = 0.0, ""
        for kat, p_ref in ref.items():
            p_obs = cnt.get(kat, 0) / m
            diff = abs(p_obs - p_ref) * 100
            if diff > max_diff:
                max_diff, max_kat = diff, kat
        navic = set(cnt) - set(ref)
        ok = max_diff <= TOLERANCE_PB and not navic
        celkove_ok &= ok
        pozn = " [18+]" if dospeli else ""
        print(f"{'OK ' if ok else 'FAIL'} {nid}{pozn}: max |Δ| = {max_diff:.2f} p.b. ({max_kat})"
              + (f"; hodnoty mimo referenci: {navic}" if navic else ""))
        if not ok and max_diff > TOLERANCE_PB:
            for kat, p_ref in sorted(ref.items(), key=lambda kv: -kv[1])[:12]:
                p_obs = cnt.get(kat, 0) / m
                flag = " <<<" if abs(p_obs - p_ref) * 100 > TOLERANCE_PB else ""
                print(f"      {kat}: ref {p_ref*100:6.2f} % vs. vzorek {p_obs*100:6.2f} %{flag}")

    print("\nVÝSLEDEK:", "PASS — marginály odpovídají ČSÚ v rámci tolerance" if celkove_ok else "FAIL")
    return 0 if celkove_ok else 1


if __name__ == "__main__":
    sys.exit(main())
