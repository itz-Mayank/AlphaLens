"""Structural enforcement of the training/inference boundary (ADR-001,
extended by Phase 10): `backend/app` may consume `ml.inference`,
`ml.explainability`, `ml.backtest`, and `ml.nlp` freely, but `ml.pipelines`
(training orchestration) and `ml.config` (experiment configuration) may
only ever be imported by `app/services/retraining_service.py` — the one
module that runs training, and only ever as background work triggered by
a Celery task, never inside a request handler. This test scans real
source files with `ast`, not string matching, so a `# ml.pipelines`
comment or a docstring mentioning it can't produce a false positive.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent.parent / "app"
TRAINING_MODULES = ("ml.pipelines", "ml.config")
ALLOWED_IMPORTER = APP_ROOT / "services" / "retraining_service.py"


def _imports_any(path: Path, module_prefixes: tuple[str, ...]) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(module_prefixes):
                    found.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(
            module_prefixes
        ):
            found.append(node.module)
    return found


def _all_python_files(*directories: Path) -> list[Path]:
    files = []
    for directory in directories:
        if directory.exists():
            files.extend(directory.rglob("*.py"))
    return files


class TestTrainingNeverReachableFromRequestHandling:
    def test_no_router_module_imports_training_pipelines_or_config(self):
        offenders = {}
        for path in _all_python_files(APP_ROOT / "api"):
            found = _imports_any(path, TRAINING_MODULES)
            if found:
                offenders[str(path.relative_to(APP_ROOT))] = found
        assert not offenders, (
            f"Router module(s) import training code directly — training must only ever run "
            f"in the background via a Celery task, never inside request handling: {offenders}"
        )

    def test_no_service_module_other_than_retraining_service_imports_training_pipelines(self):
        offenders = {}
        for path in _all_python_files(APP_ROOT / "services"):
            if path == ALLOWED_IMPORTER:
                continue
            found = _imports_any(path, TRAINING_MODULES)
            if found:
                offenders[str(path.relative_to(APP_ROOT))] = found
        assert not offenders, (
            f"Service module(s) other than retraining_service.py import training code: "
            f"{offenders}"
        )

    def test_retraining_service_is_the_one_module_that_actually_does_import_training_pipelines(
        self,
    ):
        """Sanity check that the two tests above aren't vacuously true —
        confirms `ml.pipelines`/`ml.config` really are reachable from
        somewhere, just not from a request-handling path."""
        found = _imports_any(ALLOWED_IMPORTER, TRAINING_MODULES)
        assert found, (
            "Expected app/services/retraining_service.py to import ml.pipelines/ml.config — "
            "if it no longer does, these tests aren't testing anything real."
        )

    def test_no_router_module_directly_calls_run_experiment_or_run_retraining(self):
        """A router may enqueue the Celery task (`retrain_models_task.delay(...)`)
        but must never call `run_experiment`/`run_retraining` synchronously
        in-process — that would train inside the request/response cycle."""
        forbidden_calls = {"run_experiment", "run_retraining"}
        offenders = {}
        for path in _all_python_files(APP_ROOT / "api"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            called = {
                node.func.id
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in forbidden_calls
            }
            if called:
                offenders[str(path.relative_to(APP_ROOT))] = sorted(called)
        assert not offenders, f"Router module(s) call training functions directly: {offenders}"
