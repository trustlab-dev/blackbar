# System Overview Diagram

**Status:** Active
**Applies to:** `0.1.x`

A single consolidated Mermaid diagram showing how BlackBar's pieces
fit together. Use this as the visual jumping-off point; the prose
detail lives in the surrounding architecture docs.

For deeper coverage, see:

- [`ARCHITECTURE.md`](ARCHITECTURE.md)
- [`DATA_MODELS.md`](DATA_MODELS.md)
- [`DOCUMENT_PROCESSING.md`](DOCUMENT_PROCESSING.md)
- [`SECURITY_ARCHITECTURE.md`](SECURITY_ARCHITECTURE.md)

---

## Top-level system map

```mermaid
flowchart TB
    subgraph Actors["External actors"]
        Requester[/"FOI requester<br/>(public)"/]
        Contributor[/"Named contributor<br/>(magic-link)"/]
        Staff[/"FOI staff<br/>analyst / user"/]
        Admin[/"Admin"/]
    end

    subgraph Frontend["Frontend (React 18 + TS 5.6 + Vite 5)"]
        Public["Public portal<br/>/request /track<br/>/collect /contribute"]
        App["Authenticated app<br/>/queue /cases /documents"]
        AdminUI["Admin UI<br/>/admin/*"]
        ProtectedRoute["ProtectedRoute<br/>realm + role gate"]
    end

    subgraph Backend["Backend (FastAPI + uvicorn)"]
        direction TB
        Mid["Middleware<br/>CORS / Correlation / Auth"]
        APIv1["/api/v1 router/"]

        subgraph Routers["Sub-routers per concern"]
            AuthR["auth /<br/>magic_link / activation"]
            CaseR["cases (8 sub-routers):<br/>routes / queue / collection_link /<br/>release / team / approval /<br/>public / status"]
            DocR["documents (8 sub-routers):<br/>routes / redaction /<br/>redaction_suggestion /<br/>attachment / document_status /<br/>search / share / contest"]
            WorkflowR["workflow<br/>clock / contributors /<br/>messages / reminders /<br/>transfers / queue"]
            AdminR["admin<br/>config / llm / users"]
            OtherR["categories / teams /<br/>packs / templates"]
        end

        subgraph Services["Services"]
            DPS["DocumentProcessingService<br/>(single upload chokepoint)"]
            Auth["AuthService<br/>PyJWT + bcrypt"]
            MagicLink["MagicLinkService"]
            LLMSvc["LLM client<br/>(OpenAI / Anthropic /<br/>Google / Cohere / custom)"]
        end

        BG["BackgroundTasks<br/>(AI suggestion async)"]
    end

    subgraph Data["Data layer"]
        Mongo[("MongoDB 5<br/>database: blackbar")]
        GridFS[("GridFS<br/>PDFs + originals")]
    end

    subgraph External["External (opt-in)"]
        LLMProv[("LLM provider")]
        SMTP[("SMTP")]
        OTel[("OpenTelemetry collector")]
        Sentry[("Sentry")]
        Prom[("Prometheus scraper")]
    end

    Requester --> Public
    Contributor --> Public
    Staff --> App
    Admin --> AdminUI
    Public --> APIv1
    App --> ProtectedRoute --> APIv1
    AdminUI --> ProtectedRoute

    APIv1 --> Mid --> Routers
    AuthR --> Auth
    AuthR --> MagicLink
    DocR --> DPS
    CaseR --> DPS
    WorkflowR --> DPS
    Routers --> Mongo
    DPS --> Mongo
    DPS --> GridFS
    DPS --> BG
    BG --> LLMSvc
    AdminR --> LLMSvc
    LLMSvc --> LLMProv
    MagicLink --> SMTP
    WorkflowR --> SMTP

    Mid -.-> OTel
    Mid -.-> Sentry
    APIv1 -.-> Prom

    classDef public fill:#e3f2fd
    classDef auth fill:#fff3e0
    classDef data fill:#e8f5e9
    classDef ext fill:#fce4ec
    class Public,Requester,Contributor public
    class Auth,MagicLink,ProtectedRoute auth
    class Mongo,GridFS data
    class LLMProv,SMTP,OTel,Sentry,Prom ext
```

---

## Authentication flow (login + magic link)

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant FE as Frontend
    participant Auth as /api/v1/auth
    participant Mid as AuthMiddleware
    participant DB as MongoDB

    rect rgb(255, 243, 224)
        Note over U,DB: Internal user (password)
        U->>FE: email + password
        FE->>Auth: POST /login
        Auth->>DB: find user by email
        Auth->>Auth: bcrypt.verify(password, hash)
        Auth->>Auth: AuthService.issue_token<br/>(realm = admin | org)
        Auth-->>FE: {token, user}
        FE->>FE: store token in localStorage
    end

    rect rgb(232, 245, 233)
        Note over U,DB: Public user (magic link)
        U->>FE: enter email on /request
        FE->>Auth: POST /auth/public/magic-link
        Auth->>DB: insert magic_link_tokens<br/>(token_hash, expires_at)
        Auth->>U: email with raw token link
        U->>FE: click link
        FE->>Auth: POST /auth/public/verify {token}
        Auth->>DB: lookup token, bcrypt.checkpw
        Auth->>DB: mark used = true
        Auth->>Auth: issue JWT (realm = public)
        Auth-->>FE: {token, public_user}
    end

    rect rgb(243, 229, 245)
        Note over U,DB: Subsequent requests
        U->>FE: action requiring auth
        FE->>Mid: GET /api/v1/... + Bearer token
        Mid->>Mid: validate_token<br/>(decode JWT, check exp)
        Mid->>Mid: attach request.state.user_id<br/>+ request.state.roles
        Mid-->>FE: 200 / 401 INVALID_TOKEN
    end
