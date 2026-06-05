# backend/src/utils/seed_templates.py
"""
Seed default templates for FOI response letters, communications, and status updates.

Template Categories:
- foi_response: Formal FOI response letters
- foi_internal: Internal FOI documentation
- message: Quick message templates for case communications
- status_update: Status update notifications for requesters
"""

import uuid
from datetime import datetime


def generate_template_id():
    """Generate a new UUID for template - called at runtime to ensure unique IDs"""
    return str(uuid.uuid4())


# Message Templates - Quick communications for case management
MESSAGE_TEMPLATES = [
    {
        "name": "Fee Assessment",
        "type": "message",
        "subject": "Fee Assessment Required - {case_number}",
        "content": """Dear {recipient_name},

We have completed our initial review of your request ({case_number}) and determined that fees will apply for processing.

Estimated Fee: {fee_amount}

This estimate is based on the scope of records identified. Please confirm if you wish to proceed, or contact us to discuss narrowing the scope of your request.

{analyst_name}
{organization_name}""",
        "variables": [
            "recipient_name",
            "case_number",
            "fee_amount",
            "analyst_name",
            "organization_name",
        ],
        "description": "Notify requester that fees apply to their request",
        "category": "message",
        "is_active": True,
        "is_default": True,
        "created_by": "system",
    },
    {
        "name": "Scoping Change Request",
        "type": "message",
        "subject": "Request for Clarification - {case_number}",
        "content": """Dear {recipient_name},

Thank you for your request ({case_number}). To help us process your request more efficiently, we would like to clarify the scope.

{clarification_details}

Please respond at your earliest convenience so we can proceed with your request.

{analyst_name}
{organization_name}""",
        "variables": [
            "recipient_name",
            "case_number",
            "clarification_details",
            "analyst_name",
            "organization_name",
        ],
        "description": "Request clarification or scope change from requester",
        "category": "message",
        "is_active": True,
        "is_default": True,
        "created_by": "system",
    },
    {
        "name": "Delay Notification",
        "type": "message",
        "subject": "Processing Delay - {case_number}",
        "content": """Dear {recipient_name},

We are writing to inform you that there will be a delay in processing your request ({case_number}).

Reason: {delay_reason}

We anticipate being able to respond by {new_expected_date}. We apologize for any inconvenience and appreciate your patience.

{analyst_name}
{organization_name}""",
        "variables": [
            "recipient_name",
            "case_number",
            "delay_reason",
            "new_expected_date",
            "analyst_name",
            "organization_name",
        ],
        "description": "Notify requester of processing delay",
        "category": "message",
        "is_active": True,
        "is_default": True,
        "created_by": "system",
    },
    {
        "name": "Third Party Consultation Required",
        "type": "message",
        "subject": "Third Party Consultation - {case_number}",
        "content": """Dear {recipient_name},

Your request ({case_number}) involves records that may affect a third party. We are required to consult with them before releasing any information.

This consultation process may extend our response time. We will keep you informed of any updates.

{analyst_name}
{organization_name}""",
        "variables": ["recipient_name", "case_number", "analyst_name", "organization_name"],
        "description": "Notify requester that third party consultation is required",
        "category": "message",
        "is_active": True,
        "is_default": True,
        "created_by": "system",
    },
    {
        "name": "No Responsive Records",
        "type": "message",
        "subject": "No Records Found - {case_number}",
        "content": """Dear {recipient_name},

We have completed our search for records responsive to your request ({case_number}).

After a thorough search of our records, we were unable to locate any documents that fall within the scope of your request.

If you believe records should exist, please contact us to discuss further options.

{analyst_name}
{organization_name}""",
        "variables": ["recipient_name", "case_number", "analyst_name", "organization_name"],
        "description": "Notify requester that no responsive records were found",
        "category": "message",
        "is_active": True,
        "is_default": True,
        "created_by": "system",
    },
]

