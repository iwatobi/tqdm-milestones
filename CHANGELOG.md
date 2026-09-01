# Changelog

All notable changes to this project are documented in this file. The project
uses [Semantic Versioning](https://semver.org/).

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
