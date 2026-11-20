# Methodology

## Image generation (`fittrace.simulation`, `panel-gap-generator/2.0.0`)

A top-down view of two panels separated by a gap. With `u = (x − cx)·cos θ − (y − cy)·sin θ` as the signed distance along the gap normal, pixels with `|u − offset| < gap/2` lie in the gap. Edge coverage is computed exactly per pixel (area-sampled at 4× supersampling), so the image has true sub-pixel edges and the ground truth stays at the panel silhouette.

Version 2.0 renders the **painted body** as an end-of-line camera sees it: a colour (BGR) image of a painted panel pair.

- **Paint:** one of seven invented paint codes, drawn per unit from a fixed production mix (white 28%, black 20%, grey 14%, blue metallic 12%, red 11%, silver metallic 9%, graphite metallic 6%). Codes and names are fictional.
- **Exposure recipe:** dark paints get a longer exposure, but only the square root of the full correction, and never so long that the paint's strongest colour channel would exceed 0.88 of full scale. Black panels therefore stay dark and noisy, and saturated reds do not clip.
- **Hem roll-off** (`edge_rolloff_mm`): panel brightness falls towards the edge, weighting the coverage of each edge pixel.
- **Surface:** orange peel (low-frequency texture), metallic flake sparkle on metallic paints, a styling crease line at a fixed height per location, and occasional dust specks.
- **Gap interior:** either a dark flange with a narrow lit band (`flange`, used at FD-FF-M) or a B-pillar trim with a weather seal (`pillar`, FD-RD-M).
- **Clear-coat reflection:** a soft, neutral band from a booth light tube at a random angle, position and width, scaled by the paint's gloss. It lands on the panels, not in the gap.
- **Optics and sensor:** Gaussian PSF, a linear illumination gradient and vignette, an optional occluding clip over the top rows, then read noise plus shot noise per channel and 8-bit quantisation.

The ground truth (`gap_mm`, `gap_px`, edge positions) is returned separately. The previous greyscale renderer (1.x) is kept for the condition sweeps that need it and for backwards-compatible tests.

## Gap measurement (`fittrace.vision.gap`, `fittrace.gap.scanline-subpixel` 1.1.0)

1. **Input checks:** a 2-D greyscale or 3-channel colour image of at least 32 × 32 px. Colour is converted to luma (Rec. 601 weights). A p1–p99 dynamic range of at least 40 levels is required, and saturation above 5% sets a flag.
2. **Calibration:** a positive finite `mm_per_px` (any other value fails with `invalid_calibration`). `None` gives a pixel-only result flagged `uncalibrated`. The service layer only passes a calibration valid at capture time.
3. **Smoothing:** Gaussian with σ = 1.5 px, then a horizontal Sobel derivative (levels per px).
4. **Edge pairs:** for every 4th row inside a 6 px margin, the local derivative minima and maxima beyond a **noise-adaptive threshold**: `max(2.0, 6 × 1.4826 × MAD(gradient in the ROI))`. The algorithm picks the strongest falling/rising pair at least 3 px apart whose interior is darker than both neighbouring panels.

   Version 1.0 used a fixed 6 levels/px. On black paint the panel-to-gap contrast is only a few levels, so some rows found no edge and 3 of 320 demo images failed with `insufficient_valid_rows`. Version 1.1 scales the threshold with the measured gradient noise instead: it stays well above noise on noisy images and drops low enough for dark paint. The values used are stored in the run diagnostics (`gradient_noise`, `edge_threshold`), and both parameters can be changed in an interactive re-run.
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
    − 0.002 · (film_build_µm − 110)
    + bias[FX at S20]
    + ε,   ε ~ N(0, σ_l)
```

| | FD-FF-M | FD-RD-M |
|---|---:|---:|
| s (shift sensitivity) | +1.0 | −0.6 |
| k (mm per N·m) | −0.03 | +0.02 |
| c (mm per °C) | 0.006 | 0.004 |
| σ (mm) | 0.10 | 0.09 |

Since generator 2.0 every unit also passes the **S40 paint shop** (booths PB-401/PB-402), which records film build (N(110, 6) µm) and booth temperature. Film build adds `−0.002 mm per µm` above the 110 µm nominal to the gap (paint on both flanges narrows it). The paint colour has no effect on the true gap; any colour dependence in the results comes from the measurement.

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
