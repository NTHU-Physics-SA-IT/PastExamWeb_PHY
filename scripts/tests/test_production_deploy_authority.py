from __future__ import annotations

import copy
import importlib.util
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError

import pytest

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "scripts" / "ci" / "validate_production_deploy_authority.py"
REPOSITORY = "NTHU-Physics-SA-IT/PastExamWeb_PHY"
TARGET_SHA = "a" * 40
PARENT_ONE = "b" * 40
PARENT_TWO = "c" * 40
AUTHORIZED = ["chou-chuan-chuan", "PingScientist", "Jasper-hsury"]


def _load_validator():
    spec = importlib.util.spec_from_file_location("production_deploy_authority", VALIDATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def validator():
    return _load_validator()


class FakeGitHubAPI:
    def __init__(self, objects: dict[str, dict], lists: dict[str, list]):
        self.objects = objects
        self.lists = lists

    def get_object(self, path: str) -> dict:
        return copy.deepcopy(self.objects[path])

    def get_paginated(self, path: str) -> list:
        return copy.deepcopy(self.lists[path])


def _evidence(*, merged_by: str = "HumanMerger", merger_type: str = "User"):
    prefix = f"repos/{REPOSITORY}"
    objects = {
        f"{prefix}/branches/main": {
            "name": "main",
            "commit": {"sha": TARGET_SHA},
        },
        f"{prefix}/commits/{TARGET_SHA}": {
            "sha": TARGET_SHA,
            "parents": [{"sha": PARENT_ONE}, {"sha": PARENT_TWO}],
        },
        f"{prefix}/pulls/249": {
            "number": 249,
            "merge_commit_sha": TARGET_SHA,
            "merged_at": "2026-09-03T00:00:00Z",
            "merged_by": {"login": merged_by, "type": merger_type},
            "base": {"ref": "main", "repo": {"full_name": REPOSITORY}},
            "user": {"login": "dependabot[bot]", "type": "Bot"},
        },
    }
    lists = {f"{prefix}/commits/{TARGET_SHA}/pulls": [{"number": 249}]}
    return FakeGitHubAPI(objects, lists)


def _authority_file(tmp_path: Path, members=AUTHORIZED) -> Path:
    path = tmp_path / "production-deploy-authority.json"
    path.write_text(
        json.dumps({"schema_version": 1, "authorized_deployers": members}),
        encoding="utf-8",
    )
    return path


def _authorize(validator, api: FakeGitHubAPI, authority_file: Path, **overrides):
    inputs = {
        "repository": REPOSITORY,
        "authority_sha": TARGET_SHA,
        "base_branch": "main",
        "actor": "PingScientist",
        "triggering_actor": "PingScientist",
        "authority_file": authority_file,
        "api": api,
    }
    inputs.update(overrides)
    return validator.authorize_production_deploy(**inputs)


def test_repository_authority_file_has_exact_initial_members(validator) -> None:
    authority_file = ROOT / ".github" / "production-deploy-authority.json"
    document = json.loads(authority_file.read_text(encoding="utf-8"))
    assert document == {
        "schema_version": 1,
        "authorized_deployers": AUTHORIZED,
    }
    assert list(validator.load_authorized_deployers(authority_file).values()) == (
        AUTHORIZED
    )


def test_allowlisted_merger_is_authorized(validator, tmp_path: Path) -> None:
    result = _authorize(
        validator,
        _evidence(merged_by="PingScientist"),
        _authority_file(tmp_path),
    )

    assert result["outcome"] == "authorized"
    assert result["merged_by"] == "PingScientist"
    assert result["authorized_actor"] == "PingScientist"


def test_different_allowlisted_human_can_deploy_bot_authored_merge(
    validator, tmp_path: Path
) -> None:
    authority_file = _authority_file(tmp_path)
    result = _authorize(validator, _evidence(), authority_file)

    assert result == {
        "authority_sha": TARGET_SHA,
        "pr_number": "249",
        "merged_by": "HumanMerger",
        "authorized_actor": "PingScientist",
        "authority_source": authority_file.as_posix(),
        "outcome": "authorized",
    }


@pytest.mark.parametrize("actor", AUTHORIZED)
def test_each_initial_authorized_deployer_is_accepted(
    validator, tmp_path: Path, actor: str
) -> None:
    result = _authorize(
        validator,
        _evidence(),
        _authority_file(tmp_path),
        actor=actor,
        triggering_actor=actor,
    )
    assert result["authorized_actor"] == actor


def test_login_comparison_and_membership_are_case_insensitive(
    validator, tmp_path: Path
) -> None:
    result = _authorize(
        validator,
        _evidence(),
        _authority_file(tmp_path),
        actor="pingscientist",
        triggering_actor="PINGSCIENTIST",
    )
    assert result["authorized_actor"] == "PingScientist"


def test_rejects_unauthorized_human(validator, tmp_path: Path) -> None:
    with pytest.raises(validator.ProductionDeployAuthorityError, match="not listed"):
        _authorize(
            validator,
            _evidence(),
            _authority_file(tmp_path),
            actor="OtherHuman",
            triggering_actor="OtherHuman",
        )


def test_rejects_actor_and_triggering_actor_mismatch(validator, tmp_path: Path) -> None:
    with pytest.raises(validator.ProductionDeployAuthorityError, match="same account"):
        _authorize(
            validator,
            _evidence(),
            _authority_file(tmp_path),
            triggering_actor="Jasper-hsury",
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("actor", "release[bot]", "Original actor"),
        ("triggering_actor", "release[bot]", "triggering actor"),
        ("actor", "", "Original actor"),
        ("triggering_actor", "bad--login", "triggering actor"),
    ],
)
def test_rejects_bot_missing_or_malformed_actor(
    validator, tmp_path: Path, field: str, value: str, message: str
) -> None:
    with pytest.raises(validator.ProductionDeployAuthorityError, match=message):
        _authorize(
            validator,
            _evidence(),
            _authority_file(tmp_path),
            **{field: value},
        )


