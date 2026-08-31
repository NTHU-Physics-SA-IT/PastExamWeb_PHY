from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONTROL_PATH = REPOSITORY_ROOT / "scripts" / "production-deployment-control.py"


def _load_control():
    spec = importlib.util.spec_from_file_location(
        "production_deployment_control", CONTROL_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def control():
    return _load_control()


@pytest.fixture()
def config(control, tmp_path: Path):
    releases = tmp_path / "releases"
    releases.mkdir()
    state = tmp_path / "state"
    active_env = tmp_path / "pastexam-current-release.env"
    active_env.write_text(
        "release_sha=old\n"
        "release_dir=/opt/pastexam-releases/old\n"
        "activated_at=2026-01-01T00:00:00Z\n"
        "production_override=/etc/pastexam/docker-compose.edge.yml\n"
        "postgres_volume=pastexam-postgres-data\n"
        "minio_volume=pastexam-minio-data\n"
        "redis_volume=pastexam-redis-data\n",
        encoding="utf-8",
    )
    return control.DeploymentConfig(
        state_root=state,
        releases_root=releases,
        active_link=tmp_path / "pastexam-current",
        active_env=active_env,
        mutation_lock=tmp_path / "activation.lock",
        engine_path=tmp_path / "engine",
        systemd_run="systemd-run",
        systemctl="systemctl",
        internal_health_url="http://127.0.0.1/api/health",
        external_health_url="https://example.invalid/api/health",
        runtime_verification=False,
    )


def _active(control, config, sha: str = "a" * 40):
    release = config.releases_root / sha
    release.mkdir()
    manifest = release / "release-manifest.env"
    manifest.write_text(f"release_sha={sha}\n", encoding="utf-8")
    manifest_digest = control.sha256_file(manifest)
    (release / ".activated").write_text(f"{manifest_digest}\n", encoding="utf-8")
    return control.ActiveRecord(
        schema_version=1,
        active_sha=sha,
        active_release_directory=str(release),
        manifest_sha256=manifest_digest,
        activation_request_id=None,
        activation_workflow=None,
        activated_at="2026-09-01T00:00:00Z",
        database_revision="9f1c2a7e4b63",
        previous_active_sha=None,
        receipt_reference=None,
        receipt_sha256=None,
    )


def _request(control, target: str = "b" * 40, request_id: str = "activation-100-1"):
    return control.RequestContract(
        schema_version=1,
        request_id=request_id,
        operation="activate",
        target_sha=target,
        source_ci_run_id=99,
        source_ci_run_attempt=1,
        workflow_run_id=100,
        workflow_run_attempt=1,
    )


def _candidate(control, config, request, *, legacy_nginx: bool = False) -> Path:
    release = config.releases_root / request.target_sha
    release.mkdir()
    frontend_digest = "sha256:" + "1" * 64
    backend_digest = "sha256:" + "2" * 64
    nginx_digest = control.NGINX_DIGEST
    files = {
        ".release-source-sha": f"{request.target_sha}\n",
        "docker/docker-compose.prod.yml": (
            "services:\n  nginx:\n    image: nginx:1.29.2\n"
            if legacy_nginx
            else "services: {}\n"
        ),
    }
    for relative, content in files.items():
        path = release / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    files_lines = "".join(
        f"{control.sha256_file(release / relative)}  {relative}\n" for relative in files
    )
    files_path = release / ".release-files.sha256"
    files_path.write_text(files_lines, encoding="utf-8")
    manifest = release / "release-manifest.env"
    manifest_source = (
        f"release_sha={request.target_sha}\n"
        "workflow_run_id=88\nworkflow_run_attempt=1\n"
        f"source_ci_run_id={request.source_ci_run_id}\n"
        f"source_ci_run_attempt={request.source_ci_run_attempt}\n"
        f"frontend_image=ghcr.io/example/app:frontend-{request.target_sha}@{frontend_digest}\n"
        f"frontend_image_digest={frontend_digest}\n"
        f"backend_image=ghcr.io/example/app:backend-{request.target_sha}@{backend_digest}\n"
        f"backend_image_digest={backend_digest}\n"
    )
    if not legacy_nginx:
        manifest_source += (
            f"nginx_image=nginx:1.29.2@{nginx_digest}\n"
            f"nginx_image_digest={nginx_digest}\n"
        )
    manifest.write_text(manifest_source, encoding="utf-8")
    receipt = {
        "schema_version": 1,
        "kind": "production-candidate-preparation",
        "source_sha": request.target_sha,
        "workflow_run_id": 88,
        "workflow_run_attempt": 1,
        "source_ci_run_id": request.source_ci_run_id,
        "source_ci_run_attempt": request.source_ci_run_attempt,
        "prepared_at": "2026-09-01T00:00:00Z",
        "image_digests": {
            "frontend": frontend_digest,
            "backend": backend_digest,
            **({} if legacy_nginx else {"nginx": nginx_digest}),
        },
        "package_sha256": "3" * 64,
        "release_files_sha256": control.sha256_file(files_path),
        "release_manifest_sha256": control.sha256_file(manifest),
        "release_id": request.target_sha,
        "release_path": f"releases/{request.target_sha}",
        "outcome": "verified",
    }
    receipt_path = release / "candidate-receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    (release / "candidate-receipt.sha256").write_text(
        f"{control.sha256_file(receipt_path)}  candidate-receipt.json\n",
        encoding="utf-8",
    )
    return release


