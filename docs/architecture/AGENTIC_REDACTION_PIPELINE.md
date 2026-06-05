# Agentic Redaction Pipeline for BlackBar

> ## :warning: DESIGN PROPOSAL — NOT YET IMPLEMENTED
>
> This document is a forward-looking design recommendation. **None of
> the agent stages, watch-folder ingestion, separate artifact storage,
> or proposed collections (`ingest_jobs`, `artifacts`, `document_runs`,
> `recommendations`) exist in the codebase.** The current production
> pipeline is documented in
> [`DOCUMENT_PROCESSING.md`](DOCUMENT_PROCESSING.md).
>
> Treat this file as a strategy artifact. Do not cite it as
> authoritative behaviour, do not link to it from `README.md`, and do
> not implement against it without first opening a Discussion/issue so
> the affected sections can be agreed before code lands.
>
> **2026-05 update.** Part of this design — running detection and
> classification as separate LLM passes — was prototyped and reverted
> (commits `91e810b` → `0f62d32`). The doubled latency
> (≈30–50s per doc) wasn't worth the recall improvement given how
> often operators iterate on prompts during pack tuning. The current
> classification prompt does detection inline as part of a
> single-shot call. The two-pass shape stays viable for a future
> revival if/when prompt iteration stabilises; the `detection_pass`
> definition is preserved in the BC FIPPA v2 pack for that purpose.
> See [`docs/api/AI_PROMPT_SYSTEM.md`](../api/AI_PROMPT_SYSTEM.md)
> for the current single-shot prompt structure.

---

## Purpose

This document recommends how to evolve BlackBar from a case-management-heavy FOI platform into a focused, hands-off, agent-based document ingestion and redaction recommendation system.

Target user outcome:

- Drop files into a folder
- Automatically ingest emails, attachments, Office docs, images, and PDFs
- Normalize everything into PDF
- Perform OCR and structured text extraction
- Generate redaction recommendations directly in PDFs
- Minimize manual workflow and remove most case-management overhead

---

## Executive Recommendation

BlackBar already contains the right core primitives for an agentic redaction system. The best path is *not* a rewrite.

Keep and refactor the document-processing core:

- `backend/src/documents/processing_service.py`
- `backend/src/utils/conversion.py`
- `backend/src/utils/ocr.py`
- `backend/src/utils/ai_redaction.py`
- `backend/src/utils/pii_detection.py`
- `backend/src/utils/pdf_redaction.py`
- `backend/src/utils/email_threads.py`

Remove or isolate the FOI case-management surface area as optional orchestration:

- cases
- workflow queues
- contributors
- public portal
- approvals
- release packaging
- most of the frontend except a thin review UI if desired

The recommended target is a *single product with internal agents/workers*, not a fleet of independently deployed microservices.

Reason:

- The pipeline is sequential and stateful.
- Most stages share the same document artifacts and metadata.
- Coordinate fidelity and idempotency are easier with one canonical store.
- Splitting too early will create avoidable complexity around event contracts, artifact storage, retries, and security boundaries.

That said, the internal design should be *agent-shaped*: each stage should be explicit, isolated, resumable, and event-driven.

---

## What BlackBar Already Does Well

### Reusable strengths

#### 1. Central processing entrypoint

`backend/src/documents/processing_service.py` already acts like an orchestrator for:

- validation
- deduplication by content hash
- conversion to PDF
- OCR / text extraction
- email duplicate detection by Message-ID
- attachment processing
- thread consolidation
- background AI processing hooks

This is the best seed for an agent runtime.

#### 2. Format normalization

`backend/src/utils/conversion.py` already covers the hard ingestion edge cases:

- Office to PDF via LibreOffice
- image to PDF
- EML to PDF with body extraction
- MSG conversion
- attachment extraction from emails

This is core product value and should be preserved.

#### 3. OCR and coordinate extraction

`backend/src/utils/ocr.py` is one of the most valuable modules in the repo. It does:

- native PDF text extraction first
- OCR fallback for scanned pages
- page dimensions
- word-level coordinates
- line-level grouping

That is exactly what an agentic recommendation system needs in order to produce reviewable redaction overlays.

#### 4. AI + rule-based suggestion stack

BlackBar already has both layers:

- LLM-based suggestions in `backend/src/utils/ai_redaction.py`
- Presidio-based structured detection in `backend/src/utils/pii_detection.py`
  (note: Presidio is currently **deactivated** in the production
  pipeline; the module is retained for reactivation by adding
  `presidio-analyzer` + a matching spaCy model to `pyproject.toml`.)

That gives you a strong hybrid approach (once Presidio is rewired):

- rules for cheap, deterministic detection
- LLM for contextual or policy-sensitive suggestions

