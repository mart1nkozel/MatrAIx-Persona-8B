"""Výpočet CZ priorů demografického jádra ze snapshotu (Fáze 2, P1–P7).

Každá funkce vrací (prior: dict hodnota->pravděpodobnost, provenance: dict).
Prior je normalizovaný; kategorie "Nezjištěno" se rozpouští proporcionálně
(dokumentovaná volba — alternativa null by u priorů jádra znamenala persony
bez věku/vzdělání).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, Iterable, Tuple

CZ_ROOT = Path(__file__).resolve().parents[1]

Prior = Dict[str, float]
Prov = Dict[str, object]


def _norm(d: Prior) -> Prior:
    s = sum(d.values())
    if s <= 0:
        raise ValueError("prior má nulový součet")
    return {k: v / s for k, v in d.items()}


def _rows(snapshot_dir: Path, name: str) -> list[dict]:
    with (snapshot_dir / f"{name}.csv").open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _plny_rok(rows: Iterable[dict]) -> str:
    """OBY02B: poslední rok, který má i jednotky věku (ne jen agregát)."""
    roky = sorted({r["Rok"] for r in rows})
    for rok in reversed(roky):
        if any(r["Rok"] == rok and r["VEK1C.Polozka"] != "0" for r in rows):
            return rok
    return roky[-1]


def okresy_codelist() -> list[dict]:
    with (CZ_ROOT / "codelists" / "okresy.csv").open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------- P2: region

def region_prior(snapshot_dir: Path) -> Tuple[Prior, Prov]:
    rows = _rows(snapshot_dir, "oby02b_vek_pohlavi_okres")
    rok = _plny_rok(rows)
    celk = [r for r in rows if r["Rok"] == rok and r["POHL2.Polozka"] == "0" and r["VEK1C.Polozka"] == "0"]
    podle_lau = {r["Uz0123h2.OKRES.Polozka"]: float(r["Hodnota"]) for r in celk if r["Uz0123h2.OKRES.Polozka"]}
    praha = [r for r in celk if r["Uz0123h2.KRAJ.Polozka"] == "CZ010" and not r["Uz0123h2.OKRES.Polozka"]]
    prior: Prior = {}
    for o in okresy_codelist():
        if o["lau1_kod"] == "CZ0100":
            prior[o["nazev"]] = float(praha[0]["Hodnota"])
        else:
            prior[o["nazev"]] = podle_lau[o["lau1_kod"]]
    return _norm(prior), {
        "zdroj": "csu:OBY02B", "rok": rok, "evidence": "raw_direct",
        "pozn": "77 okresů; Praha (CZ0100) doplněna z krajské úrovně — v číselníku okresů není",
    }


# ----------------------------------------------------------- P1: věk, pohlaví

VEK_BRACKETY = [
    ("Under 5", 0, 4), ("5-12", 5, 12), ("13-17", 13, 17), ("18-24", 18, 24),
    ("25-34", 25, 34), ("35-44", 35, 44), ("45-54", 45, 54), ("55-64", 55, 64),
    ("65-74", 65, 74), ("75-84", 75, 84), ("85+", 85, 200),
]


def age_prior(snapshot_dir: Path) -> Tuple[Prior, Prov]:
    rows = _rows(snapshot_dir, "oby02b_vek_pohlavi_okres")
    rok = _plny_rok(rows)
    cr = [r for r in rows if r["Rok"] == rok and r["POHL2.Polozka"] == "0"
          and r["Uz0123h2.STAT.Polozka"] and not r["Uz0123h2.REGION.Polozka"]
          and r["VEK1C.Polozka"] != "0"]
    prior = {b: 0.0 for b, _, _ in VEK_BRACKETY}
    for r in cr:
        try:
            vek = int(r["Věk (roky)"].split()[0])
        except ValueError:
            continue
        for b, lo, hi in VEK_BRACKETY:
            if lo <= vek <= hi:
                prior[b] += float(r["Hodnota"])
                break
    return _norm(prior), {"zdroj": "csu:OBY02B", "rok": rok, "evidence": "raw_direct"}


def gender_prior(snapshot_dir: Path, upstream: Prior) -> Tuple[Prior, Prov]:
    """ČSÚ muži/ženy; kategorie mimo binární sčítání neměří — ponechán
    původní (světový) podíl, M/Ž rozděleny ve zbylé mase podle ČSÚ."""
    rows = _rows(snapshot_dir, "oby02b_vek_pohlavi_okres")
    rok = _plny_rok(rows)
    cr = {r["POHL2.Polozka"]: float(r["Hodnota"]) for r in rows
          if r["Rok"] == rok and r["VEK1C.Polozka"] == "0"
          and r["Uz0123h2.STAT.Polozka"] and not r["Uz0123h2.REGION.Polozka"]}
    muzi, zeny = cr["1"], cr["2"]
    ostatni = {k: v for k, v in upstream.items() if k not in ("Man", "Woman")}
    zbytek = 1.0 - sum(ostatni.values())
    prior = dict(ostatni)
    prior["Man"] = zbytek * muzi / (muzi + zeny)
    prior["Woman"] = zbytek * zeny / (muzi + zeny)
    return _norm(prior), {
        "zdroj": "csu:OBY02B", "rok": rok, "evidence": "raw_direct",
        "pozn": "nebinární kategorie ponechány ze světového prioru (ČSÚ je neměří)",
    }


# ------------------------------------------------------------- P4: vzdělání

MAP_VZDEL1 = {
    "001": "No formal",
    "002": "Primary",
    "003": "Primary",
    "105": "Vocational / cert",
    "008": "Secondary",
    "121": "Secondary",
    "202": "Some college",
    "203": "Some college",
    "015": "Associate's",
    "011": "Associate's",
    "012": "Bachelor's",
    "013": "Master's",
    "014": "Doctorate",
}


def education_prior(snapshot_dir: Path, hodnoty: list[str]) -> Tuple[Prior, Prov]:
    rows = _rows(snapshot_dir, "sld21a002_vzdelani_detail_kraj")
    cr = [r for r in rows if r["POHL3.Polozka"] == "0" and r["Uz02.Polozka"] == "CZ"]
    prior = {h: 0.0 for h in hodnoty}
    for r in cr:
        cil = MAP_VZDEL1.get(r["Vzdel1.Polozka"])
        if cil:
            prior[cil] += float(r["Hodnota"])
    return _norm(prior), {
        "zdroj": "csu:SLD21A002/Vzdel1 (SLDB 2021, 15+)", "evidence": "raw_direct",
        "pozn": "Nezjištěno rozpuštěno proporcionálně; Postdoc=0 (ČSÚ neeviduje); "
                "populace 15+ — děti řeší kompatibilní masky věk×vzdělání",
    }


# ------------------------------------------------------------ P3: urbanicita

MAP_VELSK = {
    "98": "Rural", "99": "Rural", "2": "Rural",
    "3": "Small town", "4": "Small town", "5": "Small town", "6": "Small town",
    "7": "Suburban", "8": "Suburban",
    "9": "Dense urban",
}


def urbanicity_prior(snapshot_dir: Path, hodnoty: list[str]) -> Tuple[Prior, Prov]:
    rows = _rows(snapshot_dir, "sld21a002_vzdelani_vek_urbanicita_kraj")
    cr = [r for r in rows if r["POHL3.Polozka"] == "0" and r["Vzdel5.Polozka"] == "0"
          and r["VEKSK5A.Polozka"] == "0" and r["Uz02.Polozka"] == "CZ"
          and r["VelSkObciOP1.Polozka"] != "0"]
    prior = {h: 0.0 for h in hodnoty}
    for r in cr:
        cil = MAP_VELSK.get(r["VelSkObciOP1.Polozka"])
        if cil:
            prior[cil] += float(r["Hodnota"])
    return _norm(prior), {
        "zdroj": "csu:SLD21A002/VelSkObciOP1 (SLDB 2021, 15+)", "evidence": "raw_direct",
        "pozn": "proxy velikostní skupinou obce (řezy viz codelists/map_urbanicita.csv); "
                "Nomadic / remote = 0",
    }


# ---------------------------------------------------------------- P7: jazyk

CZ_JAZYKY = [
    "Czech", "Slovak", "Ukrainian", "Vietnamese", "Russian", "Polish",
    "German", "Romani", "Hungarian", "English", "Other",
]

MAP_JAZYK = {
    "1": "Czech", "26": "Czech", "2": "Slovak", "9": "Polish", "5": "German",
    "25": "Romani", "6": "Russian", "10": "Ukrainian", "11": "Vietnamese",
    "13": "Hungarian", "3": "English",
}


def language_prior(snapshot_dir: Path) -> Tuple[Prior, Prov]:
    rows = _rows(snapshot_dir, "sld007_matersky_jazyk_kraj")
    cr = [r for r in rows if r["POHL1.Polozka"] == "0"
          and r["UzCrKr_H.STAT.Polozka"] and not r["UzCrKr_H.KRAJ.Polozka"]]
    celkem = sum(float(r["Hodnota"]) for r in cr if r["MatJaz2.Polozka"] == "0")
    prior = {j: 0.0 for j in CZ_JAZYKY}
    zname = 0.0
    for r in cr:
        kod = r["MatJaz2.Polozka"]
        if kod in ("0", "99"):
            continue
        cil = MAP_JAZYK[kod]
        v = float(r["Hodnota"])
        prior[cil] += v
        zname += v
    # SLDB umožňoval uvést dva mateřské jazyky — součet jazyků > populace.
    # Normalizujeme přes uvedené jazyky; zbytek do Other není (kategorie
    # mimo výčet ČSÚ nepublikuje po jazycích) → Other = 0 s poznámkou.
    return _norm(prior), {
        "zdroj": "csu:SLD007 (SLDB 2021, mateřský jazyk)", "evidence": "raw_direct",
        "pozn": "Moravský sloučen s češtinou; Nezjištěno rozpuštěno; víceodpovědi "
                "normalizovány přes součet uvedených jazyků; Other=0 (ČSÚ nepublikuje zbytek po jazycích)",
        "celkem_populace": celkem,
    }


# ------------------------------------------------- P5: zaměstnanecký status

VEK_0_14 = {"1100000004", "1300050009", "1300100014"}


def employment_prior(snapshot_dir: Path, hodnoty: list[str]) -> Tuple[Prior, Prov]:
    akt = _rows(snapshot_dir, "sld21a047_ekonomicka_aktivita_kraj")
    cr = [r for r in akt if r["POHL3.Polozka"] == "0" and r["Uz02.Polozka"] == "CZ"]

    def leaf(r: dict) -> str:
        return (r["EKONAKTIV2H.EKONAKTIV3.Polozka"]
                or r["EKONAKTIV2H.EKONAKTIV2.Polozka"]
                or r["EKONAKTIV2H.EKONAKTIV1.Polozka"])

    def suma(ekon_kod: str) -> float:
        return sum(float(r["Hodnota"]) for r in cr
                   if leaf(r) == ekon_kod
                   and r["VekSk5.Polozka"] not in ({"VEKC"} | VEK_0_14)
                   and r["Hodnota"])

    zam_core = suma("1")
    prac_duch, prac_stud, materska = suma("2"), suma("3"), suma("4")
    nezam, neprac_duch, ostatni = suma("52"), suma("6"), suma("7")
    zaci, rodicovska, domacnost = suma("8"), suma("14"), suma("13")

    post = _rows(snapshot_dir, "sldzob14_postaveni_v_zamestnani")
    post_cr = {r["POSTZAMWS.Polozka"]: float(r["Hodnota"]) for r in post
               if r["POHL3.Polozka"] == "0"
               and r["UZ02456H.STAT.Polozka"] and not r["UZ02456H.KRAJ.Polozka"]}
    # POSTZAMWS: 1=zaměstnanci, 2=zaměstnavatelé, 3=OSVČ (9=nezjištěno vynecháno)
    zname = post_cr["1"] + post_cr["2"] + post_cr["3"]
    self_share = (post_cr["2"] + post_cr["3"]) / zname

    prace = _rows(snapshot_dir, "zamg07_delka_pracovni_doby")
    doba = {r["TYPPRACDO.Polozka"]: float(r["Hodnota"]) for r in prace if r["POHL1.Polozka"] == "0"}
    ft_share = doba["105"] / (doba["105"] + doba["201"])

    zam_zamestnanci = zam_core * (1.0 - self_share)
    prior = {h: 0.0 for h in hodnoty}
    prior["Full-time"] = zam_zamestnanci * ft_share
    prior["Part-time"] = zam_zamestnanci * (1.0 - ft_share)
    prior["Self-employed"] = zam_core * self_share
    prior["Gig / freelance"] = 0.0
    prior["Student"] = prac_stud + zaci
    prior["Unemployed"] = nezam
    prior["Retired"] = prac_duch + neprac_duch
    prior["Homemaker"] = materska + rodicovska + ostatni + domacnost
    return _norm(prior), {
        "zdroj": "csu:SLD21A047 (15+) + SLDZOB14 (podíl samostatných) + ZAMG07 (plný/kratší úvazek)",
        "evidence": "raw_direct+derived_split",
        "pozn": "Gig/freelance=0 (ČSÚ neodlišuje od OSVČ); FT/PT podíl z VŠPS aplikován "
                "na zaměstnance; pracující důchodci→Retired, mateřská/rodičovská→Homemaker "
                "(viz codelists/map_ekonomicka_aktivita.csv)",
        "self_share": round(self_share, 4), "ft_share": round(ft_share, 4),
    }


# -------------------------------------------- P6: socioekonomické pásmo

def socioeconomic_prior(snapshot_dir: Path, hodnoty: list[str]) -> Tuple[Prior, Prov]:
    """Pásma definována kvantily národního rozdělení příjmů (SILC):
    Low = D1–D2, Lower-middle = D3–D4, Middle = D5–D7, Upper-middle = D8–D9,
    High = D10. Decilové hranice ze snapshotu slouží jako dokumentace řezů."""
    data = json.loads((snapshot_dir / "ilc_di01_cz.json").read_text())
    from cz.data.eurostat import jsonstat_rows
    decily = {r["quant_inc"]: r["value"] for r in jsonstat_rows(data)
              if r.get("quant_inc", "").startswith("D") and r["value"] is not None}
    prior = {
        "Low income": 0.20, "Lower-middle": 0.20, "Middle": 0.30,
        "Upper-middle": 0.20, "High income": 0.10,
    }
    assert set(prior) == set(hodnoty)
    return prior, {
        "zdroj": "eurostat:ilc_di01 (SILC, národní měna)", "evidence": "definitional_quantiles",
        "pozn": "pásma = decily národního rozdělení (2+2+3+2+1); hranice v Kč viz decile_cutoffs",
        "decile_cutoffs_nac": decily,
    }


# ----------------------------- podmíněné tabulky (CPT vzdělání|věk, status|věk)

VEK5_DO_BRACKETU = {
    # VekSk5/VEKSK5A kód -> {schema bracket: váha}; 15-19 dělíme 3/5 (15-17)
    # a 2/5 (18-19) za předpokladu rovnoměrnosti uvnitř skupiny.
    "1300150019": {"13-17": 0.6, "18-24": 0.4},
    "1300200024": {"18-24": 1.0},
    "1300250029": {"25-34": 1.0}, "1300300034": {"25-34": 1.0},
    "1300350039": {"35-44": 1.0}, "1300400044": {"35-44": 1.0},
    "1300450049": {"45-54": 1.0}, "1300500054": {"45-54": 1.0},
    "1300550059": {"55-64": 1.0}, "1300600064": {"55-64": 1.0},
    "1300650069": {"65-74": 1.0}, "1300700074": {"65-74": 1.0},
    "1300750079": {"75-84": 1.0}, "1300800084": {"75-84": 1.0},
    "1300850089": {"85+": 1.0}, "1300900094": {"85+": 1.0},
    "1300950099": {"85+": 1.0}, "1201009999": {"85+": 1.0},
}

BRACKETY_18PLUS = ["18-24", "25-34", "35-44", "45-54", "55-64", "65-74", "75-84", "85+"]


def education_by_age(snapshot_dir: Path, hodnoty: list[str]) -> Tuple[Dict[str, Prior], Prov]:
    """P(vzdělání | věkový bracket) pro brackety 18+ z Vzdel1 × VEKSK5A (ČR)."""
    rows = _rows(snapshot_dir, "sld21a002_vzdelani_x_vek")
    cr = [r for r in rows if r["Uz02.Polozka"] == "CZ"
          and r["Vzdel1.Polozka"] not in ("0",) and r["VEKSK5A.Polozka"] != "0"]
    acc: Dict[str, Prior] = {b: {h: 0.0 for h in hodnoty} for b in BRACKETY_18PLUS}
    for r in cr:
        cil = MAP_VZDEL1.get(r["Vzdel1.Polozka"])
        if not cil or not r["Hodnota"]:
            continue
        for b, w in VEK5_DO_BRACKETU.get(r["VEKSK5A.Polozka"], {}).items():
            if b in acc:
                acc[b][cil] += w * float(r["Hodnota"])
    return {b: _norm(p) for b, p in acc.items()}, {
        "zdroj": "csu:SLD21A002 Vzdel1×VEKSK5A (SLDB 2021)", "evidence": "raw_direct",
        "pozn": "skupina 15-19 dělena 3/5 vs. 2/5 mezi brackety 13-17 a 18-24; "
                "brackety <18 bez CPT řádku (fallback prior + masky)",
    }


def employment_by_age(snapshot_dir: Path, hodnoty: list[str]) -> Tuple[Dict[str, Prior], Prov]:
    """P(status | věkový bracket) 18+ z EKONAKTIV × VekSk5; FT/PT/OSVČ dělení
    národními podíly (SLDZOB14, ZAMG07) konstantně napříč věkem."""
    akt = _rows(snapshot_dir, "sld21a047_ekonomicka_aktivita_kraj")
    cr = [r for r in akt if r["POHL3.Polozka"] == "0" and r["Uz02.Polozka"] == "CZ"]

    def leaf(r: dict) -> str:
        return (r["EKONAKTIV2H.EKONAKTIV3.Polozka"]
                or r["EKONAKTIV2H.EKONAKTIV2.Polozka"]
                or r["EKONAKTIV2H.EKONAKTIV1.Polozka"])

    post = _rows(snapshot_dir, "sldzob14_postaveni_v_zamestnani")
    post_cr = {r["POSTZAMWS.Polozka"]: float(r["Hodnota"]) for r in post
               if r["POHL3.Polozka"] == "0"
               and r["UZ02456H.STAT.Polozka"] and not r["UZ02456H.KRAJ.Polozka"]}
    zname = post_cr["1"] + post_cr["2"] + post_cr["3"]
    self_share = (post_cr["2"] + post_cr["3"]) / zname
    prace = _rows(snapshot_dir, "zamg07_delka_pracovni_doby")
    doba = {r["TYPPRACDO.Polozka"]: float(r["Hodnota"]) for r in prace if r["POHL1.Polozka"] == "0"}
    ft_share = doba["105"] / (doba["105"] + doba["201"])

    MAPA = {"2": "Retired", "3": "Student", "4": "Homemaker", "52": "Unemployed",
            "6": "Retired", "7": "Homemaker", "8": "Student", "14": "Homemaker",
            "13": "Homemaker"}
    acc: Dict[str, Prior] = {b: {h: 0.0 for h in hodnoty} for b in BRACKETY_18PLUS}
    for r in cr:
        kod, vek = leaf(r), r["VekSk5.Polozka"]
        if not r["Hodnota"] or vek in ("VEKC",):
            continue
        for b, w in VEK5_DO_BRACKETU.get(vek, {}).items():
            if b not in acc:
                continue
            v = w * float(r["Hodnota"])
            if kod == "1":
                zam = v * (1.0 - self_share)
                acc[b]["Full-time"] += zam * ft_share
                acc[b]["Part-time"] += zam * (1.0 - ft_share)
                acc[b]["Self-employed"] += v * self_share
            elif kod in MAPA:
                acc[b][MAPA[kod]] += v
    return {b: _norm(p) for b, p in acc.items()}, {
        "zdroj": "csu:SLD21A047 EKONAKTIV×VekSk5 + SLDZOB14 + ZAMG07",
        "evidence": "raw_direct+derived_split",
        "pozn": "FT/PT a podíl samostatných konstantní napříč věkem (národní podíly); "
                "Gig/freelance=0; brackety <18 bez CPT řádku",
        "self_share": round(self_share, 4), "ft_share": round(ft_share, 4),
    }


# --------------------------------------------- G6: kraj vrstva a urbanicita|kraj

def kraje_codelist() -> list[dict]:
    with (CZ_ROOT / "codelists" / "kraje.csv").open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def okres_do_kraje() -> Dict[str, str]:
    """Mapa název okresu -> název kraje (deterministická, z číselníků)."""
    kraj_nazvy = {k["nuts3_kod"]: k["nazev"] for k in kraje_codelist()}
    return {o["nazev"]: kraj_nazvy[o["kraj_nuts3"]] for o in okresy_codelist()}


def urbanicity_by_kraj(snapshot_dir: Path, hodnoty: list[str]) -> Tuple[Dict[str, Prior], Prov]:
    """P(urbanicita | kraj) z velikostních skupin obcí (SLDB 2021, 15+)."""
    rows = _rows(snapshot_dir, "sld21a002_vzdelani_vek_urbanicita_kraj")
    kraj_nazvy = {k["nuts3_kod"]: k["nazev"] for k in kraje_codelist()}
    acc: Dict[str, Prior] = {n: {h: 0.0 for h in hodnoty} for n in kraj_nazvy.values()}
    for r in rows:
        kod = r["Uz02.Polozka"]
        if kod not in kraj_nazvy:
            continue
        if (r["POHL3.Polozka"] != "0" or r["Vzdel5.Polozka"] != "0"
                or r["VEKSK5A.Polozka"] != "0" or r["VelSkObciOP1.Polozka"] == "0"):
            continue
        cil = MAP_VELSK.get(r["VelSkObciOP1.Polozka"])
        if cil and r["Hodnota"]:
            acc[kraj_nazvy[kod]][cil] += float(r["Hodnota"])
    return {k: _norm(p) for k, p in acc.items()}, {
        "zdroj": "csu:SLD21A002 VelSkObciOP1×kraj (SLDB 2021, 15+)", "evidence": "raw_direct",
        "pozn": "G6 smíšená granularita: urbanicita podmíněna krajem (přes uzel cz_kraj), "
                "ne okresem — dvě persony ze stejného kraje a jiného okresu mají "
                "identickou distribuci urbanicity (G7)",
    }
