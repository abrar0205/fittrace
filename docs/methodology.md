# Methodology

## Image generation (`fittrace.simulation.geometry`)

A top-down view of two panels separated by a gap. With `u = (x − cx)·cos θ − (y − cy)·sin θ` as the signed distance along the gap normal, pixels with `|u − offset| < gap/2` lie in the gap. The scene is rendered at 4× supersampling and area-averaged, so the image has true sub-pixel edges. On top of that come, in order:

- **Hem shading** (`edge_rolloff_mm`): panel brightness ramps from 35% to 100% over the roll-off width (square-root profile). The ground-truth edge stays at the silhouette.
- **Optical blur:** a Gaussian PSF with `edge_blur_px`.
- **Illumination:** a linear gradient across the field, plus an optional radial vignette.
- **Occlusion:** a textured clip over the top `occlusion_fraction` of rows.
- **Sensor noise:** additive Gaussian, with σ given as a fraction of full scale.
- **Quantisation:** 8 bit.

The ground truth (`gap_mm`, `gap_px`, edge positions) is returned separately.

## Gap measurement (`fittrace.vision.gap`, `fittrace.gap.scanline-subpixel` 1.0.0)

1. **Input checks:** a 2-D image of at least 32 × 32 px, a p1–p99 dynamic range of at least 40 grey levels, and saturation at most 5% (otherwise a flag is set).
2. **Calibration:** a positive finite `mm_per_px` (any other value fails with `invalid_calibration`). `None` gives a pixel-only result flagged `uncalibrated`. The service layer only passes a calibration valid at capture time.
3. **Smoothing:** Gaussian with σ = 1.5 px, then a horizontal Sobel derivative (grey levels per px).
4. **Edge pairs:** for every 4th row inside a 6 px margin, the local derivative minima and maxima beyond ±6 grey/px. The algorithm picks the strongest falling/rising pair at least 3 px apart whose interior is darker than both neighbouring panels.
5. **Sub-pixel refinement:** a three-point parabola through the derivative peak, clamped to ±0.5 px.
6. **Robust fits:** `x = a·y + b` per edge, least squares with iterative rejection of points beyond 3.5 × 1.4826 × MAD (up to 5 iterations). Rows that are inliers for both edges count as valid.
7. **Gates:**
   - valid rows below 35% of sampled rows fails with `insufficient_valid_rows`;
   - below 90% sets the `partial_visibility` flag;
   - edge angles differing by more than 1.5° fails with `edges_not_parallel`;
   - a gap below 3 px fails with `gap_below_resolution`.
8. **Gap:** `(x_R(y0) − x_L(y0)) · cos θ`, where θ is the mean edge angle and y0 the image centre row, which is the perpendicular distance between parallel lines. It is multiplied by `mm_per_px`.
9. **Reported dispersion:** the SD of the row-wise widths and its standard error. This is a repeatability lower bound (rows are partly correlated by the smoothing), not a GUM uncertainty budget, and the UI labels it that way.

The overlay (sampled edge points with inlier flags, fitted lines, ROI and the measurement segment) is exactly the algorithm's internal state.

## Tolerance evaluation

Specification limits are LSL = nominal + lower_tol and USL = nominal + upper_tol, versioned per location with `valid_from`. A value exactly at a limit is in tolerance. Specification limits are never derived from data.

## Simulation (`fittrace.simulation.factory`)

For unit `u` at location `l`:

```
gap = nominal_l
    + s_l · offset[FX at S20](t)
    + 0.4 · s_l · offset[FX at S10](t)
    + k_l · (torque_actual − 24 N·m)
    + c_l · (T_ambient − 21 °C)
    + bias[FX at S20]
    + ε,   ε ~ N(0, σ_l)
```

| | FD-FF-M | FD-RD-M |
|---|---:|---:|
| s (shift sensitivity) | +1.0 | −0.6 |
| k (mm per N·m) | −0.03 | +0.02 |
| c (mm per °C) | 0.006 | 0.004 |
| σ (mm) | 0.10 | 0.09 |

Static fixture biases are +0.02, −0.015 and 0 mm. Clamp pressure, weld current and cycle times are **distractors with zero effect**. Resources are assigned at random rather than round-robin, so stations are not aliased with each other.

There are two fault types:

- **Fixture shift:** a step change in a fixture's offset from a given unit onwards.
- **Tool calibration drift:** the actual torque falls by `m` N·m per 100 units, while the reported torque stays nominal. The sensor cannot see it.

Routine maintenance, check and calibration events are generated for every resource, so an event near a change point is weak evidence on its own.

## SPC (`fittrace.analytics.spc`)

I-MR chart with Phase I limits from the first `baseline_n` points: CL = mean, σ̂ = MR̄/1.128, limits CL ± 3σ̂, MR UCL = 3.267·MR̄. The rules are Western Electric R1 (beyond 3σ), R2 (2 of 3 beyond 2σ on one side) and R4 (8 in a row on one side). Applicability warnings fire when the baseline has fewer than 20 points, |lag-1 autocorrelation| exceeds 0.3, Shapiro-Wilk gives p < 0.01, or baseline points fall outside the limits. Cp/Cpk is reported only when the baseline has no signals.

## Change point and detection (`fittrace.analytics.changepoint`)

- **Localisation:** the split that maximises `|mean₂ − mean₁| · sqrt(k(n−k)/n)` (equivalent to least squares), with a minimum segment length. The p-value comes from 999 permutations of the series, which assumes exchangeability under no shift.
- **Online detection:** a two-sided tabular CUSUM with k = 0.5σ and h = 6σ (benchmark) or 5σ (investigation context), with μ₀ and σ from the baseline.

## Contributor ranking (`fittrace.analytics.contributors`, `did-attribution` 1.0.0)

The analysis uses units up to the trigger, with incomplete routes excluded and counted. With `post = 1` from the change point onwards, each candidate gets an OLS model with HC3 standard errors:

- **Equipment or categorical level L:** `y ~ post + [F=L] + post·[F=L]`. The interaction coefficient is the difference-in-differences effect. Attributable shift = share of post-change units on L × effect.
- **Parameter X:** `y ~ post + X`. Attributable shift = slope × (mean_post(X) − mean_pre(X)).

A level needs at least 5 units in each of level/rest × before/after, otherwise it is marked not estimable (for example, batches that only exist after the change, which are confounded with time). The p-values are adjusted with Benjamini-Hochberg. A hypothesis is significant when q < α and its explained fraction (attributable / observed shift) is positive. Ranking puts significant hypotheses first, ordered by explained fraction. Cramér's V above 0.8 between categorical factors is reported as aliasing. In the demo, batch and shift are aliased because coil batches run within shifts. Equipment events within 12 h before or 2 h after the change point are attached as context and never change the score.

## Corrective-action verification

The simulator continues production after the last imported unit twice, from the same seed. The baseline scenario keeps all injected faults; the adjusted scenario sets `realigned = (target,)`. Because the random draws are identical, each unit is paired. Both scenarios are rendered and measured by the vision algorithm. The comparison reports the paired mean change with a t-interval, Hedges g, the OOT rates with Fisher's exact test, and the change on the target equipment only.
