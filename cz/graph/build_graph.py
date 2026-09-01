"""Builder CZ grafu (Fáze 2): upstream full_dag.json + snapshot → cz_dag.json.

Transformace:
- výměna priorů 8 jádrových uzlů za ČSÚ/Eurostat hodnoty (P1–P7),
- výměna hodnotových sad `region` (77 okresů) a `primary_language` (CZ sada),
- suspendace prvků grafu, které po změně přestávají platit:
  * hrany/CPT/masky odkazující na změněné HODNOTY (region, primary_language)
    — jejich CPD řádky jsou klíčované starými hodnotami; Fáze 3 je nahradí
    CZ křížovými tabulkami,
  * plné CPT CÍLÍCÍ na uzly se změněným priorem — světové overlaye by
    deformovaly ČSÚ marginály.
  Kompatibilní masky bez vazby na změněné hodnoty zůstávají (logická
  konzistence, např. děti × vzdělání) — záměrně smí ohnout marginál.

  uv run python -m cz.graph.build_graph [--snapshot snap-...]
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from cz.graph import priors

REPO = Path(__file__).resolve().parents[2]
UPSTREAM_GRAPH = REPO / "persona" / "synthesis" / "graph" / "full_dag.json"
UPSTREAM_SCHEMA = REPO / "persona" / "schema" / "dimensions.json"
OUT_DIR = Path(__file__).resolve().parent
SNAPSHOTS = REPO / "cz" / "data" / "snapshots"

VALUE_CHANGED = {"region", "primary_language"}
PRIOR_ONLY = {
    "age_bracket", "gender_identity", "highest_education", "urbanicity",
    "demo_employment_status", "socioeconomic_band",
}


def latest_snapshot() -> str:
    ids = sorted(p.name for p in SNAPSHOTS.iterdir() if (p / "manifest.json").exists())
    for sid in reversed(ids):
        if not json.loads((SNAPSHOTS / sid / "manifest.json").read_text()).get("partial"):
            return sid
    raise SystemExit("žádný kompletní snapshot — spusť cz.data.fetch")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot", default=None)
    args = ap.parse_args()
    sid = args.snapshot or latest_snapshot()
    sdir = SNAPSHOTS / sid

    dag = json.loads(UPSTREAM_GRAPH.read_text())
    nodes = {n["id"]: n for n in dag["nodes"]}

    # --- CZ priory -----------------------------------------------------------
    vypocty = {
        "region": priors.region_prior(sdir),
        "age_bracket": priors.age_prior(sdir),
        "gender_identity": priors.gender_prior(sdir, nodes["gender_identity"]["prior"]),
        "highest_education": priors.education_prior(sdir, nodes["highest_education"]["values"]),
        "urbanicity": priors.urbanicity_prior(sdir, nodes["urbanicity"]["values"]),
        "primary_language": priors.language_prior(sdir),
        "demo_employment_status": priors.employment_prior(sdir, nodes["demo_employment_status"]["values"]),
        "socioeconomic_band": priors.socioeconomic_prior(sdir, nodes["socioeconomic_band"]["values"]),
    }

    report: dict = {"snapshot": sid, "nodes": {}, "suspended": {}}
    for nid, (prior, prov) in vypocty.items():
        n = nodes[nid]
        stare_hodnoty = list(n["values"])
        nove_hodnoty = list(prior.keys()) if nid in VALUE_CHANGED else stare_hodnoty
        n["values"] = nove_hodnoty
        n["values_list"] = nove_hodnoty
        n["values_count"] = len(nove_hodnoty)
        n["prior"] = {v: prior[v] for v in nove_hodnoty}
        n["cz_provenance"] = prov
        cpd = n.setdefault("cpd", {})
        cpd["calibration"] = "cz_csu_v1"
        report["nodes"][nid] = {
            "values_changed": nid in VALUE_CHANGED,
            "values_count": len(nove_hodnoty),
            "prior": n["prior"],
            "provenance": prov,
        }
    nodes["region"]["description"] = "Okres ČR, kde persona žije (77 jednotek LAU1 vč. Prahy)."
    nodes["region"]["label"] = "Okres"

    # --- suspendace ----------------------------------------------------------
    def maska_koliduje(m: dict) -> bool:
        if m.get("target") in VALUE_CHANGED:
            return True
        return any(k in VALUE_CHANGED for k in (m.get("condition") or {}))

    def cpt_parents(c: dict) -> list[str]:
        p = c.get("parents")
        if isinstance(p, str):
            try:
                import ast
                p = ast.literal_eval(p)
            except (ValueError, SyntaxError):
                p = [p]
        return list(p or [])

    edges_keep, edges_susp = [], []
    for e in dag["directed_proposal_edges"]:
        if e["source"] in VALUE_CHANGED or e["target"] in VALUE_CHANGED:
            edges_susp.append({"edge_id": e.get("edge_id"), "source": e["source"],
                               "target": e["target"], "reason": "hodnotova_sada_zmenena"})
        else:
            edges_keep.append(e)

    cpts_keep, cpts_susp = [], []
    for c in dag["full_cpts"]:
        parents = cpt_parents(c)
        if c.get("target") in VALUE_CHANGED or any(p in VALUE_CHANGED for p in parents):
            cpts_susp.append({"cpt_id": c.get("cpt_id"), "reason": "hodnotova_sada_zmenena"})
        elif c.get("target") in PRIOR_ONLY:
            cpts_susp.append({"cpt_id": c.get("cpt_id"),
                              "reason": "svetovy_overlay_na_cz_marginal"})
        else:
            cpts_keep.append(c)

    masks_keep, masks_susp = [], []
    cz_kalibrovane = VALUE_CHANGED | PRIOR_ONLY
    for m in dag["conditional_masks"]:
        if maska_koliduje(m):
            masks_susp.append({"mask_id": m.get("mask_id"), "reason": "hodnotova_sada_zmenena"})
        elif (m.get("target") in cz_kalibrovane
              and set(m.get("condition") or {}) - {"age_bracket"}):
            # Maska váže CZ-kalibrovaný uzel na světově kalibrované dimenze
            # (domain, ses, …) tvrdou nulou → deformovala by ČSÚ marginál.
            # Fáze 3 ji nahradí CZ křížovou tabulkou; věkové masky zůstávají.
            masks_susp.append({"mask_id": m.get("mask_id"),
                               "reason": "svetova_podminka_na_cz_marginal"})
        else:
            masks_keep.append(m)

    dag["directed_proposal_edges"] = edges_keep
    dag["full_cpts"] = cpts_keep
    dag["conditional_masks"] = masks_keep
    if "proposal_view" in dag:
        dag["proposal_view"]["edge_count"] = len(edges_keep)

    # --- CZ podmíněné tabulky: vzdělání|věk, status|věk (18+ řádky) ----------
    topo = dag["proposal_view"]["topological_order"]
    assert topo.index("age_bracket") < topo.index("highest_education")
    assert topo.index("age_bracket") < topo.index("demo_employment_status")

    cz_cpts = []
    for target, (cond, cprov) in {
        "highest_education": priors.education_by_age(sdir, nodes["highest_education"]["values"]),
        "demo_employment_status": priors.employment_by_age(sdir, nodes["demo_employment_status"]["values"]),
    }.items():
        cz_cpts.append({
            "cpt_id": f"cz_{target}_given_age_sldb2021",
            "target": target,
            "parents": ["age_bracket"],
            "table_type": "weighted_full_cpt",
            "source_refs": ["cz_snapshot:" + sid],
            "cpt_weight": 1.0,
            "replace_pairwise_parent_edges": True,
            "smoothing": "none",
            "rows": [{"parent_assignment": {"age_bracket": b}, "distribution": dist}
                     for b, dist in cond.items()],
            "notes": [cprov.get("pozn", "")],
            "zero_semantics": "structural_zero_from_source",
            "cz_provenance": cprov,
        })
        # referenční marginál 18+ pro check_marginals: vážený průměr řádků CPT
        vek_prior = vypocty["age_bracket"][0]
        vaha18 = {b: vek_prior[b] for b in cond}
        s18 = sum(vaha18.values())
        ref18 = {v: sum(vaha18[b] / s18 * cond[b].get(v, 0.0) for b in cond)
                 for v in nodes[target]["values"]}
        report["nodes"][target]["reference_18plus"] = ref18
        report["nodes"][target]["conditional_on_age"] = {"rows": len(cond), "provenance": cprov}
    dag["full_cpts"] = cpts_keep + cz_cpts

    report["suspended"] = {
        "edges": edges_susp, "full_cpts": cpts_susp, "masks": masks_susp,
        "counts": {"edges": len(edges_susp), "full_cpts": len(cpts_susp), "masks": len(masks_susp)},
    }

    # ====================== Fáze 3: graf a pravidla ==========================

    # --- G6: uzel cz_kraj + deterministické P(kraj|okres) --------------------
    o2k = priors.okres_do_kraje()
    kraje_nazvy = sorted(set(o2k.values()))
    kraj_marginal = {k: 0.0 for k in kraje_nazvy}
    for okres, p in nodes["region"]["prior"].items():
        kraj_marginal[o2k[okres]] += p
    cz_kraj = {
        "id": "cz_kraj",
        "label": "Kraj",
        "category": "Demographic: Core",
        "index": max(n.get("index", 0) for n in dag["nodes"]) + 1,
        "tier": 1,
        "values": kraje_nazvy,
        "values_list": kraje_nazvy,
        "values_count": len(kraje_nazvy),
        "description": "Kraj ČR (NUTS3) — odvozen deterministicky z okresu; "
                       "vrstva pro podmiňování postojových dimenzí (G6).",
        "prior": kraj_marginal,
        "parents": ["region"],
        "cpd": {"type": "deterministic_from_full_cpt", "calibration": "cz_csu_v1"},
        "cz_provenance": {"zdroj": "odvozeno z region (číselníky ČSÚ)", "evidence": "deterministic"},
    }
    dag["nodes"].append(cz_kraj)
    nodes["cz_kraj"] = cz_kraj
    topo.insert(topo.index("region") + 1, "cz_kraj")
    dag["proposal_view"]["node_count"] = len(dag["nodes"])
    dag["metadata"]["node_count"] = len(dag["nodes"])
    dag["full_cpts"].append({
        "cpt_id": "cz_kraj_given_okres_deterministic",
        "target": "cz_kraj",
        "parents": ["region"],
        "table_type": "deterministic_full_cpt",
        "source_refs": ["cz_codelists"],
        "cpt_weight": 1.0,
        "replace_pairwise_parent_edges": True,
        "rows": [{"parent_assignment": {"region": okres},
                  "distribution": {kraj: 1.0}} for okres, kraj in o2k.items()],
        "zero_semantics": "deterministic_mapping",
    })

    # --- G6/G9: urbanicita podmíněná krajem ----------------------------------
    urb_cond, urb_prov = priors.urbanicity_by_kraj(sdir, nodes["urbanicity"]["values"])
    dag["full_cpts"].append({
        "cpt_id": "cz_urbanicity_given_kraj_sldb2021",
        "target": "urbanicity",
        "parents": ["cz_kraj"],
        "table_type": "weighted_full_cpt",
        "source_refs": ["cz_snapshot:" + sid],
        "cpt_weight": 1.0,
        "replace_pairwise_parent_edges": True,
        "rows": [{"parent_assignment": {"cz_kraj": k}, "distribution": dist}
                 for k, dist in urb_cond.items()],
        "notes": [urb_prov.get("pozn", "")],
        "zero_semantics": "structural_zero_from_source",
        "cz_provenance": urb_prov,
    })
    topo.remove("urbanicity")
    topo.insert(topo.index("cz_kraj") + 1, "urbanicity")
    report["nodes"]["urbanicity"]["conditional_on_kraj"] = {"rows": len(urb_cond), "provenance": urb_prov}
    report["nodes"]["cz_kraj"] = {"values_count": len(kraje_nazvy), "prior": kraj_marginal,
                                  "provenance": cz_kraj["cz_provenance"]}

    # --- G9/P7: jazykové konzistenční masky pro CZ hodnotovou sadu -----------
    CZ_PRIMARY_LANG_UZLY = [
        ("Czech", "lang_czech"), ("Slovak", "lang_slovak"),
        ("Ukrainian", "lang_ukrainian"), ("Vietnamese", "lang_vietnamese"),
        ("Russian", "lang_russian"), ("Polish", "lang_polish"),
        ("German", "lang_german"), ("Hungarian", "lang_hungarian"),
        ("English", "lang_english"),
    ]
    cz_primary_podle_uzlu = {uzel: jazyk for jazyk, uzel in CZ_PRIMARY_LANG_UZLY}
    cz_hodnoty_jazyka = nodes["primary_language"]["values"]

    # G8: upstream "budget" masky multilingualism→lang_X byly buď suspendované
    # (podmínka na starou sadu primary_language), nebo předpokládají, že jazyk X
    # nemůže být primární (světová sada češtinu neobsahovala) — s maskou
    # "rodilý mluvčí ⇒ Native" by vznikl nulový průnik. Jednotná náhrada:
    # pro všech 50 lang_* uzlů tři CZ budget masky (mono/bi → max Basic,
    # tri+ → max Conversational), podmíněné primary_language ≠ X.
    lang_uzly = sorted(n["id"] for n in dag["nodes"] if n["id"].startswith("lang_"))
    masks_keep2, cz_lang_masky = [], []
    for m in masks_keep:
        if (m.get("target", "") in lang_uzly
                and "multilingualism" in (m.get("condition") or {})):
            masks_susp.append({"mask_id": m.get("mask_id"),
                               "reason": "nahrazeno_cz_budget_maskou"})
        else:
            masks_keep2.append(m)
    masks_keep = masks_keep2

    for uzel in lang_uzly:
        vlastni = cz_primary_podle_uzlu.get(uzel)
        podminka_primary = [v for v in cz_hodnoty_jazyka if v != vlastni]
        for rezim, bad in [("mono", ["Native", "Fluent", "Conversational"]),
                           ("bi", ["Native", "Fluent", "Conversational"]),
                           ("tri", ["Native", "Fluent"])]:
            ml = {"mono": ["Monolingual"], "bi": ["Bilingual"], "tri": ["Trilingual+"]}[rezim]
            cz_lang_masky.append({
                "mask_id": f"cz_budget_{rezim}_{uzel}",
                "target": uzel,
                "condition": {"multilingualism": ml, "primary_language": podminka_primary},
                "bad_values": bad,
                "preferred_values": [],
                "bad_value_multiplier": 0.0,
                "penalize_values_outside_preferred_set": False,
                "constraint_semantics": "hard_compatibility",
                "cz_provenance": {"evidence": "logical_consistency",
                                  "pozn": "CZ verze upstream budget masky; nefiruje, když je jazyk primární"},
            })

    for jazyk, uzel in CZ_PRIMARY_LANG_UZLY:
        cz_lang_masky.append({
            "mask_id": f"cz_primary_{jazyk.lower()}_requires_{uzel}_native_or_fluent",
            "target": uzel,
            "condition": {"primary_language": [jazyk]},
            "bad_values": ["Conversational", "Basic", "None"],
            "preferred_values": ["Native", "Fluent"],
            "bad_value_multiplier": 0.0,
            "penalize_values_outside_preferred_set": False,
            "constraint_semantics": "hard_compatibility",
            "cz_provenance": {"evidence": "logical_consistency",
                              "pozn": "CZ náhrada suspendovaných v4 primary→lang masek; "
                                      "Romani bez lang_* uzlu — bez masky (viz dokumentace)"},
        })
    cz_lang_masky.append({
        "mask_id": "cz_primary_english_requires_english_proficiency",
        "target": "english_proficiency",
        "condition": {"primary_language": ["English"]},
        "bad_values": ["None", "Basic (A1-A2)", "Intermediate (B1-B2)"],
        "preferred_values": ["Fluent (C1-C2)", "Native"],
        "bad_value_multiplier": 0.0,
        "penalize_values_outside_preferred_set": False,
        "constraint_semantics": "hard_compatibility",
        "cz_provenance": {"evidence": "logical_consistency",
                          "pozn": "rodilý mluvčí angličtiny nemůže mít nízkou english_proficiency"},
    })
    dag["conditional_masks"] = masks_keep + cz_lang_masky

    # ====================== Fáze 4: postojové dimenze z ESS ==================
    from cz.graph import ess_mapping
    schema_values = {n["id"]: n["values"] for n in dag["nodes"]}
    ess_res = ess_mapping.build_ess_priors(
        sdir, schema_values, nodes["demo_disability_status"]["prior"])
    from cz.graph import gesis_mapping
    ess_res.update(gesis_mapping.build_gesis_priors(sdir, schema_values))
    ess_res.update(gesis_mapping.build_gesis_wave2(sdir, schema_values))

    ess_dims = set(ess_res)
    # světové in-hrany a CPT na CZ-survey kalibrované uzly pryč (jinak by
    # deformovaly ESS marginály) — masky zůstávají (logická konzistence)
    edges_keep2 = []
    for e in dag["directed_proposal_edges"]:
        if e["target"] in ess_dims:
            edges_susp.append({"edge_id": e.get("edge_id"), "source": e["source"],
                               "target": e["target"], "reason": "svetovy_prior_na_cz_survey",
                               "rozhodnuti": "nahrazeno_ess_priorem_faze4"})
        else:
            edges_keep2.append(e)
    dag["directed_proposal_edges"] = edges_keep2
    cpts_keep2 = []
    for c in dag["full_cpts"]:
        if c.get("target") in ess_dims and not str(c.get("cpt_id", "")).startswith("cz_"):
            cpts_susp.append({"cpt_id": c.get("cpt_id"), "reason": "svetovy_overlay_na_cz_survey"})
        else:
            cpts_keep2.append(c)
    dag["full_cpts"] = cpts_keep2

    kraj_prior_map = cz_kraj["prior"]
    for dim, info in ess_res.items():
        n = nodes[dim]
        n["prior"] = {v: info["prior"].get(v, 0.0) for v in n["values"]}
        n["cz_provenance"] = info["provenance"]
        n.setdefault("cpd", {})["calibration"] = "cz_ess10_v1"
        ref = n["prior"]
        if info.get("cond"):
            cond_parent = info["cond"]["parent"]
            cond_a = info["cond"]["rows"]
            assert topo.index(cond_parent) < topo.index(dim), \
                f"{cond_parent} musí předcházet {dim} v topologickém pořadí"
            dag["full_cpts"].append({
                "cpt_id": f"cz_{dim}_given_{cond_parent}_ess10",
                "target": dim,
                "parents": [cond_parent],
                "table_type": "weighted_full_cpt",
                "source_refs": ["ess10:joint"],
                "cpt_weight": 1.0,
                "replace_pairwise_parent_edges": True,
                "rows": [{"parent_assignment": {cond_parent: a},
                          "distribution": {v: p for v, p in dist.items() if p > 0}}
                         for a, dist in cond_a.items()],
                "notes": [info["provenance"].get("pozn", "")],
                "zero_semantics": "survey_zero",
                "cz_provenance": info["provenance"],
            })
            # referenční marginál: složení přes afiliační prior; afiliace bez
            # CPT řádku (n<30) padají v sampleru na prior uzlu — stejně v ref
            aff_prior = ess_res[cond_parent]["prior"] if cond_parent in ess_res \
                else nodes[cond_parent]["prior"]
            ref = {v: sum(p_a * cond_a.get(a, info["prior"]).get(v, 0.0)
                          for a, p_a in aff_prior.items())
                   for v in n["values"]}
        if info["cond_kraj"]:
            dag["full_cpts"].append({
                "cpt_id": f"cz_{dim}_given_kraj_ess10",
                "target": dim,
                "parents": ["cz_kraj"],
                "table_type": "weighted_full_cpt",
                "source_refs": ["ess10:" + info["provenance"]["zdroj"].split(":", 1)[1]],
                "cpt_weight": 1.0,
                "replace_pairwise_parent_edges": True,
                "rows": [{"parent_assignment": {"cz_kraj": k},
                          "distribution": {v: p for v, p in dist.items() if p > 0}}
                         for k, dist in info["cond_kraj"].items()],
                "notes": [info["provenance"].get("pozn", "")],
                "zero_semantics": "survey_zero",
                "cz_provenance": info["provenance"],
            })
            ref = {v: sum(kraj_prior_map[k] * info["cond_kraj"][k].get(v, 0.0)
                          for k in info["cond_kraj"]) for v in n["values"]}
        report["nodes"][dim] = {
            "values_changed": False,
            "values_count": len(n["values"]),
            "prior": ref,
            "provenance": info["provenance"],
            "conditional_on_kraj": bool(info["cond_kraj"]),
        }
        if info["cond_kraj"]:
            assert topo.index(dim) > topo.index("cz_kraj"), \
                f"{dim} předchází cz_kraj v topologickém pořadí — CPT by se tiše zahodilo"

    # --- G11/G12: developer dimenze skryté (emit:false) ----------------------
    skryte = []
    for n in dag["nodes"]:
        kat = n.get("category", "")
        if kat.startswith("Developer") or kat == "Skills: Programming":
            n["emit"] = False
            n["cz_provenance"] = {"evidence": "hidden_by_decision",
                                  "pozn": "rozhodnutí: developer dimenze prázdné; uzel se "
                                          "vzorkuje (hrany fungují), ale neemituje do výstupu"}
            skryte.append(n["id"])
    report["hidden_developer_dims"] = {"count": len(skryte), "ids": skryte}

    # --- G1/G2: dispozice suspendovaných hran --------------------------------
    for e in edges_susp:
        if e["source"] == "primary_language" and e["target"].startswith("lang_"):
            e["rozhodnuti"] = "nahrazeno_cz_maskou"
        elif e["source"] == "primary_language":
            e["rozhodnuti"] = "ponechano_neovereno_faze4_komunikacni_styl"
        elif e["source"] == "region":
            cil_kat = nodes.get(e["target"], {}).get("category", "")
            if cil_kat.startswith(("Demographic", "Linguistic", "Learning", "Professional", "Health")):
                e["rozhodnuti"] = "kandidat_cz_krizovky_faze3plus"
            else:
                e["rozhodnuti"] = "ceka_na_faze4_kraj_podmineni"
        else:
            e["rozhodnuti"] = "ponechano_neovereno"

    # přepočet po zásazích Fáze 3 (jazykové masky přibyly do suspendací)
    report["suspended"]["counts"] = {
        "edges": len(edges_susp), "full_cpts": len(cpts_susp), "masks": len(masks_susp),
    }
    report["cz_added"] = {
        "nodes": ["cz_kraj"],
        "full_cpts": [c["cpt_id"] for c in dag["full_cpts"] if str(c.get("cpt_id", "")).startswith("cz_")],
        "masks": len(cz_lang_masky),
    }

    dag["metadata"]["cz"] = {
        "version": "cz_v1_faze4_postoje",
        "snapshot_id": sid,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "changed_nodes": sorted(vypocty.keys()),
        "suspended_counts": report["suspended"]["counts"],
        "note": "Fáze 2: CZ priory jádra; suspendované hrany/CPT/masky nahradí Fáze 3 CZ křížovými tabulkami.",
    }
    dag["metadata"]["name"] = "MatrAIx CZ Persona Graph — Fáze 2 (CZ priors)"

    out_graph = OUT_DIR / "cz_dag.json"
    out_graph.write_text(json.dumps(dag, ensure_ascii=False), encoding="utf-8")

    # --- schéma dimenzí ------------------------------------------------------
    schema = json.loads(UPSTREAM_SCHEMA.read_text())
    for d in schema["dimensions"]:
        if d["id"] in VALUE_CHANGED:
            d["values"] = nodes[d["id"]]["values"]
    for d in schema["dimensions"]:
        if d["id"] == "region":
            d["label"] = "Okres"
            d["description"] = "Okres ČR, kde persona žije (77 jednotek LAU1 vč. Prahy)."
            d["phrase"] = "living in the {value} district, Czechia"
    schema["dimensions"].append({
        "id": "cz_kraj",
        "label": "Kraj",
        "category": "Demographic: Core",
        "description": "Kraj ČR (NUTS3), odvozen z okresu.",
        "values": cz_kraj["values"],
        "index": max(d.get("index", 0) for d in schema["dimensions"]) + 1,
        "phrase": "in the {value} region",
        "defaultValue": None,
    })
    (OUT_DIR.parent / "schema").mkdir(exist_ok=True)
    (OUT_DIR.parent / "schema" / "dimensions.cz.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=1), encoding="utf-8")

    # --- S5: registr provenience všech dimenzí -------------------------------
    import csv as _csv
    cz_official = set(vypocty) | {"cz_kraj", "urbanicity"}
    with (OUT_DIR / "provenance_registry.csv").open("w", encoding="utf-8", newline="") as f:
        wtr = _csv.writer(f)
        wtr.writerow(["dim_id", "category", "emitovano", "provenience", "zdroj"])
        for n in sorted(dag["nodes"], key=lambda x: x.get("index", 0)):
            nid = n["id"]
            if n.get("emit") is False:
                typ = ("hidden-by-decision" if (n.get("cz_provenance", {}).get("evidence")
                                                == "hidden_by_decision") else "latent")
                zdroj = ""
            elif nid in ess_dims:
                typ, zdroj = "CZ-survey", ess_res[nid]["provenance"]["zdroj"]
            elif nid in cz_official:
                typ = "CZ-official"
                zdroj = str((report["nodes"].get(nid, {}).get("provenance") or {}).get("zdroj", ""))
            else:
                typ, zdroj = "world-default", "upstream (neověřeno pro ČR)"
            wtr.writerow([nid, n.get("category", ""), n.get("emit") is not False, typ, zdroj])
    from collections import Counter as _Counter
    typy = _Counter()
    for n in dag["nodes"]:
        if n.get("emit") is False:
            typy["hidden/latent"] += 1
        elif n["id"] in ess_dims:
            typy["CZ-survey"] += 1
        elif n["id"] in cz_official:
            typy["CZ-official"] += 1
        else:
            typy["world-default"] += 1
    report["provenance_summary"] = dict(typy)

    (OUT_DIR / "build_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    c = report["suspended"]["counts"]
    print(f"cz_dag.json: {len(dag['nodes'])} uzlů, {len(edges_keep)} hran "
          f"(suspendováno {c['edges']} hran, {c['full_cpts']} CPT, {c['masks']} masek)")
    print(f"snapshot: {sid}")
    print(f"report: {OUT_DIR / 'build_report.json'}")


if __name__ == "__main__":
    main()
