"""HTML report kohorty (Fáze 8: F12–F15) — soběstačný soubor bez závislostí.

  uv run python -m cz.report --kohorta cz/kohorty/demo-cr

- F12 grafy: rozložení kalibrovaných dimenzí (CSS bary, česky z label packu)
- F13 provenience: každý graf nese barvu původu — MĚŘENO (referenční hodnota
  ze zdroje, značka ◆) vs. ODVOZENO (vzorek z grafu, bar); SIMULOVÁNO vzniká
  až v chatu a do reportu nepatří (legenda to říká). world-default dimenze
  se nekreslí — report je jen pro CZ-podložené (viz registr provenience).
- F14 srovnání měřeno vs. odvozeno: u každé dimenze badge max |Δ| — funguje
  jako vestavěný validační pohled (výrazný rozdíl = chyba kalibrace).
- F15 rychlý náhled: report čte vzorek (výchozí max 20 000 řádků) — vzniká
  v sekundách i nad milionovou kohortou.
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

CSS = """
body{font-family:-apple-system,'Segoe UI',sans-serif;margin:24px auto;max-width:1080px;
     color:#1a1a1a;background:#fafafa}
h1{font-size:1.5em} h2{font-size:1.15em;margin-top:1.8em;border-bottom:2px solid #ddd;
     padding-bottom:4px}
.meta{background:#fff;border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;
     font-size:.9em;line-height:1.5}
.legenda{display:flex;gap:18px;font-size:.85em;margin:10px 0;flex-wrap:wrap}
.legenda span{display:flex;align-items:center;gap:6px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}
.karta{background:#fff;border:1px solid #e0e0e0;border-radius:8px;padding:10px 14px}
.karta h3{font-size:.95em;margin:0 0 2px}
.zdroj{font-size:.72em;color:#777;margin-bottom:8px}
.badge{float:right;font-size:.72em;padding:1px 7px;border-radius:9px;color:#fff}
.badge.ok{background:#2e7d32}.badge.warn{background:#e65100}
.radek{display:flex;align-items:center;gap:8px;margin:3px 0;font-size:.8em}
.nazev{flex:0 0 42%;text-align:right;color:#444;overflow:hidden;
     text-overflow:ellipsis;white-space:nowrap}
.pruh{flex:1;position:relative;height:15px;background:#f0f0f0;border-radius:3px}
.bar{position:absolute;left:0;top:0;bottom:0;background:#5b8db8;border-radius:3px}
.ref{position:absolute;top:-3px;width:0;height:0;border-left:5px solid transparent;
     border-right:5px solid transparent;border-top:8px solid #c62828;
     transform:translateX(-5px)}
.pct{flex:0 0 44px;font-variant-numeric:tabular-nums;color:#333}
.segment{background:#fff;border:1px solid #e0e0e0;border-radius:8px;padding:12px 16px;
     margin-bottom:10px}
.rys{display:inline-block;background:#eef3f8;border-radius:5px;padding:2px 8px;
     margin:2px 3px;font-size:.78em}
footer{margin-top:2.5em;font-size:.75em;color:#888}
"""


def nacti_vzorek(kohorta: Path, limit: int) -> list[dict]:
    soubory = sorted(list(kohorta.glob("*.jsonl.gz")) + list(kohorta.glob("*.jsonl")))
    recs = []
    for f in soubory:
        otevrit = gzip.open if f.suffix == ".gz" else open
        with otevrit(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                recs.append(json.loads(line))
                if len(recs) >= limit:
                    return recs
    return recs


def graf_dimenze(dim: str, recs: list[dict], info: dict) -> str:
    ref = info.get("reference_18plus") or info["prior"]
    cnt = Counter(r.get(dim) for r in recs)
    n = len(recs)
    max_d = 0.0
    radky = []
    for val, p_ref in sorted(ref.items(), key=lambda kv: -kv[1]):
        p_obs = cnt.get(val, 0) / n
        max_d = max(max_d, abs(p_obs - p_ref) * 100)
        radky.append(
            f'<div class="radek"><div class="nazev" title="{html.escape(str(val))}">'
            f'{html.escape(hodnota(dim, str(val)))}</div>'
            f'<div class="pruh"><div class="bar" style="width:{p_obs*100:.1f}%"></div>'
            f'<div class="ref" style="left:{min(p_ref*100, 100):.1f}%"></div></div>'
            f'<div class="pct">{p_obs*100:.1f}%</div></div>')
    zdroj = str((info.get("provenance") or {}).get("zdroj", ""))
    badge = ('<span class="badge ok">Δ %.1f</span>' if max_d <= 1.5
             else '<span class="badge warn">Δ %.1f</span>') % max_d
    return (f'<div class="karta">{badge}<h3>{html.escape(label(dim))}</h3>'
            f'<div class="zdroj">měřeno: {html.escape(zdroj)}</div>{"".join(radky)}</div>')


def sekce_segmentu(kohorta: Path) -> str:
    f = kohorta / "segmenty.json"
    if not f.exists():
        return ""
    data = json.loads(f.read_text())
    out = [f'<h2>Segmenty (k={data["parametry"]["k"]}, '
           f'silueta {data["silueta_vzorek"]:.2f})</h2>']
    for s in sorted(data["segmenty"], key=lambda x: -x["podil"]):
        m = s["medoid"]
        rysy = "".join(
            f'<span class="rys">{html.escape(label(r["dimenze"]))}: '
            f'{html.escape(hodnota(r["dimenze"], str(r["hodnota"])))} '
            f'({r["segment"]:.0%} vs {r["populace"]:.0%})</span>'
            for r in s["odlisujici_rysy"][:5])
        out.append(
            f'<div class="segment"><b>Segment {s["segment"]}</b> — {s["podil"]:.1%} kohorty '
            f'(n={s["n"]:,})<br><small>medoid: {html.escape(str(m.get("gender_identity")))}, '
            f'{html.escape(str(m.get("age_bracket")))}, {html.escape(str(m.get("region")))}, '
            f'{html.escape(hodnota("highest_education", str(m.get("highest_education"))))}, '
            f'{html.escape(hodnota("demo_employment_status", str(m.get("demo_employment_status"))))}'
            f'</small><br>{rysy}</div>')
    return "".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kohorta", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=20_000, help="F15: velikost náhledového vzorku")
    args = ap.parse_args()
    t0 = time.time()

    manifest = json.loads((args.kohorta / "manifest.json").read_text()) \
        if (args.kohorta / "manifest.json").exists() else {}
    build = json.loads(BUILD_REPORT.read_text())
    recs = nacti_vzorek(args.kohorta, args.limit)
    if not recs:
        raise SystemExit("Kohorta nemá jsonl data (report neumí codes formát)")
    dospeli = [r for r in recs if r.get("age_bracket") in
               {"18-24", "25-34", "35-44", "45-54", "55-64", "65-74", "75-84", "85+"}]

    poz = manifest.get("pozadavek", {})
    ctyrd = manifest.get("vstupni_4d") or {}
    grafy = []
    for dim, info in build["nodes"].items():
        zdroj = str((info.get("provenance") or {}).get("zdroj", ""))
        merene_na_15plus = zdroj.startswith(("ess10", "gesis:")) or \
            dim in ("highest_education", "demo_employment_status")
        vyber = dospeli if merene_na_15plus else recs
        if vyber:
            grafy.append(graf_dimenze(dim, vyber, info))

    html_out = f"""<!DOCTYPE html><html lang="cs"><head><meta charset="utf-8">
<title>Kohorta {html.escape(args.kohorta.name)}</title><style>{CSS}</style></head><body>
<h1>Kohorta „{html.escape(args.kohorta.name)}"</h1>
<div class="meta">
<b>n:</b> {manifest.get('vysledek', {}).get('n_vygenerovano', len(recs)):,} person
(náhled z {len(recs):,}) &nbsp; <b>seed:</b> {poz.get('seed', '?')} &nbsp;
<b>snapshot:</b> {html.escape(str(manifest.get('graf', {}).get('snapshot_id', '?')))} &nbsp;
<b>graf:</b> {html.escape(str(manifest.get('graf', {}).get('sha256', ''))[:16])}…<br>
<b>filtry:</b> {html.escape(json.dumps(poz.get('filtry', {}), ensure_ascii=False))}
{('<br><b>4D zadání:</b> „' + html.escape(ctyrd.get('zadani', '')) + '"') if ctyrd else ''}
</div>
<div class="legenda">
<span><div style="width:22px;height:11px;background:#5b8db8;border-radius:3px"></div>
 ODVOZENO — vzorek z modelu (necitovat jako zdrojová data)</span>
<span><div class="ref" style="position:static;transform:none"></div>
 MĚŘENO — referenční hodnota ze zdroje (ČSÚ/ESS/EB, citovatelné)</span>
<span>SIMULOVÁNO — vzniká až v chatu person, v reportu není</span>
</div>
<p style="font-size:.82em;color:#666">Zobrazeny jen CZ-kalibrované dimenze
({len(grafy)} ze 48); zbytek schématu nese světové priory — viz registr
provenience. Survey dimenze srovnány na subpopulaci 18+. Badge Δ = max rozdíl
měřeno vs. odvozeno v p. b. (F14 — výrazný rozdíl by značil chybu kalibrace).</p>
<h2>Rozložení dimenzí</h2>
<div class="grid">{''.join(grafy)}</div>
{sekce_segmentu(args.kohorta)}
<footer>MatrAIx CZ — vygenerováno {time.strftime('%Y-%m-%d %H:%M')} za
{time.time()-t0:.1f} s. Nástroj slouží ke screeningu a relativnímu srovnání,
ne k tvrdým číslům o reálné populaci (zděděná omezení, viz PRE-BACKLOG).</footer>
</body></html>"""

    out = args.kohorta / "report.html"
    out.write_text(html_out, encoding="utf-8")
    print(f"report → {out} ({time.time()-t0:.1f} s, {len(grafy)} grafů)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
