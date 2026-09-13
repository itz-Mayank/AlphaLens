from ml.registry.registry import (
    ModelRecord,
    ModelRegistry,
    ModelStatus,
    compute_artifact_checksum,
    new_version_string,
)


def _make_record(**overrides) -> ModelRecord:
    defaults = dict(
        model_name="xgboost_return",
        model_type="xgboost_return",
        version="xgboost_return-v1",
        dataset_version="research_sample_sp500_v1",
        feature_version="fs_v1",
        hyperparameters={"n_estimators": 200},
        train_period=("2013-02-08", "2016-06-30"),
        validation_period=("2016-07-01", "2017-06-30"),
        test_period=("2017-07-01", "2018-02-07"),
        metrics={"regression": {"rmse": 0.02}},
        artifact_path="/tmp/models/xgboost_return",
        created_at="2026-09-11T00:00:00Z",
        git_commit="abc123",
        status=ModelStatus.VALIDATED,
    )
    defaults.update(overrides)
    return ModelRecord(**defaults)


def test_register_and_list_all(tmp_path):
    registry = ModelRegistry(tmp_path / "registry.json")
    registry.register(_make_record())
    records = registry.list_all()
    assert len(records) == 1
    assert records[0]["model_name"] == "xgboost_return"


def test_get_by_record_id(tmp_path):
    registry = ModelRegistry(tmp_path / "registry.json")
    record = _make_record()
    registry.register(record)
    fetched = registry.get(record.record_id)
    assert fetched is not None
    assert fetched["record_id"] == record.record_id


def test_get_unknown_id_returns_none(tmp_path):
    registry = ModelRegistry(tmp_path / "registry.json")
    assert registry.get("does-not-exist") is None


def test_set_status_updates_the_record(tmp_path):
    registry = ModelRegistry(tmp_path / "registry.json")
    record = _make_record(status=ModelStatus.TRAINING)
    registry.register(record)
    registry.set_status(record.record_id, ModelStatus.PRODUCTION)
    assert registry.get(record.record_id)["status"] == ModelStatus.PRODUCTION


def test_set_status_unknown_id_raises(tmp_path):
    import pytest

    registry = ModelRegistry(tmp_path / "registry.json")
    with pytest.raises(KeyError):
        registry.set_status("nope", ModelStatus.FAILED)


def test_best_by_metric_lower_is_better(tmp_path):
    registry = ModelRegistry(tmp_path / "registry.json")
    good = _make_record(model_name="good", metrics={"regression": {"rmse": 0.01}})
    bad = _make_record(model_name="bad", metrics={"regression": {"rmse": 0.05}})
    registry.register(bad)
    registry.register(good)

    best = registry.best_by_metric(
        metric_path=("metrics", "regression", "rmse"), higher_is_better=False
    )
    assert best["model_name"] == "good"


def test_best_by_metric_higher_is_better(tmp_path):
    registry = ModelRegistry(tmp_path / "registry.json")
    good = _make_record(model_name="good", metrics={"classification": {"accuracy": 0.9}})
    bad = _make_record(model_name="bad", metrics={"classification": {"accuracy": 0.5}})
    registry.register(bad)
    registry.register(good)

    best = registry.best_by_metric(
        metric_path=("metrics", "classification", "accuracy"), higher_is_better=True
    )
    assert best["model_name"] == "good"


def test_best_by_metric_returns_none_when_nothing_matches(tmp_path):
    registry = ModelRegistry(tmp_path / "registry.json")
    assert registry.best_by_metric(metric_path=("metrics", "nope"), higher_is_better=True) is None


def test_best_by_metric_filters_by_model_type(tmp_path):
    registry = ModelRegistry(tmp_path / "registry.json")
    registry.register(
        _make_record(
            model_name="a", model_type="lstm_return", metrics={"regression": {"rmse": 0.1}}
        )
    )
    registry.register(
        _make_record(
            model_name="b", model_type="gru_return", metrics={"regression": {"rmse": 0.01}}
        )
    )
    best = registry.best_by_metric(
        model_type="lstm_return",
        metric_path=("metrics", "regression", "rmse"),
        higher_is_better=False,
    )
    assert best["model_name"] == "a"


def test_new_version_string_is_unique_and_includes_model_name():
    v1 = new_version_string("lstm_return")
    assert v1.startswith("lstm_return-")


def test_registry_persists_across_instances(tmp_path):
    path = tmp_path / "registry.json"
    ModelRegistry(path).register(_make_record())
    reopened = ModelRegistry(path)
    assert len(reopened.list_all()) == 1


