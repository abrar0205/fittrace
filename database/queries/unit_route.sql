-- Full simulated manufacturing route of one unit with process parameters.
SELECT st.code AS station, st.name AS station_name, st.sequence,
       eq.code AS equipment, eq.kind AS equipment_kind, eq.name AS equipment_name,
       pe.started_at, pe.ended_at,
       coalesce(jsonb_agg(jsonb_build_object('name', pp.name, 'value', pp.value, 'unit', pp.unit)
                          ORDER BY pp.name) FILTER (WHERE pp.id IS NOT NULL), '[]'::jsonb) AS parameters
  FROM production_events pe
  JOIN stations  st ON st.id = pe.station_id
  JOIN equipment eq ON eq.id = pe.equipment_id
  LEFT JOIN process_parameters pp ON pp.production_event_id = pe.id
 WHERE pe.unit_id = :unit_id
 GROUP BY st.code, st.name, st.sequence, eq.code, eq.kind, eq.name, pe.started_at, pe.ended_at
 ORDER BY st.sequence;
