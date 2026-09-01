"""HTML report kohorty (F12–F15) — čistý, srozumitelný laikovi.

  uv run python -m cz.report --kohorta cz/kohorty/cesko [--populace 10909500]

- procenta se zaokrouhlují metodou největších zbytků → součet je přesně 100,0 %
- u nefiltrované kohorty se ukazuje i přepočet na obyvatele Česka
- dlouhé číselníky (okresy) se zkracují na top 15 + „Ostatní"
- sloupec = model, značka ▼ = oficiální statistika; ✓ = shoda se statistikou
- technické detaily (zdroje, seed, otisky) jsou sbalené dole v „O datech"
"""

from __future__ import annotations

import argparse
import gzip
import html
import json
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from cz.lang.render_cs import hodnota, label  # noqa: E402

BUILD_REPORT = Path(__file__).resolve().parent / "graph" / "build_report.json"
POPULACE_CR = 10_909_500  # ČSÚ k 1. 1. 2025
DOSPELI = {"18-24", "25-34", "35-44", "45-54", "55-64", "65-74", "75-84", "85+"}

SEKCE = [
    ("Kdo jsou", ["age_bracket", "gender_identity", "highest_education",
                  "demo_employment_status", "socioeconomic_band", "urbanicity",
                  "cz_kraj", "region", "primary_language", "english_proficiency",
                  "domain"]),
    ("Co si myslí", ["political_lean", "demo_political_engagement", "topic_politics",
                     "att_immigration", "att_climate_action", "att_ai", "att_automation",
                     "att_vaccines", "att_free_markets", "att_government_regulation",
                     "att_traditional_gender_roles", "trust_level"]),
    ("Čemu věří a co je pro ně důležité", ["religiosity", "demo_religion_affiliation",
                                           "val_family", "val_community", "val_fun_enjoyment",
                                           "val_career_success", "val_spirituality_faith",
                                           "val_patriotism", "schwartz_value_self_direction",
                                           "schwartz_value_stimulation", "schwartz_value_hedonism",
                                           "schwartz_value_achievement", "schwartz_value_power",
                                           "schwartz_value_security", "schwartz_value_conformity",
                                           "schwartz_value_tradition", "schwartz_value_benevolence",
                                           "schwartz_value_universalism"]),
    ("Zdraví a životní styl", ["health_general_health", "health_mental_health",
                               "demo_disability_status", "health_mobility", "cog_optimism",
                               "lstyle_social_battery", "tech_savviness",
                               "lstyle_primary_social"]),
]
MAX_RADKU = 15

CSS = """
body{font-family:-apple-system,'Segoe UI',sans-serif;margin:24px auto;max-width:1080px;
     color:#1a1a1a;background:#fafafa}
h1{font-size:1.5em;margin-bottom:2px} .podtitul{color:#555;margin-bottom:18px}
h2{font-size:1.2em;margin-top:2em;border-bottom:2px solid #ddd;padding-bottom:4px}
.legenda{font-size:.85em;color:#555;margin:8px 0 16px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}
.karta{background:#fff;border:1px solid #e0e0e0;border-radius:8px;padding:10px 14px}
.karta h3{font-size:.98em;margin:0 0 8px}
.znamka{float:right;font-size:.85em}
.radek{display:flex;align-items:center;gap:8px;margin:3px 0;font-size:.8em}
.nazev{flex:0 0 44%;text-align:right;color:#444;overflow:hidden;
     text-overflow:ellipsis;white-space:nowrap}
.pruh{flex:1;position:relative;height:15px;background:#f0f0f0;border-radius:3px}
.bar{position:absolute;left:0;top:0;bottom:0;background:#5b8db8;border-radius:3px}
.ref{position:absolute;top:-3px;width:0;height:0;border-left:5px solid transparent;
     border-right:5px solid transparent;border-top:8px solid #c62828;
     transform:translateX(-5px)}
.pct{flex:0 0 46px;font-variant-numeric:tabular-nums;color:#333}
.abs{flex:0 0 74px;font-variant-numeric:tabular-nums;color:#888;font-size:.92em;
     text-align:right}
.segment{background:#fff;border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;
     margin-bottom:10px}
.rys{display:inline-block;background:#eef3f8;border-radius:5px;padding:2px 8px;
     margin:2px 3px;font-size:.78em}
details{margin-top:2.5em;font-size:.8em;color:#666}
summary{cursor:pointer;font-weight:600}
"""


