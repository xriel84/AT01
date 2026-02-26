TYPE: STATUS
FROM: AriBot
TO: YD
SUBJECT: Session 8 — API docs, benchmarks, error hardening

API.md created: full documentation for all 39 endpoints with schemas, curl examples, error codes.
benchmark.py added: timed benchmarks for transcribe, search, silence detect, chapter detect, full pipeline.
POST /api/benchmark endpoint live. Viewer has "Run Benchmark" button with results table.
Error responses standardized: all errors include {error, code, endpoint} fields.
Global exception handler catches unhandled errors (500 PROCESSING_ERROR).
Viewer now shows error messages in status bar (not just console).
4 new Resolve render live tests added (skip when offline).
816 tests passing, 0 failures. Pull `at` branch.
