# Evaluation

Every number here was read from a `benchmark_results` row produced by `python -m app.cli benchmark-vision` and `benchmark-investigation` (seeds 1000 and 5000). Running them again reproduces the same values: the vision benchmark was run twice in development and matched to every printed digit.

## Gap measurement against ground truth

Generator `panel-gap-generator/2.0.0` (colour, painted panels), algorithm `fittrace.gap.scanline-subpixel` 1.1.0.

**Nominal operating distribution**, 200 images: paint from the production mix, random gap interior (flange or pillar), gap U(3, 5) mm, angle N(0, 1°), offset U(±0.8) mm, illumination gradient N(0, 0.12), noise around 0.016, hem roll-off around 0.06 mm, random clear-coat reflection, orange peel and dust, spec 4.0 ± 0.5 mm.

| Metric | Value |
|---|---:|
| Bias (measured − true) | +23.7 µm |
| MAE | 23.7 µm |
| RMSE | 23.9 µm |
| 95th percentile of the absolute error | 28.4 µm |
| Failure rate | 0.0% |
| Tolerance classification accuracy | 98.5% |
| False-positive rate (truly in tolerance, called out) | 2.2% |
| False-negative rate | 0.9% |
| Latency p50 / p95 (measurement only) | 24.1 / 32.0 ms |

The figures are close to the earlier greyscale benchmark (+23.5 µm bias, 23.7 µm RMSE). The error is dominated by the hem roll-off (see the sweep below), not by colour, reflections or texture. Latency rose from 17 to 24 ms p50 because of the colour conversion and the noise estimate.

**Condition sweeps**, 24 images per point. Each sweep varies one factor and draws the rest from the nominal distribution. Values are bias / RMSE in µm, and "fail" is the share of images where the algorithm declined to report a value.

| Condition | Result |
|---|---|
| Paint (7 codes) | White 23.6/23.8, black 23.6/23.8, grey 23.9/24.1, blue metallic 25.0/25.1, red 22.5/22.8, silver metallic 24.6/24.8, graphite metallic 24.4/24.6. No failures on any paint. Red and blue metallic differ by 2.5 µm, about three standard errors at 24 images per point, so the bias probably depends slightly on colour. That is small against the 1 mm tolerance window but would matter for a bias correction. |
| Clear-coat reflection 0 to 2 (relative strength) | 25.0/25.2 at 0, 21.7 to 23.5 with a reflection. No failures; the reflection band lands on the panels, not on the edges. |
| Hem roll-off 0, 0.03, 0.06, 0.1, 0.2 mm | −0.1/1.0, 12.9/13.0, 23.8/23.8, 32.4/32.4, 31.9/32.0. The bias is caused by edge definition, not by noise. |
| Noise σ 0.005 to 0.15 of full scale | 23.2/23.4 rising to 30.7/31.1. At σ ≥ 0.1, 1 of 24 images fails (4%), in both cases a black panel. |
| Edge rotation 0 to 12° | 22.7 to 24.2 bias. Insensitive. |
| Illumination gradient 0 to 0.8 | 22.4 to 24.2 bias. Insensitive. |
| Optical blur σ 0.5 to 5 px | 22.2 to 24.1 bias. Insensitive in this range. |
| Gap width 0.1 to 8 mm | 23–25 µm from 0.2 mm upwards; 35 µm at 0.1 mm (4 px), where the edges start to interact. |
| Occluded rows 0 to 60% | Unaffected. At 70% and 80%: **100% fail** (`insufficient_valid_rows`), by design. |
| Calibration error −2% to +2% | −51.4 to +99.3 µm bias. The error is proportional to gap × scale error (about 40 µm per 1% at 4 mm). |
| Resolution 0.01 to 0.06 mm/px | At 0.01 mm/px a 3–5 mm gap needs 300–500 px of a 480 px field: **67% fail**. Bias grows from 22.3 µm (0.02) to 25.4 µm (0.06). |

