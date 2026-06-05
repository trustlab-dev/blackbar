import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from ..core.database import get_database_from_request
from ..dependencies import check_role, get_current_user
from .models import TemplateCreate, TemplateResponse, TemplateUpdate

router = APIRouter(prefix="/templates", tags=["templates"])


def render_template(template_content: str, case_data: dict, user_data: dict = None) -> str:
    """
    Render a template by replacing variables with actual data.

    Supported variables:
    - {case_number}
    - {requester_name}
    - {requester_email}
    - {requester_organization}
    - {case_title}
    - {case_description}
    - {received_date}
    - {due_date}
    - {document_count}
    - {current_date}
    - {user_name}
    - {user_title}
    - {organization}
    """

    # Prepare replacement values
    replacements = {}

    # Case information
    replacements["{case_number}"] = case_data.get("tracking_number", "")
    replacements["{case_title}"] = case_data.get("title", "")
    replacements["{case_description}"] = case_data.get("description", "")

    # Requester information
    requester = case_data.get("requester", {})
    if requester:
        replacements["{requester_name}"] = requester.get("name", "")
        replacements["{requester_email}"] = requester.get("email", "")
        replacements["{requester_organization}"] = requester.get("organization", "")

    # Dates
    received_date = case_data.get("received_date") or case_data.get("created_at")
    if received_date:
        if isinstance(received_date, datetime):
            replacements["{received_date}"] = received_date.strftime("%B %d, %Y")
        else:
            try:
                dt = datetime.fromisoformat(str(received_date).replace("Z", "+00:00"))
                replacements["{received_date}"] = dt.strftime("%B %d, %Y")
            except:
                replacements["{received_date}"] = str(received_date)

    due_date = case_data.get("due_date")
    if due_date:
        if isinstance(due_date, datetime):
            replacements["{due_date}"] = due_date.strftime("%B %d, %Y")
        else:
            try:
                dt = datetime.fromisoformat(str(due_date).replace("Z", "+00:00"))
                replacements["{due_date}"] = dt.strftime("%B %d, %Y")
            except:
                replacements["{due_date}"] = str(due_date)

    # Current date
    replacements["{current_date}"] = datetime.now().strftime("%B %d, %Y")

    # Document count (we'll need to query this)
    replacements["{document_count}"] = "[document_count]"

    # User information
    if user_data:
        replacements["{user_name}"] = user_data.get("name", user_data.get("username", ""))
        replacements["{user_title}"] = user_data.get("title", "")

    # Organization (could come from config or case)
    replacements["{organization}"] = "[Organization Name]"

    # Perform replacements
    rendered = template_content
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, str(value))

    return rendered


@router.get(
    "/",
    response_model=list[TemplateResponse],
    dependencies=[Depends(check_role(["owner", "admin", "analyst"]))],
)
async def list_templates(
    category: str = None,
    active_only: bool = True,
    current_user=Depends(get_current_user),
    db=Depends(get_database_from_request),
):
    """Get all templates"""
    query = {}
    if category:
        query["category"] = category
    if active_only:
        query["is_active"] = True

    cursor = db.templates.find(query)
    templates = await cursor.to_list(length=None)

    return templates


@router.post(
    "/", response_model=TemplateResponse, dependencies=[Depends(check_role(["owner", "admin"]))]
)
async def create_template(
    template: TemplateCreate,
    current_user=Depends(get_current_user),
    db=Depends(get_database_from_request),
):
    """Create a new template (Admin/Manager only)"""
    template_id = str(uuid.uuid4())
    now = datetime.utcnow()

    template_data = {
        "id": template_id,
        **template.dict(),
        "created_at": now,
        "updated_at": now,
        "created_by": current_user.get("id", ""),
    }

    await db.templates.insert_one(template_data)

    return template_data


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(
    template_id: str, current_user=Depends(get_current_user), db=Depends(get_database_from_request)
):
    """Get a specific template"""
    template = await db.templates.find_one({"id": template_id})
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    return template


@router.put(
    "/{template_id}",
    response_model=TemplateResponse,
    dependencies=[Depends(check_role(["owner", "admin"]))],
)
async def update_template(
    template_id: str,
    template_update: TemplateUpdate,
    current_user=Depends(get_current_user),
    db=Depends(get_database_from_request),
):
    """Update a template (Admin/Manager only)"""
    existing_template = await db.templates.find_one({"id": template_id})
    if not existing_template:
        raise HTTPException(status_code=404, detail="Template not found")

    update_data = {k: v for k, v in template_update.dict(exclude_unset=True).items()}
    update_data["updated_at"] = datetime.utcnow()

    await db.templates.update_one({"id": template_id}, {"$set": update_data})

    updated_template = await db.templates.find_one({"id": template_id})
    return updated_template


@router.delete("/{template_id}", dependencies=[Depends(check_role(["owner", "admin"]))])
async def delete_template(
    template_id: str, current_user=Depends(get_current_user), db=Depends(get_database_from_request)
):
    """Delete a template (Admin/Manager only)"""
    result = await db.templates.delete_one({"id": template_id})

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Template not found")

    return {"message": "Template deleted successfully"}


@router.post("/{template_id}/render")
async def render_template_for_case(
    template_id: str,
    case_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database_from_request),
):
    """Render a template with data from a specific case"""
    # Get template
    template = await db.templates.find_one({"id": template_id})
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    # Get case
    case = await db.cases.find_one({"id": case_id})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Get document count
    doc_count = await db.documents.count_documents({"case_id": case_id})
    case["document_count"] = doc_count

    # Render template
    rendered_content = render_template(template["content"], case, current_user)

    # Replace document count placeholder
    rendered_content = rendered_content.replace("[document_count]", str(doc_count))

    return {
        "template_id": template_id,
        "template_name": template["name"],
        "rendered_content": rendered_content,
    }


@router.get("/available-variables/list")
async def list_available_variables(current_user=Depends(get_current_user)):
    """Get list of available template variables"""
    return {
        "variables": [
            {
                "name": "{case_number}",
                "description": "Case tracking number (e.g., FOI-2025-001-WNP)",
            },
            {"name": "{requester_name}", "description": "Name of the person making the request"},
            {"name": "{requester_email}", "description": "Email address of requester"},
            {
                "name": "{requester_organization}",
                "description": "Organization of requester (if provided)",
            },
            {"name": "{case_title}", "description": "Title/subject of the case"},
            {"name": "{case_description}", "description": "Full description of the request"},
            {"name": "{received_date}", "description": "Date request was received"},
            {"name": "{due_date}", "description": "Due date for response"},
            {"name": "{document_count}", "description": "Total number of documents in case"},
            {"name": "{current_date}", "description": "Today's date"},
            {"name": "{user_name}", "description": "Your name"},
            {"name": "{user_title}", "description": "Your job title"},
            {"name": "{organization}", "description": "Organization name"},
        ]
    }