```

---

## Document processing pipeline

```mermaid
sequenceDiagram
    autonumber
    participant User
    participant Route as Upload route<br/>(documents / collect / contribute)
    participant DPS as DocumentProcessingService
    participant Conv as utils/conversion.py
    participant OCR as PyMuPDF + Tesseract
    participant LLM as LLM client
    participant Mongo as MongoDB
    participant GridFS

    User->>Route: POST file
    Route->>DPS: process_upload(bytes, ctx, background_tasks)

    DPS->>DPS: validate(ext, size, MIME)
    DPS->>DPS: SHA-256 content_hash
    DPS->>Mongo: find duplicate by hash + case_id

    alt duplicate
        DPS-->>Route: DUPLICATE
    else new
        DPS->>Conv: convert_to_pdf<br/>(LibreOffice / EML / MSG / PIL)
        Conv-->>DPS: PDF + extracted attachments

        alt email
            DPS->>Mongo: dedupe by message_id + case_id
        end

        DPS->>OCR: extract_text_with_coordinates(PDF)
        OCR-->>DPS: text_data + summary

        opt auto_generate_ai_suggestions
            DPS->>LLM: generate_document_summary
            LLM-->>DPS: summary
        end

        DPS->>GridFS: put(content) + put(original)
        DPS->>Mongo: insert document record
        loop each attachment
            DPS->>DPS: recurse pipeline
            DPS->>Mongo: insert attachment doc
        end
        opt has case_id
            DPS->>Mongo: $addToSet cases.document_ids
        end
        opt email thread
            DPS->>Mongo: consolidate thread
        end
        opt auto_generate_ai_suggestions AND background_tasks
            DPS->>Mongo: status = ai_queued
            DPS->>DPS: schedule BackgroundTask
        end
        DPS-->>Route: SUCCESS + document_id
    end

    opt background AI
        DPS->>Mongo: status = ai_processing
        DPS->>LLM: get_redaction_suggestions
        LLM-->>DPS: suggestions JSON
        DPS->>DPS: enrich with PDF coordinates
        DPS->>Mongo: cache ai_suggestions<br/>status = ai_complete
    end
```

---

## Public portal flow (magic-link contributor uploads)

```mermaid
sequenceDiagram
    autonumber
    participant Req as Requester
    participant Staff
    participant Contrib as Contributor
    participant FE as Frontend
    participant Pub as Public routes<br/>(no JWT)
    participant Auth as auth/magic_link
    participant Workflow as workflow/routes
    participant DPS as DocumentProcessingService
    participant Mongo

    Req->>FE: fill /request form
    FE->>Pub: POST /api/v1/cases/public/submit
    Pub->>Mongo: insert case<br/>(status = intake, created_by = "system")
    Pub-->>Req: tracking_number

    Staff->>FE: open case → "Invite contributor"
    FE->>Workflow: POST /cases/{id}/contributors<br/>(name, email)
    Workflow->>Mongo: insert case_contributors<br/>(upload_token hash, expires_at)
    Workflow->>Contrib: email magic link<br/>/contribute/{contributor_id}?token=...

    Contrib->>FE: open magic link
    FE->>Pub: GET /contribute/{id} (token in query)
    Pub->>Workflow: ContributorUploadInfo

    Contrib->>FE: upload documents
    FE->>Pub: POST /api/v1/contribute/{id}/upload
    Pub->>DPS: process_upload(ctx.contributor_id = ...)
    DPS->>Mongo: documents + case.document_ids
    DPS-->>FE: SUCCESS

    Contrib->>FE: "All records uploaded"
    FE->>Pub: POST /contribute/{id}/confirm-complete
    Pub->>Mongo: records_confirmed = true,<br/>status = completed
```

---

## Release flow (redaction → release package → download)

```mermaid
stateDiagram-v2
    [*] --> Intake: Case created
    Intake --> Collection: Records being collected
    Collection --> Review: All records uploaded
    Review --> Redaction: Begin redaction
    Redaction --> Approval: Submit for approval
    Approval --> Release: Approved
    Approval --> Redaction: Changes requested

    Release --> Generating: Generate package
    Generating --> Draft: Background task complete
    Draft --> Generating: Regenerate
    Draft --> Released: Click "Release"
    Released --> Expired: token TTL elapsed
    Released --> Revoked: admin revokes

    state Release {
        [*] --> ApplyRedactions
        ApplyRedactions --> ZipPackage: PyMuPDF burn-in
        ZipPackage --> StoreGridFS
        StoreGridFS --> NotifyRequester
    }

    Released --> [*]
    Expired --> [*]
    Revoked --> [*]

    Intake --> PendingFee: fee required
    PendingFee --> Collection: paid
    Review --> PrivacyReview: escalated
    PrivacyReview --> Review: returned
    Intake --> Transferred: transferred to other body
```

---

## Notes

- Diagrams render natively on GitHub. No external rendering or
  `.excalidraw` files are used in this project.
- If a diagram drifts from the source, the source is canonical — open
  an issue or send a doc PR.
