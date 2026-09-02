# tqdm-milestones

Deterministic progress milestones for terminals, logs, and monitoring systems.

`tqdm-milestones` uses a regular [`tqdm`](https://tqdm.github.io/) progress bar
in an interactive terminal. In CloudWatch Logs, CI, containers, and other
non-interactive environments, it emits append-only progress events without ANSI
control sequences.

Unlike time-only progress logging, large updates preserve every crossed
percentage and item-count milestone.

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
names such as `message`, `name`, or `levelno`.

`current` and `current_percent` are always the progress actually observed when
an event is emitted.
When one update crosses several thresholds, `milestone` identifies each crossed
threshold separately. ETA is calculated from the observed current value, never
from a synthetic historical value.

## Callbacks

A callback can route structured events to a metrics or monitoring backend. In
log mode, it takes precedence over logger and stream output. TTY mode displays a
regular tqdm bar and does not invoke the callback.

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

with ProgressReporter(total=100, desc="Importing", log_start=True) as progress:
    for completed in range(1, 101):
        process_one()
        progress.advance_to(completed)
```

Normal context-manager exit emits pending progress. Exceptional exit closes the
terminal bar without emitting a final event.

## Output modes

`mode` accepts `"auto"` (default), `"tty"`, `"log"`, or `"disabled"`. The
default can be overridden with `TQDM_MILESTONES_MODE`:

```console
TQDM_MILESTONES_MODE=log python batch.py
```

Use `log_start=False` or `log_complete=False` to control boundary events.
For an empty job, `log_complete=False` takes precedence over `log_start=True`,
so no completion event is emitted.

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

Numeric `unit_scale` values must be finite and greater than zero. Boolean
`unit_scale=False` remains the way to disable scaling.

For a sized iterable without an explicit `total`, `initial` is added to the
inferred total. This treats the iterable as the remaining work and keeps TTY and
log mode consistent. ETA uses only work completed after `initial`.

`disable=True` and tqdm's non-TTY `disable=None` both suppress output. Other
tqdm display-only keyword arguments are forwarded in TTY mode and ignored in
log mode.

Each update emits at most 10,000 milestones by default. This protects production
jobs from accidental event floods caused by an extremely small percentage
interval. Increase `max_milestones_per_update` explicitly when a larger batch of
events is intentional.

In log mode, if a callback or output destination raises an exception, the
exception is propagated. Calling `advance_to()` again with the same value
resumes at the first event that was not delivered successfully.

`ProgressReporter` instances are not thread-safe. Send updates from one thread,
or protect a shared reporter with a caller-managed lock.

Reporter configuration cannot be reassigned after initialization. The one
exception is `max_milestones_per_update`, which may be increased before retrying
an update rejected by the flood guard. The contents of `extra_fields` remain
mutable and are revalidated before every event.

`close()` and `finalize()` are idempotent. Calling `advance_to()` or entering a
context after the reporter is closed raises `RuntimeError`.

## Development

```console
git switch develop
uv sync --extra test --extra publish
uv run --extra test coverage run -m pytest
uv run --extra test coverage report
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

Both indexes keep distribution filenames immutable. Never reuse a version, even
after deleting a release. See [CONTRIBUTING.md](https://github.com/iwatobi/tqdm-milestones/blob/develop/CONTRIBUTING.md)
for the complete release procedure.

## License

MIT
