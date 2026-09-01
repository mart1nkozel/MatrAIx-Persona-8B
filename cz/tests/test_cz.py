"""Unit testy CZ vrstvy (Fáze 9, O2).

  uv run pytest cz/tests -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from cz.data.snapshots import query_hash  # noqa: E402
from cz.segmentace import gower_k_medoidum, gower_matice, k_medoids  # noqa: E402

GRAPH = REPO / "cz" / "graph" / "cz_dag.json"
SNAPSHOTS = REPO / "cz" / "data" / "snapshots"


# ------------------------------------------------------------------ Gower

def test_gower_symetrie_a_diagonala():
    X = np.array([[0.0, 1.0], [0.5, 2.0], [1.0, 1.0]], dtype=np.float32)
    maska = np.array([True, False])  # 1. ordinální, 2. nominální
    D = gower_matice(X, maska)
    assert np.allclose(D, D.T)
    assert np.allclose(np.diag(D), 0.0)
    # ordinální: |0-0.5|=0.5; nominální: 1≠2 → 1 ⇒ průměr 0.75
    assert D[0, 1] == pytest.approx(0.75)
    # ordinální |0-1|=1, nominální shoda 0 ⇒ 0.5
    assert D[0, 2] == pytest.approx(0.5)


def test_gower_null_safe_prenormalizace():
    X = np.array([[0.0, np.nan], [1.0, 1.0]], dtype=np.float32)
    maska = np.array([True, False])
    D = gower_matice(X, maska)
    # druhá dimenze chybí u prvního → počítá se jen ordinální: |0-1|/1 = 1
    assert D[0, 1] == pytest.approx(1.0)


def test_gower_k_medoidum_konzistentni_s_matici():
    rng = np.random.default_rng(0)
    X = rng.random((30, 4)).astype(np.float32)
    maska = np.array([True, True, False, False])
    D = gower_matice(X, maska)
    D2 = gower_k_medoidum(X, X[:5], maska)
    assert np.allclose(D[:, :5], D2, atol=1e-6)


def test_k_medoids_najde_oddelene_shluky():
    rng = np.random.default_rng(1)
    a = rng.normal(0.1, 0.02, (40, 3)).astype(np.float32)
    b = rng.normal(0.9, 0.02, (40, 3)).astype(np.float32)
    X = np.vstack([a, b]).clip(0, 1)
    D = gower_matice(X, np.array([True] * 3))
    _, labels = k_medoids(D, 2, np.random.default_rng(2))
    prvni, druha = set(labels[:40]), set(labels[40:])
    assert len(prvni) == 1 and len(druha) == 1 and prvni != druha


# ------------------------------------------------------------------ snapshoty

def test_query_hash_deterministicky_a_na_poradi_nezavisly():
    a = query_hash({"x": 1, "y": [2, 3]})
    b = query_hash({"y": [2, 3], "x": 1})
    assert a == b and len(a) == 16
    assert query_hash({"x": 2}) != a


# ------------------------------------------------------------------ generate

def test_parse_filtry_a_validace():
    from cz.generate import parse_filtry
    f = parse_filtry(["region=Hlavní město Praha", "age_bracket=18-24|25-34"])
    assert f["region"] == ["Hlavní město Praha"]
    assert f["age_bracket"] == ["18-24", "25-34"]
    with pytest.raises(SystemExit):
        parse_filtry(["bez_rovnitka"])


@pytest.mark.skipif(not GRAPH.exists(), reason="cz_dag.json není postavený")
def test_rozdel_filtry_clamp_vs_rejection():
    from persona.synthesis.sampler import PersonaForwardSampler, SamplingConfig
    from cz.generate import rozdel_filtry
    s = PersonaForwardSampler(GRAPH, SamplingConfig(seed=0))
    clampy, zbytek = rozdel_filtry(s, {"region": ["Hlavní město Praha"],
                                       "cz_kraj": ["Jihomoravský kraj"]})
    assert clampy == {"region": "Hlavní město Praha"}   # kořen → clamp
    assert "cz_kraj" in zbytek                          # CPT cíl → rejection
    with pytest.raises(SystemExit):
        rozdel_filtry(s, {"region": ["Atlantida"]})


# ------------------------------------------------------------------ graf/mapování

@pytest.mark.skipif(not GRAPH.exists(), reason="cz_dag.json není postavený")
def test_cz_graf_zakladni_invarianty():
    dag = json.loads(GRAPH.read_text())
    nodes = {n["id"]: n for n in dag["nodes"]}
    assert nodes["region"]["values_count"] == 77
    assert "cz_kraj" in nodes and nodes["cz_kraj"]["values_count"] == 14
    assert "Czech" in nodes["primary_language"]["values"]
    for n in dag["nodes"]:
        if n.get("prior"):
            assert abs(sum(n["prior"].values()) - 1.0) < 1e-6, n["id"]


def _posledni_snapshot() -> Path | None:
    if not SNAPSHOTS.exists():
        return None
    kompletni = [p for p in sorted(SNAPSHOTS.iterdir())
                 if (p / "manifest.json").exists()
                 and not json.loads((p / "manifest.json").read_text()).get("partial")]
    return kompletni[-1] if kompletni else None


@pytest.mark.skipif(_posledni_snapshot() is None, reason="žádný snapshot")
def test_ess_mapovani_vraci_normalizovane_priory():
    from cz.graph.ess_mapping import build_ess_priors
    dims = {n["id"]: n["values"] for n in json.loads(GRAPH.read_text())["nodes"]}
    res = build_ess_priors(_posledni_snapshot(), dims,
                           dims and {v: 1 / 7 for v in dims["demo_disability_status"]})
    assert len(res) >= 24
    for dim, info in res.items():
        assert abs(sum(info["prior"].values()) - 1.0) < 1e-6, dim
        assert info["provenance"]["zdroj"].startswith("ess10")


# ------------------------------------------------------------------ čeština

def test_karta_cs_je_cesky():
    from cz.lang.render_cs import karta_cs
    p = {"gender_identity": "Woman", "age_bracket": "25-34",
         "region": "Brno-město", "cz_kraj": "Jihomoravský kraj",
         "urbanicity": "Dense urban", "primary_language": "Czech",
         "english_proficiency": "Intermediate (B1-B2)",
         "highest_education": "Master's", "demo_employment_status": "Full-time",
         "socioeconomic_band": "Middle"}
    karta = karta_cs(p)
    assert "PROFIL PERSONY" in karta
    assert "Žena" in karta and "Brno-město" in karta
    assert "čeština" in karta and "magisterské" in karta.lower()
