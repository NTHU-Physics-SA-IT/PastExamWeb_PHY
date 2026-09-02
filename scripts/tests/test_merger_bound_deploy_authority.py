from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path
from urllib.error import HTTPError

import pytest

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "scripts" / "ci" / "validate_merger_bound_deploy.py"
REPOSITORY = "NTHU-Physics-SA-IT/PastExamWeb_PHY"
TARGET_SHA = "a" * 40
PARENT_ONE = "b" * 40
PARENT_TWO = "c" * 40


def _load_validator():
    spec = importlib.util.spec_from_file_location("merger_bound_deploy", VALIDATOR)
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


def _evidence(*, pr_author_login: str = "human-author", pr_author_type: str = "User"):
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
        f"{prefix}/pulls/227": {
            "number": 227,
            "merge_commit_sha": TARGET_SHA,
            "merged_at": "2026-09-02T08:31:05Z",
            "merged_by": {"login": "HumanMerger", "type": "User"},
            "base": {"ref": "main", "repo": {"full_name": REPOSITORY}},
            "user": {"login": pr_author_login, "type": pr_author_type},
        },
    }
    lists = {f"{prefix}/commits/{TARGET_SHA}/pulls": [{"number": 227}]}
    return FakeGitHubAPI(objects, lists)


def _authorize(validator, api: FakeGitHubAPI, **overrides):
    inputs = {
        "repository": REPOSITORY,
        "target_sha": TARGET_SHA,
        "base_branch": "main",
        "actor": "HumanMerger",
        "triggering_actor": "HumanMerger",
        "api": api,
    }
    inputs.update(overrides)
    return validator.authorize_merger_bound_deploy(**inputs)


def test_authorizes_exact_current_normal_merge_by_same_human(validator) -> None:
    result = _authorize(validator, _evidence())

    assert result == {
        "target_sha": TARGET_SHA,
        "pr_number": "227",
        "merged_by": "HumanMerger",
        "authorized_actor": "HumanMerger",
        "base_branch": "main",
        "outcome": "authorized",
    }


def test_bot_authored_pr_is_allowed_when_human_merger_dispatches(validator) -> None:
    api = _evidence(pr_author_login="dependabot[bot]", pr_author_type="Bot")

    assert _authorize(validator, api)["outcome"] == "authorized"


def test_login_comparison_is_case_insensitive(validator) -> None:
    result = _authorize(
        validator,
        _evidence(),
        actor="humanmerger",
        triggering_actor="HUMANMERGER",
    )

    assert result["merged_by"] == "HumanMerger"
    assert result["authorized_actor"] == "HumanMerger"


def test_rejects_stale_target(validator) -> None:
    api = _evidence()
    api.objects[f"repos/{REPOSITORY}/branches/main"]["commit"]["sha"] = "d" * 40

    with pytest.raises(validator.MergerBoundAuthorityError, match="current main"):
        _authorize(validator, api)


def test_rejects_direct_push_with_no_associated_pr(validator) -> None:
    api = _evidence()
    api.lists[f"repos/{REPOSITORY}/commits/{TARGET_SHA}/pulls"] = []

    with pytest.raises(validator.MergerBoundAuthorityError, match="exactly one"):
        _authorize(validator, api)


def test_rejects_one_parent_target(validator) -> None:
    api = _evidence()
    api.objects[f"repos/{REPOSITORY}/commits/{TARGET_SHA}"]["parents"] = [
        {"sha": PARENT_ONE}
    ]

    with pytest.raises(validator.MergerBoundAuthorityError, match="two parents"):
        _authorize(validator, api)


@pytest.mark.parametrize(
    "parents",
    [None, {}, [{"sha": PARENT_ONE}, {}], [{"sha": "not-a-sha"}, {"sha": PARENT_TWO}]],
)
def test_rejects_malformed_commit_parent_data(validator, parents) -> None:
    api = _evidence()
    api.objects[f"repos/{REPOSITORY}/commits/{TARGET_SHA}"]["parents"] = parents

    with pytest.raises(validator.MergerBoundAuthorityError, match="parent"):
        _authorize(validator, api)


@pytest.mark.parametrize(
    ("field_path", "value"),
    [
        (("merge_commit_sha",), "d" * 40),
        (("base", "ref"), "release"),
        (("merged_at",), None),
        (("base", "repo", "full_name"), "another/repository"),
    ],
)
def test_rejects_pr_that_does_not_qualify(validator, field_path, value) -> None:
    api = _evidence()
    pr = api.objects[f"repos/{REPOSITORY}/pulls/227"]
    target = pr
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = value

    with pytest.raises(validator.MergerBoundAuthorityError, match="exactly one"):
        _authorize(validator, api)


