# Railway deployment report — aqua_iceeis26

Date: 2026-09-10. Deployment is pending; no production URL or remote PASS is claimed yet.

Planned method: authenticated Railway CLI, dedicated project and PostgreSQL, GitHub main as web-service source, Dockerfile/Gunicorn, supported service settings through `scripts/configure_railway.graphql` and `docs/railway-service-settings.json`. The deprecated root Railway config file is no longer used.

Required production variables: random SECRET_KEY and INGEST_API_TOKEN, DEBUG=false, PostgreSQL DATABASE_URL reference, explicit ALLOWED_HOSTS and CSRF_TRUSTED_ORIGINS. Pre-deploy applies migrations; Docker startup collects static assets. Health path `/health/` checks the database and is exempt from HTTPS redirect for Railway's readiness probe.

Pending evidence: project/service/database IDs, actual public URL, deployment/build status, migration/static/Gunicorn logs, PostgreSQL vendor confirmation, public health HTTP200, dedicated 1,000/10,000-sample SIMULATED runs, remote API/export/hash validation, desktop/mobile/browser/PNG/PDF evidence and sanitized timing reports.
