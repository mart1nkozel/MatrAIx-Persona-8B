"""Mapování GESIS/Eurobarometer CZ výřezů → dimenze schématu (Fáze 4b).

Zdroje jsou lokální soubory (viz cz/data/gesis.py), výřezy ve snapshotu.
Vážení: w1 (redressment, per-country). Universum EB je 15+ — kontroly
marginálů srovnávají subpopulaci 18+ (stejně jako ESS dimenze).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple

import pandas as pd

Prior = Dict[str, float]

ENG = 12  # kód angličtiny v číselníku jazyků EB (d48)


def _norm(d: Prior) -> Prior:
    s = sum(d.values())
    return {k: v / s for k, v in d.items()} if s > 0 else d


def english_proficiency_prior(snapshot_dir: Path, hodnoty: list) -> Tuple[Prior, dict]:
    df = pd.read_parquet(snapshot_dir / "za8778_jazyky_cz.parquet")
    LVL = {1: "Fluent (C1-C2)", 2: "Intermediate (B1-B2)", 3: "Basic (A1-A2)",
           4: "Native", 5: "Basic (A1-A2)"}  # 5 = neví úroveň → konzervativně Basic

    def uroven(r) -> str:
        if r["d48a"] == ENG:
            return "Native"
        nejlepsi = None
        for poz, jaz in ((1, "d48b"), (2, "d48c"), (3, "d48d")):
            if r[jaz] == ENG and not pd.isna(r[f"q48f_{poz}"]):
                kand = LVL.get(int(r[f"q48f_{poz}"]))
                poradi = ["Basic (A1-A2)", "Intermediate (B1-B2)", "Fluent (C1-C2)", "Native"]
                if kand and (nejlepsi is None or poradi.index(kand) > poradi.index(nejlepsi)):
                    nejlepsi = kand
        return nejlepsi or "None"

    urovne = df.apply(uroven, axis=1)
    prior = {h: 0.0 for h in hodnoty}
    for u, w in zip(urovne, df["w1"]):
        prior[u] += w
    return _norm(prior), {
        "zdroj": "gesis:ZA8778 (EB Europeans and their languages, d48)",
        "evidence": "cz_survey_weighted", "vaha": "w1", "n": int(len(df)),
        "pozn": "úroveň = nejlepší z až 3 uváděných jazyků; DK úroveň → Basic; "
                "druhý mateřský jazyk → Native",
    }


def eb_scale_prior(snapshot_dir: Path, soubor: str, var: str, hodnoty: list,
                   mapa: Dict[int, str], zdroj: str) -> Tuple[Prior, dict]:
    df = pd.read_parquet(snapshot_dir / soubor)
    prior = {h: 0.0 for h in hodnoty}
    n = 0
    for v, w in zip(df[var], df["w1"]):
        cil = mapa.get(int(v)) if not pd.isna(v) else None
        if cil:
            prior[cil] += w
            n += 1
    return _norm(prior), {
        "zdroj": zdroj, "evidence": "cz_survey_weighted", "vaha": "w1", "n": n,
        "pozn": "DK vynecháno" + ("; Neutral bez opory v otázce (bez středové kategorie)"
                                  if "Neutral" not in mapa.values() else ""),
    }


def build_gesis_priors(snapshot_dir: Path, schema_values: Dict[str, list]) -> Dict[str, dict]:
    out: Dict[str, dict] = {}

    p, prov = english_proficiency_prior(snapshot_dir, schema_values["english_proficiency"])
    out["english_proficiency"] = {"prior": p, "cond_kraj": None, "provenance": prov}

    ATT = {1: "Enthusiast", 2: "Positive", 5: "Neutral", 3: "Skeptical", 4: "Opposed"}
    for dim, var, zdroj in [("att_ai", "qa6a_9", "gesis:ZA8904 qa6a_9 (technology eval AI)"),
                            ("att_vaccines", "qa6a_4", "gesis:ZA8904 qa6a_4 (technology eval vaccines)")]:
        p, prov = eb_scale_prior(snapshot_dir, "za8904_technologie_cz.parquet", var,
                                 schema_values[dim], ATT, zdroj)
        out[dim] = {"prior": p, "cond_kraj": None, "provenance": prov}

    ROBOTI = {1: "Enthusiast", 2: "Positive", 3: "Skeptical", 4: "Opposed"}
    p, prov = eb_scale_prior(snapshot_dir, "za8844_roboti_cz.parquet", "qb5",
                             schema_values["att_automation"], ROBOTI,
                             "gesis:ZA8844 qb5 (robots perception in workplace)")
    out["att_automation"] = {"prior": p, "cond_kraj": None, "provenance": prov}
    return out
