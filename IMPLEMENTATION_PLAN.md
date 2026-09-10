# Implementation plan and initial audit

The existing project contains Django settings, WSGI/ASGI entry points, a static health response, and a placeholder monitoring view. Requirements already select Django, DRF, PostgreSQL, Gunicorn and WhiteNoise. No models, migrations, templates, adapters, tests, or deployment manifests exist. No AGENTS.md was found in this workspace.

1. Retain the project and monitoring app; add experiment, sample, event and synthesis storage with optional research reference fields.
2. Add authenticated writes, bounded reads, bulk ingestion, CSV import/export and independent scientific analysis.
3. Build responsive monitoring, analysis, experiment comparison, FPGA, events, system and printable paper pages.
4. Configure Railway and document data contracts and scientific assumptions.
5. Run migrations, automated tests, checks and local HTTP validation using an explicitly simulated experiment containing at least 1,000 samples. Record evidence and limitations in the final reports.
