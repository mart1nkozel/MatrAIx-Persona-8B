"""ESS (European Social Survey) konektor (D3).

API: https://api.ess.sikt.no/docs — endpoint
GET /v1/data/dataFile/{doiPrefix}/{doiSuffix}?userId=...&fileFormat=parquet

Ověřeno (2026-08-31): endpoint NEVYŽADUJE autentizaci ani session cookie —
`userId` je povinný jen pro statistiku užití (tlačítko v UI jde přes SSO,
API ne). Odpověď je 307 redirect na časově podepsaný Azure blob.

`recodeMissingValues=true` překóduje "Not applicable"/"No answer"/"Refusal"
na chybějící hodnoty (NaN v parquetu) — přesně to chceme pro agregace.

userId se čte z env ESS_USER_ID nebo z cz/data/ess_user.json (gitignored —
je to osobní identifikátor uživatele, nepatří do public repa).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import requests

BASE = "https://api.ess.sikt.no/v1"
TIMEOUT = 600
USER_FILE = Path(__file__).resolve().parent / "ess_user.json"


class EssApiError(RuntimeError):
    pass


def user_id() -> str:
    uid = os.environ.get("ESS_USER_ID")
    if uid:
        return uid
    if USER_FILE.exists():
        return json.loads(USER_FILE.read_text())["userId"]
    raise EssApiError(
        "Chybí ESS userId: nastav env ESS_USER_ID, nebo ulož "
        f"{USER_FILE.name} s obsahem {{\"userId\": \"...\"}} "
        "(získání: https://ess.sikt.no/en/api po přihlášení)"
    )


def download_parquet(doi: str, recode_missing: bool = True) -> bytes:
    """Stáhne datafile podle DOI (např. '10.21338/ess10e03_2') jako parquet."""
    prefix, suffix = doi.split("/", 1)
    params = {"userId": user_id(), "fileFormat": "parquet"}
    if recode_missing:
        params["recodeMissingValues"] = "true"
    r = requests.get(
        f"{BASE}/data/dataFile/{prefix}/{suffix}",
        params=params,
        timeout=TIMEOUT,
        allow_redirects=True,
    )
    if r.status_code != 200:
        raise EssApiError(f"ESS {doi} -> HTTP {r.status_code}: {r.text[:300]}")
    if not r.content.startswith(b"PAR1"):
        raise EssApiError(f"ESS {doi}: odpověď není parquet ({r.content[:60]!r})")
    return r.content


def download_country_subset(doi: str, cntry: str = "CZ") -> bytes:
    """Stáhne integrovaný soubor a vrátí parquet jen s řádky dané země."""
    import io

    import pandas as pd

    raw = download_parquet(doi)
    df = pd.read_parquet(io.BytesIO(raw))
    if "cntry" not in df.columns:
        raise EssApiError(f"ESS {doi}: soubor nemá sloupec cntry")
    sub = df[df["cntry"] == cntry]
    if sub.empty:
        raise EssApiError(f"ESS {doi}: země {cntry} v souboru není "
                          f"(dostupné: {sorted(df['cntry'].unique())})")
    buf = io.BytesIO()
    sub.to_parquet(buf, index=False)
    return buf.getvalue()
