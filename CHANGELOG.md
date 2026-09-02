# Changelog

All notable changes to this project are documented in this file. The project
uses [Semantic Versioning](https://semver.org/).

## 2.0.0 - 2026-09-02

### Added

- Configurable final-event policies for always emitting final progress, emitting
  it only after another event or a milestone reached by the final update, or
  suppressing it entirely.
- Consistent final-event control across `ProgressReporter` and `tqdm_iter()`.

### Changed

- `ProgressReporter` now accepts only `total` positionally; every configuration
  option is keyword-only.
- `ProgressEvent` construction is keyword-only to prevent field-order mistakes.
- `tqdm_iter()` now exposes `total`, `initial`, `unit`, `unit_scale`,
  `unit_divisor`, `disable`, and `file` as typed keyword-only parameters instead
  of interpreting them through `**tqdm_kwargs`.
- `tqdm_iter()` validates package configuration before returning an iterator.
- Invalid argument types now raise `TypeError`; invalid values and conflicting
  option combinations raise `ValueError`.
- `callback` and `logger` are mutually exclusive instead of silently preferring
  the callback.
- `extra_fields` accepts a mapping, reserves the `progress_` namespace, and is
  snapshotted into a validated, read-only top-level mapping during
  configuration.
- `ProgressReporter` instances now use identity equality instead of dataclass
  field equality.
- The adjustable per-update safety limit can only be increased after reporter
  initialization.
- The minimum supported `tqdm` version is 4.66.3, which excludes releases
  affected by CVE-2024-34062.
- Clarified that the per-update milestone safety limit applies to raw trigger
  crossings before target deduplication as well as to emitted milestones.
- Documented how to keep short jobs below their first milestone completely
  silent.
- Clarified that default finalization reports an unchanged initial state and
  that `has_emitted` tracks log-mode events rather than TTY rendering.

### Removed

- Replaced `log_start` with the destination-neutral `emit_start` option.
- Replaced `log_complete` with the more expressive `final_event` policy.
- Replaced `stream` with the tqdm-compatible `file` option.

### Development

- Internal progress-value and reporting-option validators use keyword-only
  arguments to prevent argument-order mistakes and avoid redundant validation.
- The implementation is split into private, focused modules while the supported
  API remains available from the `tqdm_milestones` package root.
- Tests mirror the implementation modules and include English Google-style
  docstrings describing their assertions and typed arguments.
- Development and release checks use Ruff for linting and formatting and ty for
  type checking, with function-local imports prohibited.
- CI verifies 100% coverage for each implementation module through its matching
  test module, exercises the minimum supported `tqdm` version, and audits that
  environment for known dependency vulnerabilities.
- Publishing jobs can safely resume a partial PyPI or TestPyPI upload without
  replacing an accepted distribution.
- Aggregate CI and TestPyPI release gates support enforced `main` branch
  protection without coupling repository rules to individual matrix jobs.

## 1.0.0 - 2026-09-01

### Added

- TTY-aware delegation to `tqdm`.
- Plain progress output for non-interactive environments.
- Deterministic time, percentage, and item-count milestones.
- Structured `ProgressEvent` callbacks and logging fields.
- Separate observed progress and crossed milestone fields with truthful ETA data.
- Symmetric `current_percent` and `milestone_percent` event and logging fields.
- Explicit `auto`, `tty`, `log`, and `disabled` modes.
- Start and completion event controls.
- Protection against accidental milestone floods.
- Non-TTY support for `disable`, `initial`, `unit`, and `unit_scale`.
- Atomic validation failures and resumable output failures.
- Strict validation for numeric formatting and structured logging fields.
- Safe percentage and display calculations for arbitrarily large integer counts.
- Exact percentage buckets for subnormal intervals without floating-point overflow.
- Immutable reporter configuration with an explicitly adjustable flood limit.
- Hardened release workflows with strict metadata checks, cache isolation, and
  wheel and source-distribution installation tests.
