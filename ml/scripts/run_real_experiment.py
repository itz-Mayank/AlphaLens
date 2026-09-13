"""Runs one real training experiment against the actual research dataset
(`ml/data/sample_data/research_sample_sp500.csv` — real S&P 500 OHLCV, see
its PROVENANCE.md), using the default `ExperimentConfig`. This is the one
place in the repository real (non-synthetic) results are produced; every
test in `tests/` uses fabricated data on purpose and must never be
confused with this script's output.

Usage (from `ml/`, with the package's own venv active):
    python scripts/run_real_experiment.py [output_dir]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from ml.config import ExperimentConfig  # noqa: E402
from ml.pipelines.train_pipeline import run_experiment  # noqa: E402

DEFAULT_OUTPUT_ROOT = _PROJECT_ROOT / "experiments"


def main() -> None:
    output_root = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT_ROOT
    output_dir = output_root / "sp500_sample_v1"

    config = ExperimentConfig()
    result = run_experiment(config, output_dir)

    print(f"Experiment complete. Output written to: {result.output_dir}")
    print(f"Dataset: {result.provenance.source}")
    print(f"Environment: {result.provenance.environment}")
    print(f"Tickers: {result.provenance.tickers}")
    bounds = result.split_bounds
    print(
        f"Split — train: {bounds.train_start}..{bounds.train_end}, "
        f"validation: {bounds.validation_start}..{bounds.validation_end}, "
        f"test: {bounds.test_start}..{bounds.test_end}"
    )
    print()
    print(json.dumps(result.metrics, indent=2, default=str))


if __name__ == "__main__":
    main()