# Status Update Templates - Automated status notifications
STATUS_UPDATE_TEMPLATES = [
    {
        "name": "Status: Request Received",
        "type": "status_update",
        "subject": "Request Received - {case_number}",
        "content": """Dear {recipient_name},

Your request has been received and assigned tracking number {case_number}.

We will begin processing your request and keep you informed of our progress.

{organization_name}""",
        "variables": ["recipient_name", "case_number", "organization_name"],
        "description": "Automatic notification when request is received",
        "category": "status_update",
        "is_active": True,
        "is_default": True,
        "created_by": "system",
    },
    {
        "name": "Status: Call for Records Sent",
        "type": "status_update",
        "subject": "Update: Records Search Initiated - {case_number}",
        "content": """Dear {recipient_name},

We have initiated a search for records responsive to your request ({case_number}).

Relevant departments have been contacted to identify and gather applicable records.

{organization_name}""",
        "variables": ["recipient_name", "case_number", "organization_name"],
        "description": "Notification when call for records is sent to departments",
        "category": "status_update",
        "is_active": True,
        "is_default": True,
        "created_by": "system",
    },
    {
        "name": "Status: All Records Received",
        "type": "status_update",
        "subject": "Update: Records Collected - {case_number}",
        "content": """Dear {recipient_name},

All records responsive to your request ({case_number}) have been collected.

We are now proceeding with the review process.

{organization_name}""",
        "variables": ["recipient_name", "case_number", "organization_name"],
        "description": "Notification when all records have been gathered",
        "category": "status_update",
        "is_active": True,
        "is_default": True,
        "created_by": "system",
    },
    {
        "name": "Status: Redactions Underway",
        "type": "status_update",
        "subject": "Update: Review in Progress - {case_number}",
        "content": """Dear {recipient_name},

Your request ({case_number}) is currently being reviewed for any information that may need to be withheld under applicable exemptions.

We will notify you when this process is complete.

{organization_name}""",
        "variables": ["recipient_name", "case_number", "organization_name"],
        "description": "Notification when redaction review is in progress",
        "category": "status_update",
        "is_active": True,
        "is_default": True,
        "created_by": "system",
    },
    {
        "name": "Status: Final Approval Stage",
        "type": "status_update",
        "subject": "Update: Final Review - {case_number}",
        "content": """Dear {recipient_name},

Your request ({case_number}) is in the final approval stage.

You should receive our response shortly.

{organization_name}""",
        "variables": ["recipient_name", "case_number", "organization_name"],
        "description": "Notification when request is in final approval",
        "category": "status_update",
        "is_active": True,
        "is_default": True,
        "created_by": "system",
    },
]

