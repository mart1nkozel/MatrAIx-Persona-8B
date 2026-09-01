"""Segmentace kohorty a medoidní persony (Fáze 8: F7–F11).

  uv run python -m cz.segmentace --kohorta cz/kohorty/moje --k 6

Rozhodnutí:
- F7 dimenze: výchozí sada = CZ-kalibrované dimenze bez geografie (region a
  cz_kraj jsou filtr, ne segmentační osa — 77 nominálních okresů by Gower
  rozdrobilo geograficky) a bez deterministických odvozenin (health_mobility
  je funkce disability). Lze přepsat --dimenze.
- F7 metoda: k-medoids (PAM-alternate: k-medoids++ init, Voronoiho iterace)
  na Gower matici vzorku (F11: výchozí 4 000 — párové vzdálenosti jsou O(n²));
  celá kohorta se pak přiřadí k nejbližšímu medoidu (O(N·k)).
- F8: reprezentant segmentu = medoid (skutečná persona z kohorty), vzdálenost
  týmiž dimenzemi jako clustering.
- F9 Gower: ordinální dimenze podle pořadí hodnot ve schématu (|rank_i−rank_j|
  normalizované), nominální prostou shodou; hodnoty mimo škálu (Apolitical,
  Prefer not to say) se берou jako chybějící → počítají se jen dimenze
  vyplněné u obou a jmenovatel se přenormalizuje (null-safe, připraveno i na
  budoucí skutečné nully).
- F10 váhy: uniformní 1 (Gower je má jako násobič — ladění později).

Výstup do adresáře kohorty: segmenty.json (velikosti, medoidi, silueta,
odlišující rysy vs. celá kohorta) + prirazeni.parquet (index → segment).
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

GRAPH = Path(__file__).resolve().parent / "graph" / "cz_dag.json"

# Výchozí sada (F7): 12 jádrových os — demografie × politika/hodnoty/technologie.
# Plná kalibrovaná sada (45 dim.) vzdálenosti koncentruje (kvazi-nezávislé
# dimenze ⇒ silueta ~0), viz docs; dostupná přes --dimenze plna.
JADROVE_OSY = ["age_bracket", "highest_education", "demo_employment_status",
               "socioeconomic_band", "urbanicity", "political_lean", "religiosity",
               "trust_level", "att_immigration", "tech_savviness", "cog_optimism",
               "val_family"]

NOMINALNI = ["gender_identity", "demo_employment_status", "primary_language",
             "demo_religion_affiliation", "lstyle_primary_social", "demo_disability_status"]
ORDINALNI = ["age_bracket", "highest_education", "socioeconomic_band", "urbanicity",
             "english_proficiency", "trust_level", "health_general_health",
             "health_mental_health", "cog_optimism", "topic_politics", "att_immigration",
             "lstyle_social_battery", "tech_savviness", "political_lean",
             "demo_political_engagement", "religiosity",
             "schwartz_value_self_direction", "schwartz_value_stimulation",
             "schwartz_value_hedonism", "schwartz_value_achievement", "schwartz_value_power",
             "schwartz_value_security", "schwartz_value_conformity", "schwartz_value_tradition",
             "schwartz_value_benevolence", "schwartz_value_universalism",
             "val_family", "val_community", "val_fun_enjoyment", "val_career_success",
             "val_spirituality_faith", "val_patriotism", "att_free_markets",
             "att_government_regulation", "att_traditional_gender_roles",
             "att_climate_action", "att_ai", "att_vaccines", "att_automation"]
# hodnoty mimo ordinální škálu → chybějící (null-safe větev Goweru)
MIMO_SKALU = {"political_lean": {"Apolitical"}, "religiosity": {"Prefer not to say"},
              "gender_identity": set(), "urbanicity": {"Nomadic / remote"}}


def nacti_kohortu(kohorta: Path) -> list[dict]:
    soubory = sorted(list(kohorta.glob("*.jsonl.gz")) + list(kohorta.glob("*.jsonl")))
    if not soubory:
        raise SystemExit(f"V {kohorta} není jsonl — segmentace potřebuje formát jsonl(.gz)")
    recs = []
    for f in soubory:
        otevrit = gzip.open if f.suffix == ".gz" else open
        with otevrit(f, "rt", encoding="utf-8") as fh:
            recs.extend(json.loads(l) for l in fh)
    return recs


def zakoduj(recs: list[dict], dimenze: list[str], hodnoty: dict) -> tuple[np.ndarray, list[str]]:
    """Matice (n, d): ordinální → rank/(m-1) v [0,1], nominální → kód; NaN = chybějící."""
    n = len(recs)
    sloupce = []
    pouzite = []
    for dim in dimenze:
        vals = hodnoty.get(dim)
        if not vals:
            continue
        mimo = MIMO_SKALU.get(dim, set())
        if dim in ORDINALNI:
            skala = [v for v in vals if v not in mimo]
            rank = {v: i / max(len(skala) - 1, 1) for i, v in enumerate(skala)}
            col = np.array([rank.get(r.get(dim), np.nan) for r in recs], dtype=np.float32)
        else:
            kod = {v: float(i) for i, v in enumerate(vals)}
            col = np.array([kod.get(r.get(dim), np.nan) for r in recs], dtype=np.float32)
        sloupce.append(col)
        pouzite.append(dim)
    return np.stack(sloupce, axis=1), pouzite


def gower_matice(X: np.ndarray, ordinalni_maska: np.ndarray) -> np.ndarray:
    """Plná Gower matice (n×n), float32, null-safe."""
    n, d = X.shape
    D = np.zeros((n, n), dtype=np.float32)
    W = np.zeros((n, n), dtype=np.float32)
    for j in range(d):
        col = X[:, j]
        valid = ~np.isnan(col)
        vv = np.outer(valid, valid)
        if ordinalni_maska[j]:
            dif = np.abs(col[:, None] - col[None, :])
        else:
            dif = (col[:, None] != col[None, :]).astype(np.float32)
        dif = np.where(vv, dif, 0.0).astype(np.float32)
        D += dif
        W += vv.astype(np.float32)
    with np.errstate(invalid="ignore"):
        return np.where(W > 0, D / W, 1.0)


def gower_k_medoidum(X: np.ndarray, M: np.ndarray, ordinalni_maska: np.ndarray) -> np.ndarray:
    """Vzdálenosti všech řádků X k medoidům M: (n, k)."""
    n, d = X.shape
    k = M.shape[0]
    D = np.zeros((n, k), dtype=np.float32)
    W = np.zeros((n, k), dtype=np.float32)
    for j in range(d):
        x = X[:, j][:, None]
        m = M[:, j][None, :]
        vv = ~np.isnan(x) & ~np.isnan(m)
        dif = np.abs(x - m) if ordinalni_maska[j] else (x != m).astype(np.float32)
        D += np.where(vv, dif, 0.0).astype(np.float32)
        W += vv.astype(np.float32)
    with np.errstate(invalid="ignore"):
        return np.where(W > 0, D / W, 1.0)


def k_medoids(D: np.ndarray, k: int, rng: np.random.Generator, max_iter: int = 30):
    n = D.shape[0]
    medoidy = [int(rng.integers(n))]
    for _ in range(k - 1):  # k-medoids++ init
        dmin = D[:, medoidy].min(axis=1)
        p = dmin ** 2
        p = p / p.sum() if p.sum() > 0 else np.full(n, 1 / n)
        medoidy.append(int(rng.choice(n, p=p)))
    medoidy = np.array(medoidy)
    for _ in range(max_iter):
        labels = D[:, medoidy].argmin(axis=1)
        nove = medoidy.copy()
        for c in range(k):
            clen = np.flatnonzero(labels == c)
            if len(clen):
                nove[c] = clen[D[np.ix_(clen, clen)].sum(axis=1).argmin()]
        if (nove == medoidy).all():
            break
        medoidy = nove
    labels = D[:, medoidy].argmin(axis=1)
    return medoidy, labels


def silueta(D: np.ndarray, labels: np.ndarray) -> float:
    n = D.shape[0]
    s = np.zeros(n)
    for c in np.unique(labels):
        vlastni = labels == c
        for i in np.flatnonzero(vlastni):
            a = D[i, vlastni & (np.arange(n) != i)].mean() if vlastni.sum() > 1 else 0.0
            b = min(D[i, labels == j].mean() for j in np.unique(labels) if j != c)
            s[i] = (b - a) / max(a, b) if max(a, b) > 0 else 0.0
    return float(s.mean())


def odlisujici_rysy(recs: list[dict], labels_full: np.ndarray, c: int,
                    dimenze: list[str], top: int = 6) -> list[dict]:
    clen = [r for r, l in zip(recs, labels_full) if l == c]
    rysy = []
    for dim in dimenze:
        pop = pd.Series([r.get(dim) for r in recs]).value_counts(normalize=True)
        seg = pd.Series([r.get(dim) for r in clen]).value_counts(normalize=True)
        for hodnota, p_seg in seg.items():
            p_pop = float(pop.get(hodnota, 0.0))
            if p_seg >= 0.2 and p_pop > 0:
                rysy.append({"dimenze": dim, "hodnota": hodnota,
                             "segment": round(float(p_seg), 3), "populace": round(p_pop, 3),
                             "lift": round(float(p_seg) / p_pop, 2)})
    rysy.sort(key=lambda r: -abs(r["segment"] - r["populace"]))
    return rysy[:top]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kohorta", type=Path, required=True)
    ap.add_argument("--k", type=int, default=6)
    ap.add_argument("--vzorek", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--dimenze", help="čárkami oddělený seznam | 'plna' = všech 45 kalibrovaných (výchozí: 12 jádrových os)")
    args = ap.parse_args()
    t0 = time.time()

    graf = json.loads(GRAPH.read_text())
    hodnoty = {n["id"]: n["values"] for n in graf["nodes"]}
    if args.dimenze == "plna":
        dimenze = ORDINALNI + NOMINALNI
    elif args.dimenze:
        dimenze = args.dimenze.split(",")
    else:
        dimenze = JADROVE_OSY

    recs = nacti_kohortu(args.kohorta)
    print(f"kohorta: {len(recs):,} person")
    X, pouzite = zakoduj(recs, dimenze, hodnoty)
    maska = np.array([d in ORDINALNI for d in pouzite])
    print(f"dimenze pro clustering: {len(pouzite)} ({int(maska.sum())} ordinálních, "
          f"{int((~maska).sum())} nominálních)")

    rng = np.random.default_rng(args.seed)
    vzorek_idx = rng.choice(len(recs), size=min(args.vzorek, len(recs)), replace=False)
    D = gower_matice(X[vzorek_idx], maska)
    print(f"Gower matice {D.shape[0]}×{D.shape[0]} za {time.time()-t0:.1f} s")

    medoidy_s, labels_s = k_medoids(D, args.k, rng)
    sil = silueta(D, labels_s)
    medoid_global = vzorek_idx[medoidy_s]
    labels_full = gower_k_medoidum(X, X[medoid_global], maska).argmin(axis=1)
    print(f"k={args.k}, silueta {sil:.3f}")

    segmenty = []
    for c in range(args.k):
        podil = float((labels_full == c).mean())
        segmenty.append({
            "segment": c,
            "podil": round(podil, 4),
            "n": int((labels_full == c).sum()),
            "medoid_index": int(medoid_global[c]),
            "medoid": recs[medoid_global[c]],
            "odlisujici_rysy": odlisujici_rysy(recs, labels_full, c, pouzite),
        })
        print(f"  segment {c}: {podil:.1%} (medoid #{medoid_global[c]})")

    out = {
        "vytvoreno": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "parametry": {"k": args.k, "vzorek": int(len(vzorek_idx)), "seed": args.seed,
                      "dimenze": pouzite, "vahy": "uniformní (F10 v1)"},
        "silueta_vzorek": round(sil, 4),
        "segmenty": segmenty,
    }
    (args.kohorta / "segmenty.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    pd.DataFrame({"index": np.arange(len(recs)), "segment": labels_full}).to_parquet(
        args.kohorta / "prirazeni.parquet", index=False)
    print(f"→ {args.kohorta}/segmenty.json + prirazeni.parquet ({time.time()-t0:.1f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