#### 5. PDF redaction application

`backend/src/utils/pdf_redaction.py` already applies redactions to PDFs using PyMuPDF. Even if the first product only writes recommendation overlays rather than burning redactions in, this remains a key downstream capability.

#### 6. Email thread and duplicate logic

`backend/src/utils/email_threads.py` and content-hash duplicate detection are directly useful in an unattended ingestion model.

---

## What To Strip Out

For the agentic version, these parts are mostly distraction unless kept as optional admin modules:

- FOI case lifecycle management
- statutory clock management
- priority queue
- internal messaging
- named contributors and collection links
- request transfer features
- release package generation
- most role-heavy approval flows
- most public portal functionality

In short: keep *document intelligence*, drop *FOI operations software*.

---

## Recommended Target Architecture

## Core idea

Turn the current upload pipeline into a document mission pipeline with explicit agents.

### Proposed internal agents

#### 1. Intake Agent

Responsibilities:

- watch one or more inbox folders
- detect newly arrived files
- create a stable ingestion job
- compute source fingerprint and dedupe keys
- copy source files into managed storage before processing

Inputs:

- filesystem events
- batch scans for missed files

Outputs:

- `document_job`
- immutable source artifact record

Notes:

- Do not process directly from the watched folder.
- Move or copy inputs into controlled storage first.
- Use content hash plus source path plus file size plus mtime as ingestion signals.

#### 2. Expansion Agent

Responsibilities:

- inspect file type
- unpack emails
- extract attachments
- recurse through nested attachments with depth limits
- flatten each logical item into a child document job

Reuses:

- `convert_eml_to_pdf`
- `convert_msg_to_pdf`
- email parsing logic in `conversion.py`
- thread logic in `email_threads.py`

Outputs:

- parent-child artifact graph
- one normalized work item per attachment/body component

#### 3. Normalization Agent

Responsibilities:

- convert Office docs, email bodies, images, and native PDFs into canonical PDFs
- preserve original artifacts
- record conversion logs and failures

Reuses:

- `convert_office_to_pdf`
- image conversion
- PDF text extraction helpers
- file hashing helpers

Outputs:

- canonical PDF artifact
- conversion metadata

#### 4. OCR Agent

Responsibilities:

- extract text and coordinates from canonical PDFs
- determine whether native text is sufficient
- OCR only where needed
- persist page/word/line coordinate maps separately from main metadata

Reuses:

- `extract_text_with_coordinates`
- `get_text_summary`

Critical recommendation:

- move `text_data` out of the main document record into a dedicated artifact or collection
- current docs note page and text truncation due to MongoDB document size limits
- an agentic system should treat OCR output as a first-class artifact, not inline metadata

#### 5. Detection Agent

Responsibilities:

- run deterministic entity detection first
- map detections into policy categories
- produce candidate spans with confidence and provenance

Reuses:

- `detect_pii`
- `map_presidio_to_category`

Outputs:

- rule-based candidate redactions
- source provenance: `presidio`, `regex`, `metadata`, etc.

#### 6. Policy Analysis Agent

Responsibilities:

- run LLM review on extracted text and optionally page snippets
- reason about contextual sensitivity
- avoid duplicates already found by Detection Agent
- output recommendation objects, not final decisions

Reuses:

- `get_redaction_suggestions`

Recommendation:

- split current prompt logic from transport logic
- keep pack/policy system, but make it document-policy oriented rather than FOI-case oriented

#### 7. Coordinate Resolution Agent

Responsibilities:

- map text recommendations back to page coordinates
- merge overlapping candidate boxes
- snap to words/lines/regions
- flag ambiguous matches for human review

Existing fit:

- BlackBar already enriches suggestions with coordinates in current flows
- this should become a standalone step with explicit confidence scoring

#### 8. PDF Annotation Agent

Responsibilities:

- write review overlays or annotation layers into output PDFs
- keep a recommendation PDF separate from a final redacted PDF
- optionally create a machine-readable sidecar JSON

Reuses:

- `pdf_redaction.py` patterns and PyMuPDF stack

Recommendation:

Produce three outputs per logical document:

1. original artifact
2. canonical review PDF with suggestion overlays
3. machine-readable recommendations JSON

#### 9. Review/Publish Agent

Responsibilities:

- mark the mission complete
- place outputs into a `done/` folder or destination store
- optionally create a human review package
- only burn permanent redactions if explicitly requested

---

## Data and State Model

The current `documents` collection mixes too many concerns. The agentic version should separate them.

### Recommended collections / stores

#### `ingest_jobs`
One row per discovered source file.

Fields:

