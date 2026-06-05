# Data Models

**Status:** Active
**Applies to:** `0.1.x` (post-Phase-1 single-tenant cleanup)

BlackBar persists everything in a single MongoDB database named `blackbar`.
Document binaries (originals and converted PDFs) live in GridFS within
that same database; documents collections only carry references.

This doc maps the production Pydantic models to MongoDB collections.
**There is no `tenant_id` anywhere** — multi-tenancy was removed in
Phase 1 of the OSS prep. ID fields are application-level UUIDs (`id`);
MongoDB's `_id` is never used in application code.

---

## 1. Collections at a glance

| Collection            | Primary model                                       | Source                                      |
|-----------------------|-----------------------------------------------------|---------------------------------------------|
| `users`               | `User`                                              | `backend/src/users/models.py`               |
| `public_users`        | `PublicUser`                                        | `backend/src/public_users/models.py`        |
| `magic_link_tokens`   | `MagicLinkToken`                                    | `backend/src/public_users/models.py`        |
| `cases`               | `CaseDB`                                            | `backend/src/cases/models.py`               |
| `documents`           | document records (mixed-shape dict, see §4)         | `backend/src/documents/models.py` + service |
| `clock_events`        | `ClockEvent`                                        | `backend/src/workflow/models.py`            |
| `case_contributors`   | `CaseContributor`                                   | `backend/src/workflow/models.py`            |
| `case_messages`       | `CaseMessage`                                       | `backend/src/workflow/models.py`            |
| `case_reminders`      | `CaseReminder`                                      | `backend/src/workflow/models.py`            |
| `case_transfers`      | `CaseTransfer`                                      | `backend/src/workflow/models.py`            |
| `release_packages`    | `ReleasePackageDB`                                  | `backend/src/cases/release_package_models.py` |
| `system_config`       | `SystemConfiguration`                               | `backend/src/admin/config_models.py`        |
| `llm_configs`         | `LLMConfig` (API keys Fernet-encrypted)             | `backend/src/llm/models.py`                 |
| `categories`          | request categories                                  | `backend/src/categories/`                   |
| `teams`               | organizational teams                                | `backend/src/teams/`                        |
| `packs`               | jurisdiction packs                                  | `backend/src/packs/`                        |
| `templates`           | letter templates                                    | `backend/src/templates/`                    |

GridFS uses the standard `fs.files` / `fs.chunks` collections.

---

## 2. ER overview

```mermaid
erDiagram
    USER ||--o{ CASE_AUDIT : creates
    USER ||--o{ CASE : created_by
    USER ||--o{ DOCUMENT : uploaded_by
    USER }o--o{ CASE : assigned_to
    USER }o--o{ CASE_TEAM : member_of

    PUBLIC_USER ||--o{ MAGIC_LINK_TOKEN : issued
    PUBLIC_USER ||--o{ CASE : submitted_request

    CASE ||--o{ DOCUMENT : contains
    CASE ||--o{ CLOCK_EVENT : has
    CASE ||--o{ CASE_CONTRIBUTOR : invites
    CASE ||--o{ CASE_MESSAGE : has
    CASE ||--o{ CASE_REMINDER : has
    CASE ||--o{ CASE_TRANSFER : transferred
    CASE ||--o| RELEASE_PACKAGE : releases
    CASE ||--o{ CASE_TEAM : staffed_by
    CASE ||--o{ CASE_AUDIT : has

    DOCUMENT ||--o{ REDACTION : has
    DOCUMENT ||--o{ DOCUMENT : attachment_of
    DOCUMENT }o--|| GRIDFS_FILE : content_file_id
    DOCUMENT }o--o| GRIDFS_FILE : original_file_id

    SYSTEM_CONFIG ||--|| LLM_CONFIG : enables
```

`CASE_TEAM` and `CASE_AUDIT` are embedded arrays on the `cases`
document, not separate collections. `REDACTION` is an embedded array on
the `documents` document. They appear as separate entities here for
clarity.

