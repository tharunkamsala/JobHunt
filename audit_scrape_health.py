from __future__ import annotations

import json
from db import connect
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "jobs.db"
COMPANIES_PATH = ROOT / "data" / "companies.json"
EXTRA_COMPANIES_PATH = ROOT / "data" / "extra_companies.json"


@dataclass
class CompanyHealth:
    name: str
    url: str
    latest_source: str
    latest_found: int
    latest_started_at: str
    run_count: int
    positive_runs: int
    max_found: int
    active_jobs: int

    @property
    def risk(self) -> str:
        if self.positive_runs == 0 and self.active_jobs == 0:
            return "high"
        if self.positive_runs == 0 and self.active_jobs > 0:
            return "medium"
        if self.latest_found == 0 and self.active_jobs == 0:
            return "medium"
        return "ok"


def load_company_catalog() -> dict[str, dict]:
    companies = json.loads(COMPANIES_PATH.read_text())
    extra = json.loads(EXTRA_COMPANIES_PATH.read_text()) if EXTRA_COMPANIES_PATH.exists() else []
    merged = {}
    for company in companies + extra:
        merged[company["name"]] = company
    return merged


def fetch_health() -> list[CompanyHealth]:
    catalog = load_company_catalog()
    with connect() as conn:
        latest_rows = conn.execute(
            """
            select company, source, jobs_found, started_at
            from runs
            where id in (
                select max(id) from runs group by company
            )
            """
        ).fetchall()
        latest_by_company = {row["company"]: row for row in latest_rows}

        stats_rows = conn.execute(
            """
            select
                company,
                count(*) as run_count,
                sum(case when jobs_found > 0 then 1 else 0 end) as positive_runs,
                max(jobs_found) as max_found
            from runs
            group by company
            """
        ).fetchall()
        stats_by_company = {row["company"]: row for row in stats_rows}

        active_rows = conn.execute(
            """
            select company, count(*) as active_jobs
            from jobs
            where is_active = 1
            group by company
            """
        ).fetchall()
        active_by_company = {row["company"]: row["active_jobs"] for row in active_rows}

    result: list[CompanyHealth] = []
    for name, company in sorted(catalog.items()):
        latest = latest_by_company.get(name)
        stats = stats_by_company.get(name)
        result.append(
            CompanyHealth(
                name=name,
                url=company.get("url", ""),
                latest_source=latest["source"] if latest else "-",
                latest_found=latest["jobs_found"] if latest else 0,
                latest_started_at=latest["started_at"] if latest else "-",
                run_count=stats["run_count"] if stats else 0,
                positive_runs=stats["positive_runs"] if stats else 0,
                max_found=stats["max_found"] if stats else 0,
                active_jobs=active_by_company.get(name, 0),
            )
        )
    return result


def print_report(rows: list[CompanyHealth]) -> None:
    print(f"companies={len(rows)}")
    print(f"ok={sum(r.risk == 'ok' for r in rows)}")
    print(f"medium={sum(r.risk == 'medium' for r in rows)}")
    print(f"high={sum(r.risk == 'high' for r in rows)}")
    print()

    for risk in ("high", "medium"):
        risky = [r for r in rows if r.risk == risk]
        if not risky:
            continue
        print(f"[{risk}]")
        for row in risky:
            print(
                "\t".join(
                    [
                        row.name,
                        f"latest_source={row.latest_source}",
                        f"latest_found={row.latest_found}",
                        f"positive_runs={row.positive_runs}/{row.run_count}",
                        f"active_jobs={row.active_jobs}",
                        row.latest_started_at,
                        row.url,
                    ]
                )
            )
        print()


if __name__ == "__main__":
    print_report(fetch_health())
