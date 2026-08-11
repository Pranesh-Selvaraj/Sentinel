# Contributing to Sentinel

Thanks for wanting to contribute! Sentinel is a small, dependency-free
project with strong opinions about safety — the guidelines below keep it
that way.

## Repository rules (enforced)

- **`main` is protected.** Nobody pushes to `main` directly — not even
  maintainers are expected to, and the branch protection rules enforce it
  for everyone except the repository owner, who alone may push or merge
  directly.
- **All changes land via pull requests** that must pass:
  - the full test suite (Python 3.11 – 3.14),
  - `ruff check` and `ruff format --check`,
  - the security job (`bandit` + `pip-audit`),
  - an approving review from the repository owner (see `CODEOWNERS`).
- The branch is also protected against force-pushes and deletion.

## Getting started

```bash
git clone https://github.com/Pranesh-Selvaraj/Sentinel.git
cd Sentinel
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
python3 -m sentinel --help          # run without installing
```

Run the tests:

```bash
python3 -m unittest discover -s tests -v
```

The test suite uses only the standard library and a fake HTTP transport —
**no live network, ever**. Tests must stay that way.

## Development workflow

1. **Create a feature branch** off `main`:
   ```bash
   git checkout -b feat/your-feature
   ```
   Naming: `feat/…`, `fix/…`, `docs/…`, `chore/…`, `security/…`.

2. **Make your change.** Keep commits small and focused. There is no
   enforced commit convention yet, but prefer imperative subjects
   (`Add npm monitor`, not `Added`/`Adds`).

3. **Keep it clean locally**:
   ```bash
   pip install ruff
   ruff check sentinel tests
   ruff format sentinel tests
   python3 -m unittest discover -s tests
   ```

4. **Open a pull request** against `main`. CI runs automatically. Fill in
   what changed and why; link any issue.

5. **Wait for the owner's review.** All files are owned by the repository
   owner (`CODEOWNERS`), so a PR cannot merge without their approval.

## Coding style

- Python 3.11+; `from __future__ import annotations` at the top of modules.
- `ruff` with the configuration in `pyproject.toml` is the source of truth —
  including the security rules (`S`/`BLE`) it enables. Formatting is
  enforced with `ruff format` (line length 110).
- Type hints are used throughout; new code should follow suit.
- Docstrings in the existing style (plain reStructuredText-ish, module
  docstrings explain *why*).
- Zero runtime dependencies. Anything that needs a third-party package
  should be discussed in the PR first.

## Architecture notes

- `sentinel/app.py` — application services; the CLI (`cli.py`) is a thin
  parser over it. Business logic does not live in the CLI.
- `sentinel/monitors/` — one class per source type, registered in
  `monitors/__init__.py`. New source type = new Monitor + registration.
- `sentinel/updaters/` — one class per updatable source kind. Updaters must
  follow the safety rules (dry-run planning, checksum verification,
  confirmation, audit trail).
- `sentinel/httpclient.py` — the only place that talks to the network.
- `sentinel/db.py` — the only place that touches SQLite.

## Safety rules (non-negotiable)

- Monitoring must never mutate anything.
- Upgrade planning must never mutate anything (`--dry-run` safe by default).
- Downloads without verified checksums stay blocked unless the user passes
  `--allow-unverified` explicitly.
- Secrets (tokens, header values) are never stored in the database and are
  masked in output.
- One failing source never crashes a check run.
- Every applied update is recorded in the `updates` audit table.

If a change touches any of these, say so in the PR description.

## Reporting security issues

Do **not** open an issue. Follow the private reporting instructions in
[SECURITY.md](SECURITY.md).

## Questions?

Open a discussion or ask in your PR. Keep it friendly.