---

## 3. User models

### `users` — internal staff

```mermaid
erDiagram
    USER {
        string id PK "UUID"
        string email UK
        string name
        string password_hash "bcrypt"
        string role "admin|analyst|user|guest"
        string status "active|disabled|pending_activation"
        string external_id "Reserved for SSO"
        string activation_token "Hashed"
        datetime activation_token_expires_at
        datetime created_at
        datetime updated_at
    }
```

Source: `backend/src/users/models.py`. Roles are stored lowercase. The
`role` field is a flat string (not an enum on the model) but is
validated against `auth/roles.py: AVAILABLE_ROLES`.

### `public_users` — magic-link contributors

```mermaid
erDiagram
    PUBLIC_USER {
        string id PK
        string email UK
        string name
        bool email_verified
        string status "active|suspended"
        datetime created_at
        datetime updated_at
        datetime last_login_at
        list request_ids
    }
    MAGIC_LINK_TOKEN {
        string id PK
        string email
        string token_hash "bcrypt"
        datetime expires_at
        bool used
        datetime created_at
        string ip_address
        string user_agent
    }
    PUBLIC_USER ||--o{ MAGIC_LINK_TOKEN : issued
```

Source: `backend/src/public_users/models.py`. Public users have no
password; they authenticate by clicking single-use magic-link tokens
emailed to them (RFC-007).

---

## 4. Cases and embedded models

```mermaid
erDiagram
    CASE {
        string id PK
        string tracking_number UK "e.g. FOI-2024-001-ABC"
        string title
        string description
        string status "new|in_progress|review|on_hold|completed|closed"
        string priority "low|medium|high"
        string workflow_stage "intake|collection|review|redaction|approval|release|pending_fee_payment|privacy_commission_review|closed"
        string clock_status "running|paused"
        datetime clock_paused_at
        string clock_pause_reason
        int total_paused_days
        datetime adjusted_due_date
        datetime due_date
        datetime extended_due_date
        datetime received_date
        list assigned_user_ids
        string assignee "Primary"
        string privacy_officer_id
        string work_team_id
        list document_ids
        list tags
        json requester
        json metadata
        bool all_records_uploaded
        int priority_override
        string created_by
        datetime created_at
        datetime updated_at
    }
    CASE_TEAM_MEMBER {
        string user_id
        string role "manager|analyst|legal|sme|reviewer|approver|third_party"
        string department
        list permissions
        string status "active|removed"
        string review_status
        string approval_status
        string added_by
        datetime added_at
    }
    CASE_COMMENT {
        string id
        string author_id
        string author_name
        string text
        string type "internal|public"
        datetime created_at
    }
    CASE_AUDIT {
        string action
        string user_id
        string username
        datetime timestamp
        json details
    }
    CASE ||--o{ CASE_TEAM_MEMBER : embedded
    CASE ||--o{ CASE_COMMENT : embedded
    CASE ||--o{ CASE_AUDIT : embedded
```

Source: `backend/src/cases/models.py`. `case_team`, `comments`, and
`audit_log` are stored as embedded arrays on the case document, not as
separate collections.

The `requester` JSON object on a case has shape
`{name, email, phone?, organization?}` (model: `Requester`).

---

## 5. Documents and redactions

The `documents` collection has a richer runtime shape than the slim
`DocumentDB` Pydantic model — `DocumentProcessingService` builds the
record directly as a dict. The effective schema:

