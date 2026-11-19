import { useMemo } from 'react'

import { api } from '../api/client'
import { useBenchmark, useDefaultDatasetKey } from '../api/hooks'
import { Plot } from '../components/Plot'
import { Sheet } from '../components/Shell'
import { ErrorState, Loading, Panel } from '../components/ui'
import { dt, fmt, pct } from '../lib/format'

const BLUE = '#3b6fd0', INK3 = '#5f6c77', AMBER = '#a86a00'

function ConditionChart({ cond }: { cond: { label: string; points: any[] } }) {
  const data = useMemo(() => {
    const ok = cond.points.filter((p) => p.n_ok > 0)
    const sd = ok.map((p) => Math.sqrt(Math.max(0, p.rmse_um ** 2 - p.bias_um ** 2)))
    return [
      { type: 'scatter', mode: 'lines+markers', x: ok.map((p) => String(p.value)), y: ok.map((p) => p.bias_um),
        error_y: { type: 'data', array: sd, color: INK3, thickness: 1, width: 3 }, line: { color: BLUE, width: 2 }, marker: { size: 7, color: BLUE },
        text: ok.map((p, i) => `bias ${p.bias_um.toFixed(1)} µm, sd ${sd[i].toFixed(1)} µm<br>${p.n_ok} of ${p.n} measured`),
        hovertemplate: '%{x}: %{text}<extra></extra>' },
      { type: 'scatter', mode: 'text', x: cond.points.filter((p) => p.failure_rate > 0).map((p) => String(p.value)),
        y: cond.points.filter((p) => p.failure_rate > 0).map(() => 0), text: cond.points.filter((p) => p.failure_rate > 0).map((p) => `${Math.round(p.failure_rate * 100)}%<br>failed`),
        textposition: 'top center', textfont: { size: 11, color: AMBER }, hoverinfo: 'skip' },
    ]
  }, [cond])
  return (
    <div className="bench-cell">
      <h3>{cond.label}</h3>
      <Plot ariaLabel={`Measurement bias versus ${cond.label}`} height={170} data={data}
        layout={{ margin: { l: 44, r: 8, t: 6, b: 28 }, xaxis: { type: 'category' }, yaxis: { title: { text: 'error (µm)' }, zeroline: true, zerolinecolor: '#aeb9c1' } }} />
    </div>
  )
}

