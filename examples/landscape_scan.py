"""Example: a small patent landscape scan (agent-usable workflow).

Equivalent one-shot CLI usage:
    espacenet session start "示例主题专利检索" --goal "摸清核心技术布局"
    espacenet search 'ti="bicycle" AND pa="shimano"' --all --limit 500 -f csv -o hits.csv
    espacenet session end
    espacenet report -o 报告.md

Run from repo root:  python examples/landscape_scan.py
"""

from espacenet_cli.core.journal import end_session, generate_report, start_session
from espacenet_cli.core.search import run_search
from espacenet_cli.utils.edge_backend import EspacenetBackend

QUERY = 'ti="bicycle" AND pa="shimano"'
CSV_PATH = "landscape.csv"


def main():
    journal = start_session(title="示例主题专利检索", goal="演示检索会话留档与报告编译")
    print(f"session started: {journal['id']}")

    backend = EspacenetBackend.create(profile="default", mode="visible", pacing_ms=900)
    try:
        payload = run_search(backend, QUERY, size=50, fetch_all=True, limit=500,
                             on_progress=print)
    finally:
        backend.close()

    import csv

    with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["publicationNumber", "title", "applicants",
                                               "publicationDate", "familyId"])
        writer.writeheader()
        writer.writerows({k: r[k] for k in writer.fieldnames} for r in payload["results"])

    end_session()
    result = generate_report(out="示例检索报告.md")
    print(f"done: {payload['resultCount']} rows -> {CSV_PATH}")
    print(f"report: {result['file']}")


if __name__ == "__main__":
    main()
