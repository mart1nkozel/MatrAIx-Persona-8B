# Fáze 3 — graf a pravidla: rozhodnutí a výsledky

Stav k 2026-08-31. **Exit kritérium splněno**: graf je acyklický, prochází
upstream validací, marginály drží (PASS, 200k vzorek) a audit logické
konzistence (upstream pravidla + CZ pravidla CZ1–CZ4) hlásí na 50k vzorku
jediný rozpor s četností 0,002 % (soft pravidlo empty-nester, viz níže).

## G6/G7 — smíšená granularita: uzel `cz_kraj`

Nový uzel `cz_kraj` (14 hodnot NUTS3, emitovaný) s deterministickým
P(kraj|okres) z číselníků. Slouží jako podmiňovací vrstva: urbanicita je nyní
`P(urbanicita | kraj)` ze SLDB velikostních skupin obcí — Praha ⇒ Dense urban
s pravděpodobností 1. **Důsledek (G7): dvě persony ze stejného kraje, ale
jiného okresu, mají identickou distribuci urbanicity (a ve Fázi 4 i postojů)**
— přesnost na úrovni okresu nesou jen demografické priory. Postojové dimenze
se ve Fázi 4 napojí na `cz_kraj`, ne na `region`.

## G8 — revize masek (nález: konflikt s nulovou pravděpodobností)

Nejdůležitější nález fáze: upstream „budget" masky `multilingualism → lang_X`
kódují světový předpoklad, že X nemůže být primární jazyk (stará sada
primary_language češtinu neměla). V kombinaci s CZ maskou „rodilý mluvčí ⇒
Native/Fluent" vznikl **prázdný průnik povolených hodnot** — sampler pak
vzorkoval nesmysl (uniformní rozdělení). Řešení: 114 upstream masek nahrazeno
**150 CZ budget maskami** (3 režimy × 50 `lang_*` uzlů) s dodatečnou podmínkou
`primary_language ≠ X`, + 9 masek „rodilý mluvčí ⇒ Native/Fluent" pro jazyky
CZ sady + 1 maska na `english_proficiency`. Romština `lang_*` uzel nemá —
rodilí Romové (0,15 %) bez proficiency konzistence (dokumentováno).

Suspendace masek celkem 245: 127 (změněné hodnotové sady region/jazyk),
114 (nahrazeny CZ budget verzí), 4 (světová podmínka na CZ marginál, z Fáze 2).

## G1/G2 — dispozice suspendovaných hran (63)

| Rozhodnutí | Počet | Poznámka |
|---|---|---|
| `ceka_na_faze4_kraj_podmineni` | 45 | hrany region→postoje/zájmy; nahradí je podmínění přes cz_kraj z ESS/Eurobarometer dat |
| `nahrazeno_cz_maskou` | 12 | primary_language→lang_* — konzistenci nesou CZ masky |
| `ponechano_neovereno_faze4_komunikacni_styl` | 6 | primary_language→register/jargon/formality… — světové priory, bez CZ podkladu |

Plný výpis s edge_id v `build_report.json` → `suspended.edges`.

## G3 — politika null propagace (rozhodnutí)

V grafu Fáze 3 žádný uzel neemituje null. Až Fáze 4 zavede null pro postojové
dimenze bez CZ podkladu, platí: (1) null je explicitní hodnota v hodnotové
sadě dané dimenze, (2) hrana z null rodiče přispívá do log-proposalu nulou
(fallback na prior cíle), (3) maska s podmínkou na null rodiče nefiruje.
Mechanicky totéž, co sampler už dnes dělá s chybějícím řádkem CPT — žádná
změna sampleru nebude potřeba.

## G4 — validace ✅ / G5 — váhy

Acykličnost a topologické pořadí prochází upstream validací (cz_kraj vložen
do pořadí za region, urbanicita posunuta za cz_kraj). G5: shrinkage γ se
počítá ze samotného grafu automaticky; CZ CPT mají γ·w = 1 ⇒ kondicionály se
reprodukují přesně (ověřeno marginály). Plná rekalibrace vah zbylých
světových hran až po Fázi 4.

## G11/G12 — developer dimenze skryté

66 Developer + 44 Skills: Programming uzlů má `emit: false`: **vzorkují se**
(hrany, kde figurují jako rodič, fungují dál — proto skrytí, ne odstranění),
ale neemitují do výstupu person. Výstup: 1 181 emitovaných dimenzí
(1 309 − 18 latentních − 110 developer). Důsledek dokumentovaný v pre-backlogu
platí: LLM si skryté dimenze při hraní persony doplní vlastními předpoklady.

## Audit konzistence (nástroj `check_consistency`)

CZ pravidla: CZ1 rodilý mluvčí ⇒ lang_* Native/Fluent, CZ2 kraj↔okres,
CZ3 Praha ⇒ Dense urban, CZ4 monolingvní bez cizích jazyků nad Basic.
Výsledek na 50 000 personách: **0 CZ rozporů**; upstream pravidla: 1×
`empty_nester_without_adult_child_signal` (0,002 %, soft životní fáze —
vyřeší CZ kalibrace rodinných dimenzí, Fáze 3+/4).

## Známé vědomé nedostatky

- `english_proficiency` má stále světový prior (bilingvní Češi s Native
  angličtinou ~22 % — nadsazené). CZ kalibrace z Eurobarometru = Fáze 4.
- Budget masky replikují upstream hrubost: druhý jazyk bilingvní persony se
  vyjadřuje jen přes `english_proficiency`, `lang_*` nemateřské stropují na
  Basic/Conversational. Případný redesign až s CZ survey daty (Fáze 4/6).
- `domain` (obor) není vázán na vzdělání/status — kandidátní data v ZAMG07
  (NACE×ISCO×vzdělání×věk) čekají na mapování NACE→domain (Fáze 3+ dovětek).