```mermaid
erDiagram
    DOCUMENT {
        string id PK
        string filename
        string original_filename
        string content_hash "SHA-256"
        string mime_type
        string original_mime_type
        string converted_mime_type
        int size
        datetime upload_date
        datetime uploaded_at
        datetime updated_at
        string content_file_id "GridFS"
        string original_file_id "GridFS"
        string status "new|under_review|redaction_required|redaction_in_progress|ready_for_approval|approved|released|withheld"
        string processing_status "pending|ocr_complete|ai_queued|ai_processing|ai_complete|ai_timeout|ai_error"
        string conversion_status "converted|not_needed"
        string case_id FK
        string uploaded_by
        string uploaded_by_name
        string uploaded_by_contributor
        string contributor_name
        string collection_link_id
        string submitter_name
        string submitter_email
        string submitter_notes
        bool has_attachments
        list attachment_ids
        int total_attachments
        bool is_attachment
        string parent_document_id
        string message_id "Email RFC 2822"
        json thread_metadata
        string thread_status
        string extracted_text
        json text_data "Word-level coordinates"
        string text_summary
        string summary "LLM-generated"
        json ai_suggestions
        list rejected_ai_suggestions
        list redactions
    }
    REDACTION {
        float x
        float y
        float width
        float height
        int page
        string category "Legacy"
        list sections "e.g. S.22(1), S.14"
        string primary_section
        string rationale
        string description
        string type "professional|proposed"
        string status "approved|proposed|contested|rejected"
        string created_by
        string created_by_role
        string created_at
        string proposed_by
        string proposed_by_role
        string proposed_reason
        string approval_status
        string reviewed_by
        string reviewed_at
        string review_notes
        bool is_contested
        int active_contests
    }
    DOCUMENT ||--o{ REDACTION : embedded
    DOCUMENT ||--o{ DOCUMENT : attachment_of
```

Source: `backend/src/documents/models.py` (`RedactionBox`,
`DocumentStatus`) and the record builder in
`backend/src/documents/processing_service.py:_build_document_record`.

Notes:

- `text_data` is bounded by the service to 50 pages and 500K chars to
  stay under MongoDB's 16 MB document limit; truncation flips a
  `truncated: true` flag.
- Email attachments are stored as separate `DOCUMENT` rows with
  `is_attachment=true` and `parent_document_id` set.
- `ai_suggestions` caches LLM output; coordinates may be enriched
  lazily by the redaction-suggestion router.

---

## 6. Workflow collections

```mermaid
erDiagram
    CASE ||--o{ CLOCK_EVENT : has
    CASE ||--o{ CASE_CONTRIBUTOR : invites
    CASE ||--o{ CASE_MESSAGE : has
    CASE ||--o{ CASE_REMINDER : has
    CASE ||--o{ CASE_TRANSFER : transferred

    CLOCK_EVENT {
        string id PK
        string case_id FK
        string event_type "start|pause|resume|extend"
        string reason "fee_pending|scope_narrowing|third_party_consultation|privacy_commission_review|applicant_request|manual"
        datetime event_date
        string created_by
        string created_by_name
        string notes
        int days_elapsed_at_event
    }
    CASE_CONTRIBUTOR {
        string id PK
        string case_id FK
        string name
        string email
        string department
        string status "invited|active|completed|expired"
        string upload_token "Hashed"
        datetime token_expires_at
        int documents_uploaded
        datetime last_upload_at
        bool records_confirmed
        datetime records_confirmed_at
        string invited_by
        string invited_by_name
        datetime created_at
        datetime first_access_at
        datetime last_access_at
        datetime completed_at
        string notes
    }
    CASE_MESSAGE {
        string id PK
        string case_id FK
        string author_id
        string author_name
        string content
        list mentions
        datetime created_at
        datetime edited_at
    }
    CASE_REMINDER {
        string id PK
        string case_id FK
        string reminder_type "due_date|collection_deadline|fee_pending|review_not_started|package_not_generated|contributor_followup|custom"
        datetime trigger_date
        list recipient_ids
        string message
        string status "pending|sent|dismissed|cancelled"
        datetime sent_at
        list sent_via
        string created_by
        datetime created_at
        string dismissed_by
        datetime dismissed_at
    }
    CASE_TRANSFER {
        string id PK
        string case_id FK
        string tracking_number
        string recipient_organization
        string recipient_email
        string recipient_name
        bool include_documents
        list included_document_ids
        string transfer_reason
        string access_token "Hashed"
        datetime token_expires_at
        string status "pending|accessed|downloaded|expired"
        string transferred_by
        string transferred_by_name
        datetime transferred_at
        datetime accessed_at
        datetime downloaded_at
        string notes
    }
```

