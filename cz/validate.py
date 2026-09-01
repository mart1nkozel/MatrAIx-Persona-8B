"""Opakovatelný validační běh CZ vrstvy (Fáze 7: V1–V4 + determinismus).

  uv run python -m cz.validate [--n 200000] [--n-konzistence 50000] [--seed 42]

Tolerance (V2, formalizace):
- V1 marginály: max |Δ| ≤ 1,5 p. b. na kategorii (šum vzorkování při n=200k
  je ≤ ~0,3 p. b.; rezerva kryje kompozici CPT a masek). CZ-survey a SLDB
  dimenze se srovnávají na subpopulaci 18+ (reference jsou 15+).
- V3 konzistence: CZ pravidla (CZ1–CZ4) = 0 tvrdých rozporů; upstream soft
  pravidla ≤ 0,1 % vzorku.
- Determinismus: dva běhy (seed, graf) ⇒ identické hodnoty (kontrola 2×2000).

Výstup: cz/validace/report-<timestamp>.{json,md} + exit kód (0 = PASS).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from persona.synthesis.sampler import PersonaForwardSampler, SamplingConfig  # noqa: E402

from cz.graph import check_consistency, check_marginals  # noqa: E402

GRAPH = Path(__file__).resolve().parent / "graph" / "cz_dag.json"
REPORT_DIR = Path(__file__).resolve().parent / "validace"
MAX_SOFT_PODIL = 0.001  # 0,1 %


def marginaly(n: int, seed: int, report: dict) -> tuple[list, bool]:
    sampler = PersonaForwardSampler(GRAPH, SamplingConfig(seed=seed))
    idx = sampler.sample_indices(n)
    potrebne = sorted(set(report["nodes"]) | {"age_bracket"})
    sloupce = {nid: [sampler.values[nid][i] for i in idx[nid]] for nid in potrebne}
    recs = [{nid: sloupce[nid][i] for nid in potrebne} for i in range(n)]
    return check_marginals.zkontroluj(recs, report, tichy=True)


def determinismus(seed: int) -> bool:
    otisky = []
    for _ in range(2):
        s = PersonaForwardSampler(GRAPH, SamplingConfig(seed=seed))
        idx = s.sample_indices(2000)
        h = hashlib.sha256()
        for nid in sorted(idx):
            h.update(idx[nid].tobytes())
        otisky.append(h.hexdigest())
    return otisky[0] == otisky[1]


def pokryti() -> dict:
    import csv
    reg = list(csv.DictReader((Path(__file__).parent / "graph" / "provenance_registry.csv").open()))
    typy = Counter(r["provenience"] for r in reg)
    emitovane = [r for r in reg if r["emitovano"] == "True"]
    kalibrovane = [r for r in emitovane if r["provenience"] in ("CZ-official", "CZ-survey")]
    kategorie = Counter()
    kalib_kat = Counter()
    for r in emitovane:
        kat = r["category"].split(":")[0].strip()
        kategorie[kat] += 1
        if r["provenience"] in ("CZ-official", "CZ-survey"):
            kalib_kat[kat] += 1
    return {
        "celkem_uzlu": len(reg),
        "typy": dict(typy),
        "emitovanych": len(emitovane),
        "kalibrovanych": len(kalibrovane),
        "podil_kalibrovanych_emitovanych": round(len(kalibrovane) / len(emitovane), 4),
        "po_kategoriich": {k: {"celkem": kategorie[k], "kalibrovano": kalib_kat.get(k, 0)}
                           for k in sorted(kategorie)},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=200_000)
    ap.add_argument("--n-konzistence", type=int, default=50_000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    t0 = time.time()

    build_report = json.loads((Path(__file__).parent / "graph" / "build_report.json").read_text())
    graf_sha = hashlib.sha256(GRAPH.read_bytes()).hexdigest()

    print(f"V1 marginály (n={args.n:,}) …")
    v1_vysledky, v1_ok = marginaly(args.n, args.seed, build_report)
    v1_fail = [v for v in v1_vysledky if not v["ok"]]
    print(f"   {'PASS' if v1_ok else 'FAIL'} — {len(v1_vysledky)} uzlů, "
          f"max Δ {max(v['max_diff_pb'] for v in v1_vysledky):.2f} p.b."
          + (f"; FAIL: {[v['uzel'] for v in v1_fail]}" if v1_fail else ""))

    print(f"V3 konzistence (n={args.n_konzistence:,}) …")
    upstream, cz = check_consistency.spocitej(GRAPH, args.n_konzistence, args.seed)
    soft_podil = sum(upstream.values()) / args.n_konzistence
    v3_ok = (sum(cz.values()) == 0) and (soft_podil <= MAX_SOFT_PODIL)
    print(f"   {'PASS' if v3_ok else 'FAIL'} — CZ rozporů {sum(cz.values())}, "
          f"upstream soft {soft_podil:.3%}")

    print("determinismus …")
    det_ok = determinismus(args.seed)
    print(f"   {'PASS' if det_ok else 'FAIL'}")

    cov = pokryti()
    print(f"V4 pokrytí: {cov['kalibrovanych']}/{cov['emitovanych']} emitovaných dimenzí "
          f"kalibrováno CZ daty ({cov['podil_kalibrovanych_emitovanych']:.1%})")

    celkove_ok = v1_ok and v3_ok and det_ok
    report = {
        "vytvoreno": datetime.now(timezone.utc).isoformat(),
        "graf_sha256": graf_sha,
        "snapshot": build_report.get("snapshot"),
        "parametry": {"n": args.n, "n_konzistence": args.n_konzistence, "seed": args.seed},
        "tolerance": {"marginaly_pb": check_marginals.TOLERANCE_PB,
                      "max_soft_podil": MAX_SOFT_PODIL},
        "v1_marginaly": {"ok": v1_ok, "uzly": v1_vysledky},
        "v3_konzistence": {"ok": v3_ok, "cz": dict(cz), "upstream": dict(upstream),
                           "soft_podil": soft_podil},
        "determinismus": det_ok,
        "v4_pokryti": cov,
        "vysledek": "PASS" if celkove_ok else "FAIL",
        "trvani_s": round(time.time() - t0, 1),
    }
    REPORT_DIR.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    (REPORT_DIR / f"report-{ts}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    md = [f"# Validační report {ts}", "",
          f"Graf: `{graf_sha[:16]}…` | snapshot: {report['snapshot']} | "
          f"seed {args.seed} | trvání {report['trvani_s']} s", "",
          f"| Kontrola | Výsledek |", "|---|---|",
          f"| V1 marginály ({len(v1_vysledky)} uzlů, n={args.n:,}) | "
          f"{'PASS' if v1_ok else 'FAIL — ' + ', '.join(v['uzel'] for v in v1_fail)} |",
          f"| V3 konzistence (n={args.n_konzistence:,}) | "
          f"{'PASS' if v3_ok else 'FAIL'} (CZ {sum(cz.values())}, soft {soft_podil:.3%}) |",
          f"| Determinismus | {'PASS' if det_ok else 'FAIL'} |",
          f"| V4 pokrytí | {cov['kalibrovanych']}/{cov['emitovanych']} emitovaných "
          f"({cov['podil_kalibrovanych_emitovanych']:.1%}) kalibrováno CZ daty |",
          "", f"**VÝSLEDEK: {report['vysledek']}**"]
    (REPORT_DIR / f"report-{ts}.md").write_text("\n".join(md), encoding="utf-8")
    print(f"\nVÝSLEDEK: {report['vysledek']} → {REPORT_DIR / f'report-{ts}.md'}")
    return 0 if celkove_ok else 1


if __name__ == "__main__":
    sys.exit(main())
