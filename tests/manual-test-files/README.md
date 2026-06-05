# Manual Test Files

Synthetic fixtures for hand-testing BlackBar end-to-end. Use these when
walking through the UI smoke flow: upload, OCR, redaction, release package.

**All content is fabricated.** Names, email addresses, phone numbers, postal
codes, and dollar amounts are synthetic. The phone-number range `555-01XX`
and the Canadian postal code `V0V 0V0` are explicitly reserved for
fictional use.

## Layout

```
tests/manual-test-files/
├── generate_fixtures.py            re-generates everything (idempotent)
└── generated/
    ├── procurement-policy.docx     Word document with a policy + a 4-row table
    ├── contractor-list.xlsx        Excel sheet, 9 synthetic vendors + PII columns
    ├── redaction-test.pdf          2-page PDF dense with names/emails/phones
    └── email-thread/
        ├── 01-initial-request.eml          public requester → FOI office
        ├── 02-acknowledgment.eml           FOI office → requester
        ├── 03-internal-forward.eml         FOI officer → IT department
        └── 04-internal-response.eml        IT → FOI officer  (XLSX attached)
```

The four EMLs share a proper `Message-ID` / `In-Reply-To` / `References`
chain rooted at message 1 — BlackBar's email-thread consolidation
(`src/utils/email_threads.py`) should treat them as a single conversation.

## Regenerating

Run from the repo root:

```bash
backend/.venv-test/bin/python3 tests/manual-test-files/generate_fixtures.py
```

Or inside the backend container (the deps it needs — `python-docx`,
`reportlab`, `openpyxl` — are already there, except `openpyxl` which is
in the test venv):

```bash
docker compose exec backend pip install openpyxl
docker compose exec backend python tests/manual-test-files/generate_fixtures.py
```

The script is fully deterministic (no timestamps, no random IDs), so
rerunning produces byte-identical files. Commit the generated files
alongside the script.

## Suggested smoke walkthrough

1. **Create a case** in the UI (FOI-2026-042, "Procurement records for IT
   contracts 2024-2026").
2. **Upload `procurement-policy.docx`** — exercises the LibreOffice
   DOCX→PDF conversion path, then OCR fallback if the page is image-only.
3. **Upload `contractor-list.xlsx`** — same conversion path, table content.
4. **Upload `redaction-test.pdf`** — direct PDF ingestion. Open it in the
   redaction viewer and draw boxes over the synthetic phone numbers and
   email addresses. This exercises the manual redaction route + the
   coordinate-roundtrip code from Sub-phase 1.12.
5. **Upload all four EMLs** from `email-thread/`. The email-thread
   consolidation feature should detect they belong together. Inspect the
   resulting case-documents view to confirm threading.
6. **Generate a release package** from the case. The PDF should appear in
   the archive with your redactions applied; the unredacted versions
   should NOT.

## A note on MSG (Outlook) files

The `.msg` Outlook format is a Microsoft Compound Document Binary File.
Generating valid `.msg` files programmatically from Python requires
either a Win32 COM connection to Outlook or a commercial library
(`aspose-email`, etc.). The open-source ecosystem ships read-only
parsers — including BlackBar's `extract-msg` dependency.

**No `.msg` fixture is included here.** Practical options if you need
one for testing:

- Open `01-initial-request.eml` in Outlook (any version) and `File →
  Save As → Outlook Message Format (.msg)`.
- Use [`aspose-email`](https://products.aspose.com/email/) under its
  free-tier evaluation if you're comfortable with that.
- Skip MSG entirely — the EML path exercises the same email-thread
  consolidation code (the format-specific branch is only in
  `processing_service._extract_email_msg`).
