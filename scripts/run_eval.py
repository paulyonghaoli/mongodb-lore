"""Accuracy on the fixed question set, with and without shared memory (contracts: Proof to show).

An answer counts as correct when every expected number appears in the agent's rows
(rounded to 2 decimals; ratios also accepted as percentages). The agent picks definitions
differently from run to run, so each case runs --runs times per condition.

While the deliberately wrong Net margin is the active memory, expect the net margin cases to
fail WITH memory and pass without it; approving the correction should flip them.

Run scripts.expected_answers first. Usage: python -m scripts.run_eval [--runs 3] [--workers 4]
"""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app import agent, db
from app.users import get_user

EXPECTED = Path(__file__).resolve().parent.parent / "docs" / "expected_answers.json"

CASES = [
    # Net margin needs supplier_cost, which only the finance lead can see
    ("fatima", "What was net margin by region in Q3?", "q1_q3_net_margin_by_region"),
    ("fatima", "Net margin for each East store since July", "q4_east_store_margin_since_july"),
    ("fatima", "Net margin by category this year", "q6_net_margin_by_category"),
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


def run_case(case: tuple, use_memory: bool, expected: dict) -> tuple[bool, str]:
    user_id, question, key = case
    try:
        res = agent.ask(get_user(user_id), question, use_memory=use_memory)
    except Exception as e:  # an LLM or query failure counts as a wrong answer
        return False, f"error: {e}"
    want = {round(v, 2) for r in expected[key] for v in r.values() if isinstance(v, (int, float))}
    return want <= numbers(res["rows"]), ",".join(res["metrics_used"]) or "-"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1, help="runs per case and condition")
    ap.add_argument("--workers", type=int, default=4, help="questions in flight at once")
    args = ap.parse_args()

    expected = json.loads(EXPECTED.read_text())
    db.app_db(), db.business_db()  # open the clients before the threads share them
    jobs = [(case, mem) for mem in (False, True) for case in CASES for _ in range(args.runs)]
    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(lambda j: run_case(j[0], j[1], expected), jobs))

    totals = {False: 0, True: 0}
    print(f"{'case':58} {'no memory':>10} {'memory':>8}   metrics used (with memory)")
    for case in CASES:
        row = {}
        for mem in (False, True):
            hits = [r for (c, m), r in zip(jobs, results) if c == case and m == mem]
            row[mem] = sum(ok for ok, _ in hits)
            totals[mem] += row[mem]
        metrics = {info for (c, m), (_, info) in zip(jobs, results) if c == case and m}
        print(f"{case[0] + ': ' + case[1]:58} {row[False]:>6}/{args.runs:<3} {row[True]:>4}/{args.runs:<3}  "
              f"{'; '.join(sorted(metrics))}")
    n = len(CASES) * args.runs
    print(f"\nwithout memory: {totals[False]}/{n}   with memory: {totals[True]}/{n}")


if __name__ == "__main__":
    main()
