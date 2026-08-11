from pathlib import Path
import re
from urllib.parse import urlsplit


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
NGINX_CONFIG = REPOSITORY_ROOT / "proxy" / "nginx.conf"
DEVELOPMENT_LISTENERS = REPOSITORY_ROOT / "proxy" / "nginx.development-listeners.conf"
PRODUCTION_LISTENERS = REPOSITORY_ROOT / "proxy" / "nginx.production-listeners.conf"


def _config() -> str:
    return NGINX_CONFIG.read_text(encoding="utf-8")


def _access_log_map(config: str) -> tuple[str, set[str]]:
    match = re.search(
        r"map\s+\$uri\s+\$access_loggable\s*\{(?P<body>.*?)\}",
        config,
        re.DOTALL,
    )
    assert match is not None

    entries = dict(
        re.findall(r"^\s*(\S+)\s+([01]);\s*$", match.group("body"), re.MULTILINE)
    )
    return entries["default"], {path for path, value in entries.items() if value == "0"}


def _access_log_enabled(request_target: str) -> bool:
    default, suppressed_paths = _access_log_map(_config())
    assert default == "1"
    return urlsplit(request_target).path not in suppressed_paths


def test_oauth_callback_queries_are_not_written_to_nginx_access_log() -> None:
    assert not _access_log_enabled(
        "/api/auth/nthu/callback?code=non-sensitive-provider-sentinel"
    )
    assert not _access_log_enabled(
        "/login/callback?code=non-sensitive-handoff-sentinel"
    )


def test_ordinary_routes_keep_access_logging_enabled() -> None:
    config = _config()
    _, suppressed_paths = _access_log_map(config)

    assert suppressed_paths == {
        "/api/auth/nthu/callback",
        "/login/callback",
    }
    assert _access_log_enabled("/")
    assert _access_log_enabled("/api/health")
    assert (
        "access_log /var/log/nginx/access.log combined if=$access_loggable;" in config
    )


def test_frontend_callback_keeps_the_existing_spa_fallback() -> None:
    config = _config()
    location = re.search(r"location\s+/\s*\{(?P<body>.*?)\n\s*\}", config, re.DOTALL)
    assert location is not None

    body = location.group("body")
    assert "proxy_pass http://frontend/;" in body
    assert "proxy_intercept_errors on;" in body
    assert "error_page 404 = /index.html;" in body


def test_public_seo_routes_and_spa_robots_policy_remain_at_the_proxy() -> None:
    config = _config()

    assert "location = /sitemap.xml" in config
    assert "proxy_pass http://backend:8000/seo/sitemap.xml;" in config
    assert "location = /robots.txt" in config
    assert "proxy_pass http://backend:8000/seo/robots.txt;" in config
    assert "map $uri $spa_robots_tag" in config
    assert "add_header X-Robots-Tag $spa_robots_tag always;" in config


def test_development_and_production_listener_contracts_are_separate() -> None:
    config = _config()
    development = DEVELOPMENT_LISTENERS.read_text(encoding="utf-8")
    production = PRODUCTION_LISTENERS.read_text(encoding="utf-8")

    assert "include /etc/nginx/pastexam-listeners.conf;" in config
    assert development.strip() == "listen 8080;"
    assert "ssl" not in development
    assert "listen 8080;" in production
    assert "listen 8443 ssl;" in production
    assert "ssl_certificate /etc/nginx/certs/origin.pem;" in production
    assert "ssl_certificate_key /etc/nginx/certs/origin-key.pem;" in production
