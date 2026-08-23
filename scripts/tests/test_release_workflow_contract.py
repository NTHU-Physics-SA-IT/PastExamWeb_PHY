import json
from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MAIN_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "main.yml"
RELEASE_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"
CONTRIBUTING = REPOSITORY_ROOT / "CONTRIBUTING.md"
VALIDATION = REPOSITORY_ROOT / "docs" / "development" / "validation.md"
AGENTS = REPOSITORY_ROOT / "AGENTS.md"
PROJECT_GOVERNANCE = REPOSITORY_ROOT / ".github" / "project-governance.json"
PR_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "pr.yml"
CLASSIFIER = REPOSITORY_ROOT / "scripts" / "ci" / "classify_ci_mode.py"
GOVERNANCE_RESOLVER = REPOSITORY_ROOT / "scripts" / "ci" / "project_governance.py"
FEATURE_WORKFLOW = (
    REPOSITORY_ROOT / "docs" / "development" / "feature-development-workflow.md"
)


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


def test_governance_documentation_is_main_first_and_branch_decoupled() -> None:
    contributing = CONTRIBUTING.read_text(encoding="utf-8")
    validation = VALIDATION.read_text(encoding="utf-8")
    feature_workflow = FEATURE_WORKFLOW.read_text(encoding="utf-8")
    agents = AGENTS.read_text(encoding="utf-8")
    combined = "\n".join((contributing, validation, feature_workflow, agents))
    config_source = PROJECT_GOVERNANCE.read_text(encoding="utf-8")
    config = json.loads(config_source)
    coordination_branch = config["coordination_branch"]

    assert config["default_development_base"] == "main"
    if coordination_branch is None:
        assert config_source.count('"coordination_branch": null') == 1
    else:
        assert coordination_branch.startswith("integration/")
        assert config_source.count(
            f'"coordination_branch": "{coordination_branch}"'
        ) == 1
    for authority_path in (
        CONTRIBUTING,
        VALIDATION,
        FEATURE_WORKFLOW,
        AGENTS,
        MAIN_WORKFLOW,
        PR_WORKFLOW,
        CLASSIFIER,
        GOVERNANCE_RESOLVER,
    ):
        assert "integration/stage-5bd" not in authority_path.read_text(
            encoding="utf-8"
        )

    assert "Normal independent work starts from fresh `main`" in contributing
    assert "coordination branch" in combined
    assert "governance-path" in validation.lower()
    assert "integration/**" in MAIN_WORKFLOW.read_text(encoding="utf-8")
    assert "Main never uses Equivalent" in feature_workflow
    assert "exact-main-SHA CI run after `CI Gate`" in validation
    assert "Semantic-release is not deployment authority" in contributing
    assert "hard-code `v1.8.0`" not in combined
