import ipaddress
import re
from pathlib import Path
from urllib.parse import urlsplit

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
NGINX_CONFIG = REPOSITORY_ROOT / "proxy" / "nginx.conf"
DEVELOPMENT_LISTENERS = REPOSITORY_ROOT / "proxy" / "nginx.development-listeners.conf"
PRODUCTION_LISTENERS = REPOSITORY_ROOT / "proxy" / "nginx.production-listeners.conf"
PRODUCTION_COMPOSE = REPOSITORY_ROOT / "docker" / "docker-compose.prod.yml"
PRODUCTION_ENV_EXAMPLE = REPOSITORY_ROOT / "docker" / ".env.production.example"
BACKEND_DOCKERFILE = REPOSITORY_ROOT / "backend" / "Dockerfile"
COMPOSE_SAFETY_VALIDATOR = REPOSITORY_ROOT / "scripts" / "validate-compose-safety.sh"

OFFICIAL_CLOUDFLARE_NETWORKS = {
    "173.245.48.0/20",
    "103.21.244.0/22",
    "103.22.200.0/22",
    "103.31.4.0/22",
    "141.101.64.0/18",
    "108.162.192.0/18",
    "190.93.240.0/20",
    "188.114.96.0/20",
    "197.234.240.0/22",
    "198.41.128.0/17",
    "162.158.0.0/15",
    "104.16.0.0/13",
    "104.24.0.0/14",
    "172.64.0.0/13",
    "131.0.72.0/22",
    "2400:cb00::/32",
    "2606:4700::/32",
    "2803:f800::/32",
    "2405:b500::/32",
    "2405:8100::/32",
    "2a06:98c0::/29",
    "2c0f:f248::/32",
}


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


def _logged_request_target(request_target: str) -> str:
    config = _config()
    match = re.search(
        r"map\s+\$uri\s+\$access_request_target\s*\{(?P<body>.*?)\}",
        config,
        re.DOTALL,
    )
    assert match is not None
    path = urlsplit(request_target).path
    for pattern, replacement in re.findall(
        r"^\s*(\S+)\s+(\$\w+);\s*$", match.group("body"), re.MULTILINE
    ):
        if pattern == "default":
            default = replacement
        elif pattern.startswith("~") and re.match(pattern[1:], path):
            return path if replacement == "$uri" else request_target
    assert default == "$request_uri"
    return request_target


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
    assert "log_format proxy_peer_combined '$realip_remote_addr" in config
    assert (
        "access_log /var/log/nginx/access.log proxy_peer_combined "
        "if=$access_loggable;" in config
    )


def test_discussion_websocket_query_is_excluded_from_nginx_access_log_target() -> None:
    target = "/api/courses/12/archives/34/discussion/ws?ticket=opaque-ticket-sentinel"

    assert _logged_request_target(target) == "/api/courses/12/archives/34/discussion/ws"
    assert _logged_request_target(
        "/api/courses/12/archives/34/discussion/ws?token=legacy-bearer-sentinel"
    ) == "/api/courses/12/archives/34/discussion/ws"
    assert _logged_request_target("/api/courses?category=graduate") == (
        "/api/courses?category=graduate"
    )
    config = _config()
    assert '"$request"' not in config
    assert '"$request_method $access_request_target $server_protocol"' in config


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
    assert "proxy_pass http://backend-trusted:8000/seo/sitemap.xml;" in config
    assert "location = /robots.txt" in config
    assert "proxy_pass http://backend-trusted:8000/seo/robots.txt;" in config
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


def _trusted_cloudflare_networks() -> set[str]:
    production = PRODUCTION_LISTENERS.read_text(encoding="utf-8")
    return set(re.findall(r"^set_real_ip_from\s+(\S+);$", production, re.MULTILINE))


def _normalized_address(peer: str, cloudflare_header: str) -> str:
    peer_address = ipaddress.ip_address(peer)
    trusted = any(
        peer_address in ipaddress.ip_network(network)
        for network in _trusted_cloudflare_networks()
    )
    return cloudflare_header if trusted else peer


def test_production_real_ip_trusts_exact_current_cloudflare_ranges_only() -> None:
    production = PRODUCTION_LISTENERS.read_text(encoding="utf-8")

    assert "real_ip_header CF-Connecting-IP;" in production
    assert "real_ip_recursive off;" in production
    assert _trusted_cloudflare_networks() == OFFICIAL_CLOUDFLARE_NETWORKS
    assert "set_real_ip_from 0.0.0.0/0;" not in production
    assert "set_real_ip_from ::/0;" not in production


def test_cloudflare_real_ip_semantics_cover_trusted_and_untrusted_ipv4_ipv6() -> None:
    assert _normalized_address("173.245.48.5", "203.0.113.40") == "203.0.113.40"
    assert _normalized_address("2606:4700::1234", "2001:db8::40") == "2001:db8::40"
    assert _normalized_address("192.0.2.15", "203.0.113.99") == "192.0.2.15"
    assert _normalized_address("2001:db8::15", "2001:db8::99") == "2001:db8::15"