def _fake_engine_success(
    control, controller, request, candidate, *, database_revision="9f1c2a7e4b63"
) -> None:
    backup_root = controller.config.backup_root
    backup_root.mkdir(parents=True, exist_ok=True)
    postgres_metadata = backup_root / "postgres.metadata.json"
    postgres_checksum = backup_root / "postgres.sha256"
    minio_manifest = backup_root / "minio.jsonl"
    for path in (postgres_metadata, postgres_checksum, minio_manifest):
        path.write_text("verified\n", encoding="utf-8")
    evidence = {
        "schema_version": 1,
        "target_sha": request["target_sha"],
        "started_at": "2026-09-01T01:00:00Z",
        "completed_at": "2026-09-01T01:15:00Z",
        "database_revision_before": database_revision,
        "database_revision_after": database_revision,
        "postgres_backup_metadata": str(postgres_metadata),
        "postgres_backup_checksum": str(postgres_checksum),
        "minio_manifest": str(minio_manifest),
        "observation_snapshots": 3,
        "critical_error_count": 0,
        "health_outcome": "green",
        "restart_stability": "stable",
    }
    control.atomic_write_json(
        controller._engine_evidence_path(request["request_id"]), evidence
    )
    (Path(candidate["release_directory"]) / ".activated").write_text(
        f"{candidate['manifest_sha256']}\n", encoding="utf-8"
    )


def test_atomic_active_ledger_write_has_no_partial_residue(control, config) -> None:
    store = control.DeploymentStore(config)
    active = _active(control, config)

    store.seed_active(active)

    assert store.load_active() == active
    assert not list(config.state_root.glob("*.partial-*"))
    assert config.active_link.resolve() == Path(active.active_release_directory)
    values = control.read_env_file(config.active_env)
    assert values["release_sha"] == active.active_sha
    assert values["release_dir"] == active.active_release_directory
    assert values["production_override"] == "/etc/pastexam/docker-compose.edge.yml"


def test_corrupt_canonical_ledger_fails_closed_and_temp_file_is_ignored(
    control, config
) -> None:
    store = control.DeploymentStore(config)
    store.initialize()
    config.active_ledger.write_text("{not-json", encoding="utf-8")
    config.active_ledger.with_name("active.json.partial-crash").write_text(
        json.dumps({"active_sha": "a" * 40}), encoding="utf-8"
    )

    with pytest.raises(control.DeploymentError, match="active ledger"):
        store.load_active()


