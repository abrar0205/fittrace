# Limitations

## Data
- Every production history, fault and image is simulated. Nothing here describes a real plant, product or defect.
- The image model is a single top-down view with parallel edges. Generator 2.0 adds paint colour, clear-coat reflections, orange peel, metallic flake and two gap interiors, but it is still a 2-D model. Real gap sensors (laser triangulation or stereo) see curved flanges and sealer and measure along 3-D sections.
- The public datasets are not integrated: Carparts-Seg because of the ambiguous licence, NIST because the download was blocked in the build environment, and Bosch because it needs a Kaggle sign-in. See [datasets.md](datasets.md).

## Measurement
- **Flush is not measured.** It needs depth or calibrated 3-D data, and FitTrace does not estimate it from 2-D images.
- The +23.7 µm hem-shading bias is not corrected. A real system would calibrate it against a reference artefact. The bias also varies slightly with paint (22.5 µm on red to 25.0 µm on blue metallic), so a correction would need to be per paint or per colour class.
- The reported standard error is a repeatability lower bound, not a GUM uncertainty budget (it leaves out calibration, temperature and fixturing contributions).
- Calibration errors cannot be detected from the image. The algorithm trusts the stored scale that is valid at capture time.
- Gaps narrower than about 4 px, non-parallel edges (taper) and edges outside the field of view are refused, not measured.

## Statistics
- Contributor rankings are associations between recorded factors and a single mean shift. Unrecorded causes, interactions, multiple simultaneous shifts and gradual drifts are only partly captured.
- The permutation test assumes exchangeable observations. Autocorrelation (for example, a temperature cycle) inflates significance.
- Aliased factors (batch and shift in the demo) are reported, not separated.
- CUSUM limits from a 60-unit baseline give a high false-alarm rate (50% of fault-free histories).
- Recovery rates come from the simulator's own fault model and are optimistic for real data.

## Platform
- Single line, two measurement locations, one camera, one paint shop. Station codes are mapped to factor names in one place (`STATION_COLUMNS`).
- There is no authentication. The public demo relies on read-only safeguards: limits on interactive re-runs, a queue-depth limit, and retry disabled with `FITTRACE_DEMO_READONLY=true`. No destructive endpoint exists.
- The job queue is PostgreSQL-backed and suits low job volume. There is no distributed processing.
- The Docker image and compose file were written but not built in the development environment, which had no Docker daemon. CI builds and tests the code without Docker.