**Why algorithm 1.1.0.** With version 1.0's fixed edge threshold of 6 levels/px, 3 of the 320 colour images in the integration-test dataset (all black paint) failed with `insufficient_valid_rows`: the panel-to-gap contrast on black paint is only a few levels, so many rows found no edge. Version 1.1 sets the threshold from the measured gradient noise; those 3 images then measure with all rows valid, and all 1,120 demo images measure. The benchmark above was not repeated with version 1.0 on the colour generator, so no before/after accuracy comparison is claimed.

**Where it is reliable:** single-view, approximately parallel, shadowed gaps of at least 0.2 mm that fit inside the field of view with margin, with at least 35% of rows visible and a correct calibration.

**Where it breaks:**
- Heavy occlusion: it refuses to measure.
- A gap that does not fit the field of view.
- A gap narrower than about 4 px.
- Wrong calibration: undetectable from the image alone.
- Hem shading: a systematic over-read that needs a reference-artefact correction (not implemented).

The failure and worst-case gallery on the Method sheet re-renders the stored cases from their scene parameters.

## Contributor recovery against injected faults

There are 60 faulted histories (20 per class) and 20 fault-free histories, each with 400 units and location FD-FF-M. Faults have a random target, a random start between 40% and 65% of the history, and a random magnitude:
- S20 fixture shift: 0.25–0.55 mm;
- S30 drift: 4–8 N·m per 100 units;
- S10 shift: 0.3–0.6 mm.

Measured gaps use the vision benchmark's bias (+23.7 µm) and residual spread (`measurement_model` mode). A full-pipeline check that renders and measures every unit on 3 histories ranked the true target first in all 3 of them.

| Fault class | CUSUM alarm after fault | Median detection delay | Top-1 at alarm | Top-1 at alarm + 60 | Top-1 full history | Top-3 full history | Median change-point error |
|---|---:|---:|---:|---:|---:|---:|---:|
| S20 fixture shift | 65% | 7 units | 0% | 70% | 100% | 100% | 3.5 units |
| S30 torque drift | 85% | 90 units | 30% | 70% | 100% | 100% | 91.5 units |
| S10 fixture shift (weak) | 60% | 14.5 units | 20% | 60% | 100% | 100% | 3 units |

Fault-free histories:
- **CUSUM false alarm rate: 50%** (k = 0.5, h = 6, μ₀ and σ from 60 units). The textbook ARL₀ for h = 6 would suggest roughly 25% over 340 points (version 1.0 of the simulator gave 55%). The difference comes from Phase I estimation error in a short baseline, which is a practical argument for longer baselines or self-starting charts.
- **False attribution rate: 5%** (1 of 20 runs named a significant contributor).

Interpretation:
- Right at the alarm there are too few shifted units to separate the fault from noise.
- Recovery rises with post-change production.
- Drift faults have large change-point errors because a ramp has no single change point.
- "100% at full history" is a property of this simulation (recorded factors, adequately sized faults, no confounding) and is **not** a claim about real plants.

## Corrective-action verification (demo dataset)

The first three out-of-tolerance results (SIM-00266, SIM-00274, SIM-00282) come early in the fault, and the investigation behaves accordingly: the first reports no sustained shift (permutation p = 0.071), the second finds a shift but no significant contributor, and the third already names FX-202 (q = 0.008).

In the investigation triggered by SIM-00351, the change point is placed at SIM-00266 (true start SIM-00265) and FX-202 is ranked first (q < 0.0001). The simulated re-alignment of FX-202 over 120 paired units changed the mean gap by **−0.147 mm** (95% CI −0.183 to −0.111). Out-of-tolerance results fell from 9.2% to 0.0% (Fisher p = 0.0008). Re-aligning FX-203, which had no fault, changed nothing (0.000 mm, 9.2% before and after). Both are simulated experiments.
