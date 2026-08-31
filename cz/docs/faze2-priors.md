# Fáze 2 — priors demografického jádra: rozhodnutí a výsledky

Stav k 2026-08-31. **Exit kritérium splněno**: kohorta generovaná z
`cz/graph/cz_dag.json` má demografické marginály odpovídající ČSÚ v rámci
tolerance ±1,5 p. b. (viz `check_marginals`, vzorek 200 000, snapshot
`snap-20260831-145205`).

## Výsledné marginály (max |Δ| vs. ČSÚ reference)

| Uzel | max |Δ| | Zdroj prioru |
|---|---|---|
| region (77 okresů) | 0,12 p.b. | OBY02B 2025, Praha z krajské úrovně |
| age_bracket | 0,06 p.b. | OBY02B 2025, jednotky věku → brackety |
| gender_identity | 0,11 p.b. | OBY02B (M/Ž); nebinární kategorie ponechány ze světového prioru |
| highest_education [18+] | 0,13 p.b. | SLDB 2021 Vzdel1 (podrobné, rozlišuje Bc/Mgr/PhD) |
| urbanicity | 0,22 p.b. | SLDB 2021 velikostní skupiny obcí (proxy) |
| primary_language | 0,03 p.b. | SLDB 2021 mateřský jazyk — **nová CZ hodnotová sada** |
| demo_employment_status [18+] | 1,19 p.b. | SLDB 2021 ekonomická aktivita + VŠPS/SLDB dělení úvazků |
| socioeconomic_band | 0,13 p.b. | definice decily SILC (2+2+3+2+1), hranice v Kč v reportu |

## Klíčová rozhodnutí

1. **Vzdělání a status podmíněny věkem už teď** (technicky práce Fáze 3):
   plošný prior 15+ se pral s věkovými maskami (děti tlačeny do nízkých
   kategorií ⇒ dospělý marginál ujel o 4–10 p.b.). Řešení: CZ plné CPT
   `vzdělání|věk` a `status|věk` (řádky pro brackety 18+; mladší brackety
   fallback na prior + masky). γ·w=1 ⇒ sampler reprodukuje kondicionály přesně.
2. **Suspendovány 4 masky vážící CZ marginály na světové dimenze**
   (`persona8b_ses_low_education`, `v4_2_soft_adult_{high_income,stem,law}_low_education`):
   tvrdou nulou vynucovaly světový vztah domain/SES×vzdělání a deformovaly
   ČSÚ marginál (Primary −3,3 p.b.). Fáze 3 je nahradí CZ křížovými tabulkami
   (vzdělání×NACE je už ve snapshotu — ZAMG07). Věkové masky (děti × tituly)
   zůstávají všechny.
3. **primary_language — nová hodnotová sada** (P7): Czech, Slovak, Ukrainian,
   Vietnamese, Russian, Polish, German, Romani, Hungarian, English, Other.
   Moravský sloučen s češtinou; víceodpovědi SLDB normalizovány; Other=0.
   Angličtina jako sekundární jazyk zůstává v dimenzi `english_proficiency`
   (zatím světový prior — CZ kalibrace z Eurobarometru ve Fázi 4).
4. **Gig/freelance = 0**: ČSÚ neodlišuje od OSVČ; dokumentováno v mapování.
5. **Socioekonomická pásma = decily národního rozdělení** (Low=D1–2,
   Lower-middle=D3–4, Middle=D5–7, Upper-middle=D8–9, High=D10) — plně
   datová definice, hranice v Kč (SILC) uložené v build_reportu pro UI.
6. **Nezjištěno** se všude rozpouští proporcionálně (u priorů jádra by null
   znamenal persony bez věku/vzdělání).

## Známé limity (přechází do Fáze 3)

- Kromě `vzdělání|věk` a `status|věk` zůstává jádro **bez CZ křížové
  struktury** — např. urbanicita není podmíněna okresem, domain není vázán
  na vzdělání (persona „25-34, No formal, Social Sciences" je zatím možná).
  Podklady už ve snapshotu z velké části jsou (SLD21A002 vzdělání×věk×velikost
  obce×kraj, ZAMG07 NACE×ISCO×věk×vzdělání).
- 63 hran, 22 CPT a 131 masek suspendováno (úplný výpis s důvody v
  `build_report.json`) — inventura a náhrada = Fáze 3 (G1/G2).
- P8 (zdravotní stav, disabilita) odloženo (P2 priorita).
- Velikost domácnosti (SLD032) stažena, ale schéma nemá přímou dimenzi —
  využije se pro `demo_children_count`/`life_stage` ve Fázi 3.

## Reprodukce

```bash
uv run python -m cz.graph.build_graph                  # cz_dag.json + build_report.json
uv run python persona/synthesis/scripts/validate_graph.py --graph cz/graph/cz_dag.json
uv run python persona/synthesis/scripts/sample_personas.py --graph cz/graph/cz_dag.json \
  --n 200000 --seed 42 --out /tmp/vzorek.jsonl --format jsonl --workers 4
uv run python -m cz.graph.check_marginals /tmp/vzorek.jsonl
```

Determinismus ověřen: dva běhy se stejným seedem a grafem ⇒ identické MD5.