def _runtime_inspect(active, images: dict[str, str]) -> list[dict]:
    return [
        {
            "Name": f"/{name}",
            "Id": name,
            "Config": {
                "Image": image,
                "Labels": {
                    "com.docker.compose.project.working_dir": active.active_release_directory
                },
            },
            "State": {"Status": "running", "Health": {"Status": "healthy"}},
            "RestartCount": 0,
        }
        for name, image in images.items()
    ]


def _runtime_manifest(active, images: dict[str, str]) -> None:
    manifest = Path(active.active_release_directory) / "release-manifest.env"
    manifest.write_text(
        f"release_sha={active.active_sha}\n"
        f"backend_image={images['pastexam-backend']}\n"
        f"frontend_image={images['pastexam-frontend']}\n"
        f"nginx_image={images['pastexam-nginx']}\n",
        encoding="utf-8",
    )


def test_runtime_verification_binds_images_working_directory_and_health(
    control, config, monkeypatch
) -> None:
    active = _active(control, config)
    images = {
        "pastexam-backend": "ghcr.io/example/backend:release@sha256:" + "1" * 64,
        "pastexam-frontend": "ghcr.io/example/frontend:release@sha256:" + "2" * 64,
        "pastexam-nginx": "nginx:1.29.2@sha256:" + "3" * 64,
    }
    _runtime_manifest(active, images)
    inspected = _runtime_inspect(active, images)
    monkeypatch.setattr(
        control.subprocess,
        "run",
        lambda *args, **kwargs: control.subprocess.CompletedProcess(
            args[0], 0, stdout=json.dumps(inspected), stderr=""
        ),
    )

    evidence = control.verify_runtime(active)

    assert set(evidence) == set(images)
    assert all(item["health"] == "healthy" for item in evidence.values())


def test_runtime_verification_rejects_image_drift(control, config, monkeypatch) -> None:
    active = _active(control, config)
    images = {
        "pastexam-backend": "ghcr.io/example/backend:release@sha256:" + "1" * 64,
        "pastexam-frontend": "ghcr.io/example/frontend:release@sha256:" + "2" * 64,
        "pastexam-nginx": "nginx:1.29.2@sha256:" + "3" * 64,
    }
    _runtime_manifest(active, images)
    inspected = _runtime_inspect(active, images)
    inspected[0]["Config"]["Image"] = (
        "ghcr.io/example/backend:release@sha256:" + "f" * 64
    )
    monkeypatch.setattr(
        control.subprocess,
        "run",
        lambda *args, **kwargs: control.subprocess.CompletedProcess(
            args[0], 0, stdout=json.dumps(inspected), stderr=""
        ),
    )

    with pytest.raises(control.DeploymentError, match="canonical ledger"):
        control.verify_runtime(active)


def test_duplicate_identical_request_is_idempotent(control, config) -> None:
    store = control.DeploymentStore(config)
    request = _request(control)

    first, created = store.prepare_request(request, previous_active_sha="a" * 40)
    second, duplicate_created = store.prepare_request(
        request, previous_active_sha="a" * 40
    )

    assert created is True
    assert duplicate_created is False
    assert first == second
    assert second["state"] == "PREPARED"


def test_conflicting_duplicate_request_is_rejected(control, config) -> None:
    store = control.DeploymentStore(config)
    request = _request(control)
    store.prepare_request(request, previous_active_sha="a" * 40)

    with pytest.raises(control.DeploymentError, match="immutable input"):
        store.prepare_request(
            replace(request, target_sha="c" * 40), previous_active_sha="a" * 40
        )


def test_illegal_state_transition_is_rejected(control, config) -> None:
    store = control.DeploymentStore(config)
    request = _request(control)
    store.prepare_request(request, previous_active_sha="a" * 40)

    with pytest.raises(control.DeploymentError, match="transition"):
        store.transition(request.request_id, "ACTIVE", phase="finalized")

    activating = store.transition(request.request_id, "ACTIVATING", phase="preflight")
    failed = store.transition(
        request.request_id,
        "FAILED",
        phase="preflight",
        failure={"code": "candidate-invalid", "message": "candidate rejected"},
    )
    assert activating["state"] == "ACTIVATING"
    assert failed["state"] == "FAILED"


