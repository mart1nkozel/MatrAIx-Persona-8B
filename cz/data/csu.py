"""ČSÚ DataStat API client (D1).

Rozhodnutí D1: primární cesta je DataStat REST API (data.csu.gov.cz/api),
ne opendata katalog — API umí filtrovaný výběr (poslední rok, úroveň okresů)
v jednom requestu a vrací číselníkové kódy (NUTS/LAU) přímo v CSV.

Klíčové poznatky o API (ověřeno proti živému provozu, srpen 2026):
- katalog:  GET  /api/katalog/v1/sady, /sady/{kod}, /dimenze/{kod}/polozky
- data:     POST /api/dotaz/v1/data/sady/{kod}/vlastni?format=CSV&rozsah=CELY_VYBER
- Pseudo-dimenze ukazatelů se v těle jmenuje "IndicatorType" (dokumentace
  uvádí "#UKAZATEL", to ale deployované API nezná).
- Časový filtr přes casovaDimenze/POSLEDNICH_N server odmítá; funguje explicitní
  výčet položek v filtr.zobrazitPolozky (kódy z /dimenze/{kod}/polozky).
- Export celé sady bez filtru na velkých sadách selže (sync limit) — proto
  se vždy filtruje čas a vybírá jedna územní varianta.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

BASE_KATALOG = "https://data.csu.gov.cz/api/katalog/v1"
BASE_DOTAZ = "https://data.csu.gov.cz/api/dotaz/v1"
TIMEOUT = 300

# Preferenční pořadí čistých územních variant podle požadované úrovně.
UZEMNI_UROVNE = ["OKRES", "KRAJ", "REGION", "STAT"]


class CsuApiError(RuntimeError):
    def __init__(self, msg: str, payload: Any = None):
        super().__init__(msg)
        self.payload = payload


@dataclass
class SadaDetail:
    kod: str
    verze: str
    nazev: str
    dimenze: List[Dict[str, Any]] = field(default_factory=list)
    ukazatele: List[Dict[str, Any]] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    def dim_by_typ(self, typ: str) -> List[Dict[str, Any]]:
        return [d for d in self.dimenze if d.get("typDimenzeKod") == typ]

    def uzemni_varianta(self, uroven: str) -> Optional[Dict[str, Any]]:
        """Nejmenší (nejčistší) VUZEMI varianta obsahující požadovanou úroveň."""
        kandidati = [
            d for d in self.dim_by_typ("VUZEMI")
            if any(u["kodUrovne"] == uroven for u in d.get("urovneDimenze", []))
        ]
        if not kandidati:
            return None
        return min(kandidati, key=lambda d: sum(u["pocetPolozek"] for u in d["urovneDimenze"]))


def _get(url: str, **params: Any) -> Any:
    r = requests.get(url, params=params or None, timeout=TIMEOUT)
    if r.status_code != 200:
        raise CsuApiError(f"GET {url} -> HTTP {r.status_code}", r.text[:500])
    return r.json()


def katalog_sady() -> List[Dict[str, Any]]:
    return _get(f"{BASE_KATALOG}/sady")


def katalog_sada(kod: str) -> SadaDetail:
    raw = _get(f"{BASE_KATALOG}/sady/{kod}")
    return SadaDetail(
        kod=raw["kod"],
        verze=raw.get("verze", ""),
        nazev=raw.get("nazev", ""),
        dimenze=raw.get("variantyDimenze", []),
        ukazatele=raw.get("ukazatele", []),
        raw=raw,
    )


def dimenze_polozky(kod_dimenze: str) -> List[Dict[str, Any]]:
    return _get(f"{BASE_KATALOG}/dimenze/{kod_dimenze}/polozky")


def build_query(
    detail: SadaDetail,
    uzemni_uroven: str = "OKRES",
    uzemni_varianta: Optional[str] = None,
    ukazatele: Optional[List[str]] = None,
    posledni_obdobi: int = 1,
    casovy_posun: int = 0,
    pouzit_dimenze: Optional[List[str]] = None,
    vynechat_dimenze: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Sestaví tělo POST /vlastni: vše do řádků, čas a ukazatele do filtru.

    CSV výstup je long-format (každý řádek plně popsaný), rozložení do
    řádků/sloupců tedy nehraje roli pro parsování — jen pro limit velikosti.

    `pouzit_dimenze`: explicitní výběr věcných dimenzí. Nutné u sad, které
    nabízejí víc variant téže dimenze (např. vzdělání podrobně/hrubě) —
    automatické přidání všech by vedlo ke konfliktu variant.
    """
    vynechat = set(vynechat_dimenze or [])
    radky: List[Dict[str, Any]] = []
    filtry: List[Dict[str, Any]] = []

    uz = None
    if uzemni_varianta is not None:
        # Explicitní volba — např. hierarchická varianta kvůli Praze, která je
        # v číselnících kraj (CZ010), zatímco čistá okresní varianta má jen 76
        # okresů bez Prahy.
        uz = next((d for d in detail.dim_by_typ("VUZEMI") if d["kod"] == uzemni_varianta), None)
        if uz is None:
            raise CsuApiError(f"Sada {detail.kod} nemá územní variantu {uzemni_varianta}")
    else:
        for uroven in UZEMNI_UROVNE[UZEMNI_UROVNE.index(uzemni_uroven):]:
            uz = detail.uzemni_varianta(uroven)
            if uz is not None:
                break
    if uz is None:
        raise CsuApiError(f"Sada {detail.kod} nemá žádnou územní variantu")
    radky.append({"kodDimenze": uz["kod"], "popis": "kodNazev"})

    cas_dim = detail.dim_by_typ("REF_CAS")
    if not cas_dim:
        raise CsuApiError(f"Sada {detail.kod} nemá časovou dimenzi")
    cas = cas_dim[0]
    polozky = dimenze_polozky(cas["kod"])
    polozky.sort(key=lambda p: p.get("poradi", 0))
    # Číselníky času obsahují i budoucí období (projekce) — ta bez dat vynecháme.
    ted = datetime.now(timezone.utc).isoformat()
    minule = [p for p in polozky if str(p.get("casOd", "")) <= ted]
    rada = minule or polozky
    konec = len(rada) - casovy_posun
    posledni = [p["kod"] for p in rada[max(0, konec - posledni_obdobi):konec]]
    if not posledni:
        raise CsuApiError(f"Sada {detail.kod}: časový posun {casovy_posun} mimo rozsah dat")
    filtry.append({
        "kodDimenze": cas["kod"],
        "filtr": [{"zobrazitPolozky": posledni}],
        "filtrTabulkyKod": posledni[-1],
    })

    if ukazatele:
        filtry.append({
            "kodDimenze": "IndicatorType",
            "filtr": [{"zobrazitPolozky": list(ukazatele)}],
            "filtrTabulkyKod": ukazatele[0],
        })

    if pouzit_dimenze is not None:
        for kod in pouzit_dimenze:
            radky.append({"kodDimenze": kod, "popis": "kodNazev"})
    else:
        pouzite = {uz["kod"], cas["kod"]}
        for d in detail.dimenze:
            if d["kod"] in pouzite or d.get("typDimenzeKod") in ("VUZEMI", "REF_CAS"):
                continue
            if d["kod"] in vynechat:
                continue
            radky.append({"kodDimenze": d["kod"], "popis": "kodNazev"})

    return {"radky": radky, "sloupce": [], "filtryTabulky": filtry}