# FOI Response Templates - Formal letters
FOI_RESPONSE_TEMPLATES = [
    {
        "id": str(uuid.uuid4()),
        "name": "FOI Acknowledgment Letter",
        "type": "acknowledgment",
        "subject": "Acknowledgment of Freedom of Information Request - {case_number}",
        "content": """Dear {recipient_name},

Re: Freedom of Information Request - {case_number}

Thank you for your request for information under the Freedom of Information and Protection of Privacy Act (FIPPA), received on {request_date}.

Your request has been assigned the reference number {case_number} and is being processed by our office.

We will respond to your request within 30 business days as required by FIPPA. If we require an extension to respond to your request, we will notify you in writing before the initial response deadline.

If you have any questions regarding your request, please contact us at {contact_email} and reference your case number {case_number}.

Sincerely,

{analyst_name}
{organization_name}
Freedom of Information Coordinator
""",
        "variables": [
            "recipient_name",
            "case_number",
            "request_date",
            "contact_email",
            "analyst_name",
            "organization_name",
        ],
        "description": "Standard acknowledgment letter for FOI requests",
        "category": "foi_response",
        "is_active": True,
        "is_default": True,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "created_by": "system",
    },
    {
        "id": str(uuid.uuid4()),
        "name": "FOI Cover Letter",
        "type": "cover_letter",
        "subject": "Response to Freedom of Information Request - {case_number}",
        "content": """Dear {recipient_name},

Re: Freedom of Information Request - {case_number}

This letter is in response to your request for information under the Freedom of Information and Protection of Privacy Act (FIPPA), received on {request_date}.

You requested access to: {request_description}

DECISION

Access is granted to {pages_released} pages of records, with {pages_severed} pages containing severed information under the following sections of FIPPA:

{severance_sections}

The records responsive to your request are enclosed with this letter. Information that has been severed is marked with the applicable FIPPA section number.

RIGHT TO REQUEST A REVIEW

If you are not satisfied with this response, you have the right to request a review by the Information and Privacy Commissioner within 30 business days of receiving this decision. You may contact the Office of the Information and Privacy Commissioner at:

{commissioner_contact}

If you have any questions regarding this response, please contact me at {contact_email} and reference your case number {case_number}.

Sincerely,

{analyst_name}
{analyst_title}
{organization_name}

Enclosures: {pages_released} pages
""",
        "variables": [
            "recipient_name",
            "case_number",
            "request_date",
            "request_description",
            "pages_released",
            "pages_severed",
            "severance_sections",
            "commissioner_contact",
            "contact_email",
            "analyst_name",
            "analyst_title",
            "organization_name",
        ],
        "description": "Cover letter for FOI response package with disclosed records",
        "category": "foi_response",
        "is_active": True,
        "is_default": True,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "created_by": "system",
    },
    {
        "id": str(uuid.uuid4()),
        "name": "FOI Extension Notification",
        "type": "extension",
        "subject": "Extension of Time - Freedom of Information Request {case_number}",
        "content": """Dear {recipient_name},

Re: Freedom of Information Request - {case_number}
Extension of Time to Respond

This letter is to notify you that we require an extension of time to respond to your Freedom of Information request received on {request_date}.

REASON FOR EXTENSION

We require additional time for the following reason(s):

{extension_reason}

EXTENDED RESPONSE DATE

Under section {fippa_section} of the Freedom of Information and Protection of Privacy Act, we are extending the response deadline by {extension_days} days. Your new response date is {new_deadline}.

RIGHT TO COMPLAINT

You have the right to complain to the Information and Privacy Commissioner about this extension. You may contact the Commissioner's office at:

{commissioner_contact}

We apologize for the delay and appreciate your patience as we process your request. If you have any questions, please contact me at {contact_email} and reference your case number {case_number}.

Sincerely,

{analyst_name}
{analyst_title}
{organization_name}
""",
        "variables": [
            "recipient_name",
            "case_number",
            "request_date",
            "extension_reason",
            "fippa_section",
            "extension_days",
            "new_deadline",
            "commissioner_contact",
            "contact_email",
            "analyst_name",
            "analyst_title",
            "organization_name",
        ],
        "description": "Notification letter for time extension on FOI request",
        "category": "foi_response",
        "is_active": True,
        "is_default": True,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "created_by": "system",
    },
    {
        "id": str(uuid.uuid4()),
        "name": "FOI Fee Schedule",
        "type": "fee_schedule",
        "subject": "Fee Estimate - Freedom of Information Request {case_number}",
        "content": """Dear {recipient_name},

Re: Freedom of Information Request - {case_number}
Fee Estimate

This letter provides an estimate of fees for processing your Freedom of Information request received on {request_date}.

FEE BREAKDOWN

Search and Retrieval: {search_hours} hours @ ${search_rate}/hour = ${search_total}
Preparation of Records: {prep_hours} hours @ ${prep_rate}/hour = ${prep_total}
Photocopying: {page_count} pages @ ${copy_rate}/page = ${copy_total}

TOTAL ESTIMATED FEE: ${total_fee}

PAYMENT

Please note that the first 3 hours of search time are provided at no charge under FIPPA regulations. The fee estimate above reflects this exemption.

To proceed with your request, please:
1. Confirm you wish to proceed with the request at this cost
2. Submit payment of ${total_fee} by {payment_methods}
3. Reference your case number {case_number}

If you would like to narrow the scope of your request to reduce fees, please contact me at {contact_email}.

RIGHT TO REQUEST A REVIEW

If you believe the fees are unreasonable, you may request a review by the Information and Privacy Commissioner:

{commissioner_contact}

Sincerely,

{analyst_name}
{analyst_title}
{organization_name}
""",
        "variables": [
            "recipient_name",
            "case_number",
            "request_date",
            "search_hours",
            "search_rate",
            "search_total",
            "prep_hours",
            "prep_rate",
            "prep_total",
            "page_count",
            "copy_rate",
            "copy_total",
            "total_fee",
            "payment_methods",
            "contact_email",
            "commissioner_contact",
            "analyst_name",
            "analyst_title",
            "organization_name",
        ],
        "description": "Fee estimate letter for FOI request processing",
        "category": "foi_response",
        "is_active": True,
        "is_default": True,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "created_by": "system",
    },
    {
        "id": str(uuid.uuid4()),
        "name": "FOI Disclosure Statement",
        "type": "disclosure",
        "subject": "Disclosure Statement - Freedom of Information Request {case_number}",
        "content": """DISCLOSURE STATEMENT
Freedom of Information Request {case_number}

Applicant: {recipient_name}
Request Date: {request_date}
Response Date: {response_date}

RECORDS DISCLOSED

Total Pages Reviewed: {total_pages}
Pages Released in Full: {pages_full}
Pages Released in Part: {pages_partial}
Pages Withheld in Full: {pages_withheld}

EXEMPTIONS APPLIED

The following sections of the Freedom of Information and Protection of Privacy Act were applied to sever or withhold information:

{exemptions_list}

SEVERANCE DETAILS

{severance_details}

THIRD PARTY NOTIFICATION

{third_party_info}

REVIEW RIGHTS

The applicant has been informed of their right to request a review by the Information and Privacy Commissioner within 30 business days of receiving this decision.

PREPARED BY

Name: {analyst_name}
Title: {analyst_title}
Date: {response_date}
Organization: {organization_name}

This disclosure statement is maintained as part of the official record for FOI request {case_number}.
""",
        "variables": [
            "case_number",
            "recipient_name",
            "request_date",
            "response_date",
            "total_pages",
            "pages_full",
            "pages_partial",
            "pages_withheld",
            "exemptions_list",
            "severance_details",
            "third_party_info",
            "analyst_name",
            "analyst_title",
            "organization_name",
        ],
        "description": "Internal disclosure statement documenting FOI response details",
        "category": "foi_internal",
        "is_active": True,
        "is_default": True,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "created_by": "system",
    },
]


