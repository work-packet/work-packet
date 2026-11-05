# Port: the IDE's mTLS transport (incoming remote changes)

Source: uncommitted changes in `./work-packet/` (a clone at `a6e2fff`).
Not taken: the `backends/lsf.py` change and LSF test lines; the "U-20" tracker reference.

## Steps

- [x] 1. Straight hunks: `dash/tls.py` + `tests/test_unix_login.py` (self-signed CA:FALSE fix),
      `schema.py` (`sched.ide.transport`), `dash/server.py`, `slurm.py` `node_command(argv=)`,
      `docs/scheduler.md` §8.1, `docs/sites.md` §3a
- [x] 2. New: `sched/ide_tls.py`, `sched/ide_relay.py`
- [x] 3. `sched/ide_job.py`: `--transport mtls` merged with our `--launch` / `--collect`
- [x] 4. `dash/ide.py`: `MtlsJobBackend` on hooks in `JobBackend` (keeps launch records, ask-once guard)
- [x] 5. `tests/test_ide_mtls.py`: Slurm-only node_env test; fixture stops the job with SIGTERM (it leaked server + relay)
- [x] 6. Run tests; check no processes leak

## Status

Done 2026-11-05, not committed. Full suite: 1144 passed, 13 skipped; no IDE processes left after the run.

- `JobBackend` gained `transport`, `listen_argv(fake)` and `_prepare()`; `MtlsJobBackend` overrides
  those plus the connection methods, so the launch record and the ask-once guard are shared.
- `ide_job.main` builds one `started(cmd)` (launch env, `ide_launch.update`, `--collect`) used by
  both `run_tcp` and `run_mtls`.
- `docs/scheduler.md`: "runs under `node_env`" is stated for slurm only (the LSF path is unchanged).
- `tests/test_ide_mtls.py`: `stop_job()` sends SIGTERM, then reaps the fake server's pids; the
  mtls proxy test also checks the launch record (host, pid).
- `./work-packet/` (the incoming clone) is still untracked: delete it or ignore it before committing.