def test_only_one_mutation_lock_holder_is_allowed(control, config) -> None:
    first = control.MutationLock(config.mutation_lock)
    second = control.MutationLock(config.mutation_lock)

    with first, pytest.raises(control.DeploymentError, match="mutation is active"):
        second.acquire()


def test_finalization_updates_compatibility_views_and_ledger(control, config) -> None:
    store = control.DeploymentStore(config)
    old = _active(control, config)
    store.seed_active(old)
    request = _request(control)
    store.prepare_request(request, previous_active_sha=old.active_sha)
    store.transition(request.request_id, "ACTIVATING", phase="activation")
    receipt = config.receipts_dir / f"{request.request_id}.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text('{"schema_version":1}\n', encoding="utf-8")
    new = _active(control, config, request.target_sha)
    new = replace(
        new,
        activation_request_id=request.request_id,
        activation_workflow={"run_id": 100, "run_attempt": 1},
        previous_active_sha=old.active_sha,
        receipt_reference=str(receipt),
        receipt_sha256=control.sha256_file(receipt),
    )

    store.finalize_active(request.request_id, new)

    assert store.load_active() == new
    assert config.active_link.resolve() == Path(new.active_release_directory)
    assert control.read_env_file(config.active_env)["release_sha"] == new.active_sha
    assert store.load_request(request.request_id)["state"] == "ACTIVE"


def test_already_active_request_finishes_without_worker_dispatch(
    control, config
) -> None:
    store = control.DeploymentStore(config)
    active = _active(control, config)
    store.seed_active(active)
    controller = control.DeploymentController(config, dispatch_worker=lambda _: None)
    request = _request(control, target=active.active_sha)

    result = controller.start(request, candidate_verifier=lambda *_: {})

    assert result["state"] == "ACTIVE"
    assert result["phase"] == "ALREADY_ACTIVE"
    assert result["worker_dispatched"] is False


def test_runner_disconnect_leaves_durable_dispatched_request(control, config) -> None:
    store = control.DeploymentStore(config)
    active = _active(control, config)
    store.seed_active(active)
    calls: list[str] = []
    controller = control.DeploymentController(
        config, dispatch_worker=lambda request_id: calls.append(request_id)
    )
    request = _request(control)

    result = controller.start(request, candidate_verifier=lambda *_: {})
    recovered = control.DeploymentStore(config).load_request(request.request_id)

    assert calls == [request.request_id]
    assert result["worker_dispatched"] is True
    assert recovered["request_id"] == request.request_id
    assert recovered["state"] in {"PREPARED", "ACTIVATING"}


def test_resume_dispatches_only_safe_inactive_finalization_recovery(
    control, config
) -> None:
    store = control.DeploymentStore(config)
    old = _active(control, config)
    store.seed_active(old)
    request = _request(control)
    store.prepare_request(request, previous_active_sha=old.active_sha)
    store.transition(request.request_id, "ACTIVATING", phase="engine")
    calls: list[tuple[str, bool]] = []
    controller = control.DeploymentController(
        config,
        dispatch_worker=lambda request_id, *, rollback=False: calls.append(
            (request_id, rollback)
        ),
    )
    controller._worker_is_active = lambda _: False

    unchanged = controller.resume(request.request_id)
    assert unchanged["phase"] == "engine"
    assert calls == []

    committed = _active(control, config, request.target_sha)
    control.atomic_write_json(config.active_ledger, control.asdict(committed))
    recovered = controller.resume(request.request_id)

    assert recovered["worker_dispatched"] is True
    assert calls == [(request.request_id, False)]


def test_candidate_verifier_binds_receipt_source_ci_and_all_image_digests(
    control, config
) -> None:
    request = _request(control)
    _candidate(control, config, request)

    verified = control.verify_candidate(config, request.target_sha, request)

    assert verified["image_digests"]["nginx"] == control.NGINX_DIGEST
    assert verified["manifest_sha256"]


