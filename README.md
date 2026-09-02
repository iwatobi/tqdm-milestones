# tqdm-milestones

Deterministic progress milestones for terminals, logs, and monitoring systems.

`tqdm-milestones` uses a regular [`tqdm`](https://tqdm.github.io/) progress bar
in an interactive terminal. In CloudWatch Logs, CI, containers, and other
non-interactive environments, it emits append-only progress events without ANSI
control sequences.

Unlike time-only progress logging, large updates preserve every distinct item
count produced by crossed percentage and item-count thresholds.

## Installation

```console
pip install tqdm-milestones
```

Python 3.10 or later is required.

## Iterable wrapper

```python
from tqdm_milestones import tqdm_iter

for item in tqdm_iter(items, desc="Importing", percent_step=10):
    process(item)
```

Non-TTY output resembles:

```text
Importing: [##------------------] 10/100 it (10.0%) elapsed=00:03 eta=00:27
```

Milestones may be triggered by any combination of elapsed time, percentage, and
item count.

`total=None` means the total is unknown. `total=0` represents a known empty job
and produces a completed `0/0 it (100.0%)` event with the default unit.

## Logging and structured fields

```python
import logging

from tqdm_milestones import tqdm_iter

logger = logging.getLogger(__name__)

for item in tqdm_iter(
    items,
    logger=logger,
    count_step=1_000,
    extra_fields={"job_id": "import-42"},
):
    process(item)
```

Logger records include namespaced fields such as `progress_current`,
`progress_milestone`, `progress_total`, `progress_current_percent`,
`progress_milestone_percent`, and `progress_eta_seconds`.
Keys in `extra_fields` must not use reserved `logging.LogRecord` attribute
names such as `message`, `name`, or `levelno`, or the library-reserved
`progress_` prefix. The supplied top-level mapping is shallow-copied during
configuration and exposed as read-only through the reporter. Mutable field
values are not deep-copied.

`current` and `current_percent` are always the progress actually observed when
an event is emitted.
When one update crosses several thresholds, `milestone` identifies each
distinct integer item count produced by those thresholds. ETA is calculated
from the observed current value, never from a synthetic historical value.

## Callbacks

A callback can route structured events to a metrics or monitoring backend.
`callback` and `logger` are mutually exclusive so that one destination is never
silently ignored. TTY mode displays a regular tqdm bar and does not invoke the
callback.

```python
from tqdm_milestones import ProgressEvent, tqdm_iter


def publish(event: ProgressEvent) -> None:
    metrics.send("batch.progress.milestone", event.milestone_percent)


for item in tqdm_iter(items, callback=publish):
    process(item)
```

## Manual reporting

```python
from tqdm_milestones import ProgressReporter

with ProgressReporter(100, desc="Importing", emit_start=True) as progress:
    for completed in range(1, 101):
        process_one()
        progress.advance_to(completed)
```

Normal context-manager exit emits pending progress. Exceptional exit closes the
terminal bar without emitting a final event.

With the default `final_event="always"`, normal finalization emits the current
state even when no progress was made. A reporter left at zero therefore emits
`0/100 it (0.0%)` for a total of 100, and an empty unknown-length iterator emits
`0 it`. Use `final_event="after_milestone"` to keep work below its first
milestone silent.

`total` is the only positional `ProgressReporter` argument. All configuration
options are keyword-only. `ProgressEvent` fields are also keyword-only when an
event is constructed directly.

## Output modes

`mode` accepts `"auto"` (default), `"tty"`, `"log"`, or `"disabled"`. The
default can be overridden with `TQDM_MILESTONES_MODE`:

```console
TQDM_MILESTONES_MODE=log python batch.py
```

Use `emit_start=True` to emit the initial state. `final_event` controls final
progress in log mode, including both an event at a known `total` and pending
progress emitted during normal finalization:

- `"always"` is the default and emits final progress.
- `"after_milestone"` emits final progress only after another event has already
  been emitted or the final update itself reaches a configured time,
  percentage, or count milestone.
- `"never"` suppresses final progress while preserving earlier milestones.

For example, an unknown-length iterable that finishes before its first count
milestone can remain completely silent:

```python
for item in tqdm_iter(
    items,
    percent_step=None,
    count_step=1_000,
    seconds_step=None,
    final_event="after_milestone",
):
    process(item)
```

The same option is available on `ProgressReporter` and works with its context
manager. For an empty job, `final_event="never"` takes precedence over
`emit_start=True`, so no event is emitted.

Common tqdm options retain their meaning in log mode:

```python
tqdm_iter(
    items,
    disable=False,
    initial=1_000,
    unit="row",
    unit_scale=True,
)
```

Numeric `unit_scale` and `unit_divisor` values must be finite and greater than
zero. Boolean `unit_scale=False` remains the way to disable scaling.

`total`, `initial`, `unit`, `unit_scale`, `unit_divisor`, `disable`, and `file`
are explicit keyword-only arguments of `tqdm_iter()`. Other tqdm keyword
arguments are forwarded in TTY mode and ignored in log mode. Package-specific
configuration is validated when `tqdm_iter()` is called, before it returns an
iterator.

For a sized iterable without an explicit `total`, `initial` is added to the
inferred total. This treats the iterable as the remaining work and keeps TTY and
log mode consistent. ETA uses only work completed after `initial`.

`disable=True` and tqdm's non-TTY `disable=None` both suppress output. Other
tqdm display-only keyword arguments are forwarded in TTY mode and ignored in
log mode.

Each update has a default safety limit of 10,000 raw percentage crossings,
10,000 raw count crossings, and 10,000 deduplicated output milestones. Raw
crossings are checked before percentage thresholds are mapped to integer item
counts and deduplicated. Consequently, a small total combined with a very small
percentage interval can reach the limit even when several thresholds would map
to the same item count. This prevents excessive intermediate work as well as
event floods. Increase `max_milestones_per_update` explicitly when the larger
update is intentional.

In log mode, if a callback or output destination raises an exception, the
exception is propagated. Calling `advance_to()` again with the same value
resumes at the first event that was not delivered successfully.

`ProgressReporter` instances are not thread-safe. Send updates from one thread,
or protect a shared reporter with a caller-managed lock.

`has_emitted` tracks milestone events produced in log mode. Rendering or
updating a TTY bar does not set it, so it must not be used to decide whether a
TTY reporter should be finalized or closed.

Reporter configuration cannot be reassigned after initialization. The one
exception is `max_milestones_per_update`, which may be increased before retrying
an update rejected by the flood guard. The top-level `extra_fields` mapping is
shallow-copied and made read-only during initialization.

`close()` and `finalize()` are idempotent. Calling `advance_to()` or entering a
context after the reporter is closed raises `RuntimeError`.

## Migrating from 1.x

Version 2.0 makes configuration boundaries explicit:

- Pass only `total` positionally to `ProgressReporter`; pass every other option
  by keyword.
- Replace `log_start` with `emit_start`.
- Replace `log_complete=False` with `final_event="never"`.
- Replace `stream` with `file` on both public entry points.
- Do not combine `callback` and `logger`.
- Expect `TypeError` for invalid argument types and `ValueError` for invalid
  values or conflicting combinations.

## Development

```console
git switch develop
uv sync --extra test --extra publish
uv run --extra test ruff check --no-cache .
uv run --extra test ruff format --no-cache --check .
uv run --extra test ty check --error-on-warning src tests scripts
uv run --extra test --extra publish pip-audit
uv run --extra test coverage run -m pytest
uv run --extra test coverage report
uv run --extra test python scripts/check_module_coverage.py
uv build
uv run --extra publish twine check --strict dist/*
```

The test suite requires 100% statement and branch coverage.

See the [contribution and release workflow](https://github.com/iwatobi/tqdm-milestones/blob/develop/CONTRIBUTING.md),
[changelog](https://github.com/iwatobi/tqdm-milestones/blob/main/CHANGELOG.md), and
[issue tracker](https://github.com/iwatobi/tqdm-milestones/issues).

## Publishing

The GitHub workflows use PyPI Trusted Publishing and do not require long-lived
API tokens. Development is integrated on `develop`. A release pull request from
`develop` to `main` publishes a uniquely versioned candidate to TestPyPI and
verifies its installation. Merging a successful release pull request publishes
the stable version to PyPI, verifies it, and creates the matching tag and GitHub
Release.

The protected `main` branch requires both the complete CI suite and the
TestPyPI round-trip to succeed before a release pull request can be merged.

Both indexes keep distribution filenames immutable. Never reuse a version, even
after deleting a release. See [CONTRIBUTING.md](https://github.com/iwatobi/tqdm-milestones/blob/develop/CONTRIBUTING.md)
for the complete release procedure.

## License

MIT
