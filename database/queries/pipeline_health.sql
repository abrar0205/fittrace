-- Per-pipeline health: last status, run counts and cumulative reject rate.
SELECT pipeline,
       count(*)                                         AS runs,
       count(*) FILTER (WHERE status = 'failed')        AS failed_runs,
       sum(records_in)                                  AS records_in,
       sum(records_rejected)                            AS records_rejected,
       sum(records_loaded)                              AS records_loaded,
       (array_agg(status ORDER BY started_at DESC))[1]  AS last_status,
       max(started_at)                                  AS last_started_at,
       avg(extract(epoch FROM (finished_at - started_at))) AS avg_duration_s
  FROM pipeline_runs
 GROUP BY pipeline
 ORDER BY pipeline;