def test_candidate_verifier_rejects_tampered_release_file(control, config) -> None:
    request = _request(control)
    release = _candidate(control, config, request)
    (release / "docker/docker-compose.prod.yml").write_text(
        "services: {evil: {privileged: true}}\n", encoding="utf-8"
    )

    with pytest.raises(control.DeploymentError, match="checksum"):
        control.verify_candidate(config, request.target_sha, request)


def test_candidate_verifier_rejects_wrong_source_ci_authority(control, config) -> None:
    request = _request(control)
    _candidate(control, config, request)

    with pytest.raises(control.DeploymentError, match="source_ci_run_id"):
        control.verify_candidate(
            config,
            request.target_sha,
            replace(request, source_ci_run_id=request.source_ci_run_id + 1),
        )


def test_worker_finalizes_receipt_ledger_and_views_once(control, config) -> None:
    config = replace(config, backup_root=config.state_root.parent / "backups")
    store = control.DeploymentStore(config)
    active = _active(control, config)
    store.seed_active(active)
    request = _request(control)
    _candidate(control, config, request)
    store.prepare_request(request, previous_active_sha=active.active_sha)
    calls: list[str] = []
    controller = control.DeploymentController(config)

    def invoke(payload, candidate):
        calls.append(payload["request_id"])
        _fake_engine_success(control, controller, payload, candidate)

    controller._invoke_engine = invoke

    result = controller.worker(request.request_id)
    duplicate = controller.worker(request.request_id)

    assert result["state"] == "ACTIVE"
    assert duplicate == result
    assert calls == [request.request_id]
    new_active = store.load_active()
    assert new_active.active_sha == request.target_sha
    assert new_active.previous_active_sha == active.active_sha
    assert new_active.receipt_reference is not None
    assert (
        control.sha256_file(Path(new_active.receipt_reference))
        == new_active.receipt_sha256
    )
    assert config.active_link.resolve() == config.releases_root / request.target_sha
    assert control.read_env_file(config.active_env)["release_sha"] == request.target_sha


def test_worker_failure_is_durable_and_does_not_update_active(control, config) -> None:
    config = replace(config, backup_root=config.state_root.parent / "backups")
    store = control.DeploymentStore(config)
    active = _active(control, config)
    store.seed_active(active)
    request = _request(control)
    _candidate(control, config, request)
    store.prepare_request(request, previous_active_sha=active.active_sha)
    controller = control.DeploymentController(config)

    def fail_engine(*_):
        raise control.DeploymentError("simulated health failure")

    controller._invoke_engine = fail_engine

    with pytest.raises(control.DeploymentError, match="health failure"):
        controller.worker(request.request_id)

    failed = store.load_request(request.request_id)
    assert failed["state"] == "FAILED"
    assert failed["failure"]["code"] == "activation-failed"
    assert store.load_active() == active


def _rollback_setup(control, config):
    target_sha = "c" * 40
    current_sha = "d" * 40
    request = replace(
        _request(control, target=target_sha, request_id="rollback-100-1"),
        operation="rollback",
    )
    target = _candidate(control, config, request, legacy_nginx=True)
    target_manifest = control.sha256_file(target / "release-manifest.env")
    (target / ".activated").write_text(f"{target_manifest}\n", encoding="utf-8")
    active = replace(
        _active(control, config, current_sha),
        previous_active_sha=target_sha,
    )
    store = control.DeploymentStore(config)
    store.seed_active(active)
    return store, active, request


def test_separate_rollback_worker_is_exact_previous_sha_and_revision_safe(
    control, config
) -> None:
    config = replace(config, backup_root=config.state_root.parent / "backups")
    store, active, request = _rollback_setup(control, config)
    dispatched: list[str] = []
    controller = control.DeploymentController(
        config, dispatch_worker=lambda request_id, **_: dispatched.append(request_id)
    )
    controller.preflight = lambda target, contract: control.verify_candidate(
        config, target, contract, allow_activated=True
    )
    prepared = controller.rollback_start(request)

    def invoke(payload, candidate):
        _fake_engine_success(control, controller, payload, candidate)

    controller._invoke_engine = invoke
    result = controller.rollback_worker(request.request_id)

    assert prepared["worker_dispatched"] is True
    assert dispatched == [request.request_id]
    assert result["state"] == "ROLLED_BACK"
    rolled_back = store.load_active()
    assert rolled_back.active_sha == request.target_sha
    assert rolled_back.previous_active_sha == active.active_sha
    receipt = json.loads(
        Path(rolled_back.receipt_reference).read_text(encoding="utf-8")
    )
    assert receipt["kind"] == "production-rollback"
    assert receipt["rollback_from_sha"] == active.active_sha
    assert receipt["rollback_to_sha"] == request.target_sha


