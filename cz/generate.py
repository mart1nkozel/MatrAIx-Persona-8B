"""On-demand generování CZ kohort (Fáze 5: E1, E2, E5; E3/E4 delegací).

  uv run python -m cz.generate --n 10000 --seed 42 --out kohorty/praha \
      --filtr "region=Hlavní město Praha" --filtr "gender_identity=Woman"

Filtry: `dim=hodnota` nebo `dim=hodnota1|hodnota2`. Jednohodnotový filtr na
kořenový uzel (bez rodičů v grafu) se řeší clampem v sampleru (přesné a bez
režie); vše ostatní rejection samplingem po dávkách. Clamp na nekořenový uzel
by nebyl podmiňováním (rodiče by se nepřepočítali), proto se nepoužívá.

Stratifikace: `--stratifikovat dim` vygeneruje rovnoměrný počet person pro
každou hodnotu dimenze (child seed = seed*1000+index → deterministické).

Determinismus (E2): stejný seed + stejný graf (sha256 v manifestu, uvnitř
grafu pin na datový snapshot) ⇒ bitově identický výstup. Manifest kohorty
(E5) zaznamenává požadavek, skutečný výsledek i akceptační poměry.
Bez filtrů a se `--format codes` se generování deleguje na upstream
paralelní sampler (E3 streaming, E4 shardování).
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from persona.synthesis.sampler import (  # noqa: E402
    PersonaForwardSampler,
    SamplingConfig,
    sample_to_file_parallel,
)

DEFAULT_GRAPH = Path(__file__).resolve().parent / "graph" / "cz_dag.json"
MAX_DAVEK = 500
MIN_AKCEPTACE = 1e-4


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_filtry(polozky: list[str] | None) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for p in polozky or []:
        dim, _, hodnoty = p.partition("=")
        if not hodnoty:
            raise SystemExit(f"Filtr '{p}' nemá tvar dim=hodnota")
        out[dim.strip()] = [h.strip() for h in hodnoty.split("|")]
    return out


def rozdel_filtry(
    sampler: PersonaForwardSampler, filtry: dict[str, list[str]]
) -> tuple[dict[str, str], dict[str, set[str]]]:
    """Vrátí (clampy, zbytkove_filtry) + validuje dimenze a hodnoty."""
    cpt_cile = {c.get("target") for c in sampler.graph.get("full_cpts", [])}
    clampy: dict[str, str] = {}
    zbytek: dict[str, set[str]] = {}
    for dim, hodnoty in filtry.items():
        if dim not in sampler.nodes:
            raise SystemExit(f"Neznámá dimenze: {dim}")
        chybne = [h for h in hodnoty if h not in sampler.vtoi[dim]]
        if chybne:
            raise SystemExit(f"{dim}: neznámé hodnoty {chybne}; "
                             f"platné: {sampler.values[dim]}")
        je_koren = not sampler.in_edges.get(dim) and dim not in cpt_cile
        if len(hodnoty) == 1 and je_koren:
            clampy[dim] = hodnoty[0]
        else:
            zbytek[dim] = set(hodnoty)
    return clampy, zbytek


def generuj_filtrovanou(
    graph_path: Path, n: int, seed: int, clampy: dict[str, str],
    zbytek: dict[str, set[str]], out_file: Path, compress: bool,
) -> dict:
    sampler = PersonaForwardSampler(graph_path, SamplingConfig(seed=seed))
    if clampy and not sampler.assignment_supported(clampy):
        raise SystemExit(f"Kombinace clampů {clampy} je maskami vyloučená (nulová buňka)")

    # gzip s mtime=0 — jinak časové razítko v hlavičce rozbije determinismus
    def _gz(p: Path):
        import io
        raw = p.open("wb")
        gz = gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0)
        return io.TextIOWrapper(gz, encoding="utf-8")

    otevrit = _gz if compress else (lambda p: p.open("w", encoding="utf-8"))
    prijato = odmitnuto = davek = 0
    with otevrit(out_file) as f:
        while prijato < n and davek < MAX_DAVEK:
            davek += 1
            zbyva = n - prijato
            akceptace = prijato / max(prijato + odmitnuto, 1) if (prijato + odmitnuto) else 1.0
            batch = min(max(int(zbyva / max(akceptace, 0.01)) + 1000, 5000), 200_000)
            idx = sampler.sample_indices(batch, fixed=clampy or None)
            for i in range(batch):
                row = sampler.decode_row(idx, i)
                if all(row.get(d) in povolene for d, povolene in zbytek.items()):
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    prijato += 1
                    if prijato >= n:
                        break
                else:
                    odmitnuto += 1
            if (prijato + odmitnuto) > 50_000 and prijato / (prijato + odmitnuto) < MIN_AKCEPTACE:
                raise SystemExit(
                    f"Akceptační poměr {prijato/(prijato+odmitnuto):.2e} je pod limitem — "
                    "filtr je příliš restriktivní pro rejection sampling")
    return {"prijato": prijato, "odmitnuto": odmitnuto, "davek": davek,
            "akceptacni_pomer": round(prijato / max(prijato + odmitnuto, 1), 6)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, required=True, help="Adresář kohorty")
    ap.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    ap.add_argument("--filtr", action="append", help='např. "region=Hlavní město Praha"')
    ap.add_argument("--stratifikovat", help="dimenze pro rovnoměrné strata")
    ap.add_argument("--format", choices=["jsonl", "jsonl.gz", "codes"], default="jsonl.gz")
    ap.add_argument("--workers", type=int, default=4, help="jen pro nefiltrovaný codes běh")
    ap.add_argument("--vstup-4d", type=Path, help="JSON z cz.vstup — propíše se do manifestu (F6)")
    args = ap.parse_args()

    t0 = time.time()
    args.out.mkdir(parents=True, exist_ok=True)
    graf = json.loads(args.graph.read_text())
    cz_meta = graf.get("metadata", {}).get("cz", {})
    filtry = parse_filtry(args.filtr)

    sampler = PersonaForwardSampler(args.graph, SamplingConfig(seed=args.seed))
    clampy, zbytek = rozdel_filtry(sampler, filtry)

    strata: list[tuple[str, dict, dict]] = []  # (label, clampy, zbytek)
    if args.stratifikovat:
        sdim = args.stratifikovat
        if sdim not in sampler.nodes:
            raise SystemExit(f"Neznámá stratifikační dimenze: {sdim}")
        # strata jen v průniku s případným filtrem na téže dimenzi — jinak by
        # vznikla nesplnitelná kombinace (např. filtr věk 18-34 × stratum Under 5)
        povolene = set(filtry.get(sdim, sampler.values[sdim]))
        for hodnota in sampler.values[sdim]:
            if hodnota not in povolene:
                continue
            sc = {k: v for k, v in clampy.items() if k != sdim}
            sz = {k: set(v) for k, v in zbytek.items() if k != sdim}
            sf = rozdel_filtry(sampler, {sdim: [hodnota]})
            sc.update(sf[0]); sz.update(sf[1])
            strata.append((f"{sdim}={hodnota}", sc, sz))
    else:
        strata.append(("vse", clampy, zbytek))

    vysledky = []
    soubory = []
    if not filtry and not args.stratifikovat and args.format == "codes":
        out_file = args.out / "kohorta.codes"
        meta = sample_to_file_parallel(
            args.graph, n=args.n, out=out_file, fmt="codes",
            seed=args.seed, workers=args.workers)
        vysledky.append({"stratum": "vse", "prijato": args.n, "delegovano": "sample_to_file_parallel",
                         "workers": args.workers})
        soubory.append(out_file)
        schema_file = out_file.with_suffix(out_file.suffix + ".schema.json")
        if schema_file.exists():
            # codes_path normalizovat na basename — kvůli přenositelnosti
            # adresáře kohorty i determinismu hashů napříč výstupními cestami
            sch = json.loads(schema_file.read_text())
            if "codes_path" in sch:
                sch["codes_path"] = out_file.name
                schema_file.write_text(json.dumps(sch, ensure_ascii=False, indent=1))
            soubory.append(schema_file)
    else:
        n_na_stratum = args.n // len(strata)
        pripona = ".jsonl.gz" if args.format in ("jsonl.gz", "codes") else ".jsonl"
        for i, (label, sc, sz) in enumerate(strata):
            bezpecny = label.replace("=", "_").replace(" ", "-").replace("/", "-")
            out_file = args.out / f"kohorta_{bezpecny}{pripona}"
            seed_s = args.seed if len(strata) == 1 else args.seed * 1000 + i
            r = generuj_filtrovanou(args.graph, n_na_stratum, seed_s, sc, sz,
                                    out_file, compress=pripona.endswith(".gz"))
            r.update({"stratum": label, "seed": seed_s, "file": out_file.name})
            vysledky.append(r)
            soubory.append(out_file)
            print(f"  {label}: {r['prijato']} person (akceptace {r['akceptacni_pomer']:.1%})")

    manifest = {
        "pozadavek": {
            "n": args.n, "seed": args.seed,
            "filtry": {k: v for k, v in filtry.items()},
            "stratifikace": args.stratifikovat, "format": args.format,
        },
        "graf": {
            "soubor": str(args.graph), "sha256": file_sha256(args.graph),
            "cz_verze": cz_meta.get("version"),
            "snapshot_id": cz_meta.get("snapshot_id"),
            "postaveno": cz_meta.get("built_at"),
        },
        "vysledek": {
            "n_vygenerovano": sum(r.get("prijato", 0) for r in vysledky),
            "strata": vysledky,
            "soubory": {f.name: file_sha256(f) for f in soubory},
            "trvani_s": round(time.time() - t0, 1),
        },
        "vytvoreno": datetime.now(timezone.utc).isoformat(),
        "vstupni_4d": (json.loads(args.vstup_4d.read_text()) if args.vstup_4d else None),
    }
    (args.out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nKohorta: {manifest['vysledek']['n_vygenerovano']:,} person "
          f"za {manifest['vysledek']['trvani_s']} s → {args.out}/")
    print(f"snapshot pin: {manifest['graf']['snapshot_id']} | graf sha256: "
          f"{manifest['graf']['sha256'][:16]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
