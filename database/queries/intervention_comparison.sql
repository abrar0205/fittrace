-- Before/after summary of simulated corrective-action verification runs.
SELECT vr.id, ca.kind, ca.target_code, vr.status, vr.n_units,
       (vr.result -> 'baseline' ->> 'mean_mm')::float      AS baseline_mean_mm,
       (vr.result -> 'adjusted' ->> 'mean_mm')::float      AS adjusted_mean_mm,
       (vr.result -> 'baseline' ->> 'oot_rate')::float     AS baseline_oot_rate,
       (vr.result -> 'adjusted' ->> 'oot_rate')::float     AS adjusted_oot_rate,
       vr.created_at
  FROM verification_runs vr
  JOIN corrective_actions ca ON ca.id = vr.corrective_action_id
 WHERE ca.investigation_id = :investigation_id
 ORDER BY vr.created_at DESC;
