-- Current measurement per inspection image for one dataset + location, in production
-- order, with each unit's route (station -> equipment) and process parameters.
-- Used by: analytics series, SPC, station comparison, investigations.
SELECT ii.id                AS image_id,
       pu.id                AS unit_id,
       pu.serial,
       pu.built_at,
       pu.batch_code,
       ii.captured_at,
       ir.id                AS run_id,
       ir.status            AS run_status,
       m.gap_mm,
       m.deviation_mm,
       m.status             AS tolerance_status,
       (SELECT jsonb_object_agg(st.code, eq.code)
          FROM production_events pe
          JOIN stations  st ON st.id = pe.station_id
          JOIN equipment eq ON eq.id = pe.equipment_id
         WHERE pe.unit_id = pu.id)                                    AS route,
       (SELECT jsonb_object_agg(pp.name, pp.value)
          FROM production_events pe
          JOIN process_parameters pp ON pp.production_event_id = pe.id
         WHERE pe.unit_id = pu.id AND pp.name <> 'cycle_time_s')      AS params
  FROM inspection_images ii
  JOIN production_units      pu ON pu.id = ii.unit_id
  JOIN measurement_locations ml ON ml.id = ii.location_id
  JOIN inspection_runs       ir ON ir.id = ii.current_run_id
  LEFT JOIN measurements      m ON m.run_id = ir.id
 WHERE ii.dataset_id = :dataset_id
   AND ml.code = :location
   AND (CAST(:until AS timestamptz) IS NULL OR pu.built_at <= CAST(:until AS timestamptz))
 ORDER BY pu.built_at, pu.id;