def test_development_does_not_trust_cloudflare_visitor_headers() -> None:
    development = DEVELOPMENT_LISTENERS.read_text(encoding="utf-8")

    assert "real_ip_header" not in development
    assert "set_real_ip_from" not in development


def test_proxy_rebuilds_a_single_authoritative_forwarded_identity() -> None:
    config = _config()

    assert "$proxy_add_x_forwarded_for" not in config
    assert config.count("proxy_set_header X-Real-IP $remote_addr;") == 7
    assert config.count("proxy_set_header X-Forwarded-For $remote_addr;") == 7


def test_production_uvicorn_trust_matches_the_static_nginx_network_address() -> None:
    compose = PRODUCTION_COMPOSE.read_text(encoding="utf-8")
    environment = PRODUCTION_ENV_EXAMPLE.read_text(encoding="utf-8")
    dockerfile = BACKEND_DOCKERFILE.read_text(encoding="utf-8")

    required_reference = "${PRODUCTION_NGINX_PROXY_IP:?Set PRODUCTION_NGINX_PROXY_IP}"
    assert f"FORWARDED_ALLOW_IPS: {required_reference}" in compose
    assert f"ipv4_address: {required_reference}" in compose
    assert "name: pastexam-trusted-proxy-network" in compose
    assert "subnet: 172.30.0.0/28" in compose
    assert "ip_range: 172.30.0.8/29" in compose
    assert "gateway: 172.30.0.1" in compose
    assert "backend-trusted" in compose
    assert "proxy_pass http://backend-trusted:8000/;" in _config()

    match = re.search(r"^PRODUCTION_NGINX_PROXY_IP=(\S+)$", environment, re.MULTILINE)
    assert match is not None
    address = ipaddress.ip_address(match.group(1))
    assert any(
        address in ipaddress.ip_network(network)
        for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    )
    assert '"--proxy-headers"' in dockerfile
    assert '"--forwarded-allow-ips", "*"' not in dockerfile


def test_standalone_nginx_parser_resolves_the_trusted_backend_alias() -> None:
    validator = COMPOSE_SAFETY_VALIDATOR.read_text(encoding="utf-8")

    assert "--network none" in validator
    assert "--add-host backend-trusted:127.0.0.1" in validator


def _location_body(config: str, selector: str) -> str:
    marker = f"        location {selector} {{"
    start = config.find(marker)
    assert start >= 0
    next_location = config.find("\n        location ", start + len(marker))
    end = next_location if next_location >= 0 else len(config)
    return config[start:end]


def test_api_request_body_limits_are_route_specific() -> None:
    config = _config()
    generic_api = _location_body(config, "/api/")
    upload = _location_body(config, "= /api/archives/upload")
    minio = _location_body(config, "/minio/")

    assert "client_max_body_size 1M;" in generic_api
    assert "client_max_body_size 21M;" in upload
    assert "client_max_body_size 100M;" in minio


def test_exact_upload_route_preserves_api_proxy_security_contract() -> None:
    config = _config()
    generic_api = _location_body(config, "/api/")
    upload = _location_body(config, "= /api/archives/upload")

    shared_directives = (
        "proxy_http_version 1.1;",
        "proxy_pass_request_headers on;",
        "proxy_set_header Host $host;",
        "proxy_set_header X-Real-IP $remote_addr;",
        "proxy_set_header X-Forwarded-For $remote_addr;",
        "proxy_set_header X-Forwarded-Proto $scheme;",
        "proxy_set_header Authorization $http_authorization;",
        "Access-Control-Allow-Credentials",
        "Access-Control-Allow-Headers",
    )
    for directive in shared_directives:
        assert directive in generic_api
        assert directive in upload

    assert "proxy_pass http://backend-trusted:8000/archives/upload;" in upload
    assert "$proxy_add_x_forwarded_for" not in upload


def test_websocket_location_suppresses_unredactable_nginx_error_requests() -> None:
    config = _config()
    websocket = _location_body(
        config,
        "~ ^/api/courses/[0-9]+/archives/[0-9]+/discussion/ws$",
    )
    generic_api = _location_body(config, "/api/")

    assert "error_log /dev/null crit;" in websocket
    assert "error_log /dev/null" not in generic_api
    assert "rewrite ^/api/(.*)$ /$1 break;" in websocket
    assert "proxy_pass http://backend-trusted:8000;" in websocket
    for directive in (
        "proxy_http_version 1.1;",
        "proxy_set_header Upgrade $http_upgrade;",
        'proxy_set_header Connection "upgrade";',
        "proxy_pass_request_headers on;",
        "proxy_set_header Host $host;",
        "proxy_set_header X-Real-IP $remote_addr;",
        "proxy_set_header X-Forwarded-For $remote_addr;",
        "proxy_set_header X-Forwarded-Proto $scheme;",
        "proxy_set_header Authorization $http_authorization;",
    ):
        assert directive in websocket
