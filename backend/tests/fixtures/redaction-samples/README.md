# Redaction Test Fixtures

Sample documents used for testing BlackBar's OCR, PII detection, and
redaction pipeline. All files in this directory are **synthetic fixtures**
— they do not contain real personal information.

## Files

- `APA_Student_Paper.docx` — academic-paper layout for testing
  structured-document OCR
- `Expanded_FOIPPA_Test_Document.docx` — multi-page FOIPPA-style content
- `FOIPPA_Test_Document.docx` — minimal FOIPPA-style content
- `Realistic_FOIPPA_Test_Document.docx` — realistic-language FOIPPA
  fixture (synthetic names, addresses, IDs)
- `PII_Excel.xlsx` — spreadsheet with synthetic PII for column-detection
- `receipt_img.png` — image-only receipt for OCR testing
- `test.eml` — plain-text email for `.eml` parsing tests

## Adding new fixtures

Only commit synthetic data. Real customer or maintainer documents are
NOT acceptable in this directory. If you need a fixture that reflects
real-world structure, generate or anonymize it first.