def fetch_csv(kod_sady: str, query: Dict[str, Any], verze: Optional[str] = None) -> str:
    params = {"format": "CSV", "rozsah": "CELY_VYBER", "kodCiselniku": "true"}
    if verze:
        params["verzeSady"] = verze
    r = requests.post(
        f"{BASE_DOTAZ}/data/sady/{kod_sady}/vlastni",
        params=params,
        json=query,
        timeout=TIMEOUT,
    )
    if r.status_code != 200:
        raise CsuApiError(
            f"POST vlastni {kod_sady} -> HTTP {r.status_code}",
            {"response": r.text[:500], "query": query},
        )
    return r.text


def fetch_csv_s_posunem(
    detail: SadaDetail,
    query_args: Dict[str, Any],
    max_posun: int = 6,
) -> tuple[Dict[str, Any], str]:
    """Stažení s automatickým posunem časového okna dozadu.

    API vrací HTTP 400 "No dimensions for filter", pokud vyfiltrované období
    v sadě (zatím) nemá data — např. registr nezaměstnanosti končí rokem 2024,
    ale číselník let sahá do 2040. Při této chybě se okno posune o období zpět.
    """
    posledni_chyba: Optional[CsuApiError] = None
    for posun in range(max_posun):
        query = build_query(detail, casovy_posun=posun, **query_args)
        try:
            return query, fetch_csv(detail.kod, query, verze=detail.verze)
        except CsuApiError as e:
            text = str(e.payload) if e.payload else str(e)
            if "No dimensions for filter" not in text:
                raise
            posledni_chyba = e
    raise posledni_chyba  # type: ignore[misc]


def probe(kod_sady: str) -> str:
    """Lidsky čitelný přehled dimenzí a ukazatelů sady (pomůcka pro sources.yaml)."""
    d = katalog_sada(kod_sady)
    lines = [f"{d.kod} v{d.verze}: {d.nazev}"]
    lines.append("  ukazatele:")
    for u in d.ukazatele:
        lines.append(f"    {u['kod']}: {u['nazev']}")
    lines.append("  dimenze:")
    for dim in d.dimenze:
        urovne = ", ".join(f"{u['kodUrovne']}({u['pocetPolozek']})" for u in dim.get("urovneDimenze", []))
        lines.append(f"    {dim['kod']} [{dim.get('typDimenzeKod')}]: {dim.get('nazev')} — {urovne}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        print(probe(sys.argv[1]))
    else:
        print(json.dumps([s["kod"] for s in katalog_sady()][:50], indent=2))
