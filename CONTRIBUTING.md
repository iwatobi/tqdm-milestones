# Contributing

Development is based on the `develop` branch. The `main` branch is the
production release branch and accepts changes only through release pull
requests from `develop`.

## Development workflow

1. Start work from `develop`.
2. Commit directly to `develop`, or open a feature pull request targeting
   `develop` when review is useful.
3. Keep tests, typing, linting, and 100% statement and branch coverage passing.

```console
git switch develop
git pull --ff-only
uv sync --extra test --extra publish
uv run --extra test ruff check --no-cache .
uv run --extra test ruff format --no-cache --check .
uv run --extra test ty check --error-on-warning src tests scripts
uv run --extra test --extra publish pip-audit
uv run --extra test coverage run -m pytest
uv run --extra test coverage report
uv run --extra test python scripts/check_module_coverage.py
```

## Release workflow

Prepare a release on `develop` by updating the stable semantic version in
`pyproject.toml`, refreshing `uv.lock`, and adding the corresponding dated entry
to `CHANGELOG.md`. Each production version must be new on PyPI.

Open a pull request from `develop` to `main`. The release-candidate workflow:

1. accepts only the repository's `develop` branch as the pull-request source;
2. rehearses the same checks and stable-distribution build used by the
   production workflow;
3. changes the version only inside the runner to a unique `.devN` version;
4. publishes wheel and source distributions to TestPyPI; and
5. installs the candidate from TestPyPI under Python 3.10 and imports the public
   API.

Merge only after CI and the TestPyPI round-trip succeed. The merge to `main`
then builds and tests the stable version on every supported Python version,
publishes it to PyPI, verifies a clean installation from PyPI, and creates the
matching `vX.Y.Z` tag and GitHub Release.

The `main` ruleset requires the `CI success` and `TestPyPI release gate` checks,
requires a pull request, and blocks branch deletion and force pushes. Do not
bypass these release safeguards.

Do not create production tags or GitHub Releases manually. PyPI and TestPyPI
distribution filenames are immutable and cannot be reused after deletion.

If an upload succeeds only partially or a publishing job fails after uploading,
rerun only the failed jobs in the same GitHub Actions run. The workflow reuses
the original distributions and enables duplicate skipping only on a retried
attempt, so filenames already accepted by the index are skipped while missing
files are uploaded. It then continues with installation verification. Do not
rerun the entire production workflow: its build preflight intentionally rejects
a stable version that already exists on PyPI.
