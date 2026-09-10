# Railway deployment report — aqua_iceeis26

Date: 2026-09-10. **Railway deployment, PostgreSQL connectivity, public HTTPS health, remote API/export and production browser acceptance: PASS.**

## Deployment identity

| Item | Actual value |
| --- | --- |
| Public URL | [aquaiceeis26-production.up.railway.app](https://aquaiceeis26-production.up.railway.app/) |
| GitHub source | [haivpm2-web/aqua_iceeis26](https://github.com/haivpm2-web/aqua_iceeis26), `main` |
| Verified application commit | `7679b9991d968ec62495ee9c3212d11b706b633a` |
| Dedicated Railway project | `711fa77a-a6c4-4180-8c5d-ab75c22c7ee1` |
| Production environment | `af9aa5a6-dcac-402f-b4e3-dc0fef91c010` |
| Web service | `5dce9cce-8309-46c8-8d18-f72d522c383e` |
| PostgreSQL service | `0d9d1344-0a74-41ed-b538-c40550b70c22` |
| Web deployment | `6be21a27-d191-4941-9dac-84ec8d1d6f86` — SUCCESS |
| PostgreSQL deployment | `f9cd4e31-83a0-487f-8d28-dcf35c9aee2d` — SUCCESS |
| Database image | `ghcr.io/railwayapp-templates/postgres-ssl:18` |
| Web image digest | `sha256:2e77c3ad58a5fc6d822558a9485903e7080ba339966761a03493f874de60364b` |

The dedicated project was created through the authenticated Railway CLI, and the web service is connected to GitHub `main`. Service settings were applied through the supported Railway API using `scripts/configure_railway.graphql` and `docs/railway-service-settings.json`. The API accepts `RAILPACK` as the service builder setting with `dockerfilePath=Dockerfile`; the actual deployment manifest records the detected builder as `DOCKERFILE`. The archived `docs/railway.legacy.json` is not active configuration. This release makes no general claim that Railway config-as-code is deprecated.

## Production configuration and executed startup

Configured variables include a generated strong `SECRET_KEY`, a separate generated `INGEST_API_TOKEN`, `DEBUG=false`, a PostgreSQL `DATABASE_URL` service reference, the actual public hostname and `healthcheck.railway.app` in `ALLOWED_HOSTS`, and the HTTPS public origin in `CSRF_TRUSTED_ORIGINS`. Secret values and connection credentials are not published. The deployed software version resolves to Railway's Git commit identity.

Pre-deploy runs `python manage.py migrate --noinput`. Actual logs show Django migrations, `monitoring.0001_initial` and `monitoring.0002_experimentrun_accumulator_q_format_and_more` applied successfully against the configured PostgreSQL database. Startup runs static collection inside the application container: 168 files copied and 484 post-processed. Gunicorn 24.0.0 then starts two synchronous workers on `0.0.0.0:8000` under the Dockerfile's non-root application user.

The service uses `/health/`, a 120-second readiness timeout, `ON_FAILURE` restart policy with three retries and application sleeping disabled. Deployment watch paths cover the Dockerfile, requirements, application configuration and monitoring source, so report/evidence-only commits do not rebuild the runtime. The health endpoint checks database access and is exempt from HTTPS redirection for Railway's readiness probe. Public application traffic uses HTTPS with the configured proxy/security settings.

## Verification evidence

| Verification | Result |
| --- | --- |
| GitHub publication and source commit | PASS: repository/main and deployed manifest identify the verified application commit |
| PostgreSQL/container CI | PASS: [Actions run 34486127629](https://github.com/haivpm2-web/aqua_iceeis26/actions/runs/34486127629) executed all 82 tests on PostgreSQL 17, migrations, production checks and an actual Linux Docker/Gunicorn health check |
| Railway PostgreSQL and web deployments | PASS: both deployment statuses are SUCCESS |
| Pre-deploy migrations | PASS: migrations 0001/0002 and Django migrations appear as OK in actual startup evidence |
| Static assets and Gunicorn | PASS: static collection and two-worker Gunicorn startup recorded |
| Public `/health/` | PASS: HTTP 200, `status=ok`, `database=ok` |
| Public `/api/v1/status/` | PASS: HTTP 200, `database_vendor=postgresql`, verified software commit |
| Remote SIMULATED API/export checks | PASS: aggregate checks on runs 1/3 in `evidence/final-remote-api-verification.json`; individual driver FAIL results are preserved below |
| Remote browser and downloads | PASS: desktop/mobile routes, charts, CSV/PNG/PDF/ZIP, source labels, 390 × 844 layout and no JavaScript/API errors |

The first remote driver passed run 1 with 1,000 SIMULATED samples (3.195889 seconds, five 200-sample batches). Its next run, ID 2, stopped after 400 samples because the client timed out during an SSL handshake. Independent health/read requests still succeeded. Run 2 was marked FAILED and its partial evidence retained. A separate SIMULATED retry, ID 3, ingested all 10,000 samples in 38.331178 seconds over fifty 200-sample batches and passed statistics/history/tables/pages/CSV/locking checks, then encountered a client read timeout while downloading its research ZIP.

Two independent curl GET downloads subsequently returned the identical 4,487,329-byte ZIP for locked run 3. All eleven member checksums passed. ZIP SHA256 `c1867b8f0fbde7eb5ce2033294bbfe748a5e03bbf239eed57dad8be530d84830` and dataset SHA256 `961c126e2c5b2dfe01cab5ee113b6d1634fdb4d815396461c41b67ef8a1dae79` match the stored integrity fields. The two original driver reports retain FAIL and are not replaced by the successful independent recheck. Evidence: `evidence/final-remote-initial-attempt.json`, `evidence/final-remote-retry-attempt.json`, `evidence/final-remote-package-recheck.json`.

`evidence/final-remote-api-verification.json` records aggregate PASS for all required API/export checks on runs 1 and 3 across attempts and independent package rechecks. Neither original driver report is relabelled PASS. The first browser run exposed horizontal overflow from the long SIMULATED run name; `evidence/final-remote-browser-pre-fix.json` preserves that failure. The source banner now wraps at arbitrary long tokens, deployment `6be21a27-d191-4941-9dac-84ec8d1d6f86` serves the corrected CSS, and the unchanged full browser suite then passed. `evidence/final-remote-browser-checks.json` plus the final remote dashboard/mobile/paper screenshots record the accepted result. Client request failures are recorded as observed; their root cause has not been established.

Evidence files: `evidence/final-ci-verification-7679b99.json`, `evidence/final-railway-web-deployment-7679b99.json`, `evidence/final-railway-postgres-deployment.json`, `evidence/final-railway-startup.json`, `evidence/final-remote-health-7679b99.json`, `evidence/final-remote-browser-checks.json` and the final remote screenshots. Earlier snapshots remain for audit; the first public status snapshot correctly reports zero samples because it precedes demo ingestion.

## Reproduction and limits

With `INGEST_API_TOKEN` set securely to the deployed service's token, run:

```powershell
& .\.venv\Scripts\python.exe scripts/verify_release.py --base-url https://aquaiceeis26-production.up.railway.app --counts 1000 10000 --run-prefix SIMULATED_RAILWAY_TEST --output-dir evidence/remote-release
& .\.venv\Scripts\python.exe scripts/verify_browser.py --base-url https://aquaiceeis26-production.up.railway.app --run-ids 1 3 --output-dir evidence/remote-release/browser
```

Use the actual run IDs returned by the API driver when repeating it: each invocation creates new SIMULATED experiments. HTTP ingestion duration measures application/network behavior and must not be cited as FPGA latency or throughput. The browser driver uses existing completed/locked SIMULATED runs and does not submit admin credentials.

An additional SSH diagnostic attempt was unavailable because no SSH key was configured. Deployment proof comes from executed CI, actual Railway deployment/startup records and public database-backed HTTP responses; no SSH-based verification is claimed. No physical FPGA/Vivado experiment, serial/MQTT gateway integration, sustained concurrent load/capacity test or backup/restore exercise was executed as part of this deployment.
