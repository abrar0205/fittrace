-- Hourly deviation trend and out-of-tolerance frequency per location.
-- Aggregates use exact numeric arithmetic so results do not depend on summation order (query plan).
SELECT ml.code AS location,
       date_trunc('hour', ii.captured_at)                    AS bucket,
       count(*)                                              AS n,
       avg(m.deviation_mm::numeric)::float8                  AS mean_deviation_mm,
       stddev_samp(m.deviation_mm::numeric)::float8          AS sd_deviation_mm,
       count(*) FILTER (WHERE m.status IN ('out_low','out_high')) AS n_oot
  FROM measurements m
  JOIN inspection_runs       ir ON ir.id = m.run_id
  JOIN inspection_images     ii ON ii.current_run_id = ir.id
  JOIN measurement_locations ml ON ml.id = ii.location_id
 WHERE ii.dataset_id = :dataset_id
 GROUP BY 1, 2
 ORDER BY 1, 2;
