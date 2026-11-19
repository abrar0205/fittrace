# data/

Generated at runtime, not committed.

- `raw/<dataset>-incNNN/` - simulated MES-style exports written by `python -m app.cli seed-demo`:
  `units.csv`, `production_events.csv`, `process_parameters.csv`, `equipment_events.csv`,
  `inspections.csv`, `calibration.csv`, `images/*.png`, `manifest.json` (checksums, injected
  data-quality defects), and `ground_truth/` (true gaps and injected faults, kept apart from the export).
- `raw/<dataset>-inc002-corrupt/` - a deliberately truncated delivery used to exercise the failed-run path.

Generation is deterministic (fixed seeds): deleting `raw/` and re-seeding recreates byte-identical files,
so the import pipeline recognises them by checksum and skips them.