def test_rollback_revision_mismatch_fails_without_ledger_change(
    control, config
) -> None:
    config = replace(config, backup_root=config.state_root.parent / "backups")
    store, active, request = _rollback_setup(control, config)
    store.prepare_request(request, previous_active_sha=active.active_sha)
    controller = control.DeploymentController(config)

    def invoke(payload, candidate):
        _fake_engine_success(
            control,
            controller,
            payload,
            candidate,
            database_revision="different-revision",
        )

    controller._invoke_engine = invoke

    with pytest.raises(control.DeploymentError, match="ledger database revision"):
        controller.rollback_worker(request.request_id)

    assert store.load_active() == active
    assert store.load_request(request.request_id)["state"] == "FAILED"


def test_receipt_failure_preserves_recoverable_state_and_does_not_rerun_engine(
    control, config
) -> None:
    config = replace(config, backup_root=config.state_root.parent / "backups")
    store = control.DeploymentStore(config)
    active = _active(control, config)
    store.seed_active(active)
    request = _request(control)
    _candidate(control, config, request)
    store.prepare_request(request, previous_active_sha=active.active_sha)
    controller = control.DeploymentController(config)
    engine_calls: list[str] = []

    def invoke(payload, candidate):
        engine_calls.append(payload["request_id"])
        _fake_engine_success(control, controller, payload, candidate)

    controller._invoke_engine = invoke
    original_write_receipt = controller._write_receipt
    controller._write_receipt = lambda *_: (_ for _ in ()).throw(
        control.DeploymentError("simulated receipt storage failure")
    )

    with pytest.raises(control.DeploymentError, match="receipt storage"):
        controller.worker(request.request_id)

    recoverable = store.load_request(request.request_id)
    assert recoverable["state"] == "ACTIVATING"
    assert recoverable["phase"] == "finalization-retry-required"
    assert store.load_active() == active

    controller._write_receipt = original_write_receipt
    result = controller.worker(request.request_id)

    assert result["state"] == "ACTIVE"
    assert engine_calls == [request.request_id]


def test_crash_after_ledger_commit_reconciles_views_without_rerunning_engine(
    control, config
) -> None:
    config = replace(config, backup_root=config.state_root.parent / "backups")
    store = control.DeploymentStore(config)
    active = _active(control, config)
    store.seed_active(active)
    request = _request(control)
    _candidate(control, config, request)
    store.prepare_request(request, previous_active_sha=active.active_sha)
    controller = control.DeploymentController(config)
    engine_calls: list[str] = []

    def invoke(payload, candidate):
        engine_calls.append(payload["request_id"])
        _fake_engine_success(control, controller, payload, candidate)

    controller._invoke_engine = invoke
    original_views = controller.store._write_compatibility_views
    controller.store._write_compatibility_views = lambda *_: (_ for _ in ()).throw(
        control.DeploymentError("simulated compatibility-view crash")
    )

    with pytest.raises(control.DeploymentError, match="compatibility-view crash"):
        controller.worker(request.request_id)

    committed = store.load_active()
    assert committed.active_sha == request.target_sha
    assert (
        store.load_request(request.request_id)["phase"] == "finalization-retry-required"
    )
    assert config.active_link.resolve() == Path(active.active_release_directory)

    controller.store._write_compatibility_views = original_views
    result = controller.worker(request.request_id)

    assert result["state"] == "ACTIVE"
    assert result["phase"] == "finalized-recovery"
    assert config.active_link.resolve() == Path(committed.active_release_directory)
    assert engine_calls == [request.request_id]
