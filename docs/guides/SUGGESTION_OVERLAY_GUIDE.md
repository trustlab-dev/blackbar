# AI Suggestion Overlays — User Guide

How to use BlackBar's AI-assisted redaction features: generating
suggestions, reviewing the reasoning, and manipulating redaction boxes on
the document.

---

## What the AI does (and doesn't)

The AI reads the document text, identifies content that may need to be
withheld under your jurisdiction's FOI legislation, and returns a list of
suggestions. **The default is disclosure** — the AI is calibrated to err
on the side of *not* redacting. You should still review every suggestion;
the AI gets the law right most of the time and the context wrong
sometimes.

The AI does **not** auto-apply anything. Nothing is redacted until you
accept a suggestion or draw a redaction box yourself.

---

## Generating suggestions

Open a document in the viewer and click the **Auto Suggest** button
(sparkle icon) on the right edge. The drawer has two tabs:

### Quick PII

Pattern-matched detections — emails, phone numbers, postal codes,
government IDs. Fast (no LLM call) but only catches things that match a
known regex. Use when you want a deterministic first pass.

### AI Recommended

LLM-generated suggestions using your jurisdiction pack. Slower (~10–25
seconds per document, depending on LLM provider and document length) but
context-aware.

Two buttons:

- **Generate AI Suggestions** — first call on a document. Returns cached
  results if the document has been analysed before.
- **Regenerate** — forces a fresh LLM call, bypassing the cache. Use this
  after a pack/prompt update so you see the new behaviour.

---

## Reading a suggestion

Each row in the AI Recommended tab shows:

- The text the AI proposes to redact (truncated to ~60 chars)
- A confidence chip (high / medium / low)
- A category line: `s.22(3)(a) — <reason>` (or just `S22 — <reason>` if
  the AI didn't cite a subsection)
- The page number

### Badges

- **Review** (orange) — the AI flagged this for mandatory human review.
  This fires for low-confidence items, s.21 third-party items (s.23
  notification required regardless), and items where the AI considered
  multiple exemptions.
- **s.25?** (purple) — the AI flagged this for public-interest override
  consideration. Means: even if the exemption applies, you may need to
  release it under s.25 (BC FIPPA) if it relates to public safety,
  environmental harm, or significant accountability matters.

### The "Why" expander

Click **Why** under any suggestion to see the AI's structured reasoning:

- **Reasoning** — step-by-step cascade the AI walked through
- **Harm identified** — for harm-based exemptions (s.15, s.17, s.21,
  etc.), the specific harm the AI articulated
- **Severance** — why the AI chose this exact span (not more, not less)
- **Exceptions considered** — s.22(4)(e), s.13(2)(a), etc. that the AI
  weighed against the redaction

If a suggestion looks wrong, the "Why" expander usually tells you which
rule the AI is misapplying. Reject the suggestion, and if it's a
recurring pattern across documents, the pack prompt may need tightening
(see [AI_PROMPT_SYSTEM](../api/AI_PROMPT_SYSTEM.md)).

---

## Accepting & rejecting

From the drawer:

- **Accept** — applies the suggestion as a redaction. Becomes a solid
  blue box on the page (or solid black when preview mode is off).
- **Reject** — drops the suggestion from the list and won't surface it
  again on this document (stored in `rejected_ai_suggestions`).
- **Bulk Accept Filtered / Bulk Reject Filtered** — apply to every
  suggestion matching the current page/category filter.

---

## Working with redaction boxes on the page

Once a redaction is on the page (whether AI-accepted or hand-drawn):

### Click to select

Click anywhere on a redaction box. It becomes the selected redaction:

- Blue highlight border appears around the box
- 8 resize handles appear at the corners and edges
- The redaction action menu opens at the click point

### Resize

Grab any of the 8 handles (white squares around the selected box) and
drag. Cursor changes to the resize direction. Resizing snaps when you
release; the new dimensions persist via the redaction-edit API.

### Drag to move

With a box selected, click and drag the **body** of the box (not a
handle) to move it. Cursor changes to `move`. A 2-pixel movement
threshold disambiguates a real drag from a click-to-open-menu; the
synthesised click after a drag is suppressed so the menu doesn't pop
back open.

### Keyboard

- **Esc** — closes the action menu. Selection stays so you can keep
  resizing.
- **Esc again** — deselects the redaction. Handles disappear.

### Editing the category / reason

In the action menu, click **Edit**, change category + description, click
**Save**. To delete the redaction, click **Delete** in the menu.

---

## Filtering suggestions

Use the drawer filters to narrow the list:

- **Page filter** — show only suggestions on a specific page
- **Category filter** — show only suggestions of a specific exemption
  (S22, S13, S14, S17, etc.)
- **Clear filters** — reset

Useful workflow: filter to one category (e.g. S22), bulk-accept the
high-confidence ones, then move to the next category.

---

## Tips

- **Generate vs Regenerate** — clicking Generate again is free (cached);
  Regenerate spends another LLM call. If suggestions look stale, hit
  Regenerate.
- **Suggestions persist across sessions** — accepted/rejected state is
  saved per document. You can leave a document partway through and
  return.
- **Hand-drawn redactions** also get the resize/drag/Why treatment. The
  Why expander is empty for hand-drawn (no AI reasoning to surface).
- **Scanned PDFs** without an OCR text layer may produce suggestions
  without coordinates. The drawer still lists them; use the page filter
  to find them and apply manually.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| "AI redaction suggestions unavailable - no default LLM is set" | Admin → LLM Configuration → click **Set Default** on an enabled config. |
| Suggestions return the same stale content after a pack edit | Click **Regenerate** (not Generate) — the plain fetch returns cached results. |
| Resize handles don't appear on a redaction | The redaction must be *selected* (click it first). If the menu is open and covering the handles, press Esc to close the menu — the selection persists. |
| Redaction box is wider than the text it covers | Known limitation of OCR-derived word boundaries on some PDFs. Use the resize handles to trim. |
| "Why" expander has nothing in it | The suggestion came from a legacy pack (Ontario MFIPPA) that doesn't emit the rich schema, or from Quick PII. Only BC FIPPA v2 and similar packs produce structured reasoning. |

---

## Admin settings

If you're an administrator:

- **Auto-generate AI suggestions** (Admin → System Configuration): when
  on, BlackBar runs the AI immediately after document upload as a
  FastAPI BackgroundTask. Adds ~10–25s per upload and incurs LLM cost
  on every doc — leave off unless your operators actually use AI
  suggestions on most uploads.
- **LLM Configuration** (Admin → LLM Configuration): manages provider
  configs (OpenAI, Anthropic, Google, Cohere). Exactly one config must be
  marked as default for AI features to work. The first enabled config
  created is auto-promoted to default; later ones don't override it.
