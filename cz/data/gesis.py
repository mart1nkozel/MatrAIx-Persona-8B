"""GESIS konektor (D4) — lokální soubory stažené uživatelem.

GESIS nemá volné API (studie vyžadují přihlášení a souhlas s podmínkami),
uživatel proto stahuje .dta/.sav ručně; výchozí umístění ~/Desktop/gesis_studie.
Konektor čte vybrané proměnné, filtruje zemi (isocntry=='CZ' u Eurobarometrů)
a do snapshotu ukládá jen CZ výřez jako parquet — 1,7 GB zdrojů zůstává mimo
projekt i snapshoty.

Licence GESIS/Eurobarometer: akademické/nekomerční užití dle podmínek
jednotlivých studií (uživatel je odsouhlasil při stažení).
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pandas as pd

VYCHOZI_SLOZKA = Path.home() / "Desktop" / "gesis_studie"


class GesisError(RuntimeError):
    pass


def slozka() -> Path:
    return Path(os.environ.get("GESIS_DIR", VYCHOZI_SLOZKA))


def extract_cz(
    soubor: str,
    promenne: list[str],
    zeme_var: str = "isocntry",
    zeme: str = "CZ",
) -> bytes:
    """Vrátí parquet s CZ řádky a vybranými proměnnými (+ vahami/zemí)."""
    cesta = slozka() / soubor
    if not cesta.exists():
        raise GesisError(f"Soubor {cesta} neexistuje — zkontroluj GESIS_DIR")
    cols = list(dict.fromkeys(promenne + [zeme_var]))
    df = pd.read_stata(cesta, columns=cols, convert_categoricals=False)
    sub = df[df[zeme_var].astype(str).str.strip() == zeme]
    if sub.empty:
        raise GesisError(f"{soubor}: {zeme_var}=={zeme} nemá žádné řádky "
                         f"(hodnoty: {sorted(df[zeme_var].astype(str).unique())[:10]})")
    buf = io.BytesIO()
    sub.to_parquet(buf, index=False)
    return buf.getvalue()


def zdrojova_znacka(soubor: str) -> str:
    """Cache klíč lokálního souboru: velikost + mtime (sha 30MB souborů je drahé)."""
    st = (slozka() / soubor).stat()
    return f"{st.st_size}:{int(st.st_mtime)}"