def get_all_default_templates():
    """
    Get all default templates with fresh UUIDs and timestamps.
    Called at runtime to ensure unique IDs for each seeding operation.
    """
    now = datetime.utcnow()
    all_templates = []

    # Add message templates
    for template in MESSAGE_TEMPLATES:
        t = template.copy()
        t["id"] = generate_template_id()
        t["created_at"] = now
        t["updated_at"] = now
        all_templates.append(t)

    # Add status update templates
    for template in STATUS_UPDATE_TEMPLATES:
        t = template.copy()
        t["id"] = generate_template_id()
        t["created_at"] = now
        t["updated_at"] = now
        all_templates.append(t)

    # Add FOI response templates (already have structure)
    for template in FOI_RESPONSE_TEMPLATES:
        t = template.copy()
        t["id"] = generate_template_id()  # Generate fresh ID
        t["created_at"] = now
        t["updated_at"] = now
        all_templates.append(t)

    return all_templates


async def seed_default_templates(templates_collection):
    """
    Seed default templates into the database.
    Only inserts templates that don't already exist (by name).
    Includes message templates and status updates.
    """
    import logging

    logger = logging.getLogger(__name__)

    inserted_count = 0
    skipped_count = 0
    error_count = 0

    # Get all templates with fresh IDs
    all_templates = get_all_default_templates()

    logger.info(f"Starting template seeding. {len(all_templates)} templates to process.")

    for template in all_templates:
        try:
            # Check if template already exists
            existing = await templates_collection.find_one({"name": template["name"]})
            if existing:
                logger.debug(f"Template '{template['name']}' already exists, skipping...")
                skipped_count += 1
                continue

            # Insert template
            await templates_collection.insert_one(template)
            logger.info(f"Inserted template: {template['name']}")
            inserted_count += 1

        except Exception as e:
            error_count += 1
            logger.error(f"Failed to insert template '{template['name']}': {str(e)}")

    summary = f"Template seeding complete: {inserted_count} inserted, {skipped_count} skipped, {error_count} errors"
    logger.info(summary)

    return {
        "inserted": inserted_count,
        "skipped": skipped_count,
        "errors": error_count,
        "total": len(all_templates),
    }
