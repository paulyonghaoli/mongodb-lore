"""Accuracy on the fixed question set, with and without shared memory (contracts: Proof to show).

An answer counts as correct when every expected number appears in the agent's rows
(rounded to 2 decimals; ratios also accepted as percentages).
Run scripts.expected_answers first. Usage: python -m scripts.run_eval
"""
import json
from pathlib import Path

from app import agent
from app.users import get_user

EXPECTED = Path(__file__).resolve().parent.parent / "docs" / "expected_answers.json"

CASES = [
    # Finance lead can read supplier_cost; analysts remain correctly blocked by the guard.
    ("fatima", "What was net margin by region in Q3?", "q1_q3_net_margin_by_region"),
    ("alex", "Return rate by category in September", "q7_return_rate_by_category_september"),
    ("alex", "Sales growth by region, August to September", "q8_sales_growth_by_region_aug_to_sep"),
]


def numbers(rows) -> set[float]:
    out: set[float] = set()
    for r in rows:
        for v in r.values():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out.add(round(v, 2))
                out.add(round(v * 100, 2))
                out.add(round(v / 100, 2))
    return out


def main() -> None:
    expected = json.loads(EXPECTED.read_text())
    results = {True: 0, False: 0}
    for use_memory in (False, True):
        correct = 0
        for user_id, question, key in CASES:
            res = agent.ask(get_user(user_id), question, use_memory=use_memory)
            got = numbers(res["rows"])
            want = {round(v, 2) for r in expected[key] for v in r.values() if isinstance(v, (int, float))}
            ok = want <= got
            correct += ok
            print(f"memory={use_memory!s:5} {'PASS' if ok else 'FAIL'}  {question}")
        results[use_memory] = correct
    n = len(CASES)
    print(f"\nwithout memory: {results[False]}/{n}   with memory: {results[True]}/{n}")


if __name__ == "__main__":
    main()
