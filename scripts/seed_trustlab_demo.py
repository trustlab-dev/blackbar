#!/usr/bin/env python3
"""Seed the TrustLab Inc / CCSA FOI demo case into a running BlackBar.

This script is intentionally narrow: it creates ONE realistic FOI case
(TrustLab Inc fractional CIO proposal evaluation, FOI-style) and uploads
the four DOCX records plus the four-message email thread. It does not
seed redactions; the operator runs through the redaction tooling
themselves once the case exists.

Usage::

    # Against a stack started by setup.sh (defaults to localhost:8000):
    python3 scripts/seed_trustlab_demo.py \
        --admin-email matt@example.org \
        --admin-password "$(grep '^  password:' INITIAL_CREDS.txt | head -1 | awk '{print $2}')"

    # Against an explicit base URL:
    python3 scripts/seed_trustlab_demo.py \
        --base-url http://localhost:8000/api/v1 \
        --admin-email matt@example.org \
        --admin-password "<password>"

The script is idempotent on the case-creation side: re-running it
creates a fresh case with a fresh tracking number, leaving any earlier
seed in place. To start clean, delete the previous case in the UI first.

Source of the uploaded files: ``tests/manual-test-files/trustlab-foi/
generated/``. Re-generate them with::

    python3 tests/manual-test-files/trustlab-foi/generate.py

Requires httpx (``pip install httpx``). httpx is already in the backend
container if you'd rather run this in-container.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import httpx
except ImportError:
    print(
        "httpx is required. Install with `pip install httpx`, or run this "
        "script inside the backend container where it's already present.",
        file=sys.stderr,
    )
    sys.exit(1)


REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "manual-test-files" / "trustlab-foi" / "generated"

# Files uploaded into the case. Order matters only for storytelling: the
# proposal letter is the primary record, the CV is its attachment, then
# internal records, then the email thread.
UPLOADS = [
    FIXTURES / "trustlab-proposal-letter.docx",
    FIXTURES / "trustlab-cv.docx",
    FIXTURES / "ccsa-evaluation-memo.docx",
    FIXTURES / "ccsa-referee-notes.docx",
    FIXTURES / "email-thread" / "01-foi-request.eml",
    FIXTURES / "email-thread" / "02-acknowledgment.eml",
    FIXTURES / "email-thread" / "03-internal-forward.eml",
    FIXTURES / "email-thread" / "04-internal-response.eml",
]

CASE_PAYLOAD = {
    "title": "FOI request: TrustLab Inc fractional CIO proposal records",
    "description": (
        "Public FOI request (registered as FOI-2026-058) for records held by "
        "Coastal Crown Services Authority concerning its evaluation of "
        "TrustLab Inc's response to RFP CCSA-2025-FCIO-014 (fractional "
        "Chief Information Officer advisory services). Responsive records "
        "include the original proposal letter and CV, internal evaluation "
        "memo, reference-check notes, and four-message email thread. "
        "Personal information about CCSA staff and reference contacts is "
        "to be redacted under FIPPA s.22; some committee deliberations may "
        "warrant withholding under s.13 (advice and recommendations)."
    ),
    "priority": "medium",
    "status": "new",
    "tags": ["demo", "trustlab-foi", "procurement"],
    "requester": {
        "name": "Jordan Park",
        "email": "jordan.park@example.org",
        "phone": "555-0145",
        "organization": "Independent",
    },
}


def login(client: httpx.Client, email: str, password: str) -> str:
    r = client.post("/auth/login", json={"email": email, "password": password})
    if r.status_code != 200:
        raise SystemExit(
            f"login failed ({r.status_code}): {r.text}\n"
            "Check the admin email/password. The initial password is in "
            "INITIAL_CREDS.txt after setup.sh has run."
        )
    return r.json()["access_token"]


def create_case(client: httpx.Client) -> dict:
    r = client.post("/cases/", json=CASE_PAYLOAD)
    if r.status_code != 200:
        raise SystemExit(f"create case failed ({r.status_code}): {r.text}")
    return r.json()


def upload_document(client: httpx.Client, case_id: str, path: Path) -> dict:
    with path.open("rb") as f:
        files = {"file": (path.name, f.read(), _guess_mime(path))}
    r = client.post("/documents/", data={"case_id": case_id}, files=files, timeout=120.0)
    if r.status_code != 200:
        raise SystemExit(f"upload {path.name} failed ({r.status_code}): {r.text}")
    return r.json()


def _guess_mime(path: Path) -> str:
    if path.suffix == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if path.suffix == ".eml":
        return "message/rfc822"
    return "application/octet-stream"


def advance_to_in_progress(client: httpx.Client, case_id: str) -> None:
    """Mark the case as in_progress so the demo opens on something more
    interesting than the default 'new' state."""
    r = client.put(f"/cases/{case_id}", json={"status": "in_progress"})
    if r.status_code != 200:
        # Non-fatal — the case still exists and is usable.
        print(
            f"  warning: could not advance case to in_progress ({r.status_code}): {r.text}",
            file=sys.stderr,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000/api/v1",
        help="API base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--admin-email",
        required=True,
        help="Email of an admin user (created by setup.sh).",
    )
    parser.add_argument(
        "--admin-password",
        required=True,
        help="Password for the admin user.",
    )
    args = parser.parse_args()

    missing = [p for p in UPLOADS if not p.exists()]
    if missing:
        print(
            "Generated fixtures are missing. Run:\n"
            "  python3 tests/manual-test-files/trustlab-foi/generate.py\n"
            "Missing files:",
            file=sys.stderr,
        )
        for p in missing:
            print(f"  {p}", file=sys.stderr)
        return 1

    with httpx.Client(base_url=args.base_url, timeout=30.0) as client:
        print(f"Logging in as {args.admin_email}...")
        token = login(client, args.admin_email, args.admin_password)
        client.headers["Authorization"] = f"Bearer {token}"

        print("Creating demo case...")
        case = create_case(client)
        case_id = case["id"]
        tracking = case.get("tracking_number", "(no tracking number)")
        print(f"  case id: {case_id}")
        print(f"  tracking: {tracking}")

        print(f"Uploading {len(UPLOADS)} documents...")
        for path in UPLOADS:
            doc = upload_document(client, case_id, path)
            doc_id = doc.get("id") or doc.get("document", {}).get("id") or "?"
            print(f"  uploaded {path.name}  (doc_id={doc_id})")

        print("Advancing case to in_progress...")
        advance_to_in_progress(client, case_id)

    print()
    print(f"Done. Open the case in the UI: /cases/{case_id}")
    print(f"      Tracking number:        {tracking}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
