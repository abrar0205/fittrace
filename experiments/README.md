# experiments/

Benchmarks are reproducible CLI commands (results are stored in `benchmark_results` and shown on the Method sheet):

```bash
cd apps/api
python -m app.cli benchmark-vision --per-condition 24          # fittrace/evaluation/vision_bench.py, seed 1000
python -m app.cli benchmark-investigation --runs 60 --null 20           # fittrace/evaluation/investigation_bench.py, seed 5000
```

Pure-Python use without a database:

```python
from fittrace.evaluation.vision_bench import run_vision_benchmark
from fittrace.evaluation.investigation_bench import run_investigation_benchmark
r = run_investigation_benchmark(n_runs=12, mode="full_pipeline")  # renders and measures every unit
```
