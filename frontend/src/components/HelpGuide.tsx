import React, { useState } from 'react';
import './HelpGuide.css';

// In-app help. Content reviewed for accuracy 2026-05-16 against the
// codebase as-shipped:
//   - 4-tier system role taxonomy (admin / analyst / user / guest) plus
//     the per-case team taxonomy of 7 peer roles
//   - Single-shot AI classification pipeline against the active
//     jurisdiction pack (see docs/api/AI_PROMPT_SYSTEM.md)
//   - Resize + drag-to-move on selected redactions, Esc to deselect
//   - Magic-link auth for public users, demo-mode shortcut for testing
//   - Real troubleshooting entries reflecting the bugs operators have
//     actually hit
// When the surface drifts, update both this file and the linked docs.

const HelpGuide: React.FC = () => {
  const [searchQuery, setSearchQuery] = useState('');
  const [activeSection, setActiveSection] = useState<string>('getting-started');

  // Small reusable accent boxes.
  const tipBox = (text: React.ReactNode) => (
    <p style={{marginTop: '15px', padding: '10px', background: '#f0f7ff', borderLeft: '3px solid #0969da', fontSize: '14px'}}>
      💡 <strong>Tip:</strong> {text}
    </p>
  );
  const warnBox = (text: React.ReactNode) => (
    <p style={{marginTop: '15px', padding: '10px', background: '#fff3cd', borderLeft: '3px solid #ffc107', fontSize: '14px'}}>
      ⚠️ <strong>Note:</strong> {text}
    </p>
  );

  const helpSections = [
    // -----------------------------------------------------------------
    {
      id: 'getting-started',
      title: '🚀 Getting Started',
      content: [
        {
          question: 'What is BlackBar?',
          answer: (
            <div>
              <p>BlackBar is an open-source FOI (Freedom of Information) case-management and document-redaction system, designed for public bodies subject to FOI legislation. It handles the full lifecycle of a request:</p>
              <ul style={{marginLeft: '20px', marginTop: '10px'}}>
                <li>Intake (from a public portal or internal entry)</li>
                <li>Case management, workflow, and team collaboration</li>
                <li>Document upload, OCR, and email-thread consolidation</li>
                <li>Manual and AI-assisted redaction</li>
                <li>Release-package generation and delivery to the requester</li>
              </ul>
              <p style={{marginTop: '15px'}}>BlackBar is shipped with a BC FIPPA jurisdiction pack by default; an Ontario MFIPPA pack is also included. New jurisdictions are added as pack files, not code.</p>
            </div>
          ),
          tags: ['basics', 'overview', 'introduction', 'foi', 'fippa']
        },
        {
          question: 'Two distinct UIs: internal staff vs public requesters',
          answer: (
            <div>
              <p>BlackBar serves two audiences from the same backend:</p>
              <ul style={{marginLeft: '20px', marginTop: '10px'}}>
                <li><strong>Internal staff portal</strong> — login at <code>/login</code> with email + password. Case queue, document viewer, redaction tools, admin.</li>
                <li><strong>Public portal</strong> — login at <code>/public/login</code> via magic link (passwordless). Requesters see only their own cases, status, and any released documents.</li>
              </ul>
              <p style={{marginTop: '10px'}}>The two identity stores (<code>users</code> and <code>public_users</code> in MongoDB) are separate. An internal user account does <em>not</em> let you log into the public side, and vice versa.</p>
              {tipBox(<>An anonymous tracking page is available at <code>/track</code> — requesters can check status with just the tracking number, no login.</>)}
            </div>
          ),
          tags: ['login', 'portal', 'public', 'internal', 'magic-link']
        },
        {
          question: 'Understanding user roles',
          answer: (
            <div>
              <p>BlackBar uses <strong>two independent role taxonomies</strong>. Knowing the difference matters when you can't do something you think you should be able to.</p>
              <p style={{marginTop: '15px'}}><strong>1. System roles (4 tiers — on your user record):</strong></p>
              <ul style={{marginLeft: '20px', marginTop: '5px'}}>
                <li><strong>admin</strong> — full system access: user management, system configuration, LLM configuration, pack management, case deletion</li>
                <li><strong>analyst</strong> — case + document management, redaction, release packages</li>
                <li><strong>user</strong> — limited internal access (basic case viewing, comments)</li>
                <li><strong>guest</strong> — view shared documents only (per-document share grants)</li>
              </ul>
              <p style={{marginTop: '15px'}}><strong>2. Case-team roles (7 peer roles — per case):</strong></p>
              <p style={{marginTop: '5px'}}>Independent of your system role, you can be added to a specific case's team in one of these roles. Each grants different permissions on that single case:</p>
              <ul style={{marginLeft: '20px', marginTop: '5px'}}>
                <li><strong>manager</strong> — coordinates the case, can edit team membership</li>
                <li><strong>analyst</strong> — primary worker on the case (different concept from the system "analyst" role above — name collision)</li>
                <li><strong>legal</strong> — reviews exemptions and privilege calls</li>
                <li><strong>sme</strong> — subject-matter expert; consulted but doesn't redact</li>
                <li><strong>reviewer</strong> — reviews proposed redactions before approval</li>
                <li><strong>approver</strong> — final sign-off on release</li>
                <li><strong>third_party</strong> — outside party notified under FIPPA s.23</li>
              </ul>
              {tipBox(<>The case-team taxonomy is documented in detail at <code>docs/standards/ROLES.md</code> in the repo.</>)}
            </div>
          ),
          tags: ['roles', 'permissions', 'basics', 'admin', 'analyst', 'team', 'taxonomy']
        },
        {
          question: 'Navigating the interface',
          answer: (
            <div>
              <p><strong>Internal staff top nav:</strong></p>
              <ul style={{marginLeft: '20px', marginTop: '10px'}}>
                <li><strong>Cases</strong> — case queue with filters, search, and "all cases" / "my cases" toggle</li>
                <li><strong>New Request</strong> — submit a new case (also accessible to public requesters via the portal)</li>
                <li><strong>Admin</strong> — user management (admins only)</li>
                <li><strong>Configuration</strong> — system + LLM + pack management (admins only)</li>
                <li><strong>Help</strong> — this guide</li>
              </ul>
              <p style={{marginTop: '15px'}}>Your role and username appear in the top-right corner. If a menu item is missing, you don't have the role required to see it.</p>
            </div>
          ),
          tags: ['navigation', 'basics', 'interface', 'menu']
        }
      ]
    },

    // -----------------------------------------------------------------
    {
      id: 'cases',
      title: '📋 Cases & Workflow',
      content: [
        {
          question: 'How do I create a new case?',
          answer: (
            <div>
              <p><strong>Who can do this:</strong> admins and analysts (system role).</p>
              <p style={{marginTop: '10px'}}><strong>Steps:</strong></p>
              <ol style={{marginLeft: '20px', marginTop: '10px'}}>
                <li>Click <strong>New Request</strong> in the top nav.</li>
                <li>Fill in: title (required), category, description, requester details (name, email, phone, organization).</li>
                <li>Submit. A tracking number like <code>FOI-2026-007-DJH</code> is generated and the case lands in the queue with status <strong>New</strong>.</li>
              </ol>
              <p style={{marginTop: '15px'}}>Cases submitted via the public portal at <code>/request</code> end up in the same queue.</p>
              {tipBox(<>The default due date is set by the active jurisdiction pack (BC FIPPA defaults to 30 calendar days under s.7(1)). You can override per case.</>)}
            </div>
          ),
          tags: ['create', 'new case', 'analyst', 'request', 'intake']
        },
        {
          question: 'What do the case statuses mean?',
          answer: (
            <ul style={{marginLeft: '20px'}}>
              <li><strong>new</strong> — received, not yet started</li>
              <li><strong>in_progress</strong> — actively being worked</li>
              <li><strong>review</strong> — pending review/approval</li>
              <li><strong>on_hold</strong> — paused (waiting on requester, third-party notification, etc.)</li>
              <li><strong>completed</strong> — finished, released to requester</li>
              <li><strong>closed</strong> — archived</li>
            </ul>
          ),
          tags: ['status', 'workflow', 'cases']
        },
        {
          question: 'Adding people to a case team',
          answer: (
            <div>
              <p>Open the case, scroll to the <strong>Case Team</strong> panel. Click <strong>Add Member</strong>, pick an existing internal user, and assign one of the 7 case-team roles (manager / analyst / legal / sme / reviewer / approver / third_party).</p>
              <p style={{marginTop: '10px'}}>Permissions on this case follow the case-team role, not the user's system role. Example: a system <strong>user</strong> added as case-team <strong>analyst</strong> gets full redaction permissions on that single case.</p>
              {warnBox(<>The case-team <strong>analyst</strong> role and the system <strong>analyst</strong> role share a name but mean different things. See <code>docs/standards/ROLES.md</code> for the distinction.</>)}
            </div>
          ),
          tags: ['team', 'case-team', 'collaboration', 'permissions']
        },
        {
          question: 'Tracking SLA / due dates',
          answer: (
            <div>
              <p>Each case has a <strong>due date</strong> set from the active jurisdiction pack's response window (30 calendar days for BC FIPPA s.7(1)). SLA status surfaces in the queue as on-track / approaching / overdue.</p>
              <p style={{marginTop: '10px'}}>Extensions can be granted under the legislation (e.g. FIPPA s.10(1)(a)-(d): insufficient detail, large volume, consultation, applicant consent). Longer than 30 days requires Commissioner permission under s.10(1.1).</p>
            </div>
          ),
          tags: ['sla', 'due date', 'extension', 'fippa']
        }
      ]
    },

    // -----------------------------------------------------------------
    {
      id: 'documents',
      title: '📄 Documents & Upload',
      content: [
        {
          question: 'How do I upload documents?',
          answer: (
            <div>
              <p><strong>Who can do this:</strong> admins, analysts (system role), and users with case-team roles that grant upload permission.</p>
              <p style={{marginTop: '10px'}}><strong>Steps:</strong></p>
              <ol style={{marginLeft: '20px', marginTop: '10px'}}>
                <li>Open a case.</li>
                <li>Go to the <strong>Documents</strong> tab.</li>
                <li>Click <strong>Upload Document</strong> or drag-and-drop files into the upload area.</li>
                <li>The backend converts to PDF, runs OCR if needed, and (when enabled) generates AI redaction suggestions in the background.</li>
              </ol>
              <p style={{marginTop: '15px'}}><strong>Supported formats:</strong></p>
              <ul style={{marginLeft: '20px'}}>
                <li>PDF (renders directly)</li>
                <li>Word: <code>.doc</code>, <code>.docx</code></li>
                <li>Excel: <code>.xls</code>, <code>.xlsx</code></li>
                <li>Email: <code>.eml</code>, <code>.msg</code> (with attachments auto-extracted)</li>
                <li>Images (JPG, PNG, TIFF) — OCR'd to extract text</li>
                <li>Plain text, RTF</li>
              </ul>
              {tipBox(<>Multi-message email threads with proper <code>Message-ID</code>/<code>In-Reply-To</code> headers get consolidated into a single conversation by the email-thread service.</>)}
            </div>
          ),
          tags: ['upload', 'documents', 'files', 'pdf', 'docx', 'eml', 'ocr']
        },
        {
          question: 'How does OCR work?',
          answer: (
            <div>
              <p>BlackBar uses <strong>PyMuPDF</strong> for native PDF text extraction and falls back to <strong>Tesseract OCR</strong> for scanned/image-based PDFs. Office documents are converted to PDF via <strong>LibreOffice</strong> first, then text-extracted.</p>
              <p style={{marginTop: '10px'}}>Word-level bounding boxes are captured so manual and AI redactions can land on exact text — not just whole lines or paragraphs.</p>
              {warnBox(<>Scanned documents with poor image quality may produce noisy OCR text. AI suggestions on those documents will be less accurate; manual review is more important.</>)}
            </div>
          ),
          tags: ['ocr', 'pymupdf', 'tesseract', 'scanned']
        },
        {
          question: 'Email-thread consolidation',
          answer: (
            <div>
              <p>When you upload multiple <code>.eml</code> or <code>.msg</code> files that share a thread (via <code>Message-ID</code> / <code>In-Reply-To</code> / <code>References</code> headers), BlackBar consolidates them into one canonical thread with the older messages marked <strong>superseded</strong>.</p>
              <p style={{marginTop: '10px'}}>Attachments in those emails are auto-extracted and stored as separate documents, linked to their parent email via <code>parent_document_id</code>.</p>
            </div>
          ),
          tags: ['email', 'thread', 'consolidation', 'attachments']
        }
      ]
    },

    // -----------------------------------------------------------------
    {
      id: 'redaction',
      title: '✏️ Redaction Tools',
      content: [
        {
          question: 'Drawing a redaction manually',
          answer: (
            <div>
              <ol style={{marginLeft: '20px', marginTop: '10px'}}>
                <li>Open a document in the viewer.</li>
                <li>Click <strong>Draw</strong> in the left tool rail (or use the <strong>Select</strong> tool and drag over text — auto-snaps to word boundaries).</li>
                <li>Draw a box over the content. A category picker opens for you to pick the exemption section (S22, S13, S14, etc.) and add an optional reason note.</li>
                <li>Save. The box turns solid blue (or solid black if preview-mode is off).</li>
              </ol>
            </div>
          ),
          tags: ['manual', 'draw', 'redaction']
        },
        {
          question: 'Selecting, resizing, and moving redactions',
          answer: (
            <div>
              <p><strong>Click</strong> a redaction box to select it. You get:</p>
              <ul style={{marginLeft: '20px', marginTop: '10px'}}>
                <li><strong>8 resize handles</strong> at the corners and edges (cursor changes to the resize direction)</li>
                <li><strong>Drag-to-move</strong> by grabbing the body of the box (cursor changes to <code>move</code>)</li>
                <li>An <strong>action menu</strong> at the click point with Edit / Delete options</li>
              </ul>
              <p style={{marginTop: '15px'}}><strong>Keyboard:</strong></p>
              <ul style={{marginLeft: '20px'}}>
                <li><strong>Esc</strong> — close the action menu (selection persists)</li>
                <li><strong>Esc again</strong> — deselect the box (handles disappear)</li>
              </ul>
              {tipBox(<>If the resize handles are covered by the action menu, press Esc once to close the menu — the box stays selected so you can grab the handles.</>)}
            </div>
          ),
          tags: ['resize', 'drag', 'move', 'select', 'esc', 'handles']
        },
        {
          question: 'Reason categories & exemption sections',
          answer: (
            <div>
              <p>Every redaction needs a <strong>category</strong> (exemption section) plus an optional <strong>reason note</strong>. Categories come from the active jurisdiction pack. For BC FIPPA:</p>
              <ul style={{marginLeft: '20px', marginTop: '10px'}}>
                <li><strong>S12</strong> — Cabinet/local public body confidences</li>
                <li><strong>S13</strong> — Policy advice or recommendations</li>
                <li><strong>S14</strong> — Legal advice (solicitor-client privilege)</li>
                <li><strong>S15-19, S21</strong> — Harm-based exemptions (law enforcement, intergovernmental, financial, third-party business)</li>
                <li><strong>S22</strong> — Unreasonable invasion of personal privacy</li>
                <li><strong>S22.1</strong> — Abortion services identifying information</li>
              </ul>
              <p style={{marginTop: '15px'}}>The reason note shows up in the audit trail and helps with FOI office reviews + applicant appeals.</p>
            </div>
          ),
          tags: ['category', 'reason', 'exemption', 'fippa', 's22', 's13']
        },
        {
          question: 'Approval workflow on redactions',
          answer: (
            <div>
              <p>By default, redactions move through:</p>
              <ol style={{marginLeft: '20px', marginTop: '10px'}}>
                <li><strong>pending</strong> — drafted by an analyst</li>
                <li><strong>proposed</strong> — submitted for review</li>
                <li><strong>approved</strong> — signed off by a reviewer/approver</li>
                <li><strong>applied</strong> — burned into the final PDF at release</li>
              </ol>
              <p style={{marginTop: '15px'}}>Reviewers and approvers can also <strong>contest</strong> a redaction or <strong>reject</strong> it with a reason. The contest history is preserved on the document.</p>
            </div>
          ),
          tags: ['approval', 'review', 'workflow', 'contest', 'reject']
        }
      ]
    },

    // -----------------------------------------------------------------
    {
      id: 'ai-suggestions',
      title: '🤖 AI Suggestions',
      content: [
        {
          question: 'How AI suggestions work',
          answer: (
            <div>
              <p>BlackBar runs <strong>one LLM call per document</strong>, using the active jurisdiction pack's prompt. The default for any candidate is <em>disclosure</em> — the AI is calibrated to err on the side of NOT redacting. You should still review every suggestion.</p>
              <p style={{marginTop: '10px'}}><strong>To generate suggestions:</strong></p>
              <ol style={{marginLeft: '20px'}}>
                <li>Open a document in the viewer.</li>
                <li>Click the <strong>Auto Suggest</strong> button (sparkle icon) on the right edge.</li>
                <li>Pick the <strong>AI Recommended</strong> tab.</li>
                <li>Click <strong>Generate AI Suggestions</strong>. Takes ~10-25 seconds depending on provider and document length.</li>
              </ol>
              <p style={{marginTop: '15px'}}>Suggestions are cached per document. The list survives reloads.</p>
              {warnBox(<>An LLM provider must be configured and marked as default before this works. See the LLM Configuration section.</>)}
            </div>
          ),
          tags: ['ai', 'suggestions', 'llm', 'auto-suggest']
        },
        {
          question: 'Generate vs Regenerate',
          answer: (
            <div>
              <ul style={{marginLeft: '20px'}}>
                <li><strong>Generate AI Suggestions</strong> — first call on a document. Uses the cache if present (so this is free on re-open).</li>
                <li><strong>Regenerate</strong> — bypasses the cache and makes a fresh LLM call. Use this after a pack/prompt update.</li>
              </ul>
            </div>
          ),
          tags: ['regenerate', 'cache', 'ai']
        },
        {
          question: 'Reading a suggestion (the "Why" expander)',
          answer: (
            <div>
              <p>Each row in the AI tab shows:</p>
              <ul style={{marginLeft: '20px', marginTop: '10px'}}>
                <li><strong>Text</strong> the AI proposes to redact (truncated to ~60 chars)</li>
                <li><strong>Confidence chip</strong> (high / medium / low)</li>
                <li><strong>Section line</strong> like <code>s.22(3)(a)</code> with a brief reason</li>
              </ul>
              <p style={{marginTop: '15px'}}>Click <strong>Why</strong> under any suggestion to see the AI's structured reasoning:</p>
              <ul style={{marginLeft: '20px'}}>
                <li><strong>Reasoning</strong> — step-by-step cascade the AI walked through</li>
                <li><strong>Harm identified</strong> — for harm-based exemptions (s.15, s.17, s.21)</li>
                <li><strong>Severance</strong> — why the AI picked this exact span</li>
                <li><strong>Exceptions considered</strong> — s.22(4)(e), s.13(2)(a), etc. the AI weighed against the redaction</li>
              </ul>
              {tipBox(<>If a suggestion looks wrong, the Why expander usually tells you which rule the AI misapplied. Reject it and, if it's recurring, the pack prompt may need tightening.</>)}
            </div>
          ),
          tags: ['why', 'reasoning', 'ai', 'section', 'subsection']
        },
        {
          question: 'What do the badges mean?',
          answer: (
            <div>
              <ul style={{marginLeft: '20px'}}>
                <li><strong>Review</strong> (orange) — the pack flagged this for mandatory human review (low confidence, s.21 third-party items requiring s.23 notification, or items where multiple exemptions were considered).</li>
                <li><strong>s.25?</strong> (purple) — the AI flagged this for public-interest override consideration. Even if the exemption applies, you may need to release under s.25 if the content relates to public safety, environmental harm, or significant accountability matters.</li>
              </ul>
            </div>
          ),
          tags: ['badge', 'review', 's25', 'public interest', 'override']
        },
        {
          question: 'Accept, reject, bulk operations',
          answer: (
            <div>
              <ul style={{marginLeft: '20px'}}>
                <li><strong>Accept</strong> — applies the suggestion as a redaction on the page.</li>
                <li><strong>Reject</strong> — drops the suggestion. It won't surface again on this document (stored in <code>rejected_ai_suggestions</code>).</li>
                <li><strong>Bulk Accept Filtered / Bulk Reject Filtered</strong> — apply to every suggestion matching the current page/category filter.</li>
              </ul>
              <p style={{marginTop: '15px'}}>The <strong>Quick PII</strong> tab is a separate, pattern-matched (no LLM) detection for things like emails, phone numbers, postal codes, and government IDs. Fast and deterministic but only catches things that match a regex.</p>
            </div>
          ),
          tags: ['accept', 'reject', 'bulk', 'quick-pii']
        }
      ]
    },

    // -----------------------------------------------------------------
    {
      id: 'llm-config',
      title: '🔌 LLM Configuration',
      content: [
        {
          question: 'Add an LLM provider (admins)',
          answer: (
            <div>
              <p><strong>Who:</strong> admins only.</p>
              <p style={{marginTop: '10px'}}><strong>Steps:</strong></p>
              <ol style={{marginLeft: '20px'}}>
                <li>Admin → <strong>LLM Configuration</strong>.</li>
                <li>Click <strong>Add LLM</strong>.</li>
                <li>Pick the request format (OpenAI / Anthropic / Google / Cohere).</li>
                <li>Enter the API endpoint, API key, and model name (e.g. <code>gpt-4o-mini</code>, <code>claude-3-5-sonnet-latest</code>).</li>
                <li>Save.</li>
              </ol>
              <p style={{marginTop: '15px'}}>The first enabled config you create is <strong>auto-promoted to default</strong>. Subsequent configs are added but don't displace the default — click <strong>Set Default</strong> on a row to switch.</p>
              {tipBox(<>API keys are encrypted at rest with Fernet using the <code>LLM_API_KEY_ENCRYPTION_KEY</code> env var.</>)}
            </div>
          ),
          tags: ['llm', 'provider', 'openai', 'anthropic', 'admin', 'config']
        },
        {
          question: 'Testing a provider',
          answer: (
            <div>
              <p>Each row in the LLM Configuration list has a <strong>Test</strong> button (play icon). Clicking it sends a short test prompt to the configured provider and reports success / failure + latency.</p>
              <p style={{marginTop: '10px'}}>If you see <em>"Connection failed (1.37s): Client error '404 Not Found'"</em>, the model name is wrong — common cause is a retired model identifier like <code>gpt-4-turbo-preview</code>. Use a current name.</p>
            </div>
          ),
          tags: ['test', 'llm', 'connection', 'model']
        },
        {
          question: 'Why "AI redaction suggestions unavailable - no default LLM is set"',
          answer: (
            <div>
              <p>You created an LLM config but never marked one as the default. Admin → LLM Configuration → click <strong>Set Default</strong> on an enabled row.</p>
              <p style={{marginTop: '10px'}}>The first enabled config you create is auto-promoted, so this only bites you if you create a disabled config first, or delete and replace your default.</p>
            </div>
          ),
          tags: ['llm', 'default', 'error', 'not configured', 'troubleshooting']
        },
        {
          question: 'Switching jurisdictions / editing the pack',
          answer: (
            <div>
              <p>Active pack is set in <code>src/packs/loader.py</code> (default: <code>bc-fippa-v1</code>). Packs live at <code>backend/packs/*.json</code>.</p>
              <p style={{marginTop: '10px'}}>Pack content covers: exemption categories, interpretation rules, AI prompts, fee schedule, response templates. The current pack uses a structured prompt with a STEP 0 record-type framing, explicit allow/deny lists, and a forbidden-reasoning catalogue.</p>
              <p style={{marginTop: '10px'}}>Full pack-structure details: <code>docs/api/AI_PROMPT_SYSTEM.md</code>.</p>
              {warnBox(<>After editing a pack JSON, restart the backend (<code>docker compose restart backend</code>) — the active pack is cached at module load. Then use <strong>Regenerate</strong> in the viewer to re-run AI on docs that already have cached suggestions.</>)}
            </div>
          ),
          tags: ['pack', 'jurisdiction', 'prompt', 'bc fippa', 'mfippa']
        }
      ]
    },

    // -----------------------------------------------------------------
    {
      id: 'public-portal',
      title: '🌐 Public Portal',
      content: [
        {
          question: 'How a requester submits an FOI request',
          answer: (
            <div>
              <p>Anyone can visit <code>/request</code> (no login) and submit a request. The form collects:</p>
              <ul style={{marginLeft: '20px', marginTop: '10px'}}>
                <li>Request title + description + category</li>
                <li>Requester contact details (name, email, phone, organization)</li>
              </ul>
              <p style={{marginTop: '10px'}}>On submission they get a tracking number (e.g. <code>FOI-2026-007-DJH</code>) and an email confirmation (when SendGrid is configured).</p>
            </div>
          ),
          tags: ['public', 'request', 'intake', 'submit']
        },
        {
          question: 'How a requester tracks a request',
          answer: (
            <div>
              <p>Two ways:</p>
              <ul style={{marginLeft: '20px', marginTop: '10px'}}>
                <li><strong>Anonymous tracking</strong> at <code>/track</code> — enter the tracking number, see status + due date + public comments. No login.</li>
                <li><strong>Authenticated dashboard</strong> at <code>/public/login</code> — log in via magic link (passwordless email auth). See all requests submitted under your email, with full timeline and downloadable release packages.</li>
              </ul>
            </div>
          ),
          tags: ['track', 'public', 'dashboard', 'magic link']
        },
        {
          question: 'Magic-link authentication (no password)',
          answer: (
            <div>
              <p>Public users authenticate by entering their email at <code>/public/login</code>. The backend emails a single-use link valid for 15 minutes. Clicking the link exchanges the token for a JWT in the <code>public</code> realm.</p>
              <p style={{marginTop: '10px'}}>Rate-limited to 3 requests per email per hour (configurable via <code>MAGIC_LINK_RATE_LIMIT_MAX</code> / <code>MAGIC_LINK_RATE_LIMIT_HOURS</code>).</p>
              {warnBox(<>Magic-link email delivery requires SendGrid to be configured. Without it, tokens are created in the DB but never sent — see the demo-login workaround below.</>)}
            </div>
          ),
          tags: ['magic link', 'public', 'auth', 'sendgrid']
        },
        {
          question: 'Demo mode — "Log in as Jordan Park"',
          answer: (
            <div>
              <p>When <code>BLACKBAR_DEMO_MODE=true</code> is set in <code>.env</code>, the public login page (<code>/public/login</code>) shows an amber <strong>DEMO MODE</strong> panel with a <strong>Log in as Jordan Park (demo)</strong> button. One click logs you in as the demo persona without going through magic-link emails — useful for local development, demos, and screenshots.</p>
              <p style={{marginTop: '10px'}}>The endpoint behind the button (<code>POST /api/v1/auth/public/demo-login</code>) returns 404 when the env var is off, so the route effectively doesn't exist in production deployments.</p>
              <p style={{marginTop: '10px'}}>Jordan Park matches the requester on the bundled TrustLab demo case (<code>FOI-2026-007-DJH</code>), so clicking through to the dashboard immediately shows real-looking content.</p>
              {tipBox(<><code>setup.sh</code> auto-enables this when you opt into seeding the TrustLab demo case.</>)}
            </div>
          ),
          tags: ['demo', 'jordan park', 'public', 'env', 'dev']
        },
        {
          question: 'Contributor uploads',
          answer: (
            <div>
              <p>Sometimes an FOI requester or third party needs to upload supporting documents. Internal staff can issue a <strong>contributor link</strong> from the case view — a tokenised URL valid for a configurable period (default 14 days).</p>
              <p style={{marginTop: '10px'}}>The recipient visits the URL (no login needed), uploads documents, and they land directly on the case linked to that contributor. The contributor's name is recorded on each upload.</p>
            </div>
          ),
          tags: ['contributor', 'upload', 'public']
        }
      ]
    },

    // -----------------------------------------------------------------
    {
      id: 'release',
      title: '📦 Release Packages',
      content: [
        {
          question: 'When can I release?',
          answer: (
            <div>
              <p>Practical checklist before generating a release package:</p>
              <ul style={{marginLeft: '20px', marginTop: '10px'}}>
                <li>All relevant documents are uploaded.</li>
                <li>Each document has been reviewed and any required redactions are approved.</li>
                <li>The case workflow has moved through <strong>review</strong> and any case-team approvers have signed off.</li>
                <li>If the case includes third-party records, s.23 notification has been served and any objection period has elapsed.</li>
              </ul>
            </div>
          ),
          tags: ['release', 'workflow', 'approval', 's23']
        },
        {
          question: 'Generating a release package',
          answer: (
            <div>
              <ol style={{marginLeft: '20px', marginTop: '10px'}}>
                <li>Open the case.</li>
                <li>Click <strong>Generate Release Package</strong> in the case actions.</li>
                <li>The system applies all approved redactions permanently to copies of the PDFs, optionally generates a cover letter from the pack's template, and bundles everything into a ZIP.</li>
                <li>The package is recorded with a unique access token, an expiry date, and an optional download limit.</li>
              </ol>
            </div>
          ),
          tags: ['release', 'package', 'export', 'zip']
        },
        {
          question: 'Requester downloading the release',
          answer: (
            <div>
              <p>Released packages appear on the requester's <strong>public dashboard</strong> under the relevant case, with a download button. Each download is counted; once the configured limit is reached the link stops working.</p>
              <p style={{marginTop: '10px'}}>Packages can be released with or without a download limit, and with an expiry date — both configured when generating.</p>
            </div>
          ),
          tags: ['release', 'download', 'public', 'requester']
        }
      ]
    },

    // -----------------------------------------------------------------
    {
      id: 'admin',
      title: '⚙️ Admin & System Config',
      content: [
        {
          question: 'Creating internal users',
          answer: (
            <div>
              <p><strong>Who:</strong> admins only.</p>
              <p style={{marginTop: '10px'}}>Admin → <strong>User Management</strong> → <strong>Create New User</strong>. Fill in email, name, password, and assign one of the 4 system roles (admin / analyst / user / guest). The new user can log in immediately.</p>
              <p style={{marginTop: '10px'}}>To set the case-team role for a specific case, add the user to that case's team from the case view.</p>
            </div>
          ),
          tags: ['admin', 'users', 'create', 'roles']
        },
        {
          question: 'Organization branding',
          answer: (
            <div>
              <p>Admin → <strong>Configuration</strong> → <strong>Organization Branding</strong>. Set the org name, logo URL, primary brand colour, contact email, and footer text. These show up on the public portal landing page, the public login page, and the requester dashboard.</p>
            </div>
          ),
          tags: ['branding', 'config', 'public', 'org name', 'logo']
        },
        {
          question: 'System configuration',
          answer: (
            <div>
              <p>Admin → <strong>Configuration</strong> covers:</p>
              <ul style={{marginLeft: '20px', marginTop: '10px'}}>
                <li>Default response window (calendar days)</li>
                <li>Default priority</li>
                <li>Public-portal toggles (enable public requests, enable tracking, enable public upload)</li>
                <li>Request categories shown on the public form</li>
                <li>Auto-generate AI suggestions on upload (off by default — turning it on incurs LLM cost on every upload)</li>
              </ul>
            </div>
          ),
          tags: ['config', 'system', 'admin']
        }
      ]
    },

    // -----------------------------------------------------------------
    {
      id: 'troubleshooting',
      title: '🔧 Troubleshooting',
      content: [
        {
          question: '"AI redaction suggestions unavailable - no default LLM is set"',
          answer: (
            <div>
              <p>The AI codepath needs an LLM config flagged as the global default. Admin → <strong>LLM Configuration</strong> → click <strong>Set Default</strong> on an enabled row.</p>
              <p style={{marginTop: '10px'}}>The first enabled config is auto-promoted, so this typically only happens after you delete + recreate a config.</p>
            </div>
          ),
          tags: ['llm', 'error', 'configuration', 'default']
        },
        {
          question: 'Suggestions stay stale after editing a pack',
          answer: (
            <div>
              <ul style={{marginLeft: '20px'}}>
                <li>Restart the backend (<code>docker compose restart backend</code>) — the active pack is cached at module load.</li>
                <li>Click <strong>Regenerate</strong> (not Generate) — Generate may return cached suggestions; Regenerate always re-calls the LLM.</li>
              </ul>
            </div>
          ),
          tags: ['pack', 'cache', 'regenerate', 'stale']
        },
        {
          question: 'Resize handles on a redaction don\'t respond',
          answer: (
            <div>
              <p>The action menu that opens on click can cover the handles. Press <strong>Esc</strong> once to close the menu — the box stays selected, the handles become reachable. Press Esc again to deselect entirely.</p>
            </div>
          ),
          tags: ['redaction', 'resize', 'handles', 'esc']
        },
        {
          question: 'Upload fails with 422 / "file missing"',
          answer: (
            <div>
              <p>Usually means the frontend sent the wrong <code>Content-Type</code>. If you're hitting this on a clean install, check that the axios client (<code>frontend/src/api/client.ts</code>) isn't setting a global <code>Content-Type</code> default — that breaks multipart form data.</p>
              <p style={{marginTop: '10px'}}>If you wrote a custom upload helper, make sure it lets axios derive the multipart Content-Type from the FormData body (don't set it manually).</p>
            </div>
          ),
          tags: ['upload', 'error', '422', 'content-type']
        },
        {
          question: '"Submitted: December 31, 1969" on the public dashboard',
          answer: (
            <div>
              <p>A historical bug: cases created via the authenticated API didn't have <code>created_at</code> set, so the frontend got <code>null</code> and <code>new Date(null)</code> returns Unix epoch.</p>
              <p style={{marginTop: '10px'}}>Fixed in commit <code>5bbb51f</code>: new cases write <code>created_at</code> properly, and <code>scripts/migrate_dates_to_bson.py</code> backfills old cases from their MongoDB <code>_id</code> timestamp. If you see this on existing data, run the migration.</p>
            </div>
          ),
          tags: ['date', '1969', 'submitted', 'epoch', 'migration']
        },
        {
          question: '403 Forbidden errors',
          answer: (
            <div>
              <p>You don't have the role required for that action. Common causes:</p>
              <ul style={{marginLeft: '20px', marginTop: '10px'}}>
                <li>Trying to access admin features without the system <strong>admin</strong> role.</li>
                <li>Trying to perform a case-specific action you're not in the right case-team role for (the case-team role is independent of your system role).</li>
                <li>JWT expired — log out and back in.</li>
              </ul>
            </div>
          ),
          tags: ['403', 'forbidden', 'permissions', 'roles']
        },
        {
          question: 'Demo-login button doesn\'t appear on /public/login',
          answer: (
            <div>
              <p>Check <code>.env</code> — <code>BLACKBAR_DEMO_MODE</code> must be set to <code>true</code> (the literal string). Restart the backend after changing the env var so the change takes effect.</p>
            </div>
          ),
          tags: ['demo', 'public', 'env', 'login']
        }
      ]
    }
  ];

  const filteredSections = helpSections.map(section => ({
    ...section,
    content: section.content.filter(item => {
      if (!searchQuery) return true;
      const query = searchQuery.toLowerCase();
      return (
        item.question.toLowerCase().includes(query) ||
        item.tags.some(tag => tag.toLowerCase().includes(query)) ||
        (typeof item.answer === 'string' && item.answer.toLowerCase().includes(query))
      );
    })
  })).filter(section => section.content.length > 0);

  return (
    <div className="help-guide-container">
      <div className="help-header">
        <h1>📚 BlackBar Help Guide</h1>
        <p style={{color: '#586069', marginTop: '10px'}}>Reviewed for accuracy 2026-05-16</p>
      </div>

      {/* Search */}
      <div className="help-search">
        <input
          type="text"
          placeholder="Search help articles..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          style={{
            width: '100%',
            padding: '12px 16px',
            fontSize: '16px',
            border: '2px solid #d1d5da',
            borderRadius: '6px',
            outline: 'none'
          }}
        />
      </div>

      {/* Section Navigation */}
      <div className="help-nav" style={{
        display: 'flex',
        justifyContent: 'center',
        flexWrap: 'wrap',
        gap: '8px',
        marginBottom: '30px'
      }}>
        {helpSections.map(section => (
          <button
            key={section.id}
            onClick={() => setActiveSection(section.id)}
            className={activeSection === section.id ? 'active' : ''}
            style={{
              padding: '10px 16px',
              border: activeSection === section.id ? '2px solid #0366d6' : '1px solid #d1d5da',
              background: activeSection === section.id ? '#f0f7ff' : 'white',
              color: activeSection === section.id ? '#0366d6' : '#24292e',
              borderRadius: '6px',
              cursor: 'pointer',
              fontSize: '14px',
              fontWeight: activeSection === section.id ? '600' : '400'
            }}
          >
            {section.title}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="help-content">
        {filteredSections.map(section => (
          <div key={section.id} style={{display: activeSection === section.id ? 'block' : 'none'}}>
            <h2 style={{fontSize: '24px', marginBottom: '20px', color: '#24292e'}}>{section.title}</h2>
            {section.content.map((item, index) => (
              <div key={index} style={{
                marginBottom: '30px',
                padding: '20px',
                background: 'white',
                border: '1px solid #d1d5da',
                borderRadius: '6px'
              }}>
                <h3 style={{fontSize: '18px', marginBottom: '15px', color: '#24292e'}}>{item.question}</h3>
                <div style={{color: '#586069', lineHeight: '1.6'}}>
                  {typeof item.answer === 'string' ? <p>{item.answer}</p> : item.answer}
                </div>
                <div style={{marginTop: '15px'}}>
                  {item.tags.map(tag => (
                    <span key={tag} style={{
                      display: 'inline-block',
                      padding: '4px 8px',
                      margin: '4px 4px 0 0',
                      background: '#f6f8fa',
                      border: '1px solid #d1d5da',
                      borderRadius: '12px',
                      fontSize: '12px',
                      color: '#586069'
                    }}>
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ))}

        {filteredSections.length === 0 && (
          <div style={{textAlign: 'center', padding: '60px 20px', color: '#586069'}}>
            <div style={{fontSize: '48px', marginBottom: '20px'}}>🔍</div>
            <h3>No results found</h3>
            <p style={{marginTop: '10px'}}>Try a different search term or browse the sections above.</p>
          </div>
        )}
      </div>

      {/* Footer */}
      <div style={{
        marginTop: '40px',
        padding: '20px',
        background: '#f6f8fa',
        borderRadius: '6px',
        textAlign: 'center'
      }}>
        <p style={{color: '#586069', fontSize: '14px'}}>
          Need more detail? See the project docs in the repo: <code>docs/</code>, especially{' '}
          <code>docs/api/AI_PROMPT_SYSTEM.md</code>, <code>docs/guides/SUGGESTION_OVERLAY_GUIDE.md</code>,
          and <code>docs/architecture/ARCHITECTURE.md</code>.
        </p>
      </div>
    </div>
  );
};

export default HelpGuide;
