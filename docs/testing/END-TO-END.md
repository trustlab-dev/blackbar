# BlackBar End-to-End Testing Checklist

> **Date**: _______________
> **Tester**: _______________
> **Environment**: ☐ Local ☐ Staging ☐ Production

> ⚠️ **Stale content notice:** Sections describing Tenant Management (create/edit/suspend/delete tenants), tenant subdomain routing, and multi-tenant isolation tests describe flows that no longer exist post single-tenant cleanup. A rewrite to match the current single-instance UI is scheduled alongside the testing-guide overhaul in Task 1.16.

---

## 1. Global Admin Portal (`admin.blackbar.app`)

### 1.1 Authentication
- [X] Login to Global Admin portal
- [X] Logout from Global Admin portal
- [x] tenant users cannot log in to global admin

### 1.2 Tenant Management
- [X] View tenant list/dashboard
- [X] Create new tenant (name, slug, owner email, owner name)
- [X] Verify tenant owner receives welcome email
- [X] View tenant detail page
- [X] Edit tenant details - confirmed flows through to tenant
- [ ] Suspend/Activate tenant (function doesn't exist)
- [X] Delete tenant (cleanup test only)

### 1.3 LLM Configuration
- [X] View LLM configuration page
- [X] Add/update OpenAI API key
- [X] Test LLM connection

---

## 2. Tenant Owner Activation

### 2.1 Account Activation Flow
- [X] Receive welcome email with activation link
- [X] Click activation link → redirects to activation page
- [X] Email field pre-populated from URL
- [X] Set password (meets requirements)
- [X] Submit activation → success message
- [X] Redirect to login

### 2.2 Edge Cases
- [X] Email with `+` sign (e.g., `user+test@example.com`) works correctly
- [ ] Expired token shows appropriate error
- [ ] Invalid token shows appropriate error
- [ ] Already-activated account shows appropriate error

---

## 3. Tenant Application (`{tenant}.blackbar.app`)

### 3.1 Authentication
- [X] Login with activated account
- [ ] User sees correct tenant branding (name, logo, colors) 
    - Name is wrong, created issue 37
    - Can't upload logo, only link to it. 
- [X] User has correct role (owner/admin)
- [X] Logout

### 3.2 Navigation
- [ ] Cases link visible and works
- [ ] Admin link visible (owner/admin only)
- [ ] Help link visible and works
- [ ] User menu dropdown works

---

## 4. Case Management

### 4.1 Case Queue
- [ ] View case queue/list
- [ ] Cases display with tracking number, status, due date
- [ ] Sort/filter cases works
- [ ] Search cases works

### 4.2 Create Case
- [ ] Navigate to create case form
- [ ] Fill required fields (tracking number, requester info)
- [ ] Set request type, category
- [ ] Submit case → success
- [ ] New case appears in queue

### 4.3 Case Detail View
- [ ] View case detail page
- [ ] See case summary, status, dates
- [ ] See assigned team members
- [ ] View activity/history log

### 4.4 Case Workflow
- [ ] Update case status (Intake → Collection → Review → Redaction → Approval → Release)
- [ ] Pause/resume statutory clock
- [ ] Add clock event (fee payment, consultation, extension)
- [ ] Assign case to user
- [ ] Add team members/contributors

---

## 5. Document Management

### 5.1 Document Upload
- [ ] Upload single PDF document
- [ ] Upload multiple documents (bulk)
- [ ] Upload DOCX → auto-converts to PDF
- [ ] Upload XLSX → auto-converts to PDF
- [ ] Upload EML/MSG email files
- [ ] OCR runs on scanned documents

### 5.2 Document List
- [ ] View documents for a case
- [ ] See document status (pending, processed, reviewed)
- [ ] Download original document
- [ ] Delete document

### 5.3 Document Processing
- [ ] Duplicate detection works
- [ ] Email thread consolidation works
- [ ] Page count displays correctly

---

## 6. Redaction (Document Viewer)

### 6.1 Viewer Shell
- [X] Open document in viewer
- [X] Navigate pages (next/prev, page number input)
- [X] Zoom in/out
- [X] Document renders correctly

### 6.2 Select Tool (Text Redaction)
- [X] Select text with mouse → highlights
- [X] Apply redaction with exemption section
- [X] Redaction rectangle appears
- [X] Undo redaction

### 6.3 Draw Tool (Box Redaction)
- [X] Switch to draw tool
- [X] Draw rectangle over image/table
- [X] Apply exemption section
- [X] Redaction box appears

### 6.4 Find & Redact Tool
- [ ] Search for term across document
    - Fails - Issue 54
- [ ] Results show all matches
- [ ] Batch apply redaction to all matches

### 6.5 AI Suggestions
- [ ] Request AI suggestions
    - Fails - Issue 
- [ ] Suggestions appear with confidence score
- [ ] Accept suggestion → applies redaction
- [ ] Reject suggestion → removes from list
- [ ] FIPPA section auto-mapped

### 6.6 Redaction Sections
- [X] S13 (Policy advice)
- [X] S14 (Legal advice)
- [X] S15 (Law enforcement)
- [X] S21 (Business interests)
- [X] S22 (Personal privacy)

### 6.7 Export
- [ ] Export redacted PDF
- [ ] Redactions are flattened/permanent
- [ ] Original text not recoverable

---

## 7. Admin Console (Tenant)

### 7.1 User Management
- [X] View user list
- [X] Create new user (email, name, role)
    - Partial, amendments needed, cases created
- [X ] Edit user details

- [X] Change user role
- [ ] Disable/enable user
- [ ] Delete user from tenant

### 7.2 Roles
- [ ] Owner can access all features
- [ ] Admin can access all features
- [ ] Analyst can manage cases
- [ ] User has limited access
- [ ] Guest can only see shared documents

### 7.3 Configuration
- [ ] View tenant settings
- [ ] Update organization name
- [ ] Update primary color/branding
- [ ] Configure public request settings

### 7.4 Templates
- [ ] View response templates
- [ ] Create new template
- [ ] Edit template
- [ ] Delete template

---

## 8. Public Portal

### 8.1 Public Request Form
- [X] Access public request page
- [X] Submit new FOI request (name, email, description)
- [X] Receive tracking number
- [ ] Confirmation email sent

### 8.2 Magic Link Authentication
- [X] Enter email on public login page
- [X] Receive magic link email
- [X] Click magic link → authenticated
- [X] Redirect to public dashboard

### 8.3 Public Dashboard
- [X] View submitted requests
- [X] See request status
- [X] View request details

### 8.4 Request Tracking
- [X] Access `/track/{trackingNumber}`
- [X] See request status without authentication
    - This is not expected to work, as it requires authentication

### 8.5 Public Upload
- [ ] Access upload portal via link
- [ ] Upload documents as requester
- [ ] Documents attached to case

---

## 9. Contributor Portal

### 9.1 Token-Based Access
- [X] Access `/contribute/{contributorId}` with valid token
- [ ] Invalid token shows error
- [X] View contributor dashboard

### 9.2 Contributor Actions
- [X] View assigned case
- [X] Upload responsive documents
- [ ] Add notes/comments
    - CAn't see where to add notes or comments. 
- [X] Submit contribution

---

## 10. Priority Queue

### 10.1 Workflow Queue
- [ ] Access `/queue` route
- [ ] View cases prioritized by due date
- [ ] See case complexity indicators
- [ ] Quick actions from queue

---

## 11. Multi-Tenant Isolation

### 11.1 Data Isolation
- [ ] Tenant A cannot see Tenant B's cases
- [ ] Tenant A cannot access Tenant B's documents
- [ ] Search only returns current tenant's data

### 11.2 Subdomain Routing
- [ ] `tenant1.blackbar.app` shows Tenant 1 data
- [ ] `tenant2.blackbar.app` shows Tenant 2 data
- [ ] Cross-tenant token fails

---

## 12. Security

### 12.1 Authentication
- [ ] JWT token required for protected routes
- [ ] Expired token returns 401
- [ ] Invalid token returns 401

### 12.2 Authorization
- [ ] Non-admin cannot access admin routes
- [ ] Guest cannot access case management
- [ ] Role-based navigation works

### 12.3 Session Management
- [ ] Token stored in localStorage
- [ ] Logout clears token
- [ ] Session timeout works

---

## 13. Error Handling

### 13.1 Frontend Errors
- [ ] 404 page for invalid routes
- [ ] Error boundary catches crashes
- [ ] Loading states display correctly

### 13.2 Backend Errors
- [ ] 400 Bad Request returns helpful message
- [ ] 401 Unauthorized redirects to login
- [ ] 403 Forbidden shows access denied
- [ ] 500 Server Error shows generic message

---

## 14. Performance

### 14.1 Page Load
- [ ] Login page loads < 2s
- [ ] Case queue loads < 3s
- [ ] Document viewer loads < 5s

### 14.2 Large Documents
- [ ] 50+ page PDF renders correctly
- [ ] 100+ page PDF doesn't crash
- [ ] Bulk upload of 20+ documents works

---

## Notes

_Use this space for any issues found, screenshots, or additional observations:_

```
Issue #: 
Description:
Steps to Reproduce:
Expected:
Actual:
```

---

**Checklist Version**: 1.0  
**Last Updated**: 2026-01-12
