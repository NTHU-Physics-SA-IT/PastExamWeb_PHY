from types import SimpleNamespace

import pytest

from app.api.services.reports import _safe_github_issue_url


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/NTHU-Physics-SA-IT/PastExamWeb_PHY/issues/123",
        "https://github.com/PingScientist/PastExamWeb_PHY/issues/123",
    ],
)
def test_safe_github_issue_url_accepts_current_and_legacy_repositories(url):
    report = SimpleNamespace(github_issue_url=url, github_issue_number=123)

    assert _safe_github_issue_url(report) == url


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/OtherOwner/PastExamWeb_PHY/issues/123",
        "https://github.com/NTHU-Physics-SA-IT/OtherRepository/issues/123",
    ],
)
def test_safe_github_issue_url_rejects_different_repository(url):
    report = SimpleNamespace(github_issue_url=url, github_issue_number=123)

    assert _safe_github_issue_url(report) is None


def test_safe_github_issue_url_rejects_mismatched_issue_number():
    report = SimpleNamespace(
        github_issue_url=(
            "https://github.com/NTHU-Physics-SA-IT/PastExamWeb_PHY/issues/124"
        ),
        github_issue_number=123,
    )

    assert _safe_github_issue_url(report) is None
