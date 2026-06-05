#!/usr/bin/env python3
"""Convert ISO-string date fields to BSON Date in cases + documents.

History: writers in cases/routes.py, team_routes.py, approval_routes.py,
redaction_routes.py, redaction_suggestion_routes.py, share_routes.py,
contest_routes.py mixed two date-storage styles — some fields were
serialised via `.isoformat()` before insert (str on disk), others
written as raw `datetime.utcnow()` (BSON Date). That broke read code
that called `.isoformat()` on already-string values and made Mongo date
queries unreliable. Writers are now consistent (BSON Date everywhere);
this script cleans existing data so reads don't have to be defensive
forever.

Idempotent: skips fields that already parse as Date. Safe to run
multiple times.

Usage::

    # Against a stack started by setup.sh:
    docker compose exec backend python /app/scripts/../scripts/migrate_dates_to_bson.py

    # Or with explicit MONGODB_URI (e.g. on host):
    MONGODB_URI="mongodb://..." python3 scripts/migrate_dates_to_bson.py

Use --dry-run to print what would change without writing.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from typing import Any

try:
    from pymongo import MongoClient
except ImportError:
    print("pymongo required: pip install pymongo", file=sys.stderr)
    sys.exit(1)


# Field paths to normalize, per collection. Top-level fields use bare
# names; embedded-array members use "array_field.*.subfield" to mean
# "every element of array_field, look for subfield". Nothing else.
CASES_TOP_LEVEL = ["created_at", "updated_at", "due_date", "received_date",
                   "extended_due_date", "estimated_completion", "approved_at"]
CASES_ARRAY_PATHS = [
    ("case_team", "added_at"),
    ("audit_log", "timestamp"),
    ("comments", "created_at"),
]
DOCUMENTS_TOP_LEVEL = ["created_at", "updated_at", "upload_date", "uploaded_at"]
DOCUMENTS_ARRAY_PATHS = [
    ("redactions", "created_at"),
    ("redactions", "reviewed_at"),
    ("shared_with", "shared_at"),
    ("contests", "created_at"),
    ("contests", "resolved_at"),
    ("rejected_ai_suggestions", "rejected_at"),
]


def parse_iso(value: Any) -> datetime | None:
    """Parse an ISO-8601 string into datetime. Returns None for
    non-strings or unparseable strings."""
    if not isinstance(value, str):
        return None
    try:
        # fromisoformat doesn't accept the "Z" suffix on Python <3.11;
        # normalise just in case.
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _convert_top_level(doc: dict, fields: list[str]) -> dict:
    """Return {field: new_value} for fields where the value is an ISO
    string that parses successfully."""
    changes = {}
    for field in fields:
        parsed = parse_iso(doc.get(field))
        if parsed is not None:
            changes[field] = parsed
    return changes


def _convert_array(doc: dict, array_field: str, subfield: str) -> tuple[list, bool]:
    """Walk doc[array_field], convert each element's subfield if it's an
    ISO string. Returns (new_array, changed_anything). When the field is
    missing or non-list, returns ([], False) so the caller's type
    expectation holds even though that array won't be written."""
    arr = doc.get(array_field)
    if not isinstance(arr, list):
        return [], False
    changed = False
    new_arr: list = []
    for item in arr:
        if isinstance(item, dict):
            parsed = parse_iso(item.get(subfield))
            if parsed is not None:
                item = {**item, subfield: parsed}
                changed = True
        new_arr.append(item)
    return new_arr, changed


def migrate_collection(
    coll,
    top_level: list[str],
    array_paths: list[tuple[str, str]],
    dry_run: bool,
    backfill_created_at: bool = False,
) -> tuple[int, int]:
    """Returns (docs_scanned, docs_updated).

    If backfill_created_at is True, also sets `created_at` for any doc
    that's missing it (or has it as null) using the `_id` ObjectId's
    embedded timestamp as a fallback — this is the only defensible
    source for old documents that were inserted without created_at.
    """
    scanned = 0
    updated = 0
    for doc in coll.find({}):
        scanned += 1

        set_payload: dict[str, Any] = {}

        # Top-level fields.
        top_changes = _convert_top_level(doc, top_level)
        set_payload.update(top_changes)

        # Backfill created_at from the ObjectId's embedded timestamp
        # when the doc is missing it. BSON ObjectIds carry a 4-byte
        # creation timestamp; pymongo exposes it via .generation_time.
        if backfill_created_at and not doc.get("created_at"):
            _id = doc.get("_id")
            if hasattr(_id, "generation_time"):
                # generation_time is tz-aware UTC; convert to naive UTC
                # to match the rest of the date fields in this codebase.
                set_payload["created_at"] = _id.generation_time.replace(tzinfo=None)

        # Array-embedded fields. We rewrite the entire array because
        # MongoDB's positional operators don't help when multiple
        # elements need conversion.
        for array_field, subfield in array_paths:
            new_arr, changed = _convert_array(doc, array_field, subfield)
            if changed:
                set_payload[array_field] = new_arr

        if not set_payload:
            continue

        updated += 1
        if dry_run:
            preview_fields = ", ".join(sorted(set_payload.keys()))
            print(f"  would update {doc.get('id', doc.get('_id'))}: {preview_fields}")
            continue
        coll.update_one({"_id": doc["_id"]}, {"$set": set_payload})

    return scanned, updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--mongodb-uri",
        default=os.environ.get("MONGODB_URI"),
        help="MongoDB connection URI (default: $MONGODB_URI)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would change without writing"
    )
    args = parser.parse_args()

    if not args.mongodb_uri:
        print(
            "MongoDB URI required. Pass --mongodb-uri or set MONGODB_URI.",
            file=sys.stderr,
        )
        return 1

    client = MongoClient(args.mongodb_uri)
    db = client.get_default_database()
    print(f"Connected to {db.name} on {args.mongodb_uri.rsplit('@', 1)[-1]}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'WRITE'}")
    print()

    scanned, updated = migrate_collection(
        db.cases,
        CASES_TOP_LEVEL,
        CASES_ARRAY_PATHS,
        args.dry_run,
        backfill_created_at=True,
    )
    print(f"cases:     scanned {scanned}, {'would update' if args.dry_run else 'updated'} {updated}")

    scanned, updated = migrate_collection(
        db.documents,
        DOCUMENTS_TOP_LEVEL,
        DOCUMENTS_ARRAY_PATHS,
        args.dry_run,
        backfill_created_at=True,
    )
    print(f"documents: scanned {scanned}, {'would update' if args.dry_run else 'updated'} {updated}")

    print()
    print("Done." if not args.dry_run else "Dry run complete — re-run without --dry-run to apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