- `job_id`
- `source_uri`
- `source_filename`
- `source_hash`
- `status`
- `discovered_at`
- `started_at`
- `completed_at`
- `error_stage`
- `retry_count`

#### `artifacts`
One row per persisted artifact.

Types:

- source-original
- extracted-email-body
- extracted-attachment
- canonical-pdf
- ocr-json
- recommendations-json
- annotated-pdf
- redacted-pdf
- logs

Fields:

- `artifact_id`
- `job_id`
- `parent_artifact_id`
- `artifact_type`
- `storage_uri`
- `mime_type`
- `content_hash`
- `metadata`

#### `document_runs`
Tracks stage-by-stage processing.

Fields:

- `job_id`
- `stage`
- `agent`
- `status`
- `started_at`
- `completed_at`
- `input_artifact_ids`
- `output_artifact_ids`
- `error`
- `attempt`

#### `recommendations`
Normalized redaction candidates.

Fields:

- `recommendation_id`
- `job_id`
- `page`
- `text`
- `bbox`
- `category`
- `reason`
- `confidence`
- `source_agent`
- `source_method`
- `provenance`
- `status` (`proposed`, `accepted`, `rejected`, `uncertain`)

This separation matters because OCR, attachment expansion, and recommendation generation all create large or evolving artifacts.

---

## Orchestration Model

Use a central orchestrator with explicit stage transitions.

### Recommended execution pattern

- Watch folder scanner creates `ingest_job`
- Orchestrator advances job through stages
- Each stage is idempotent and writes output artifacts
- Next stage consumes artifacts from prior stage
- Failures are stage-local and retryable

### Why this is better than free-form agents

For this workload, "agentic" should mean explicit, bounded workers with autonomy inside a stage, not unconstrained autonomous behavior.

This is a document factory, not a chatbot society.

### Good orchestration options

In order of practicality:

1. *Single FastAPI app + background worker loop + Mongo-backed job table*
2. *FastAPI + dedicated worker process + Redis/Mongo queue*
3. *Temporal / Celery / Dramatiq* if reliability requirements grow

My recommendation for v1:

- keep one backend service codebase
- add a dedicated worker runtime
- use Mongo for job state and artifact metadata
- use filesystem or object storage for large binary artifacts

That gives enough reliability without jumping straight to distributed systems overhead.

---

## Folder-Based Hands-Off Flow

### Proposed flow

`watch/` → `quarantine/` → `processing/` → `done/` or `failed/`

#### `watch/`
External drop location.

#### `quarantine/`
File is copied here immediately and assigned a job id.
No processing from the original drop path.

#### `processing/`
Managed workspace for temporary expansion and conversion.

#### `done/`
Contains final outputs:

- annotated PDF
- recommendations JSON
- manifest.json

#### `failed/`
Contains failure manifest and partial logs.

### Why quarantine matters

It prevents:

- processing files while they are still being copied
- accidental double processing
- source changes during processing
- ambiguous ownership of input files

---

## Keep vs Remove

## Keep

- `DocumentProcessingService` as the orchestration seed
- conversion utilities
- OCR extraction pipeline
- PII detection logic
- AI redaction logic
- PyMuPDF redaction and annotation capabilities
- duplicate and email thread logic
- pack-based policy configuration, if simplified

## Refactor

- split `processing_service.py` into stage services
- move OCR payloads out of inline document metadata
- separate artifact storage from document metadata
- make suggestion enrichment its own stage
- replace request/route-driven background tasks with durable job execution

## Remove or isolate

- case-centric domain model from the core pipeline
- user/team role complexity for unattended processing
- workflow module and case queue from the core product
- most frontend case management surfaces

---

## Key Risks and Mitigations

### 1. OCR quality and coordinate fidelity

Risk:

- OCR coordinates may drift from rendered page geometry
- Office-to-PDF conversions can alter text positioning
- email-to-PDF generation may not preserve semantic layout cleanly

Mitigation:

- treat canonical PDF as the source of truth for all coordinate generation
- never generate boxes from pre-conversion text alone
- persist page dimensions and render version metadata
- add confidence levels for coordinate resolution
- store both text span and bbox provenance

### 2. Mongo document bloat

Risk:

- current docs already note truncation at 50 pages / 500K chars
- large OCR structures will break a hands-off high-volume system

Mitigation:

- store OCR JSON and large recommendation payloads as separate artifacts
- keep document metadata records small
- use GridFS or object storage for large JSON and PDFs

### 3. Attachment recursion and explosion

Risk:

- emails with nested emails and attachment chains can fan out dramatically
- zip or embedded-file recursion can become unbounded if added later

Mitigation:

- set explicit recursion depth limits
- enforce per-job artifact count limits
- record parent-child lineage
- allow policy-based skipping for unsupported deep nesting

