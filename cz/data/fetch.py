"""CLI: stáhne registrované zdroje do nového verzovaného snapshotu.

  uv run python -m cz.data.fetch            # vše ze sources.yaml
  uv run python -m cz.data.fetch --only oby02b_vek_pohlavi_okres
  uv run python -m cz.data.fetch --dry-run  # jen vypíše, co by se stáhlo
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from cz.data import csu, ess, eurostat, gesis
from cz.data.snapshots import SnapshotStore, query_hash

SOURCES_PATH = Path(__file__).resolve().parent / "sources.yaml"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", action="append", help="Stáhnout jen vyjmenované zdroje")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    registry = yaml.safe_load(SOURCES_PATH.read_text(encoding="utf-8"))
    store = SnapshotStore()
    writer = None if args.dry_run else store.new_snapshot()
    chyby = {}

    def chci(source_id: str) -> bool:
        return not args.only or source_id in args.only

    for source_id, src in (registry.get("csu") or {}).items():
        if not chci(source_id):
            continue
        detail = csu.katalog_sada(src["sada"])
        query_args = src.get("query") or {}
        # Klíč cache: stabilní vůči časovému posunu (hash argumentů, ne
        # sestaveného dotazu) + invalidace při změně definice sady. Detekci
        # změny samotných DAT (bez změny definice) doplní až D8 refresh.
        zmena = detail.raw.get("casZmenyDefinice", "")
        cache_key = f"{detail.kod}:v{detail.verze}:{zmena}:{query_hash(query_args)}"
        print(f"[csu] {source_id}: {detail.kod} v{detail.verze}", end=" ")
        if args.dry_run:
            print(f"(dry-run, cache_key={cache_key})")
            continue
        meta = {
            "zdroj": "csu-datastat", "sada": detail.kod, "verze_sady": detail.verze,
            "nazev": detail.nazev, "provenience": src.get("provenience"),
            "cilove_dimenze": src.get("cilove_dimenze"),
        }
        cached = writer.cached(source_id, cache_key)
        if cached is not None:
            writer.add_file(source_id, f"{source_id}.csv", copy_from=cached, cache_key=cache_key, meta=meta)
            print("→ cache")
            continue
        try:
            skutecny_dotaz, text = csu.fetch_csv_s_posunem(detail, query_args)
        except csu.CsuApiError as e:
            chyby[source_id] = str(e)
            print(f"→ CHYBA: {e}")
            continue
        meta["query"] = skutecny_dotaz
        writer.add_file(source_id, f"{source_id}.csv", content=text, cache_key=cache_key, meta=meta)
        print(f"→ staženo ({len(text)} B, {text.count(chr(10))} řádků)")

    for source_id, src in (registry.get("eurostat") or {}).items():
        if not chci(source_id):
            continue
        filters = dict(src.get("filters") or {})
        cache_key = f"eurostat:{src['dataset']}:{query_hash(filters)}"
        print(f"[eurostat] {source_id}: {src['dataset']}", end=" ")
        if args.dry_run:
            print(f"(dry-run, cache_key={cache_key})")
            continue
        meta = {
            "zdroj": "eurostat", "dataset": src["dataset"], "popis": src.get("popis"),
            "provenience": src.get("provenience"), "cilove_dimenze": src.get("cilove_dimenze"),
            "filters": filters,
        }
        cached = writer.cached(source_id, cache_key)
        if cached is not None:
            writer.add_file(source_id, f"{source_id}.json", copy_from=cached, cache_key=cache_key, meta=meta)
            print("→ cache")
            continue
        try:
            data = eurostat.fetch_jsonstat(src["dataset"], **filters)
        except eurostat.EurostatApiError as e:
            chyby[source_id] = str(e)
            print(f"→ CHYBA: {e}")
            continue
        writer.add_file(
            source_id, f"{source_id}.json",
            content=json.dumps(data, ensure_ascii=False), cache_key=cache_key, meta=meta,
        )
        print(f"→ staženo ({len(data.get('value', {}))} hodnot)")


    for source_id, src in (registry.get("ess") or {}).items():
        if not chci(source_id):
            continue
        cache_key = f"ess:{src['doi']}:{src.get('cntry','ALL')}"
        print(f"[ess] {source_id}: {src['doi']}", end=" ")
        if args.dry_run:
            print(f"(dry-run, cache_key={cache_key})")
            continue
        meta = {"zdroj": "ess-sikt", "doi": src["doi"], "popis": src.get("popis"),
                "provenience": src.get("provenience"), "cntry": src.get("cntry"),
                "pozn": src.get("pozn")}
        cached = writer.cached(source_id, cache_key)
        if cached is not None:
            import shutil as _sh
            cil = writer.dir / f"{source_id}.parquet"
            _sh.copyfile(cached, cil)
            writer.sources[source_id] = {**meta, "file": f"{source_id}.parquet",
                                         "cache_key": cache_key, "origin": "cache",
                                         "bytes": cil.stat().st_size}
            print("→ cache")
            continue
        try:
            data = ess.download_country_subset(src["doi"], src.get("cntry", "CZ"))
        except ess.EssApiError as e:
            chyby[source_id] = str(e)
            print(f"→ CHYBA: {e}")
            continue
        cil = writer.dir / f"{source_id}.parquet"
        cil.write_bytes(data)
        from cz.data.snapshots import file_sha256
        writer.sources[source_id] = {**meta, "file": f"{source_id}.parquet",
                                     "cache_key": cache_key, "origin": "download",
                                     "bytes": len(data), "sha256": file_sha256(cil)}
        print(f"→ staženo ({len(data)} B)")


    for source_id, src in (registry.get("gesis") or {}).items():
        if not chci(source_id):
            continue
        try:
            znacka = gesis.zdrojova_znacka(src["soubor"])
        except (OSError, gesis.GesisError) as e:
            chyby[source_id] = str(e)
            print(f"[gesis] {source_id}: CHYBA {e}")
            continue
        cache_key = f"gesis:{src['soubor']}:{znacka}:{','.join(src['promenne'])}"
        print(f"[gesis] {source_id}: {src['soubor']}", end=" ")
        if args.dry_run:
            print(f"(dry-run, cache_key={cache_key})")
            continue
        meta = {"zdroj": "gesis-local", "soubor": src["soubor"], "popis": src.get("popis"),
                "provenience": src.get("provenience"), "cilove_dimenze": src.get("cilove_dimenze")}
        cached = writer.cached(source_id, cache_key)
        if cached is not None:
            import shutil as _sh
            cil = writer.dir / f"{source_id}.parquet"
            _sh.copyfile(cached, cil)
            writer.sources[source_id] = {**meta, "file": f"{source_id}.parquet",
                                         "cache_key": cache_key, "origin": "cache",
                                         "bytes": cil.stat().st_size}
            print("→ cache")
            continue
        try:
            data = gesis.extract_cz(src["soubor"], src["promenne"],
                                    src.get("zeme_var", "isocntry"), src.get("zeme", "CZ"))
        except gesis.GesisError as e:
            chyby[source_id] = str(e)
            print(f"→ CHYBA: {e}")
            continue
        cil = writer.dir / f"{source_id}.parquet"
        cil.write_bytes(data)
        from cz.data.snapshots import file_sha256 as _sha
        writer.sources[source_id] = {**meta, "file": f"{source_id}.parquet",
                                     "cache_key": cache_key, "origin": "download",
                                     "bytes": len(data), "sha256": _sha(cil)}
        print(f"→ extrahováno ({len(data)} B)")

    if args.dry_run:
        return 0

    extra = {}
    if chyby:
        extra["errors"] = chyby
    if args.only:
        # Částečný snapshot (vývojový) — nepoužívat jako pin kohorty.
        extra["partial"] = list(args.only)
        print("VAROVÁNÍ: --only vytváří částečný snapshot, nepoužívat pro pin kohorty.")
    manifest = writer.finalize(extra=extra or None)
    print(f"\nSnapshot: {manifest['snapshot_id']} ({len(manifest['sources'])} zdrojů"
          + (f", {len(chyby)} chyb" if chyby else "") + ")")
    return 1 if chyby else 0


if __name__ == "__main__":
    sys.exit(main())
