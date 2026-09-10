# Research integrity contract

Schema version: 1. Measurements are supplied evidence; this server never generates REAL/HIL data automatically.

## Finalization

A COMPLETED run can be locked through authenticated POST `/api/v1/runs/<id>/lock/` or staff Admin. The operation records LOCKED, locked_at and the staff user if available, creates the canonical archive and stores its hashes in one transaction. API bearer finalization has no staff identity and leaves locked_by empty.

Ordinary sample, reference, event, run and shared implementation changes are refused while locked. Application mutations use row locks on PostgreSQL to serialize with finalization. Superusers can explicitly unlock with a reason, preserving an immutable unlock audit with previous hashes; this returns the run to COMPLETED and invalidates its active integrity record. Direct SQL, database administrators and deliberately invoked private ORM internals remain trusted infrastructure and can bypass application guards. SHA256 verification detects resulting differences; it is not a digital signature or protection against an administrator replacing both evidence and hashes.

## Canonical ZIP

GET research-package downloads without modifying completed-run bookkeeping. Protected POST generates and records hashes. Locked GET/POST validates the prior record and returns HTTP 409 on mismatch; it does not silently issue a replacement hash.

The ZIP includes original samples, events, complete scientific metadata, calculated metrics, FPGA/filter configuration and tables A–E. HIL references are included when present. Text is UTF-8, CSV records use LF and deterministic field/row order, JSON has sorted keys and compact separators, and timestamps are UTC with fixed precision. ZIP members use fixed timestamps/permissions/order and no compression to avoid compression-library differences. Source labels remain in metadata, README, events, references and tables; samples retain each transmitted source.

`SHA256SUMS.txt` covers every other member, including README. `dataset_sha256` equals SHA256(samples.csv). `research_package_sha256` equals SHA256(complete ZIP). The latter cannot be embedded in the ZIP without circularity. Only the three integrity bookkeeping fields are excluded from metadata. Locking changes lifecycle metadata, so a newly locked package intentionally differs from its preceding COMPLETED package.

Canonical research CSV preserves supplied text exactly; unlike the spreadsheet-oriented sample download, it does not prefix formula-like text. Import text columns as text in spreadsheet tools. Retain the downloaded archive with the corresponding software Git commit. Analysis changes across software releases can change recomputed metrics; a mismatch requires investigation rather than automatic acceptance.

## HIL pairing

Independent references use a unique run/sensor/sequence key. FPGA outputs remain in SensorSample's `<sensor>_filtered` and `<sensor>_fpga_code`; software reference values/codes remain in HILReference. A unique matching packet is paired. Duplicate packet sequences are reported as ambiguous and excluded, and missing matches remain unmatched. No timestamp interpolation occurs. Integer code pairs alone determine bit-exact counts; numeric errors require actual software values. Sensor ground-truth fields remain separate.

## Scientific prerequisites

Missing references, true labels, STEP definitions, FPGA latency or Vivado data produce null/N/A. Sequence gaps are observed missing IDs inside an interval, not proven packet loss. Source SIMULATED and SYNTHETIC cannot substantiate measured hardware claims. Real calibration, synchronization, numeric-format definitions, reference provenance, fault labels, physical latency measurements and synthesis reports remain responsibilities of the experiment.
