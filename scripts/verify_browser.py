"""Verify desktop/mobile browser behavior against existing SIMULATED runs.

Works against a local server or the actual Railway public origin. Install optional
Playwright tooling separately; this script never creates or changes experiment data.
"""

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

from verify_release import check, csv_evidence, validated_base_url, verify_package


def run_checks(args, results):
    base, out, primary = args.base_url, args.output_dir, args.run_ids[-1]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.set_default_timeout(args.timeout * 1000)
        context.set_default_navigation_timeout(args.timeout * 1000)
        runs = {}
        for run_id in args.run_ids:
            response = context.request.get(f"{base}/api/v1/runs/{run_id}/")
            check(response.status == 200, f"Run {run_id}: HTTP {response.status}")
            runs[run_id] = response.json()
            check(
                runs[run_id]["source"] == "SIMULATED",
                f"Run {run_id} is not SIMULATED; choose dedicated verification runs",
            )
            check(
                runs[run_id]["status"] in ("COMPLETED", "LOCKED"),
                f"Run {run_id} must be COMPLETED or LOCKED",
            )
        response = context.request.get(f"{base}/api/v1/runs/{primary}/stats/")
        check(response.status == 200, f"Primary statistics: HTTP {response.status}")
        summary = response.json()
        sample_count = summary["sample_count"]
        check(
            sample_count >= 100,
            "Primary run needs at least 100 samples to verify the visible window",
        )
        page, errors, api_failures = context.new_page(), [], []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.on(
            "response",
            lambda response: (
                api_failures.append({"url": response.url, "status": response.status})
                if "/api/" in response.url and response.status >= 400
                else None
            ),
        )

        def ready():
            page.wait_for_function(
                "document.getElementById('connection').textContent !== 'Connecting'"
            )
            page.wait_for_function("!busy")
            check(
                page.locator("#error").is_hidden(), page.locator("#error").inner_text()
            )

        for route in (
            "/",
            "/runs/",
            "/live/",
            "/analysis/",
            "/compare/",
            "/fpga/",
            "/events/",
            "/paper/",
            "/system/",
            f"/runs/{primary}/",
            f"/runs/{primary}/paper/",
        ):
            started = time.perf_counter()
            response = page.goto(f"{base}{route}?run_id={primary}")
            check(response.status == 200, f"{route}: HTTP {response.status}")
            ready()
            chart_points = page.evaluate(
                "Object.fromEntries(Object.entries(charts).map(([k,c])=>[k,c.data.datasets[0].data.filter(v=>v!==null).length]))"
            )
            paper = route in ("/paper/", f"/runs/{primary}/paper/")
            if route in ("/", "/live/", "/analysis/", f"/runs/{primary}/") or paper:
                expected = min(1000 if paper else 500, sample_count)
                check(
                    len(chart_points) == 5
                    and all(value == expected for value in chart_points.values()),
                    f"{route}: expected {expected} chart points: {chart_points}",
                )
                check(
                    page.locator("#source").get_attribute("data-source") == "SIMULATED",
                    "Visible source label missing",
                )
            if route == "/compare/":
                page.locator("#compare-runs").select_option(
                    [str(run_id) for run_id in args.run_ids]
                )
                page.locator("#compare-button").click()
                page.wait_for_selector("#comparison tbody tr")
                check(
                    page.locator("#comparison tbody tr").count()
                    == len(args.run_ids) * 2,
                    "Comparison sensor row count mismatch",
                )
                check(
                    "SIMULATED" in page.locator("#comparison").inner_text(),
                    "Comparison source label missing",
                )
            if route == "/fpga/":
                check(
                    chart_points == {"diagnostics": min(500, sample_count)},
                    f"FPGA diagnostics chart count mismatch: {chart_points}",
                )
            if route == "/":
                page.locator("#window").select_option("100")
                page.wait_for_function("!busy && charts.do.data.labels.length===100")
                with page.expect_download() as download:
                    page.locator(".chart-heading button").first.click()
                download.value.save_as(out / "simulated-do-chart.png")
                check(
                    (out / "simulated-do-chart.png")
                    .read_bytes()
                    .startswith(b"\x89PNG\r\n\x1a\n"),
                    "PNG download signature invalid",
                )
                page.screenshot(
                    path=str(out / "dashboard-simulated.png"), full_page=True
                )
                with page.expect_download() as download:
                    page.locator("#csv").click()
                csv_path = out / f"run-{primary}-simulated.csv"
                download.value.save_as(csv_path)
                with csv_path.open(encoding="utf-8-sig", newline="") as stream:
                    csv_info = csv_evidence(stream, sample_count)
                results.append(
                    {
                        "check": "100-sample window, PNG and CSV download",
                        "run_id": primary,
                        "csv": csv_info,
                        "result": "PASS",
                    }
                )
            if route == "/paper/":
                check(
                    page.locator("aside").count() == 0,
                    "Paper view includes navigation sidebar",
                )
                check(
                    "SIMULATED" in page.locator("#source").inner_text(),
                    "Paper source label missing",
                )
                page.screenshot(path=str(out / "paper-simulated.png"), full_page=True)
                # Exercise the print control without opening a modal print dialog.
                page.evaluate(
                    "window.__printRequested = false; window.print = () => { window.__printRequested = true; }"
                )
                page.locator("#print").click()
                check(
                    page.evaluate("window.__printRequested"),
                    "Print control did not invoke window.print",
                )
                page.emulate_media(media="print")
                check(
                    page.locator("#source").is_visible(),
                    "Print styles hide the source label",
                )
                page.pdf(
                    path=str(out / "paper-simulated.pdf"),
                    format="A4",
                    print_background=True,
                )
                check(
                    (out / "paper-simulated.pdf").read_bytes().startswith(b"%PDF-"),
                    "PDF signature invalid",
                )
                page.emulate_media(media="screen")
                with page.expect_download() as download:
                    page.locator("#research-package").click()
                package_path = out / f"run_{primary}_research_package.zip"
                download.value.save_as(package_path)
                package = verify_package(package_path, sample_count)
                results.append(
                    {
                        "check": "Paper screenshot, print, PDF and research ZIP",
                        "run_id": primary,
                        "research_package": package,
                        "result": "PASS",
                    }
                )
            results.append(
                {
                    "path": route,
                    "status": response.status,
                    "chart_points": chart_points,
                    "seconds": round(time.perf_counter() - started, 6),
                    "result": "PASS",
                }
            )

        response = page.goto(base + "/admin/login/?next=/admin/")
        check(
            response.status == 200
            and page.locator("#id_username").is_visible()
            and page.locator("#id_password").is_visible(),
            "Admin login is unavailable",
        )
        results.append(
            {
                "path": "/admin/login/",
                "status": response.status,
                "check": "Unauthenticated login form (no credential submission)",
                "result": "PASS",
            }
        )
        health = context.request.get(base + "/health/")
        check(
            health.status == 200
            and health.json().get("database") == "ok"
            and health.json().get("status") == "ok",
            "Health/database check failed",
        )
        results.append(
            {
                "path": "/health/",
                "status": health.status,
                "body": health.json(),
                "result": "PASS",
            }
        )
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(f"{base}/?run_id={primary}")
        ready()
        page.wait_for_function(
            "!busy && Object.keys(charts).length===5 && charts.do.data.labels.length>0"
        )
        check(
            page.evaluate("document.documentElement.scrollWidth <= innerWidth"),
            "Mobile horizontal overflow",
        )
        check(
            "SIMULATED" in page.locator("#source").inner_text(),
            "Mobile source label missing",
        )
        page.screenshot(path=str(out / "mobile-simulated.png"), full_page=True)
        check(not errors, f"JavaScript runtime errors: {errors}")
        check(not api_failures, f"Browser API failures: {api_failures}")
        results.append(
            {
                "check": "Mobile 390x844, JavaScript runtime and API requests",
                "errors": errors,
                "api_failures": api_failures,
                "result": "PASS",
            }
        )
        context.close()
        browser.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url", type=validated_base_url, default="http://127.0.0.1:8000"
    )
    parser.add_argument(
        "--run-ids",
        type=int,
        nargs="+",
        default=[1, 2],
        help="Two to five SIMULATED run IDs; last is used for chart/export checks",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("evidence"))
    parser.add_argument(
        "--timeout", type=float, default=180, help="Browser timeout in seconds"
    )
    args = parser.parse_args(argv)
    if (
        not 2 <= len(args.run_ids) <= 5
        or len(set(args.run_ids)) != len(args.run_ids)
        or any(value < 1 for value in args.run_ids)
    ):
        parser.error("Supply two to five distinct positive run IDs.")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be a positive finite number.")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = [
        {
            "base_url": args.base_url,
            "run_ids": args.run_ids,
            "source": "SIMULATED",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "notice": "Application verification only; not physical experimental evidence.",
        }
    ]
    success = False
    try:
        run_checks(args, results)
        success = True
    except Exception as exc:
        results.append({"result": "FAIL", "error": str(exc)})
        print(str(exc), file=sys.stderr)
    finally:
        results.append(
            {
                "result": "PASS" if success else "FAIL",
                "check": "Overall browser verification",
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        (args.output_dir / "browser-checks.json").write_text(
            json.dumps(results, indent=2), encoding="utf-8"
        )
    print(json.dumps(results, indent=2))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
