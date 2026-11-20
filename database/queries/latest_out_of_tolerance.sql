-- Most recent out-of-tolerance inspections (current pipeline result per image).
SELECT ii.id AS image_id, pu.serial, ml.code AS location, ii.captured_at,
       m.gap_mm, m.deviation_mm, m.status
  FROM measurements m
  JOIN inspection_runs       ir ON ir.id = m.run_id
  JOIN inspection_images     ii ON ii.current_run_id = ir.id
  JOIN production_units      pu ON pu.id = ii.unit_id
  JOIN measurement_locations ml ON ml.id = ii.location_id
 WHERE ii.dataset_id = :dataset_id
   AND m.status IN ('out_low', 'out_high')
 ORDER BY ii.captured_at DESC, ii.id DESC  -- tie-break: a unit's images share a capture time
 LIMIT :limit;
