"""Mapování ESS10 CZ → postojové dimenze schématu (Fáze 4, S1–S3).

Zásady:
- Agregace vždy s post-stratifikační vahou `pspwght` (vzorek ~2 476
  respondentů by jinak zkresloval populační distribuce).
- Chybějící hodnoty (recodeMissingValues=true ⇒ NaN) se z agregací vynechávají
  (výjimka: lrscale, kde NaN → Apolitical, dokumentováno).
- Regionální podmínění: ESS region = NUTS3 kraj, ale ~175 respondentů na kraj
  je málo ⇒ distribuce se počítají per NUTS2 (8 regionů soudržnosti, dle
  rozhodnutí "kraj/NUTS2") s lehkým shrinkage k národní distribuci
  (váha n/(n+50)); řádky CPT pro cz_kraj pak replikují NUTS2 hodnoty.
- Schwartz PVQ (21 položek): průměr položek dané hodnoty s MRAT centrováním
  (odečet průměru respondenta přes všech 21 položek — standardní ESS postup),
  binování váženými populačními kvantily 10/25/30/25/10. Jen národně
  (kvantilové binování per region by bylo na ~300 lidech nestabilní).

Provenience všech výstupů: CZ-survey (ess10:<var>).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from cz.graph.priors import kraje_codelist

SHRINK_K = 50.0

# --- binování 0-10 škál a kategoriálních položek -----------------------------
# (dim, ess_var, mapa: ess hodnota / interval -> schema hodnota, NUTS2 podmínění)

SKALY = [
    ("trust_level", "ppltrst",
     [(8, 10, "Trusting"), (5, 7, "Verifying"), (2, 4, "Skeptical"), (0, 1, "Hostile")], True),
    ("health_general_health", "health",
     [(1, 1, "Excellent"), (2, 2, "Good"), (3, 3, "Fair"), (4, 5, "Poor")], True),
    ("health_mental_health", "stflife",
     [(8, 10, "Thriving"), (5, 7, "Stable"), (2, 4, "Struggling"), (0, 1, "In crisis")], True),
    ("cog_optimism", "happy",
     [(9, 10, "Very high"), (7, 8, "High"), (4, 6, "Moderate"), (2, 3, "Low"), (0, 1, "None")], True),
    ("topic_politics", "polintr",
     [(1, 1, "Passionate"), (2, 2, "Interested"), (3, 3, "Neutral"), (4, 4, "Indifferent")], True),
    ("att_immigration", "imwbcnt",
     [(0, 2, "Opposed"), (3, 4, "Skeptical"), (5, 5, "Neutral"), (6, 7, "Positive"), (8, 10, "Enthusiast")], True),
    ("lstyle_social_battery", "sclmeet",
     [(1, 2, "Strong introvert"), (3, 3, "Introvert"), (4, 5, "Ambivert"), (6, 6, "Extrovert"), (7, 7, "Strong extrovert")], True),
    ("tech_savviness", "netusoft",
     [(5, 5, "Digital native"), (4, 4, "Comfortable"), (3, 3, "Cautious adopter"), (2, 2, "Reluctant"), (1, 1, "Avoidant")], True),
]

PVQ = {
    "schwartz_value_self_direction": ["ipcrtiv", "impfree"],
    "schwartz_value_stimulation": ["impdiff", "ipadvnt"],
    "schwartz_value_hedonism": ["ipgdtim", "impfun"],
    "schwartz_value_achievement": ["ipshabt", "ipsuces"],
    "schwartz_value_power": ["imprich", "iprspot"],
    "schwartz_value_security": ["impsafe", "ipstrgv"],
    "schwartz_value_conformity": ["ipfrule", "ipbhprp"],
    "schwartz_value_tradition": ["ipmodst", "imptrad"],
    "schwartz_value_benevolence": ["iphlppl", "iplylfr"],
    "schwartz_value_universalism": ["ipeqopt", "ipudrst", "impenv"],
}
PVQ_VSE = sorted({v for vs in PVQ.values() for v in vs})
PVQ_BINY = [(0.90, "Very high"), (0.65, "High"), (0.35, "Average"), (0.10, "Low"), (0.0, "Very low")]


def _wdist(hodnoty: pd.Series, vahy: pd.Series, kategorie: list[str]) -> Dict[str, float]:
    ok = hodnoty.notna()
    d = {k: 0.0 for k in kategorie}
    for v, w in zip(hodnoty[ok], vahy[ok]):
        d[v] += w
    s = sum(d.values())
    return {k: v / s for k, v in d.items()} if s > 0 else d


def _bin_scale(series: pd.Series, mapa) -> pd.Series:
    def f(x):
        if pd.isna(x):
            return np.nan
        for lo, hi, cil in mapa:
            if lo <= x <= hi:
                return cil
        return np.nan
    return series.map(f)


def _shrink(dist: Dict[str, float], national: Dict[str, float], n: float) -> Dict[str, float]:
    w = n / (n + SHRINK_K)
    return {k: w * dist.get(k, 0.0) + (1 - w) * national[k] for k in national}


def load_cz(snapshot_dir: Path) -> pd.DataFrame:
    df = pd.read_parquet(snapshot_dir / "ess10_cz.parquet")
    df = df[df["pspwght"].notna()].copy()
    df["nuts2"] = df["region"].str[:4]
    return df


def build_ess_priors(
    snapshot_dir: Path,
    schema_values: Dict[str, list],
    schema_values_prior_disability: Dict[str, float] | None = None,
) -> Dict[str, dict]:
    """Vrátí {dim: {prior, cond_kraj|None, provenance}} pro všechny mapované dimenze."""
    df = load_cz(snapshot_dir)
    w = df["pspwght"]
    kraj_nuts2 = {k["nazev"]: k["nuts2_kod"] for k in kraje_codelist()}
    out: Dict[str, dict] = {}

    def pridat(dim: str, binned: pd.Series, var_popis: str, nuts2_cond: bool,
               chybejici_do: Optional[str] = None, extra_pozn: str = "") -> None:
        hodnoty = schema_values[dim]
        b = binned.copy()
        if chybejici_do is not None:
            b = b.fillna(chybejici_do)
        prior = _wdist(b, w, hodnoty)
        cond = None
        if nuts2_cond:
            national = prior
            nuts2_dist = {}
            for n2, sub in df.groupby("nuts2"):
                bb = b.loc[sub.index]
                nuts2_dist[n2] = _shrink(_wdist(bb, w.loc[sub.index], hodnoty), national, len(sub))
            cond = {kraj: nuts2_dist[n2] for kraj, n2 in kraj_nuts2.items()}
        out[dim] = {
            "prior": prior,
            "cond_kraj": cond,
            "provenance": {
                "zdroj": f"ess10:{var_popis}", "evidence": "cz_survey_weighted",
                "vaha": "pspwght", "n": int(binned.notna().sum()),
                "pozn": ("NUTS2 podmínění se shrinkage k=50; " if nuts2_cond else "jen národní; ")
                        + extra_pozn,
            },
        }

    for dim, var, mapa, nuts2_cond in SKALY:
        pridat(dim, _bin_scale(df[var], mapa), var, nuts2_cond)

    # demo_religion_affiliation: kompozit rlgblg × rlgdnm × rlgdgr
    RLGDNM = {1: "Christian", 2: "Christian", 3: "Christian", 4: "Christian",
              5: "Jewish", 6: "Muslim", 7: "Buddhist", 8: "Folk / traditional"}
    def relig(r):
        if pd.isna(r["rlgblg"]):
            return np.nan
        if r["rlgblg"] == 1:
            return RLGDNM.get(r["rlgdnm"], "Folk / traditional")
        if not pd.isna(r["rlgdgr"]) and r["rlgdgr"] >= 3:
            return "Spiritual but unaffiliated"
        return "Atheist / agnostic"
    pridat("demo_religion_affiliation", df.apply(relig, axis=1), "rlgblg×rlgdnm×rlgdgr", False)

    # political_lean: lrscale + NaN -> Apolitical
    mapa_lr = [(0, 2, "Left"), (3, 4, "Center-left"), (5, 5, "Center"),
               (6, 7, "Center-right"), (8, 10, "Right")]
    pridat("political_lean", _bin_scale(df["lrscale"], mapa_lr), "lrscale", True,
           chybejici_do="Apolitical", extra_pozn="chybějící lrscale → Apolitical (12 % vzorku)")

    # demo_political_engagement: kompozit vote × polintr
    def eng(r):
        if pd.isna(r["vote"]):
            return np.nan
        if r["vote"] == 1:
            return "Engaged voter" if r["polintr"] in (1, 2) else "Occasional voter"
        if r["vote"] == 2:
            return "Non-voter"
        return "Disengaged"  # vote=3 not eligible
    pridat("demo_political_engagement", df.apply(eng, axis=1), "vote×polintr", True,
           extra_pozn="Activist bez ESS podkladu = 0")

    # religiosity: podmíněná afiliací (joint rlgdgr × rlgblg je v ESS) —
    # řeší kolizi s maskou "ateista ⇒ ne Observant/Devout" datově správně
    mapa_rlg = [(0, 2, "Secular"), (3, 5, "Spiritual"), (6, 8, "Observant"), (9, 10, "Devout")]
    rlg_bin = _bin_scale(df["rlgdgr"], mapa_rlg)
    affil = df.apply(relig, axis=1)
    rlg_prior = _wdist(rlg_bin, w, schema_values["religiosity"])
    cond_aff = {}
    for a, sub in df.groupby(affil):
        if len(sub) >= 30:
            cond_aff[a] = _wdist(rlg_bin.loc[sub.index], w.loc[sub.index],
                                 schema_values["religiosity"])
    out["religiosity"] = {
        "prior": rlg_prior,
        "cond_kraj": None,
        "cond": {"parent": "demo_religion_affiliation", "rows": cond_aff},
        "provenance": {"zdroj": "ess10:rlgdgr|afiliace", "evidence": "cz_survey_weighted",
                       "vaha": "pspwght", "n": int(rlg_bin.notna().sum()),
                       "pozn": "podmíněno demo_religion_affiliation (řádky s n≥30); "
                               "místo NUTS2 — joint z téhož dotazníku"},
    }

    # demo_disability_status: celkový podíl No disability z hlthhmp (dlouhodobé
    # omezení), typy postižení ve světovém poměru (ESS typy nerozlišuje)
    svet = schema_values_prior_disability
    hampered = _wdist(df["hlthhmp"].map({3.0: "No", 2.0: "Yes", 1.0: "Yes"}), w, ["No", "Yes"])
    typy = {k: v for k, v in svet.items() if k not in ("No disability", "Prefers not to say")}
    s_typy = sum(typy.values())
    dis_prior = {"No disability": hampered["No"], "Prefers not to say": 0.0}
    for k, v in typy.items():
        dis_prior[k] = hampered["Yes"] * v / s_typy
    out["demo_disability_status"] = {
        "prior": dis_prior, "cond_kraj": None,
        "provenance": {"zdroj": "ess10:hlthhmp", "evidence": "cz_survey_weighted+world_type_split",
                       "vaha": "pspwght", "n": int(df["hlthhmp"].notna().sum()),
                       "pozn": "celkový podíl z hlthhmp (dlouhodobé omezení 32 %), "
                               "rozpad na typy ve světovém poměru (ESS typy neměří)"},
    }

    # health_mobility: DETERMINISTICKY z demo_disability_status — obě dimenze
    # jsou odvozené z téže proměnné hlthhmp, nezávislé vzorkování by joint
    # rozbilo (maska no_disability by ořezala Moderate). No disability ⇔
    # hlthhmp=3 ⇔ Full; mezi omezenými (hlthhmp 1-2) je poměr Mild:Moderate
    # z ESS. Marginál se složí přesně na ESS hodnoty.
    ham = _wdist(df["hlthhmp"].map({3.0: "Full", 2.0: "Mild limitation",
                                    1.0: "Moderate limitation"}), w,
                 ["Full", "Mild limitation", "Moderate limitation"])
    omezeni = ham["Mild limitation"] + ham["Moderate limitation"]
    dis_radek = {"Mild limitation": ham["Mild limitation"] / omezeni,
                 "Moderate limitation": ham["Moderate limitation"] / omezeni}
    mob_rows = {"No disability": {"Full": 1.0}}
    for typ in dis_prior:
        if typ not in ("No disability", "Prefers not to say") and dis_prior[typ] > 0:
            mob_rows[typ] = dict(dis_radek)
    mob_prior = {"Full": ham["Full"], "Mild limitation": ham["Mild limitation"],
                 "Moderate limitation": ham["Moderate limitation"], "Uses mobility aid": 0.0}
    out["health_mobility"] = {
        "prior": mob_prior,
        "cond_kraj": None,
        "cond": {"parent": "demo_disability_status", "rows": mob_rows},
        "provenance": {"zdroj": "ess10:hlthhmp|disability", "evidence": "cz_survey_weighted",
                       "vaha": "pspwght", "n": int(df["hlthhmp"].notna().sum()),
                       "pozn": "deterministický joint s demo_disability_status (táž zdrojová "
                               "proměnná hlthhmp); Uses mobility aid=0 (ESS neměří)"},
    }

    # Schwartz PVQ s MRAT centrováním (nižší skór = "více jako já")
    mrat = df[PVQ_VSE].mean(axis=1)
    for dim, items in PVQ.items():
        skor = mrat - df[items].mean(axis=1)  # kladné = důležitější než osobní průměr
        ok = skor.notna()
        q = {p: _wquantile(skor[ok].to_numpy(), w[ok].to_numpy(), p) for p, _ in PVQ_BINY if p > 0}
        def bin_pvq(x):
            if pd.isna(x):
                return np.nan
            for p, cil in PVQ_BINY:
                if p == 0.0 or x >= q[p]:
                    return cil
            return "Very low"
        pridat(dim, skor.map(bin_pvq), f"PVQ:{'+'.join(items)}", False,
               extra_pozn="MRAT centrování, vážené kvantily 10/25/30/25/10")

    return out


def _wquantile(x: np.ndarray, w: np.ndarray, q: float) -> float:
    order = np.argsort(x)
    cw = np.cumsum(w[order])
    return float(x[order][np.searchsorted(cw, q * cw[-1])])