Source: `backend/src/workflow/models.py`.

---

## 7. Release packages

```mermaid
erDiagram
    CASE ||--o| RELEASE_PACKAGE : current
    RELEASE_PACKAGE ||--o{ INCLUDED_DOCUMENT : packages
    RELEASE_PACKAGE ||--o{ DOWNLOAD_RECORD : tracks

    RELEASE_PACKAGE {
        string id PK
        string case_id FK
        int version
        string status "generating|draft|released|expired|revoked"
        datetime generated_at
        string generated_by
        datetime released_at
        string released_by
        datetime expires_at
        int max_downloads
        int download_count
        string access_token "Hashed"
        string gridfs_zip_id
        bool include_cover_letter
        string cover_letter_template_id
        string revoke_reason
        datetime revoked_at
        string revoked_by
    }
    INCLUDED_DOCUMENT {
        string document_id
        string filename
        string original_filename
        int page_count
        int redaction_count
        list exemptions
    }
    DOWNLOAD_RECORD {
        datetime downloaded_at
        string ip_address
        string user_agent
        string downloaded_by
    }
```

Source: `backend/src/cases/release_package_models.py`.

---

## 8. System configuration

```mermaid
erDiagram
    SYSTEM_CONFIG {
        string org_name
        string org_logo_url
        string contact_email
        string primary_color "Hex"
        string footer_text
        int default_due_days
        string default_assignee_id
        string default_priority "low|normal|high|urgent"
        int session_timeout_minutes
        int password_min_length
        bool enable_public_requests
        bool enable_request_tracking
        bool enable_public_upload
        list request_categories
        bool auto_generate_ai_suggestions
        datetime updated_at
        string updated_by
    }
    LLM_CONFIG {
        string id PK
        string name
        bool enabled
        string api_endpoint
        string model_name
        string request_format "openai|anthropic|google|cohere|custom"
        string api_key_encrypted "Fernet"
        json default_settings
        json headers
        string notes
        string created_by
        datetime created_at
        datetime updated_at
    }
    SYSTEM_CONFIG ||--o{ LLM_CONFIG : configures
```

Source: `backend/src/admin/config_models.py` and
`backend/src/llm/models.py`. `auto_generate_ai_suggestions` is what
gates the background AI processing in `DocumentProcessingService`.

LLM API keys are encrypted at rest using a Fernet key supplied via the
`LLM_API_KEY_ENCRYPTION_KEY` env var
(`backend/src/llm/encryption.py`).

---

## 9. ID and field conventions

- **Application IDs** are UUID4 strings stored in `id`. All
  cross-collection references use these, never MongoDB's `_id`.
- **Timestamps** are stored as MongoDB `ISODate` (Python `datetime`,
  UTC). Many models default to `datetime.utcnow` at construction.
- **Role values** are always lowercase. User roles
  (`admin/analyst/user/guest`) and case-team roles
  (`manager/analyst/legal/sme/reviewer/approver/third_party`) live in
  separate namespaces.
- **Status enums** are stored as their string values
  (e.g. `"new"`, `"in_progress"`).

---

## 10. Related documentation

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — system overview
- [`DOCUMENT_PROCESSING.md`](DOCUMENT_PROCESSING.md) — how documents
  become records
- [`SECURITY_ARCHITECTURE.md`](SECURITY_ARCHITECTURE.md) — auth + RBAC
  details
- [`../standards/ROLES.md`](../standards/ROLES.md) (Batch 4.5) — full
  user-role vs case-team-role reconciliation
