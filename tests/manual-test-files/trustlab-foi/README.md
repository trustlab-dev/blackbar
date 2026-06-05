# TrustLab Inc / CCSA — Demo FOI Case

A complete, realistic FOI case for walking through BlackBar end-to-end:
case intake → document upload → email-thread consolidation → AI
suggestions → manual redaction → release package.

## The scenario

**Coastal Crown Services Authority (CCSA)** — a fictional BC Crown
corporation — issued an RFP for fractional Chief Information Officer
advisory services. **TrustLab Inc** (one-person consultancy, principal
Matt Crossley) submitted a proposal. CCSA's selection committee
evaluated it, contacted two referees, and prepared an internal memo
recommending short-listing.

A journalist (**Jordan Park**) then files an FOI request asking for
"all records concerning CCSA's evaluation of TrustLab Inc's fractional
CIO proposal." That's the case BlackBar is processing.

## What's in the case

| Record                              | Purpose for the demo                                  |
|-------------------------------------|--------------------------------------------------------|
| `trustlab-proposal-letter.docx`     | Primary responsive record. Mild redactions.            |
| `trustlab-cv.docx`                  | Attached to the proposal. Light redactions (phone).    |
| `ccsa-evaluation-memo.docx`         | Heavy redactions: committee deliberations (FIPPA s.13).|
| `ccsa-referee-notes.docx`           | Heaviest redactions: third-party personal info (s.22). |
| `email-thread/01-foi-request.eml`   | Initial FOI request from the requester.                |
| `email-thread/02-acknowledgment.eml`| FOI office acknowledges, registers FOI-2026-058.       |
| `email-thread/03-internal-forward.eml` | FOI officer forwards to procurement records.        |
| `email-thread/04-internal-response.eml`| Procurement responds with two attachments.          |

The four EMLs share a proper `Message-ID` / `In-Reply-To` / `References`
chain rooted at message 1, so BlackBar's email-thread consolidation
treats them as a single conversation.

## Layout

```
trustlab-foi/
├── README.md
├── generate.py              re-generates all 4 DOCX + 4 EML files (idempotent)
├── source/                  authoritative content in markdown
│   ├── cv-matt-crossley.md
│   ├── proposal-letter.md
│   ├── evaluation-memo.md
│   └── referee-notes.md
└── generated/               output (commit alongside the script)
    ├── trustlab-cv.docx
    ├── trustlab-proposal-letter.docx
    ├── ccsa-evaluation-memo.docx
    ├── ccsa-referee-notes.docx
    └── email-thread/
        ├── 01-foi-request.eml
        ├── 02-acknowledgment.eml
        ├── 03-internal-forward.eml
        └── 04-internal-response.eml
```

## Regenerating the files

The source markdown is authoritative. After editing any `source/*.md`:

```bash
python3 tests/manual-test-files/trustlab-foi/generate.py
```

The script needs `python-docx`. Install on the host with
`pip install python-docx`, or run inside the backend container which
already has it.

## Loading into a running BlackBar

After `setup.sh` has created an admin user, load the case via:

```bash
python3 scripts/seed_trustlab_demo.py \
    --admin-email "$ADMIN_EMAIL" \
    --admin-password "$ADMIN_PASSWORD"
```

`setup.sh` will offer to do this automatically (see the
`Seed TrustLab demo FOI case` prompt). The loader needs `httpx` on the
host (`pip install httpx`).

The loader creates a fresh case each time it runs — it does not check
for duplicates. To start clean, delete the previous case in the UI
first.

## Privacy posture

- The principal's real name (Matt Crossley), email, employer history,
  education, and certifications are kept as-is — all are public on
  LinkedIn.
- The principal's phone number is `555-0142` (synthetic), not the real
  one on his CV.
- Every other named person (the FOI requester Jordan Park, the FOI
  officer Riley Chen, the procurement records custodian Sam Beaumont,
  the selection committee members, the referees Dr. Vance and
  Mr. Tan) is **fictional**.
- "Coastal Crown Services Authority" is fictional — it does not
  collide with any real BC Crown corporation.
- All phone numbers use the reserved fictional `555-01XX` range.
- All email domains use `example.org` or `ccsa-bc.example.org`
  (`.example.org` is reserved by IANA for documentation).
