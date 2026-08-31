"""Eurostat dissemination API client (D2) — JSON-stat 2.0, bez autentizace."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import requests

BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
TIMEOUT = 300


class EurostatApiError(RuntimeError):
    pass


def fetch_jsonstat(dataset: str, **filters: Any) -> Dict[str, Any]:
    """Stáhne dataset jako JSON-stat 2.0.

    Filtry jsou URL parametry Eurostat API, např.:
      fetch_jsonstat("demo_r_pjangrp3", geo="CZ010", time="2024")
    Opakované hodnoty lze předat listem: geo=["CZ01", "CZ02"].
    """
    params: Dict[str, Any] = {"format": "JSON", "lang": "EN"}
    params.update(filters)
    r = requests.get(f"{BASE}/{dataset}", params=params, timeout=TIMEOUT)
    if r.status_code != 200:
        raise EurostatApiError(f"GET {dataset} -> HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    if "error" in data and data["error"]:
        raise EurostatApiError(f"{dataset}: {json.dumps(data['error'])[:300]}")
    return data


def jsonstat_rows(data: Dict[str, Any]):
    """Rozbalí JSON-stat 2.0 do long-format řádků (dict dimenze->kód + value)."""
    dims = data["id"]
    sizes = data["size"]
    cats = []
    for d in dims:
        idx = data["dimension"][d]["category"]["index"]
        if isinstance(idx, dict):
            ordered = sorted(idx, key=idx.get)
        else:
            ordered = list(idx)
        cats.append(ordered)
    values = data["value"]
    n = 1
    for s in sizes:
        n *= s
    for flat, val in (values.items() if isinstance(values, dict) else enumerate(values)):
        flat = int(flat)
        row = {}
        rem = flat
        for d, size, cat in zip(reversed(dims), reversed(sizes), reversed(cats)):
            rem, i = divmod(rem, size)
            row[d] = cat[i]
        row["value"] = val
        yield row
