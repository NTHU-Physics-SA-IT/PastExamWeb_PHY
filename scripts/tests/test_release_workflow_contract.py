from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MAIN_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "main.yml"
RELEASE_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"


def _workflow(path: Path) -> tuple[str, dict]:
    source = path.read_text(encoding="utf-8")
    parsed = yaml.load(source, Loader=yaml.BaseLoader)
    return source, parsed


def test_release_is_reusable_only_and_requires_exact_sha() -> None:
    source, workflow = _workflow(RELEASE_WORKFLOW)

    assert set(workflow["on"]) == {"workflow_call"}
    release_sha = workflow["on"]["workflow_call"]["inputs"]["release_sha"]
    assert release_sha == {
        "description": "Exact validated main SHA eligible for semantic-release",
        "required": "true",
        "type": "string",
    }
    assert "workflow_dispatch" not in source
    assert "workflow_run" not in source
    assert "push:" not in source

    assert workflow["permissions"] == {
        "contents": "write",
        "issues": "write",
        "pull-requests": "write",
    }
    assert workflow["concurrency"] == {
        "group": "semantic-release-${{ inputs.release_sha }}",
        "cancel-in-progress": "false",
    }


def test_release_validates_caller_event_and_checkout_sha() -> None:
    source, workflow = _workflow(RELEASE_WORKFLOW)
    steps = workflow["jobs"]["release"]["steps"]
    checkout = next(step for step in steps if step["name"] == "Checkout")
    verify = next(
        step for step in steps if step["name"] == "Verify exact validated main SHA"
    )

    assert checkout["with"] == {
        "fetch-depth": "0",
        "ref": "${{ inputs.release_sha }}",
    }
    assert verify["env"] == {
        "RELEASE_SHA": "${{ inputs.release_sha }}",
        "EVENT_SHA": "${{ github.sha }}",
        "EVENT_REF": "${{ github.ref }}",
        "EVENT_NAME": "${{ github.event_name }}",
    }
    assert '"$EVENT_NAME" != "push"' in verify["run"]
    assert '"$EVENT_REF" != "refs/heads/main"' in verify["run"]
    assert '"$RELEASE_SHA" != "$EVENT_SHA"' in verify["run"]
    assert 'checked_out_sha="$(git rev-parse HEAD)"' in verify["run"]
    assert '"$checked_out_sha" != "$RELEASE_SHA"' in verify["run"]
    assert "npx semantic-release" in source
    assert "v1.8.0" not in source
    assert "PRODUCTION_DEPLOY_ENABLED" not in source


def test_main_calls_release_only_after_successful_full_ci_gate() -> None:
    source, workflow = _workflow(MAIN_WORKFLOW)
    release = workflow["jobs"]["release"]
    condition = release["if"]

    assert release["needs"] == ["ci_mode", "lint", "test", "build", "ci_gate"]
    assert "needs.ci_mode.outputs.ci_mode == 'full'" in condition
    for job in ("lint", "test", "build", "ci_gate"):
        assert f"needs.{job}.result == 'success'" in condition
    assert "github.event_name == 'push'" in condition
    assert "github.ref == 'refs/heads/main'" in condition
    assert release["uses"] == "./.github/workflows/release.yml"
    assert release["with"] == {"release_sha": "${{ github.sha }}"}
    assert release["secrets"] == "inherit"
    assert release["permissions"] == {
        "contents": "write",
        "issues": "write",
        "pull-requests": "write",
    }

    assert workflow["jobs"]["ci_gate"]["name"] == "CI Gate"
    assert workflow["jobs"]["deploy"]["needs"] == [
        "ci_mode",
        "lint",
        "test",
        "build",
        "ci_gate",
    ]
    assert "vars.PRODUCTION_DEPLOY_ENABLED == 'true'" in source
