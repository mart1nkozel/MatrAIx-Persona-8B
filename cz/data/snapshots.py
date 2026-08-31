"""Verzované snapshoty zdrojových dat (D5 cache + D6 verzování).

Snapshot = adresář cz/data/snapshots/<snapshot_id>/ s datovými soubory a
manifest.json. Snapshot ID se ukládá do manifestu kohorty (E2 pin), takže
stejný seed + stejný snapshot ⇒ identická kohorta i po pozdějším refreshi dat.

Cache pravidlo (D5): soubor se znovu nestahuje, pokud poslední snapshot má
stejný klíč zdroje (sada + verze sady + hash dotazu) — místo stažení se
přenese existující soubor a v manifestu se označí origin snapshotem.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

SNAPSHOTS_ROOT = Path(__file__).resolve().parent / "snapshots"


def query_hash(query: Any) -> str:
    return hashlib.sha256(json.dumps(query, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class SnapshotStore:
    root: Path = SNAPSHOTS_ROOT

    def latest_id(self) -> Optional[str]:
        if not self.root.exists():
            return None
        ids = sorted(p.name for p in self.root.iterdir() if (p / "manifest.json").exists())
        return ids[-1] if ids else None

    def manifest(self, snapshot_id: str) -> Dict[str, Any]:
        return json.loads((self.root / snapshot_id / "manifest.json").read_text())

    def new_snapshot(self) -> "SnapshotWriter":
        sid = "snap-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return SnapshotWriter(store=self, snapshot_id=sid, previous_id=self.latest_id())


@dataclass
class SnapshotWriter:
    store: SnapshotStore
    snapshot_id: str
    previous_id: Optional[str]

    def __post_init__(self) -> None:
        self.dir = self.store.root / self.snapshot_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.sources: Dict[str, Dict[str, Any]] = {}

    def cached(self, source_id: str, cache_key: str) -> Optional[Path]:
        """Najde soubor se stejným cache klíčem v libovolném starším snapshotu."""
        if not self.store.root.exists():
            return None
        for sid in sorted((p.name for p in self.store.root.iterdir()
                           if (p / "manifest.json").exists()), reverse=True):
            if sid == self.snapshot_id:
                continue
            entry = self.store.manifest(sid).get("sources", {}).get(source_id)
            if entry and entry.get("cache_key") == cache_key:
                f = self.store.root / sid / entry["file"]
                if f.exists():
                    self._cache_origin = sid
                    return f
        return None

    def add_file(
        self,
        source_id: str,
        filename: str,
        content: Optional[str] = None,
        copy_from: Optional[Path] = None,
        *,
        cache_key: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Path:
        target = self.dir / filename
        if copy_from is not None:
            shutil.copyfile(copy_from, target)
            origin = "cache"
        else:
            assert content is not None
            target.write_text(content, encoding="utf-8")
            origin = "download"
        entry = {
            "file": filename,
            "cache_key": cache_key,
            "origin": origin,
            "bytes": target.stat().st_size,
            "sha256": file_sha256(target),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        if origin == "cache":
            entry["cached_from_snapshot"] = getattr(self, "_cache_origin", self.previous_id)
        entry.update(meta or {})
        self.sources[source_id] = entry
        return target

    def finalize(self, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        manifest = {
            "snapshot_id": self.snapshot_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "previous_snapshot": self.previous_id,
            "sources": self.sources,
        }
        manifest.update(extra or {})
        (self.dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return manifest