def test_rejects_stale_authority_sha(validator, tmp_path: Path) -> None:
    api = _evidence()
    api.objects[f"repos/{REPOSITORY}/branches/main"]["commit"]["sha"] = "d" * 40
    with pytest.raises(validator.ProductionDeployAuthorityError, match="current main"):
        _authorize(validator, api, _authority_file(tmp_path))


@pytest.mark.parametrize(
    "parents",
    [
        [{"sha": PARENT_ONE}],
        None,
        {},
        [{"sha": PARENT_ONE}, {}],
        [{"sha": PARENT_ONE}, {"sha": PARENT_ONE}],
    ],
)
def test_rejects_non_two_distinct_or_malformed_parents(
    validator, tmp_path: Path, parents
) -> None:
    api = _evidence()
    api.objects[f"repos/{REPOSITORY}/commits/{TARGET_SHA}"]["parents"] = parents
    with pytest.raises(validator.ProductionDeployAuthorityError, match="parent"):
        _authorize(validator, api, _authority_file(tmp_path))


def test_rejects_zero_qualifying_prs(validator, tmp_path: Path) -> None:
    api = _evidence()
    api.lists[f"repos/{REPOSITORY}/commits/{TARGET_SHA}/pulls"] = []
    with pytest.raises(validator.ProductionDeployAuthorityError, match="found 0"):
        _authorize(validator, api, _authority_file(tmp_path))


@pytest.mark.parametrize(
    ("field_path", "value"),
    [
        (("merge_commit_sha",), "d" * 40),
        (("base", "ref"), "release"),
        (("merged_at",), None),
        (("base", "repo", "full_name"), "another/repository"),
    ],
)
def test_rejects_associated_pr_that_does_not_qualify(
    validator, tmp_path: Path, field_path, value
) -> None:
    api = _evidence()
    target = api.objects[f"repos/{REPOSITORY}/pulls/249"]
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = value
    with pytest.raises(validator.ProductionDeployAuthorityError, match="found 0"):
        _authorize(validator, api, _authority_file(tmp_path))


def test_rejects_multiple_qualifying_prs(validator, tmp_path: Path) -> None:
    api = _evidence()
    prefix = f"repos/{REPOSITORY}"
    second = copy.deepcopy(api.objects[f"{prefix}/pulls/249"])
    second["number"] = 250
    api.objects[f"{prefix}/pulls/250"] = second
    api.lists[f"{prefix}/commits/{TARGET_SHA}/pulls"].append({"number": 250})
    with pytest.raises(validator.ProductionDeployAuthorityError, match="found 2"):
        _authorize(validator, api, _authority_file(tmp_path))


@pytest.mark.parametrize(
    ("merged_by", "merger_type", "message"),
    [
        (None, "User", "merged_by"),
        ("release-bot", "Bot", "human"),
        ("release[bot]", "User", "human"),
        ("HumanMerger", "Organization", "human"),
    ],
)
def test_rejects_malformed_or_non_human_merger(
    validator, tmp_path: Path, merged_by, merger_type: str, message: str
) -> None:
    api = _evidence()
    if merged_by is None:
        api.objects[f"repos/{REPOSITORY}/pulls/249"]["merged_by"] = None
    else:
        api.objects[f"repos/{REPOSITORY}/pulls/249"]["merged_by"] = {
            "login": merged_by,
            "type": merger_type,
        }
    with pytest.raises(validator.ProductionDeployAuthorityError, match=message):
        _authorize(validator, api, _authority_file(tmp_path))


