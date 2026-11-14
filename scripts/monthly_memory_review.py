"""Run the previous calendar month's memory and query review scan.

Usage: python -m scripts.monthly_memory_review [YYYY-MM]
Schedule this command monthly with cron or another job scheduler.
"""
import argparse

from app.memory_review import run_monthly


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("month", nargs="?", help="month to scan, in YYYY-MM format")
    args = parser.parse_args()
    print(run_monthly(args.month))


if __name__ == "__main__":
    main()