def zaokrouhli_na_sto(podily: list[float], des: int = 1) -> list[float]:
    """Největší zbytky: zaokrouhlené hodnoty dají přesně 100.0."""
    f = 10 ** des
    cile = [p * 100 * f for p in podily]
    dole = [int(c) for c in cile]
    chybi = round(100 * f) - sum(dole)
    poradi = sorted(range(len(cile)), key=lambda i: -(cile[i] - dole[i]))
    for i in poradi[:max(chybi, 0)]:
        dole[i] += 1
    return [d / f for d in dole]


def nacti_vzorek(kohorta: Path, limit: int, dimenze: set[str]) -> list[dict]:
    soubory = sorted(list(kohorta.glob("*.jsonl.gz")) + list(kohorta.glob("*.jsonl")))
    recs = []
    for f in soubory:
        otevrit = gzip.open if f.suffix == ".gz" else open
        with otevrit(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                recs.append({d: r.get(d) for d in dimenze})
                if len(recs) >= limit:
                    return recs
    return recs


def graf_dimenze(dim: str, recs: list[dict], info: dict, populace: int | None) -> str:
    ref = info.get("reference_18plus") or info["prior"]
    cnt = Counter(r.get(dim) for r in recs)
    n = len(recs)
    polozky = sorted(ref.items(), key=lambda kv: -kv[1])
    if len(polozky) > MAX_RADKU:
        top = polozky[:MAX_RADKU]
        zbytek_ref = sum(p for _, p in polozky[MAX_RADKU:])
        zbytek_obs = sum(cnt.get(v, 0) for v, _ in polozky[MAX_RADKU:]) / n
        polozky = top + [(f"Ostatní ({len(ref) - MAX_RADKU})", zbytek_ref)]
        obs = [cnt.get(v, 0) / n for v, _ in top] + [zbytek_obs]
    else:
        obs = [cnt.get(v, 0) / n for v, _ in polozky]

    obs_kulate = zaokrouhli_na_sto(obs)
    max_d = max(abs(o - p) * 100 for o, (_, p) in zip(obs, polozky))
    znamka = "✓" if max_d <= 1.5 else "⚠"
    radky = []
    for (val, p_ref), p_obs, p_kulate in zip(polozky, obs, obs_kulate):
        nazev = val if str(val).startswith("Ostatní") else hodnota(dim, str(val))
        absolutne = (f'<div class="abs">{round(populace * p_obs / 1000) * 1000:,}</div>'
                     .replace(",", " ") if populace else "")
        radky.append(
            f'<div class="radek"><div class="nazev" title="{html.escape(str(nazev))}">'
            f'{html.escape(str(nazev))}</div>'
            f'<div class="pruh"><div class="bar" style="width:{p_obs*100:.1f}%"></div>'
            f'<div class="ref" style="left:{min(p_ref*100, 100):.1f}%"></div></div>'
            f'<div class="pct">{p_kulate:.1f}%</div>{absolutne}</div>')
    return (f'<div class="karta"><span class="znamka" title="shoda se statistikou">{znamka}</span>'
            f'<h3>{html.escape(label(dim))}</h3>{"".join(radky)}</div>')


def sekce_segmentu(kohorta: Path, populace: int | None) -> str:
    f = kohorta / "segmenty.json"
    if not f.exists():
        return ""
    data = json.loads(f.read_text())
    out = ["<h2>Skupiny obyvatel</h2>",
           '<p class="legenda">Kohorta rozdělená do podobnostních skupin; '
           'každou reprezentuje jedna typická persona.</p>']
    for s in sorted(data["segmenty"], key=lambda x: -x["podil"]):
        m = s["medoid"]
        kolik = (f' ≈ {round(populace * s["podil"] / 1000) * 1000:,} lidí'.replace(",", " ")
                 if populace else "")
        rysy = "".join(
            f'<span class="rys">{html.escape(label(r["dimenze"]))}: '
            f'{html.escape(hodnota(r["dimenze"], str(r["hodnota"])))}</span>'
            for r in s["odlisujici_rysy"][:5])
        out.append(
            f'<div class="segment"><b>{s["podil"]:.0%} kohorty{kolik}</b><br>'
            f'<small>typická persona: {html.escape(hodnota("gender_identity", str(m.get("gender_identity"))))}, '
            f'{html.escape(str(m.get("age_bracket")))} let, {html.escape(str(m.get("region")))}, '
            f'{html.escape(hodnota("highest_education", str(m.get("highest_education"))).lower())}, '
            f'{html.escape(hodnota("demo_employment_status", str(m.get("demo_employment_status"))).lower())}'
            f'</small><br>{rysy}</div>')
    return "".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kohorta", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=50_000)
    ap.add_argument("--populace", type=int,
                    help="přepočet na absolutní počty (výchozí: 10 909 500 u nefiltrované kohorty)")
    args = ap.parse_args()
    t0 = time.time()

    manifest = json.loads((args.kohorta / "manifest.json").read_text()) \
        if (args.kohorta / "manifest.json").exists() else {}
    build = json.loads(BUILD_REPORT.read_text())
    recs = nacti_vzorek(args.kohorta, args.limit,
                        set(build["nodes"]) | {"age_bracket"})
    if not recs:
        raise SystemExit("Kohorta nemá jsonl data")
    dospeli = [r for r in recs if r.get("age_bracket") in DOSPELI]

    poz = manifest.get("pozadavek", {})
    filtry = poz.get("filtry") or {}
    populace = args.populace or (POPULACE_CR if not filtry else None)
    ctyrd = manifest.get("vstupni_4d") or {}

    if populace:
        podtitul = (f"Vzorek {len(recs):,} syntetických person reprezentuje "
                    f"{populace:,} obyvatel Česka.").replace(",", " ")
    else:
        popis_f = ", ".join(f"{label(d)}: {'/'.join(hodnota(d, v) for v in vs)}"
                            for d, vs in filtry.items())
        podtitul = (f"Vzorek {len(recs):,} syntetických person; výběr: {popis_f}."
                    ).replace(",", " ")

    sekce_html = []
    for nazev, dims in SEKCE:
        grafy = []
        for dim in dims:
            info = build["nodes"].get(dim)
            if not info:
                continue
            zdroj = str((info.get("provenance") or {}).get("zdroj", ""))
            jen_dospeli = zdroj.startswith(("ess10", "gesis:")) or \
                dim in ("highest_education", "demo_employment_status")
            vyber = dospeli if jen_dospeli else recs
            if vyber:
                grafy.append(graf_dimenze(dim, vyber, info,
                                          populace if not jen_dospeli else None))
        if grafy:
            sekce_html.append(f"<h2>{nazev}</h2><div class='grid'>{''.join(grafy)}</div>")

    graf_meta = manifest.get("graf", {})
    html_out = f"""<!DOCTYPE html><html lang="cs"><head><meta charset="utf-8">
<title>{html.escape(args.kohorta.name)}</title><style>{CSS}</style></head><body>
<h1>Syntetická populace: {html.escape(ctyrd.get('zadani') or args.kohorta.name)}</h1>
<p class="podtitul">{podtitul}</p>
<p class="legenda">Modrý sloupec = náš model &nbsp;·&nbsp;
<span style="color:#c62828">▼</span> = oficiální statistika (ČSÚ a evropské výzkumy)
&nbsp;·&nbsp; ✓ = model se statistikou souhlasí. Postojové otázky se týkají dospělých.</p>
{''.join(sekce_html)}
{sekce_segmentu(args.kohorta, populace)}
<details><summary>O datech</summary>
<p>Persony jsou vygenerované statistickým modelem kalibrovaným na česká data:
Český statistický úřad (sčítání 2021, demografie 2025, VŠPS), European Social
Survey (2020/21) a Eurobarometr/ISSP/EVS. U zobrazených vlastností model
odpovídá zdrojovým statistikám; ostatní vlastnosti person (zájmy, osobnost)
vycházejí z mezinárodních odhadů a v reportu nejsou. Nástroj slouží
k orientačnímu průzkumu a porovnávání — ne jako náhrada skutečného výzkumu.</p>
<p>vzorek {len(recs):,} · seed {poz.get('seed', '?')} ·
data {html.escape(str(graf_meta.get('snapshot_id', '?')))} ·
model {html.escape(str(graf_meta.get('sha256', ''))[:16])}… ·
vygenerováno {time.strftime('%d.%m.%Y %H:%M')}</p>
</details></body></html>"""

    out = args.kohorta / "report.html"
    out.write_text(html_out, encoding="utf-8")
    print(f"report → {out} ({time.time()-t0:.1f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