export function Method() {
  const datasetKey = useDefaultDatasetKey()
  const vision = useBenchmark('vision')
  const inv = useBenchmark('investigation')
  const v = vision.data?.summary as any
  const iv = inv.data?.summary as any

  const hist = useMemo(() => v ? [{ type: 'histogram', x: v.nominal_errors_um, marker: { color: BLUE }, nbinsx: 30, hovertemplate: '%{x} µm: %{y}<extra></extra>' }] : [], [v])

  return (
    <Sheet no={7} title="Method and evaluation"
      lede="How the measurements and rankings are produced, and how well they recover known simulated ground truth. Every figure on this sheet is read from a stored benchmark run."
      tb={{ dataset: datasetKey, extra: [['Benchmarks', v ? dt(vision.data!.created_at) : '—']] }}>
      <div className="grid cols-3">
        <Panel title="Measurement">
          <ol className="steps">
            <li>Validate image size, dynamic range, saturation and the calibration valid at capture time.</li>
            <li>Gaussian smoothing, then a horizontal Sobel derivative.</li>
            <li>Every 4th row: strongest falling and rising edge pair around a darker interior.</li>
            <li>Three-point parabolic refinement to sub-pixel edge positions.</li>
            <li>Robust line fit per edge with iterative MAD outlier rejection; parallelism check.</li>
            <li>Gap = edge distance at the measurement row × cos θ, × mm per px.</li>
          </ol>
          <p className="small muted">Without valid calibration the result stays in pixels. If prerequisites fail, no value is reported.</p>
        </Panel>
        <Panel title="Simulation">
          <p className="small" style={{ marginBottom: 8 }}>Gap = nominal + location sensitivity × fixture offset + torque coefficient × (actual torque − 24 N·m) + thermal coefficient × (T − 21 °C) + static fixture bias + noise.</p>
          <p className="small" style={{ marginBottom: 8 }}>The demo dataset injects a +0.42 mm lateral shift on fixture FX-202 from unit 265. Clamp pressure and weld current are documented distractors with zero effect.</p>
          <p className="small muted">Images are rendered from the simulated gap with known scale (0.025 mm/px), hem shading, blur, illumination gradient and sensor noise. Ground truth is stored separately and never read by the algorithm.</p>
        </Panel>
        <Panel title="Investigation">
          <ol className="steps">
            <li>Single mean-shift change point with a 999-permutation p-value.</li>
            <li>Difference-in-differences per equipment level and slope per parameter, OLS with HC3 errors.</li>
            <li>Benjamini-Hochberg adjustment across all hypotheses.</li>
            <li>Rank by share of the observed shift explained, significant first.</li>
          </ol>
          <p className="small muted">Associations only. Aliased factors are reported, not separated.</p>
        </Panel>
      </div>

      <Panel title="Gap measurement against ground truth" aside={v ? `${v.algorithm}, ${v.generator}` : undefined}
        note={v ? <>The positive bias at nominal conditions comes from hem shading (edge roll-off): the intensity edge sits outside the true panel silhouette. It is systematic and could be removed with a reference-artefact correction, which is not applied here.</> : undefined}>
        {vision.isLoading ? <Loading /> : vision.error ? <ErrorState error={vision.error} /> : v && (
          <div className="grid cols-main">
            <div>
              <div className="stat-row">
                <div><span className="fig-k">Bias</span><span className="fig-v">{fmt(v.overall.bias_um, 1)}<small>µm</small></span></div>
                <div><span className="fig-k">RMSE</span><span className="fig-v">{fmt(v.overall.rmse_um, 1)}<small>µm</small></span></div>
                <div><span className="fig-k">95th pct. |error|</span><span className="fig-v">{fmt(v.overall.p95_abs_um, 1)}<small>µm</small></span></div>
                <div><span className="fig-k">Failure rate</span><span className="fig-v">{pct(v.overall.failure_rate, 1)}</span></div>
                <div><span className="fig-k">Tolerance calls correct</span><span className="fig-v">{pct(v.overall.classification_accuracy, 1)}</span></div>
                <div><span className="fig-k">Latency p50 / p95</span><span className="fig-v">{fmt(v.overall.latency_p50_ms, 1)}<small>/ {fmt(v.overall.latency_p95_ms, 1)} ms</small></span></div>
              </div>
              <p className="small muted" style={{ marginTop: 8 }}>
                {v.overall.n} images drawn from the nominal operating distribution. False positives (in tolerance, called out) {pct(v.overall.false_positive_rate, 1)}; false negatives {pct(v.overall.false_negative_rate, 1)}, both near the limits where the bias matters.
              </p>
            </div>
            <Plot ariaLabel="Distribution of measurement errors at nominal conditions" height={190} data={hist}
              layout={{ margin: { l: 40, r: 8, t: 6, b: 34 }, xaxis: { title: { text: 'measured − true gap (µm)' } }, yaxis: { title: { text: 'images' } } }} />
          </div>
        )}
      </Panel>

      {v && (
        <Panel title="Where the algorithm holds and where it breaks" aside={`${v.params.per_condition} images per point; bars show ±1 SD`}
          note="Each panel varies one condition and draws the rest from the nominal distribution. Failure labels mark points where the algorithm declined to report a value (for example, too few visible rows, or a field of view too small for the gap).">
          <div className="bench-grid">
            {Object.entries(v.conditions).map(([k, c]: [string, any]) => <ConditionChart key={k} cond={c} />)}
          </div>
        </Panel>
      )}

      {v?.cases?.length > 0 && (
        <Panel title="Failure and worst-case gallery" aside="re-rendered from stored scene parameters">
          <div className="case-grid">
            {v.cases.map((c: any, i: number) => (
              <figure key={i} className="case" style={{ margin: 0 }}>
                <img src={api.imageUrl(`/api/v1/evaluation/vision/cases/${i}/image`)} alt={`Benchmark case: ${c.condition} ${c.value}`} loading="lazy" />
                <figcaption>
                  <b className="cond">{c.kind === 'failure' ? `No value: ${String(c.failure_code).replace(/_/g, ' ')}` : `Error ${(c.error_mm * 1000).toFixed(1)} µm`}</b>
                  <span className="muted">{c.condition.replace(/_/g, ' ')} = {c.value}, true gap {fmt(c.true_gap_mm, 3)} mm</span>
                </figcaption>
              </figure>
            ))}
          </div>
        </Panel>
      )}

      <Panel title="Contributor recovery against injected faults" aside={iv ? `${iv.params.n_runs} faulted and ${iv.params.n_null} fault-free simulated histories, ${iv.mode.replace('_', ' ')}` : undefined}
        note={iv ? <>Each history is simulated with a random fault target, start and magnitude. The investigation sees only measured gaps and recorded factors up to the horizon. Measured gaps use the vision benchmark's bias and spread; a full-pipeline check on {iv.full_pipeline_consistency?.runs.length ?? 0} histories ranked the true target first in {pct(iv.full_pipeline_consistency?.overall.top1_full_history)}.</> : undefined}>
        {inv.isLoading ? <Loading /> : inv.error ? <ErrorState error={inv.error} /> : iv && (
          <>
            <table className="table">
              <thead>
                <tr><th>Fault class</th><th className="r">Runs</th><th className="r">CUSUM alarm</th><th className="r">Median delay</th>
                  <th className="r">Top-1 at alarm</th><th className="r">Top-1 at alarm + 60</th><th className="r">Top-1 full history</th><th className="r">Top-3 full history</th><th className="r">Median change-point error</th></tr>
              </thead>
              <tbody>
                {Object.entries(iv.classes).map(([name, c]: [string, any]) => (
                  <tr key={name}>
                    <td>{name}</td><td className="r">{c.n}</td><td className="r">{pct(c.alarm_rate)}</td>
                    <td className="r">{c.median_detection_delay_units !== null ? `${c.median_detection_delay_units} units` : '—'}</td>
                    <td className="r">{pct(c.horizons.at_alarm.top1_recovery)}</td><td className="r">{pct(c.horizons.alarm_plus_60.top1_recovery)}</td>
                    <td className="r">{pct(c.horizons.full_history.top1_recovery)}</td><td className="r">{pct(c.horizons.full_history.top3_recovery)}</td>
                    <td className="r">{c.horizons.full_history.median_cp_error_units !== null ? `${c.horizons.full_history.median_cp_error_units} units` : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="callout" style={{ marginTop: 12 }}>
              Fault-free histories: the CUSUM (k = {iv.params.cusum.k}, h = {iv.params.cusum.h}, limits from {iv.params.cusum.baseline} units) raised an alarm in <b>{pct(iv.null.cusum_false_alarm_rate)}</b> of them, far above the textbook rate because the short baseline misestimates the process mean and sigma.
              The investigation itself named a significant contributor in <b>{pct(iv.null.false_attribution_rate_full_history)}</b>. Right at the alarm there are too few shifted units to rank reliably; recovery improves with more post-change production. Drift faults have large change-point errors because a ramp has no single change point.
            </div>
          </>
        )}
      </Panel>

      <Panel title="Data tracks">
        <table className="table">
          <thead><tr><th>Track</th><th>Role</th><th>Status in this build</th></tr></thead>
          <tbody>
            <tr><td>Calibrated synthetic panel images and simulated production</td><td>End-to-end product demonstration with known ground truth</td><td>Implemented and loaded</td></tr>
            <tr><td>Carparts-Seg (Ultralytics, 3,833 images, 23 classes)</td><td>Component segmentation only; masks cannot give calibrated millimetre gaps</td><td>Not integrated: licence is ambiguous between AGPL-3.0 and CC BY 4.0</td></tr>
            <tr><td>NIST design, manufacturing and inspection data for a box assembly</td><td>Independent real-data ingestion track, never linked to simulated units</td><td>Blocked: mtc.zip could not be downloaded from the build environment; contents not assumed</td></tr>
            <tr><td>Bosch production line performance (Kaggle)</td><td>Optional high-volume ETL benchmark</td><td>Not attempted: requires Kaggle sign-in and competition rules acceptance</td></tr>
          </tbody>
        </table>
      </Panel>
    </Sheet>
  )
}
