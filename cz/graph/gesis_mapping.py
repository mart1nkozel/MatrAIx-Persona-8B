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


# ------------------------------- vlna 2: EVS, ISSP, platformy, klima ---------

EVS_IMPORTANT = {1: "Core value", 2: "Important", 3: "Minor", 4: "Irrelevant"}
AGREE5 = {1: "Enthusiast", 2: "Positive", 3: "Neutral", 4: "Skeptical", 5: "Opposed"}


def _weighted_map(df, var, wvar, mapa, hodnoty) -> Prior:
    prior = {h: 0.0 for h in hodnoty}
    for v, w in zip(df[var], df[wvar].fillna(1.0)):
        if not pd.isna(v) and int(v) in mapa:
            prior[mapa[int(v)]] += float(w)
    return _norm(prior)


def build_gesis_wave2(snapshot_dir: Path, schema_values: Dict[str, list]) -> Dict[str, dict]:
    out: Dict[str, dict] = {}

    # --- EVS/WVS (poslední CZ vlna = WVS 2022, n=1200; váha gwght) -----------
    evs = pd.read_parquet(snapshot_dir / "za7505_evs_cz.parquet")
    evs = evs[evs["year"] == evs["year"].max()]
    rok = int(evs["year"].max())
    for dim, var, pozn in [
        ("val_family", "A001", "important in life: family"),
        ("val_community", "A002", "PROXY: important in life: friends"),
        ("val_fun_enjoyment", "A003", "PROXY: important in life: leisure time"),
        ("val_career_success", "A005", "PROXY: important in life: work"),
        ("val_spirituality_faith", "A006", "important in life: religion"),
        ("val_patriotism", "G006", "how proud of nationality"),
    ]:
        out[dim] = {
            "prior": _weighted_map(evs, var, "gwght", EVS_IMPORTANT, schema_values[dim]),
            "cond_kraj": None,
            "provenance": {"zdroj": f"gesis:ZA7505 {var} (EVS/WVS {rok})",
                           "evidence": "cz_survey_weighted", "vaha": "gwght",
                           "n": int(evs[var].notna().sum()),
                           "pozn": pozn + "; 4bodová škála, Moderate bez opory"},
        }
    # E036 private vs state ownership (1=více soukromého … 10=více státního)
    E036 = {1: "Enthusiast", 2: "Enthusiast", 3: "Positive", 4: "Positive",
            5: "Neutral", 6: "Neutral", 7: "Skeptical", 8: "Skeptical",
            9: "Opposed", 10: "Opposed"}
    out["att_free_markets"] = {
        "prior": _weighted_map(evs, "E036", "gwght", E036, schema_values["att_free_markets"]),
        "cond_kraj": None,
        "provenance": {"zdroj": f"gesis:ZA7505 E036 (EVS/WVS {rok})",
                       "evidence": "cz_survey_weighted", "vaha": "gwght",
                       "n": int(evs["E036"].notna().sum()),
                       "pozn": "1-10 škála soukromé vs. státní vlastnictví, nízká = pro-trh"},
    }

    # --- ISSP 2022 Gender Roles: v2 předškolní dítě trpí, když matka pracuje --
    issp = pd.read_parquet(snapshot_dir / "za10000_issp_gender_cz.parquet")
    wvar = "DWEIGHT_TS" if issp["DWEIGHT_TS"].notna().any() else "DWEIGHT_HH"
    out["att_traditional_gender_roles"] = {
        "prior": _weighted_map(issp, "v2", wvar, AGREE5, schema_values["att_traditional_gender_roles"]),
        "cond_kraj": None,
        "provenance": {"zdroj": "gesis:ZA10000 v2 (ISSP 2022 Family & Gender Roles)",
                       "evidence": "cz_survey_weighted", "vaha": wvar,
                       "n": int(issp["v2"].notna().sum()),
                       "pozn": "souhlas s tradiční rolí (dítě trpí, když matka pracuje)"},
    }

    # --- ISSP Social Inequality: v22 vláda má snižovat příjmové rozdíly ------
    ineq = pd.read_parquet(snapshot_dir / "za7600_issp_inequality_cz.parquet")
    out["att_government_regulation"] = {
        "prior": _weighted_map(ineq, "v22", "WEIGHT", AGREE5, schema_values["att_government_regulation"]),
        "cond_kraj": None,
        "provenance": {"zdroj": "gesis:ZA7600 v22 (ISSP Social Inequality)",
                       "evidence": "cz_survey_weighted", "vaha": "WEIGHT",
                       "n": int(ineq["v22"].notna().sum()),
                       "pozn": "PROXY: odpovědnost vlády za snižování rozdílů ≈ postoj k regulaci"},
    }

    # --- platformy: q8 multi-select → frakční atribuce ----------------------
    ai = pd.read_parquet(snapshot_dir / "za8929_ai_platformy_cz.parquet")
    # q8_i → platforma dle value labelů; WhatsApp/Messenger/Snapchat/Telegram/
    # Viber/Discord nemají hodnotu v sadě schématu — vynechány
    PLATFORMY = {5: "Instagram", 7: "TikTok", 6: "X / Twitter", 2: "Facebook",
                 8: "LinkedIn", 3: "YouTube"}
    hodnoty = schema_values["lstyle_primary_social"]
    prior = {h: 0.0 for h in hodnoty}
    for _, r in ai.iterrows():
        w = float(r["w1"]) if not pd.isna(r["w1"]) else 1.0
        zminky = [PLATFORMY[i] for i in PLATFORMY if r.get(f"q8_{i}") == 1]
        if zminky:
            for z in zminky:
                prior[z] += w / len(zminky)
        else:
            prior["None"] += w
    out["lstyle_primary_social"] = {
        "prior": _norm(prior), "cond_kraj": None,
        "provenance": {"zdroj": "gesis:ZA8929 q8 (platformy pro politické info)",
                       "evidence": "cz_survey_weighted", "vaha": "w1", "n": int(len(ai)),
                       "pozn": "PROXY: multi-select zdrojů politických informací, frakční "
                               "atribuce; messagingové platformy mimo sadu schématu vynechány"},
    }

    # --- klima: sd1 klimatická změna způsobena člověkem (proxy) --------------
    kl = pd.read_parquet(snapshot_dir / "za9127_klima_cz.parquet")
    SD1 = {1: "Enthusiast", 2: "Positive", 3: "Skeptical", 4: "Opposed"}
    out["att_climate_action"] = {
        "prior": _weighted_map(kl, "sd1", "w1", SD1, schema_values["att_climate_action"]),
        "cond_kraj": None,
        "provenance": {"zdroj": "gesis:ZA9127 sd1 (standard EB 2024)",
                       "evidence": "cz_survey_weighted", "vaha": "w1",
                       "n": int(kl["sd1"].notna().sum()),
                       "pozn": "PROXY: souhlas s antropogenním původem změny klimatu ≈ podpora "
                               "klimatické akce; Neutral bez opory (bez středové kategorie)"},
    }
    return out
