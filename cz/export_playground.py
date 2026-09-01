"""Export kohorty do upstream Playground datasetu (Fáze 8: F18).

  uv run python -m cz.export_playground --kohorta cz/kohorty/demo-cr \
      [--nazev cz-demo] [--limit 200] [--jen-medoidy]

Vytvoří persona/datasets/<nazev>/ ve formátu upstreamu (manifest.json +
persona_XXXX.yaml) — Playground i CLI tasky pak CZ persony vidí jako každý
jiný dataset (Dataset → <nazev>). `--jen-medoidy` exportuje jen medoidní
persony segmentů (pro chat tří person v Playgroundu). Display jména jsou
česká, deterministická ze seedu kohorty; do YAML se přidává cz_segment
(loader upstreamu extra klíče ignoruje).
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

JMENA_Z = ["Jana", "Marie", "Eva", "Hana", "Anna", "Lenka", "Kateřina", "Lucie",
           "Věra", "Alena", "Petra", "Veronika", "Jaroslava", "Tereza", "Martina"]
JMENA_M = ["Jiří", "Jan", "Petr", "Josef", "Pavel", "Martin", "Tomáš", "Jaroslav",
           "Miroslav", "Zdeněk", "František", "Václav", "Karel", "Milan", "Michal"]
PRIJMENI = ["Novák", "Svoboda", "Novotný", "Dvořák", "Černý", "Procházka", "Kučera",
            "Veselý", "Horák", "Němec", "Marek", "Pokorný", "Pospíšil", "Hájek",
            "Král", "Jelínek", "Růžička", "Beneš", "Fiala", "Sedláček"]


def jmeno(rng: np.random.Generator, zena: bool) -> str:
    krestni = rng.choice(JMENA_Z if zena else JMENA_M)
    prijmeni = str(rng.choice(PRIJMENI))
    if zena:
        prijmeni = prijmeni[:-1] + "á" if prijmeni.endswith("ý") else prijmeni + "ová"
    return f"{krestni} {prijmeni}"


def yaml_persona(pid: str, display: str, dims: dict, segment: int | None) -> str:
    radky = [f"persona_id: '{pid}'", "version: '1.0'", "source: matraix-cz",
             f"display_name: {display}"]
    if segment is not None:
        radky.append(f"cz_segment: {segment}")
    radky.append("dimensions:")
    for k, v in dims.items():
        v = str(v).replace("'", "''")
        radky.append(f"  {k}: '{v}'")
    return "\n".join(radky) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kohorta", type=Path, required=True)
    ap.add_argument("--nazev", help="název datasetu (výchozí: cz-<jméno kohorty>)")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--jen-medoidy", action="store_true")
    args = ap.parse_args()

    nazev = args.nazev or f"cz-{args.kohorta.name}"
    cil = REPO / "persona" / "datasets" / nazev
    cil.mkdir(parents=True, exist_ok=True)

    manifest_k = json.loads((args.kohorta / "manifest.json").read_text()) \
        if (args.kohorta / "manifest.json").exists() else {}
    seed = manifest_k.get("pozadavek", {}).get("seed", 42)
    rng = np.random.default_rng(seed)

    segmenty_f = args.kohorta / "segmenty.json"
    prirazeni = None
    if segmenty_f.exists():
        import pandas as pd
        prirazeni = pd.read_parquet(args.kohorta / "prirazeni.parquet")["segment"].to_numpy() \
            if (args.kohorta / "prirazeni.parquet").exists() else None

    if args.jen_medoidy:
        if not segmenty_f.exists():
            raise SystemExit("--jen-medoidy potřebuje segmenty.json (spusť cz.segmentace)")
        seg = json.loads(segmenty_f.read_text())
        persony = [(s["medoid"], s["segment"]) for s in seg["segmenty"]]
    else:
        soubory = sorted(list(args.kohorta.glob("*.jsonl.gz")) + list(args.kohorta.glob("*.jsonl")))
        persony = []
        i = 0
        for f in soubory:
            otevrit = gzip.open if f.suffix == ".gz" else open
            with otevrit(f, "rt", encoding="utf-8") as fh:
                for line in fh:
                    if len(persony) >= args.limit:
                        break
                    p = json.loads(line)
                    persony.append((p, int(prirazeni[i]) if prirazeni is not None
                                    and i < len(prirazeni) else None))
                    i += 1

    dim_ids = list(persony[0][0].keys())
    for idx, (p, segment) in enumerate(persony):
        pid = f"{idx:04d}"
        display = jmeno(rng, p.get("gender_identity") == "Woman")
        (cil / f"persona_{pid}.yaml").write_text(
            yaml_persona(pid, display, p, segment), encoding="utf-8")

    (cil / "manifest.json").write_text(json.dumps({
        "kind": nazev,
        "count": len(persony),
        "seed": seed,
        "schema_version": "1.0",
        "smoke_persona_id": "0000",
        "dimension_count": len(dim_ids),
        "dimension_ids": dim_ids,
        "cz_zdroj_kohorty": str(args.kohorta),
        "cz_graf_sha256": manifest_k.get("graf", {}).get("sha256"),
        "cz_snapshot": manifest_k.get("graf", {}).get("snapshot_id"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"dataset '{nazev}': {len(persony)} person → {cil}")
    print(f"Playground: Dataset → {nazev} | CLI: --dataset persona/datasets/{nazev}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
