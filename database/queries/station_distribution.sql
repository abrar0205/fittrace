-- Gap distribution by the equipment used at one station (fixture / tool comparison).
SELECT eq.code                                                    AS equipment,
       count(*)                                                   AS n,
       avg(m.gap_mm)                                              AS mean_mm,
       stddev_samp(m.gap_mm)                                      AS sd_mm,
       percentile_cont(0.5)  WITHIN GROUP (ORDER BY m.gap_mm)     AS median_mm,
       percentile_cont(0.05) WITHIN GROUP (ORDER BY m.gap_mm)     AS p05_mm,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY m.gap_mm)     AS p95_mm,
       count(*) FILTER (WHERE m.status IN ('out_low','out_high'))  AS n_oot,
       array_agg(m.gap_mm ORDER BY pu.built_at)                   AS values
  FROM measurements m
  JOIN inspection_runs       ir ON ir.id = m.run_id
  JOIN inspection_images     ii ON ii.current_run_id = ir.id
  JOIN measurement_locations ml ON ml.id = ii.location_id
  JOIN production_units      pu ON pu.id = ii.unit_id
  JOIN production_events     pe ON pe.unit_id = pu.id
  JOIN stations              st ON st.id = pe.station_id
  JOIN equipment             eq ON eq.id = pe.equipment_id
 WHERE ii.dataset_id = :dataset_id
   AND ml.code = :location
   AND st.code = :station
 GROUP BY eq.code
 ORDER BY eq.code;
