-- Equipment events on the resources a unit used, in the window before it was built.
SELECT eq.code AS equipment, ee.occurred_at, ee.kind, ee.description,
       extract(epoch FROM (:built_at - ee.occurred_at)) / 3600.0 AS hours_before
  FROM equipment_events ee
  JOIN equipment eq ON eq.id = ee.equipment_id
 WHERE ee.dataset_id = :dataset_id
   AND ee.equipment_id IN (SELECT pe.equipment_id FROM production_events pe WHERE pe.unit_id = :unit_id)
   AND ee.occurred_at BETWEEN :built_at - make_interval(hours => :hours) AND :built_at
 ORDER BY ee.occurred_at DESC, ee.id DESC;
