"""Generátor číselníků a mapovacích tabulek (D7).

Územní číselníky (okresy, kraje) se stahují živě z DataStat API — jsou tedy
vždy v souladu s kódy, které vracejí datové exporty. Mapovací tabulky
ČSÚ → hodnotové sady schématu jsou definované zde v kódu (reviewovatelné
v diffu) a generují se do CSV.

Stav mapování: NÁVRH pro Fázi 2 — sloupec `stav` říká, zda je mapování
jednoznačné (ok), ztrátové (hrubší zdroj než schéma) nebo čeká na rozhodnutí.

  uv run python -m cz.codelists.build_codelists
"""

from __future__ import annotations

import csv
from pathlib import Path

from cz.data import csu

VYSTUP = Path(__file__).resolve().parent

# NUTS2 regiony soudržnosti — odvoditelné z prefixu NUTS3 kódu (CZ0xy -> CZ0x).
NUTS2_NAZVY = {
    "CZ01": "Praha",
    "CZ02": "Střední Čechy",
    "CZ03": "Jihozápad",
    "CZ04": "Severozápad",
    "CZ05": "Severovýchod",
    "CZ06": "Jihovýchod",
    "CZ07": "Střední Morava",
    "CZ08": "Moravskoslezsko",
}

# Vzdel5 (SLDB 2021, hrubé) -> ISCED 2011 -> highest_education schématu.
# Pozn.: kategorie 109 slučuje ISCED 6-8; rozpad Bachelor's/Master's/Doctorate
# umí až podrobná varianta Vzdel1 (15 položek) — rozhodnutí Fáze 2.
MAP_VZDELANI = [
    ("102", "Bez vzdělání, neúplné základní a základní", "ISCED 0-2", "Primary", "ztrátové: slučuje No formal + Primary"),
    ("105", "Střední vč. vyučení bez maturity", "ISCED 3C", "Vocational / cert", "ok"),
    ("132", "Úplné střední s maturitou, nástavbové", "ISCED 3A-4", "Secondary", "ok"),
    ("130", "Vyšší odborné, konzervatoř", "ISCED 5", "Associate's", "ok"),
    ("109", "Vysokoškolské", "ISCED 6-8", "Bachelor's", "ztrátové: slučuje Bc/Mgr/PhD — rozpad přes Vzdel1 ve Fázi 2"),
    ("900", "Nezjištěno", "", "", "null"),
]

# VelSkObciOP1 (velikostní skupina obce) -> urbanicity schématu.
# Prahové hodnoty jsou návrh (rozhodnutí Fáze 2/3); ČR nemá oficiální
# urbanicitu, ČSÚ velikostní skupiny jsou nejbližší CZ-official proxy.
MAP_URBANICITA = [
    ("98", "do 199 obyvatel", "Rural", "návrh"),
    ("99", "200 - 499 obyvatel", "Rural", "návrh"),
    ("2", "500 až 999 obyvatel", "Rural", "návrh"),
    ("3", "1000 až 1999 obyvatel", "Small town", "návrh"),
    ("4", "2000 až 4999 obyvatel", "Small town", "návrh"),
    ("5", "5000 až 9999 obyvatel", "Small town", "návrh"),
    ("6", "10000 až 19999 obyvatel", "Small town", "návrh"),
    ("7", "20000 až 49999 obyvatel", "Suburban", "návrh: CZ nemá suburb koncept, aproximace střední město"),
    ("8", "50000 až 99999 obyvatel", "Suburban", "návrh"),
    ("9", "100000 a více obyvatel", "Dense urban", "návrh"),
]

# EKONAKTIV2H (SLDB 2021) -> demo_employment_status schématu.
# Full-time/Part-time/Gig sčítání nerozlišuje — rozpad vyžaduje VŠPS (Fáze 2).
MAP_EKON_AKTIVITA = [
    ("1", "Zaměstnaní bez prac. důchodců/studentů/mateřské", "Full-time", "ztrátové: FT/PT/gig nerozlišeno, rozpad přes VŠPS"),
    ("2", "Pracující důchodci", "Retired", "návrh: pracující důchodce ~ Retired s aktivitou"),
    ("3", "Pracující žáci a studenti", "Student", "ok"),
    ("4", "Osoby na mateřské dovolené", "Homemaker", "návrh"),
    ("52", "Nezaměstnaní", "Unemployed", "ok"),
    ("6", "Nepracující důchodci", "Retired", "ok"),
    ("7", "Ostatní s vlastním zdrojem obživy", "Homemaker", "návrh"),
    ("8", "Žáci, studenti", "Student", "ok"),
    ("14", "Osoby na rodičovské dovolené", "Homemaker", "návrh"),
    ("13", "Osoby v domácnosti, předškolní děti, závislé osoby", "Homemaker", "ztrátové: zahrnuje děti"),
    ("99", "Nezjištěno", "", "null"),
]

# MatJaz2 (mateřský jazyk, SLDB 2021) -> cílová hodnotová sada primary_language
# CZ verze schématu (P7: čeština primární — hodnoty vzniknou ve Fázi 2).
MAP_JAZYK = [
    ("1", "Český", "Czech", "ok"),
    ("26", "Moravský", "Czech", "návrh: sloučit s češtinou"),
    ("2", "Slovenský", "Slovak", "ok"),
    ("9", "Polský", "Polish", "ok"),
    ("5", "Německý", "German", "ok"),
    ("25", "Romský", "Romani", "ok"),
    ("6", "Ruský", "Russian", "ok"),
    ("10", "Ukrajinský", "Ukrainian", "ok"),
    ("11", "Vietnamský", "Vietnamese", "ok"),
    ("13", "Maďarský", "Hungarian", "ok"),
    ("3", "Anglický", "English", "ok"),
    ("99", "Nezjištěno", "", "null"),
]


def zapis(nazev: str, hlavicka: list[str], radky: list) -> None:
    path = VYSTUP / nazev
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(hlavicka)
        w.writerows(radky)
    print(f"  {nazev}: {len(radky)} řádků")


def main() -> None:
    print("Územní číselníky z DataStat API:")
    okresy = [p for p in csu.dimenze_polozky("UZ023H2U") if p.get("kodUrovne") == "OKRES"]
    zapis(
        "okresy.csv",
        ["lau1_kod", "nazev", "kraj_nuts3", "nuts2"],
        [(p["kod"], p["nazev"], p["kod"][:5], p["kod"][:4]) for p in sorted(okresy, key=lambda x: x["kod"])],
    )
    kraje = [p for p in csu.dimenze_polozky("Uz2")]
    zapis(
        "kraje.csv",
        ["nuts3_kod", "nazev", "nuts2_kod", "nuts2_nazev"],
        [(p["kod"], p["nazev"], p["kod"][:4], NUTS2_NAZVY.get(p["kod"][:4], "")) for p in sorted(kraje, key=lambda x: x["kod"])],
    )

    print("Mapovací tabulky ČSÚ → schéma (návrh pro Fázi 2):")
    zapis("map_vzdelani.csv", ["csu_kod", "csu_nazev", "isced", "schema_highest_education", "stav"], MAP_VZDELANI)
    zapis("map_urbanicita.csv", ["csu_kod", "csu_nazev", "schema_urbanicity", "stav"], MAP_URBANICITA)
    zapis("map_ekonomicka_aktivita.csv", ["csu_kod", "csu_nazev", "schema_demo_employment_status", "stav"], MAP_EKON_AKTIVITA)
    zapis("map_jazyk.csv", ["csu_kod", "csu_nazev", "cz_primary_language", "stav"], MAP_JAZYK)


if __name__ == "__main__":
    main()