def test_rejects_missing_authority_file(validator, tmp_path: Path) -> None:
    with pytest.raises(validator.ProductionDeployAuthorityError, match="could not be read"):
        _authorize(validator, _evidence(), tmp_path / "missing.json")


def test_rejects_malformed_json(validator, tmp_path: Path) -> None:
    path = tmp_path / "authority.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(validator.ProductionDeployAuthorityError, match="malformed JSON"):
        _authorize(validator, _evidence(), path)


def test_rejects_duplicate_json_key(validator, tmp_path: Path) -> None:
    path = tmp_path / "authority.json"
    path.write_text(
        '{"schema_version":1,"schema_version":1,"authorized_deployers":["PingScientist"]}',
        encoding="utf-8",
    )
    with pytest.raises(validator.ProductionDeployAuthorityError, match="duplicate JSON"):
        _authorize(validator, _evidence(), path)


@pytest.mark.parametrize(
    "document",
    [
        {"schema_version": 1, "authorized_deployers": AUTHORIZED, "extra": True},
        {"schema_version": 2, "authorized_deployers": AUTHORIZED},
        {"schema_version": True, "authorized_deployers": AUTHORIZED},
        {"schema_version": 1, "authorized_deployers": []},
        {"schema_version": 1, "authorized_deployers": "PingScientist"},
        {"schema_version": 1, "authorized_deployers": ["release[bot]"]},
        {"schema_version": 1, "authorized_deployers": ["*"]},
        {
            "schema_version": 1,
            "authorized_deployers": ["PingScientist", "pingscientist"],
        },
    ],
)
def test_rejects_invalid_authority_schema_or_members(
    validator, tmp_path: Path, document
) -> None:
    path = tmp_path / "authority.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(validator.ProductionDeployAuthorityError):
        _authorize(validator, _evidence(), path)


@pytest.mark.skipif(os.name == "nt", reason="Windows symlink creation needs privilege")
def test_rejects_symlink_authority_file(validator, tmp_path: Path) -> None:
    target = _authority_file(tmp_path)
    link = tmp_path / "authority-link.json"
    link.symlink_to(target)
    with pytest.raises(validator.ProductionDeployAuthorityError, match="non-symlink"):
        _authorize(validator, _evidence(), link)


def test_rejects_api_failure(validator, tmp_path: Path) -> None:
    api = _evidence()

    def fail(_path: str):
        raise validator.ProductionDeployAuthorityError(
            "GitHub API request failed with status 403."
        )

    api.get_object = fail
    with pytest.raises(validator.ProductionDeployAuthorityError, match="403"):
        _authorize(validator, api, _authority_file(tmp_path))


@pytest.mark.parametrize(
    ("location", "mutation"),
    [
        ("branch", lambda value: value.pop("commit")),
        ("commit", lambda value: value.pop("sha")),
        ("associated", lambda value: value[0].pop("number")),
        ("pull", lambda value: value.pop("base")),
        ("pull", lambda value: value["merged_by"].pop("type")),
    ],
)
def test_rejects_missing_required_api_fields(
    validator, tmp_path: Path, location: str, mutation
) -> None:
    api = _evidence()
    prefix = f"repos/{REPOSITORY}"
    targets = {
        "branch": api.objects[f"{prefix}/branches/main"],
        "commit": api.objects[f"{prefix}/commits/{TARGET_SHA}"],
        "associated": api.lists[f"{prefix}/commits/{TARGET_SHA}/pulls"],
        "pull": api.objects[f"{prefix}/pulls/249"],
    }
    mutation(targets[location])
    with pytest.raises(validator.ProductionDeployAuthorityError, match="malformed"):
        _authorize(validator, api, _authority_file(tmp_path))


def test_http_error_is_sanitized_and_never_exposes_token(validator, monkeypatch) -> None:
    token = "super-secret-fixture-token"

    def fail(*_args, **_kwargs):
        raise HTTPError("https://api.example.invalid", 403, "forbidden", {}, None)

    monkeypatch.setattr(validator.urllib.request, "urlopen", fail)
    api = validator.GitHubAPI("https://api.github.com", token)
    with pytest.raises(validator.ProductionDeployAuthorityError) as error:
        api.get_object(f"repos/{REPOSITORY}/branches/main")
    assert "403" in str(error.value)
    assert token not in str(error.value)


def test_cli_accepts_token_only_from_environment(validator) -> None:
    parser = validator.build_parser()
    option_strings = {
        option for action in parser._actions for option in action.option_strings
    }
    assert "--token" not in option_strings
    assert "--github-token" not in option_strings
