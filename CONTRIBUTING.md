# Contributing

Development is based on the `develop` branch. The `main` branch always
represents the latest production release.

## Development workflow

1. Start work from `develop`.
2. Commit directly to `develop`, or open a feature pull request targeting
   `develop` when review is useful.
3. Keep tests, typing, linting, and 100% statement and branch coverage passing.

```console
git switch develop
git pull --ff-only
uv sync --extra test --extra publish
uv run --extra test ruff check .
uv run --extra test pyright src tests
uv run --extra test coverage run -m pytest
uv run --extra test coverage report
```

## Release workflow

Prepare a release on `develop` by updating the stable semantic version in
`pyproject.toml`, refreshing `uv.lock`, and adding the corresponding dated entry
to `CHANGELOG.md`. Each production version must be new on PyPI.

Open a pull request from `develop` to `main`. The release-candidate workflow:

1. accepts only the repository's `develop` branch as the pull-request source;
2. runs linting, type checking, and the full-coverage test suite;
3. changes the version only inside the runner to a unique `.devN` version;
4. publishes wheel and source distributions to TestPyPI; and
5. installs the candidate from TestPyPI under Python 3.10 and imports the public
   API.

Merge only after CI and the TestPyPI round-trip succeed. The merge to `main`
then builds and tests the stable version on every supported Python version,
publishes it to PyPI, verifies a clean installation from PyPI, and creates the
matching `vX.Y.Z` tag and GitHub Release.

Do not create production tags or GitHub Releases manually. PyPI and TestPyPI
distribution filenames are immutable and cannot be reused after deletion.
