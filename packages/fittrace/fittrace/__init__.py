"""FitTrace scientific core.

Sub-packages are deliberately free of web and database concerns:

- ``fittrace.simulation`` - calibrated synthetic panel images and a manufacturing event simulator
- ``fittrace.vision``     - image-based gap measurement and tolerance evaluation
- ``fittrace.analytics``  - SPC, change-point detection and contributor ranking
- ``fittrace.etl``        - pure-Python record validation used by the ingestion pipelines
- ``fittrace.evaluation`` - reproducible benchmarks against simulated ground truth
"""

__version__ = "1.0.0"