def test_rejects_zero_qualifying_prs_even_when_associated_pr_exists(validator) -> None:
    api = _evidence()
    api.objects[f"repos/{REPOSITORY}/pulls/227"]["merge_commit_sha"] = "d" * 40

    with pytest.raises(validator.MergerBoundAuthorityError, match="found 0"):
        _authorize(validator, api)


def test_rejects_multiple_qualifying_prs(validator) -> None:
    api = _evidence()
    prefix = f"repos/{REPOSITORY}"
    second = copy.deepcopy(api.objects[f"{prefix}/pulls/227"])
    second["number"] = 228
    api.objects[f"{prefix}/pulls/228"] = second
    api.lists[f"{prefix}/commits/{TARGET_SHA}/pulls"].append({"number": 228})

    with pytest.raises(validator.MergerBoundAuthorityError, match="found 2"):
        _authorize(validator, api)


def test_rejects_missing_merger(validator) -> None:
    api = _evidence()
    api.objects[f"repos/{REPOSITORY}/pulls/227"]["merged_by"] = None

    with pytest.raises(validator.MergerBoundAuthorityError, match="merged_by"):
        _authorize(validator, api)


@pytest.mark.parametrize(
    ("merged_by", "message"),
    [
        ({"login": "release-bot", "type": "Bot"}, "human"),
        ({"login": "release[bot]", "type": "User"}, "non-bot"),
        ({"login": "HumanMerger", "type": "Organization"}, "human"),
    ],
)
def test_rejects_non_human_or_bot_merger(validator, merged_by, message) -> None:
    api = _evidence()
    api.objects[f"repos/{REPOSITORY}/pulls/227"]["merged_by"] = merged_by

    with pytest.raises(validator.MergerBoundAuthorityError, match=message):
        _authorize(
            validator,
            api,
            actor=merged_by["login"],
            triggering_actor=merged_by["login"],
        )


def test_rejects_original_actor_mismatch(validator) -> None:
    with pytest.raises(validator.MergerBoundAuthorityError, match="original actor"):
        _authorize(validator, _evidence(), actor="AnotherHuman")


def test_rejects_triggering_actor_mismatch(validator) -> None:
    with pytest.raises(validator.MergerBoundAuthorityError, match="triggering actor"):
        _authorize(validator, _evidence(), triggering_actor="AnotherHuman")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("actor", "release[bot]", "[Oo]riginal actor"),
        ("triggering_actor", "release[bot]", "triggering actor"),
        ("actor", "", "[Oo]riginal actor"),
        ("triggering_actor", "bad--login", "triggering actor"),
    ],
)
def test_rejects_bot_missing_or_malformed_actor(validator, field, value, message) -> None:
    api = _evidence()
    api.objects[f"repos/{REPOSITORY}/pulls/227"]["merged_by"]["login"] = value

    with pytest.raises(validator.MergerBoundAuthorityError, match=message):
        _authorize(validator, api, **{field: value})


def test_rejects_api_failure(validator) -> None:
    api = _evidence()

    def fail(_path: str):
        raise validator.MergerBoundAuthorityError(
            "GitHub API request failed with status 403."
        )

    api.get_object = fail
    with pytest.raises(validator.MergerBoundAuthorityError, match="403"):
        _authorize(validator, api)


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
def test_rejects_missing_required_api_fields(validator, location, mutation) -> None:
    api = _evidence()
    prefix = f"repos/{REPOSITORY}"
    targets = {
        "branch": api.objects[f"{prefix}/branches/main"],
        "commit": api.objects[f"{prefix}/commits/{TARGET_SHA}"],
        "associated": api.lists[f"{prefix}/commits/{TARGET_SHA}/pulls"],
        "pull": api.objects[f"{prefix}/pulls/227"],
    }
    mutation(targets[location])

    with pytest.raises(validator.MergerBoundAuthorityError, match="malformed"):
        _authorize(validator, api)


def test_http_error_is_sanitized_and_never_exposes_token(validator, monkeypatch) -> None:
    token = "super-secret-fixture-token"

    def fail(*_args, **_kwargs):
        raise HTTPError("https://api.example.invalid", 403, "forbidden", {}, None)

    monkeypatch.setattr(validator.urllib.request, "urlopen", fail)
    api = validator.GitHubAPI("https://api.github.com", token)

    with pytest.raises(validator.MergerBoundAuthorityError) as error:
        api.get_object(f"repos/{REPOSITORY}/branches/main")
    assert "403" in str(error.value)
    assert token not in str(error.value)


def test_cli_accepts_token_only_from_environment(validator) -> None:
    parser = validator.build_parser()
    option_strings = {
        option
        for action in parser._actions
        for option in action.option_strings
    }

    assert "--token" not in option_strings
    assert "--github-token" not in option_strings
