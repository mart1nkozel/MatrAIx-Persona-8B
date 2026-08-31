"""Kontrola logických rozporů CZ kohorty (exit Fáze 3, předloha V3).

Kombinuje upstream `consistency_audit` (jejich pravidla — child/parent status,
minor adult-work, blind driver, …) s CZ pravidly:

  CZ1  primary_language z CZ sady ⇒ příslušný lang_* je Native/Fluent
  CZ2  cz_kraj odpovídá okresu (deterministické mapování)
  CZ3  region = Praha ⇒ urbanicity = Dense urban
  CZ4  Monolingual ⇒ žádný nemateřský lang_* nad Basic

  uv run python -m cz.graph.check_consistency [--n 50000] [--seed 42]
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from persona.synthesis.sampler import PersonaForwardSampler, SamplingConfig  # noqa: E402
from persona.synthesis.sampler.audit import consistency_issues  # noqa: E402

from cz.graph import priors  # noqa: E402

CZ_LANG = {
    "Czech": "lang_czech", "Slovak": "lang_slovak", "Ukrainian": "lang_ukrainian",
    "Vietnamese": "lang_vietnamese", "Russian": "lang_russian", "Polish": "lang_polish",
    "German": "lang_german", "Hungarian": "lang_hungarian", "English": "lang_english",
}


def cz_issues(sample: dict, o2k: dict) -> list[str]:
    out = []
    primary = sample.get("primary_language")
    uzel = CZ_LANG.get(primary)
    if uzel and sample.get(uzel) not in ("Native", "Fluent"):
        out.append(f"CZ1 rodilý mluvčí {primary} má {uzel}={sample.get(uzel)}")
    okres = sample.get("region")
    if okres in o2k and sample.get("cz_kraj") != o2k[okres]:
        out.append(f"CZ2 okres {okres} ⇒ kraj {o2k[okres]}, ale cz_kraj={sample.get('cz_kraj')}")
    if okres == "Hlavní město Praha" and sample.get("urbanicity") != "Dense urban":
        out.append(f"CZ3 Praha s urbanicity={sample.get('urbanicity')}")
    if sample.get("multilingualism") == "Monolingual":
        for jazyk, lu in CZ_LANG.items():
            if jazyk != primary and sample.get(lu) in ("Conversational", "Fluent", "Native"):
                out.append(f"CZ4 monolingvní ({primary}) má {lu}={sample.get(lu)}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--graph", default=str(Path(__file__).parent / "cz_dag.json"))
    ap.add_argument("--n", type=int, default=50000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    sampler = PersonaForwardSampler(Path(args.graph), SamplingConfig(seed=args.seed))
    idx = sampler.sample_indices(args.n)
    o2k = priors.okres_do_kraje()

    upstream = Counter()
    cz = Counter()
    for i in range(args.n):
        s = sampler.decode_row(idx, i)
        for issue in consistency_issues(s):
            upstream[issue["rule"]] += 1
        for msg in cz_issues(s, o2k):
            cz[msg.split(" ", 1)[0]] += 1

    print(f"vzorek: {args.n:,} person\n")
    print("upstream pravidla (hard/soft rozpory):")
    if not upstream:
        print("  žádné")
    for rule, cnt in upstream.most_common():
        print(f"  {rule}: {cnt} ({cnt / args.n:.3%})")
    print("\nCZ pravidla:")
    if not cz:
        print("  žádné rozpory")
    for rule, cnt in cz.most_common():
        print(f"  {rule}: {cnt} ({cnt / args.n:.3%})")
    hard = sum(cz.values())
    print("\nVÝSLEDEK:", "PASS — žádné CZ rozpory" if hard == 0 else f"FAIL — {hard} CZ rozporů")
    return 0 if hard == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
