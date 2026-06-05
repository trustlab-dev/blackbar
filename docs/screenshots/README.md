# Screenshots

A guided tour of BlackBar's core flows. These are captured against the seeded
demo data; regenerate them any time with
[`scripts/demo_screenshots.sh`](../../scripts/demo_screenshots.sh).

## Requester-facing

### Public login (demo mode)
One-click "Log in as Jordan Park" appears only when `BLACKBAR_DEMO_MODE=true`.

![Public login](01-public-login.png)

### Requester portal
Requesters track their FOI requests and see a status timeline.

![Requester portal](02-requester-portal.png)

## Staff workspace

### Staff sign-in
![Staff login](03-staff-login.png)

### Case queue
Every case with status, priority, assignee, and colour-coded due dates.

![Case queue](04-case-queue.png)

### Case detail
Statutory clock, records collection, and the document set for a case.

![Case detail](05-case-detail.png)

### Document list — email-thread deduplication
Uploaded email threads are consolidated: the latest message is kept and older
replies are marked **superseded**, so reviewers don't redact the same content
repeatedly.

![Email thread deduplication](11-email-thread.png)

## Document viewer & redaction

### Viewer with AI suggestion overlays
The rendered document with AI-suggested redactions highlighted inline.

![Document viewer](06-document-viewer.png)

### AI redaction suggestions
Suggestions classified under FOIPPA s.22 (personal information), with confidence.

![AI suggestions drawer](08-ai-suggestions.png)

### Suggestion reasoning
Each suggestion can show its reasoning chain and a severance note.

![Suggestion reasoning](09-review-reasoning.png)

### Manual redaction
Draw rectangular redactions directly on the page.

![Manual redaction tool](07-manual-redaction.png)

### Redacted preview
Toggle the eye to preview the final output — content burned out as black bars.

![Redacted view](12-redacted-view.png)

## Release

### Generate release package
Select documents (redaction counts shown) and produce the package for the requester.

![Release package](10-release-package.png)
