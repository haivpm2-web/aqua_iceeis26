# Final release plan — aqua_iceeis26

Audit date: 2026-09-09. Preserve the existing Django/DRF application, migration 0001, independent analysis functions, charts and scientific safeguards. The four existing audit/README documents and source/configuration/test structure were reviewed before implementation.

## Existing features

Four-channel ingestion, atomic batch writes, bounded history/downsampling, experiment metadata, ground-truth/software-reference separation, statistical/outlier/STEP/fixed-point analysis, synthesis input, CSV import/export, comparison, responsive paper charts and tables, local simulation, 47 regression tests and browser evidence are implemented. SQLite contains two SIMULATED demonstrations. PostgreSQL and Gunicorn configuration exist but have not yet been executed. There is no local Git repository.

## Required changes

1. Add nullable/defaulted reproducibility, numerical, filter, calibration and source-version metadata without invalidating old runs.
2. Implement protected locking/unlocking with mutation checks across API, ingestion, admin, model/queryset operations and shared FPGA configuration. Serialize writes with run finalization and record lock provenance.
3. Generate deterministic canonical ZIP research packages, per-file SHA256 sums and stored dataset/package hashes, excluding self-referential integrity fields from metadata hashing. Refuse silent modification of locked evidence.
4. Add sequence-keyed HIL reference records, deterministic pairing and unmatched/ambiguous counts; retain integer-only bit agreement.
5. Expose release actions and source/integrity information in existing pages; preserve all existing charts and exports.
6. Document gateway HTTP protocol; finalize README, release/deployment reports, ignore rules and source checksum manifest.

## Deployment plan

GitHub CLI is authenticated as haivpm2-web; target repository does not yet exist. Railway CLI 5.45.5 is authenticated. After source validation and secret checks, initialize main, create aqua_iceeis26 without overwriting another repository, commit/push and verify the remote hash. Use current Railway CLI/service configuration, create a dedicated project/web service/PostgreSQL, configure secrets without printing them, run migrations/static collection, deploy Gunicorn and verify its real public URL. Existing unrelated Railway services will not be modified. Docker is not currently found on PATH; do not claim a local Docker run without execution.

## Verification plan

Run migration/check/static/test/deploy-check/dependency/JavaScript checks. Add regression tests for metadata, lifecycle guards, package determinism/hash verification and HIL ambiguity. Exercise 10,000 and preferably 50,000 SIMULATED samples through batched APIs with application timings. Verify pages, Admin login, PNG/CSV/PDF/research ZIP and mobile layout. Execute the same database behavior on actual PostgreSQL before deployment where feasible; then remotely create only SIMULATED verification runs (1,000 and 10,000 samples), test public APIs/browser and record truthful deployment evidence. Completion requires verified GitHub and public Railway results, not local tests alone.
