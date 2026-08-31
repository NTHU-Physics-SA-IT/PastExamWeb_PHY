"""Bind activation inputs to exact Full CI image and candidate artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from validate_candidate_receipt import ReceiptError, validate_receipt

NGINX_DIGEST = "sha256:029d4461bd98f124e531380505ceea2072418fdf28752aa73b7b273ba3048903"


class ActivationAuthorityError(RuntimeError):
    """Activation artifacts do not bind to the requested source authority."""


def _read_authority(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ActivationAuthorityError("Image authority is unavailable.") from error
    for line in lines:
        key, separator, value = line.partition("=")
        if not separator or not key or key in values or not value:
            raise ActivationAuthorityError("Image authority is malformed.")
        values[key] = value
    if set(values) != {"source_sha", "frontend_digest", "backend_digest"}:
        raise ActivationAuthorityError("Image authority has an unexpected schema.")
    return values


def validate_activation_authority(
    receipt_path: Path,
    image_authority_path: Path,
    release_sha: str,
    source_ci_run_id: int,
    source_ci_run_attempt: int,
    legacy_nginx_compose: Path | None = None,
) -> dict[str, str]:
    if re.fullmatch(r"[0-9a-f]{40}", release_sha) is None:
        raise ActivationAuthorityError("Release SHA is malformed.")
    if source_ci_run_id < 1 or source_ci_run_attempt < 1:
        raise ActivationAuthorityError("Source CI authority is malformed.")
    authority = _read_authority(image_authority_path)
    if authority["source_sha"] != release_sha:
        raise ActivationAuthorityError("Image authority source SHA disagrees.")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ActivationAuthorityError("Candidate receipt is malformed.") from error
    if not isinstance(receipt, dict):
        raise ActivationAuthorityError("Candidate receipt is malformed.")
    if (
        receipt.get("source_ci_run_id") != source_ci_run_id
        or receipt.get("source_ci_run_attempt") != source_ci_run_attempt
    ):
        raise ActivationAuthorityError(
            "Candidate receipt Source Full authority disagrees."
        )
    image_digests = receipt.get("image_digests")
    legacy_nginx = isinstance(image_digests, dict) and set(image_digests) == {
        "frontend",
        "backend",
    }
    normalized_receipt = receipt
    if legacy_nginx:
        if legacy_nginx_compose is None:
            raise ActivationAuthorityError("Legacy nginx authority was not supplied.")
        try:
            compose = legacy_nginx_compose.read_text(encoding="utf-8")
        except OSError as error:
            raise ActivationAuthorityError(
                "Legacy nginx authority is unavailable."
            ) from error
        nginx_section = re.search(
            r"(?ms)^  nginx:\s*\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:\s*$|^volumes:)",
            compose,
        )
        images = (
            re.findall(r"(?m)^    image:\s*([^\s#]+)\s*$", nginx_section.group("body"))
            if nginx_section
            else []
        )
        if images != ["nginx:1.29.2"]:
            raise ActivationAuthorityError("Legacy nginx tag authority is unexpected.")
        normalized_receipt = dict(receipt)
        normalized_receipt["image_digests"] = {
            **image_digests,
            "nginx": NGINX_DIGEST,
        }
    try:
        validate_receipt(
            normalized_receipt,
            {
                "release_sha": release_sha,
                "frontend_digest": authority["frontend_digest"],
                "backend_digest": authority["backend_digest"],
                "nginx_digest": NGINX_DIGEST,
                "source_archive_sha256": str(receipt.get("package_sha256", "")),
                "release_files_sha256": str(receipt.get("release_files_sha256", "")),
            },
        )
    except ReceiptError as error:
        raise ActivationAuthorityError(str(error)) from error
    receipt_digest = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    return {
        "release_sha": release_sha,
        "source_ci_run_id": str(source_ci_run_id),
        "source_ci_run_attempt": str(source_ci_run_attempt),
        "frontend_digest": authority["frontend_digest"],
        "backend_digest": authority["backend_digest"],
        "nginx_digest": NGINX_DIGEST,
        "candidate_receipt_sha256": receipt_digest,
        "release_manifest_sha256": str(receipt["release_manifest_sha256"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--image-authority", type=Path, required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--source-ci-run-id", type=int, required=True)
    parser.add_argument("--source-ci-run-attempt", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--legacy-nginx-compose", type=Path)
    args = parser.parse_args()
    values = validate_activation_authority(
        args.receipt,
        args.image_authority,
        args.release_sha,
        args.source_ci_run_id,
        args.source_ci_run_attempt,
        args.legacy_nginx_compose,
    )
    with args.output.open("a", encoding="utf-8", newline="\n") as output:
        for key, value in values.items():
            output.write(f"{key}={value}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