### 4. Repeat processing / idempotency

Risk:

- folder watchers re-fire
- restarts can re-run jobs
- attachment children can be duplicated

Mitigation:

- key every stage by content hash + stage + config version
- make artifact writes content-addressed where possible
- store stage completion records before advancing
- use source hash and Message-ID together for email dedupe

### 5. Security and privacy

Risk:

- highly sensitive documents and extracted text are being persisted
- LLM calls may exfiltrate protected content
- logs can accidentally capture PII

Mitigation:

- default to local-only processing for OCR and rule detection
- make LLM usage optional and policy-controlled
- redact or hash sensitive text in logs
- encrypt artifact storage at rest if leaving local disk
- define data-retention windows for intermediates
- keep recommendation generation separate from permanent redaction

### 6. Ambiguous recommendation matching

Risk:

- the same text can appear multiple times on a page or across pages
- naive text-to-coordinate matching will place the wrong boxes

Mitigation:

- resolve against page-local word sequences, not plain substring search alone
- include nearby context when matching candidate spans
- if multiple matches remain, mark recommendation as `uncertain`

---

## Recommended Product Shape

## Version 1

A single deployable service with:

- watch-folder intake
- durable job store
- internal worker agents
- artifact store
- thin review UI or filesystem output

### Internal components

- API server
- worker/orchestrator
- Mongo for metadata/jobs
- artifact storage on filesystem or S3-compatible store

### Why not microservices yet

Because the hard part is not horizontal scale. The hard part is artifact integrity.

You want:

- exact lineage
- consistent coordinate systems
- easy retries
- strong privacy boundaries

Those are easier in one codebase with well-separated internal stages than in many services connected by brittle queues.

---

## Incremental Migration Plan

### Phase 1: Extract the document core

Goal:

Create a new "agentic pipeline" module inside the existing backend without breaking current product behavior.

Steps:

1. Refactor `DocumentProcessingService` into explicit stages:
   - validate
   - dedupe
   - expand
   - normalize
   - ocr
   - detect
   - analyze
   - annotate
2. Introduce durable stage records
3. Move OCR payloads into separate artifact storage
4. Keep existing upload API working

### Phase 2: Add folder ingestion

Goal:

Support unattended batch processing from disk.

Steps:

1. Add a watch-folder scanner
2. Create `ingest_jobs` and `artifacts`
3. Copy files into quarantine before processing
4. Emit outputs to `done/` and `failed/`

### Phase 3: Replace case dependency

Goal:

Make processing independent of `case_id`.

Steps:

1. Make `case_id` optional everywhere in the new pipeline
2. Remove case-only assumptions from duplicate logic and document storage
3. Treat each ingestion job as the primary unit of work

### Phase 4: Separate review UI from operations UI

Goal:

Keep only a slim interface for reviewing recommendations and exporting results.

Steps:

1. Create a minimal document review screen
2. Hide or remove queue, contributors, transfer, and internal message features
3. Show provenance and confidence for each recommendation

### Phase 5: Optional externalization

Goal:

Only if needed, split heavy workers later.

Possible splits:

- OCR worker
- LLM policy-analysis worker
- file intake worker

Do this only after stage contracts are stable.

---

## Concrete Reuse Map

### Reuse as-is or nearly as-is

- `backend/src/utils/conversion.py`
- `backend/src/utils/ocr.py`
- `backend/src/utils/pdf_redaction.py`
- `backend/src/utils/email_threads.py`

### Reuse with refactoring

- `backend/src/documents/processing_service.py`
  - split into smaller stage handlers
- `backend/src/utils/ai_redaction.py`
  - separate prompt assembly from execution
  - output stronger provenance metadata
- `backend/src/utils/pii_detection.py`
  - ensure dependency is active and optional by policy

### De-emphasize or retire from core product

- `backend/src/cases/*`
- `backend/src/workflow/*`
- much of `frontend` except a review shell

---

## Opinionated Conclusion

The right move is to turn BlackBar into an *artifact pipeline with agent stages*, not into a swarm of free-roaming agents and not into a case-management app with more automation bolted on.

If you do that, you keep the genuinely valuable parts BlackBar already has:

- robust ingestion
- document normalization
- OCR with coordinates
- hybrid detection
- PDF output capability

And you shed the parts that are getting in the way of the product you actually want:

- human workflow administration
- case operations overhead
- FOI office process management

In practical terms:

- *keep one backend product*
- *make stages explicit and durable*
- *treat artifacts as first-class objects*
- *add watch-folder ingestion*
- *preserve reviewable PDF overlays as the main output*
- *only burn final redactions on explicit request*

That is the cleanest path from BlackBar today to the hands-off agentic redaction system you described.
