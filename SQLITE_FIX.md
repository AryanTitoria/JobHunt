# Resume upload database-lock fix

The upload view could fail with `OperationalError: database is locked` while discovery was writing to SQLite. Matching held a streaming job-query cursor while performing read-then-write upserts, and collection held a write transaction for an entire source.

Changes:

- SQLite uses WAL, IMMEDIATE transactions, a 30-second busy timeout, and non-persistent request connections.
- Matching reads closed, bounded pages before writing short bulk-upsert batches. An older matching run cannot overwrite a newer resume/profile version.
- Collection commits individual postings instead of holding a writer lock for the entire source. Missing jobs are reconciled only after the complete snapshot is processed; direct ATS closure still outranks stale syndicated copies.

All 46 tests pass, including a real file-backed SQLite regression that uploads a resume while a collector inserts 300 jobs and verifies 900 final matches. No schema migration, database reset, credential changes, or resume deletion is needed.

Stop any running JobSearch server/worker with Ctrl+C, then restart normally:

```powershell
.\.venv\Scripts\python.exe run.py
```

Use `run.py --demo` only when you want the separate fictional demo workspace. PostgreSQL remains the recommended database for a hosted multi-user installation.