def test_get_active_returns_the_production_record(tmp_path):
    registry = ModelRegistry(tmp_path / "registry.json")
    registry.register(_make_record(status=ModelStatus.VALIDATED))
    production = _make_record(status=ModelStatus.PRODUCTION)
    registry.register(production)
    active = registry.get_active("xgboost_return")
    assert active is not None
    assert active["status"] == ModelStatus.PRODUCTION


def test_get_active_returns_none_for_a_model_type_with_no_production_record(tmp_path):
    registry = ModelRegistry(tmp_path / "registry.json")
    registry.register(_make_record(status=ModelStatus.VALIDATED))
    assert registry.get_active("xgboost_return") is None


def test_list_by_status_filters_correctly(tmp_path):
    registry = ModelRegistry(tmp_path / "registry.json")
    registry.register(_make_record(status=ModelStatus.VALIDATED))
    registry.register(_make_record(status=ModelStatus.FAILED))
    registry.register(_make_record(status=ModelStatus.FAILED))
    assert len(registry.list_by_status(model_type="xgboost_return", status=ModelStatus.FAILED)) == 2
    assert (
        len(registry.list_by_status(model_type="xgboost_return", status=ModelStatus.VALIDATED)) == 1
    )


def test_best_by_metric_can_be_restricted_to_specific_statuses(tmp_path):
    registry = ModelRegistry(tmp_path / "registry.json")
    registry.register(
        _make_record(metrics={"regression": {"rmse": 0.001}}, status=ModelStatus.FAILED)
    )
    registry.register(
        _make_record(metrics={"regression": {"rmse": 0.05}}, status=ModelStatus.PRODUCTION)
    )
    # Unrestricted: the FAILED record wins on the raw number alone — this
    # is exactly the pre-Phase-10 behavior that made `status` decorative.
    unrestricted = registry.best_by_metric(
        metric_path=("metrics", "regression", "rmse"), higher_is_better=False
    )
    assert unrestricted["status"] == ModelStatus.FAILED
    # Restricted to PRODUCTION: only the actually-approved record is even
    # a candidate, regardless of what a FAILED record's number says.
    restricted = registry.best_by_metric(
        metric_path=("metrics", "regression", "rmse"),
        higher_is_better=False,
        statuses=(ModelStatus.PRODUCTION,),
    )
    assert restricted["status"] == ModelStatus.PRODUCTION


def test_set_status_records_a_reason(tmp_path):
    registry = ModelRegistry(tmp_path / "registry.json")
    record = _make_record()
    registry.register(record)
    registry.set_status(record.record_id, ModelStatus.FAILED, reason="did not beat baseline")
    assert registry.get(record.record_id)["status_reason"] == "did not beat baseline"


class TestArtifactChecksum:
    def test_returns_none_for_a_nonexistent_directory(self, tmp_path):
        assert compute_artifact_checksum(tmp_path / "does_not_exist") is None

    def test_returns_none_for_an_empty_directory(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        assert compute_artifact_checksum(empty) is None

    def test_is_deterministic_for_the_same_content(self, tmp_path):
        artifact = tmp_path / "artifact"
        artifact.mkdir()
        (artifact / "model.json").write_text('{"weights": [1, 2, 3]}')
        first = compute_artifact_checksum(artifact)
        second = compute_artifact_checksum(artifact)
        assert first == second
        assert first is not None

    def test_changes_when_the_file_content_changes(self, tmp_path):
        artifact = tmp_path / "artifact"
        artifact.mkdir()
        (artifact / "model.json").write_text('{"weights": [1, 2, 3]}')
        before = compute_artifact_checksum(artifact)
        (artifact / "model.json").write_text('{"weights": [9, 9, 9]}')
        after = compute_artifact_checksum(artifact)
        assert before != after

    def test_verify_artifact_integrity_detects_tampering(self, tmp_path):
        artifact_dir = tmp_path / "models" / "xgboost_return"
        artifact_dir.mkdir(parents=True)
        (artifact_dir / "model.json").write_text('{"weights": [1, 2, 3]}')

        registry = ModelRegistry(tmp_path / "registry.json")
        record = _make_record(
            artifact_path=str(artifact_dir),
            artifact_checksum=compute_artifact_checksum(artifact_dir),
        )
        registry.register(record)
        stored = registry.get(record.record_id)
        assert registry.verify_artifact_integrity(stored) is True

        (artifact_dir / "model.json").write_text('{"weights": [999, 999, 999]}')
        assert registry.verify_artifact_integrity(stored) is False

    def test_verify_artifact_integrity_is_true_for_a_record_with_no_stored_checksum(self, tmp_path):
        """An old record from before this field existed — never treated as
        tampered just because it predates the check."""
        registry = ModelRegistry(tmp_path / "registry.json")
        record = _make_record(artifact_checksum=None)
        registry.register(record)
        assert registry.verify_artifact_integrity(registry.get(record.record_id)) is True
