import logging
import re
from typing import Any

from src.database import documents
from src.utils.conversion import extract_text_from_pdf
from src.utils.llm_client import get_llm_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAX_CONTENT_LENGTH = 8000


async def generate_document_summary(content: bytes, filename: str, mime_type: str) -> str:
    """
    Generate a concise summary (at most two sentences) of the document content.

    Args:
        content: The binary content of the document
        filename: The name of the file
        mime_type: The MIME type of the file

    Returns:
        A brief summary of the content
    """
    try:
        llm_client = await get_llm_client()
        if not llm_client:
            return (
                "AI summary not available - no default LLM is set. "
                "Visit Admin → LLM Configuration and click 'Set Default' on an enabled config."
            )

        text_content = ""

        if mime_type == "application/pdf":
            # Use our OCR-enhanced PDF text extraction
            text_content = extract_text_from_pdf(content)
            logger.info(f"Extracted text from PDF using OCR: {len(text_content)} characters")
        else:
            # For other formats, use simple text extraction
            text_content = content.decode("utf-8", errors="ignore")

        # Check if we have meaningful text content
        if (
            not text_content
            or text_content.startswith("Error extracting text")
            or len(text_content.strip()) < 20
        ):
            return "Unable to extract meaningful text from this document."

        # Truncate content if too long
        if len(text_content) > MAX_CONTENT_LENGTH:
            text_content = text_content[:MAX_CONTENT_LENGTH] + "..."

        system_prompt = "You are an AI assistant that generates brief, accurate document summaries."
        user_prompt = f"""Filename: {filename}
MIME Type: {mime_type}

Please summarize the following document in AT MOST TWO SENTENCES. Focus on the main topic and key information only.
If the content appears to be binary data, image encoding, or otherwise not meaningful text, indicate that the document appears to be primarily non-textual content.

DOCUMENT CONTENT:
{text_content}

TWO-SENTENCE SUMMARY:"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # Use configured LLM client
        summary = await llm_client.chat_completion(messages, temperature=0.3, max_tokens=150)

        # Ensure we only return two sentences maximum
        sentences = re.split(r"(?<=[.!?]) +", summary)
        if len(sentences) > 2:
            summary = " ".join(sentences[:2])

        return summary
    except Exception as e:
        logger.error(f"Error generating document summary: {str(e)}")
        return f"Error generating summary: {str(e)}"


async def generate_ai_suggestions(
    content: bytes, filename: str, mime_type: str
) -> list[dict[str, Any]]:
    """
    Generate AI suggestions for potential redactions or important information.

    Args:
        content: The binary content of the document
        filename: The name of the file
        mime_type: The MIME type of the file

    Returns:
        A list of suggestions, each with type, description, and optional location
    """
    try:
        llm_client = await get_llm_client()
        if not llm_client:
            return [
                {
                    "type": "error",
                    "description": (
                        "AI suggestions not available - no default LLM is set. "
                        "Visit Admin → LLM Configuration and click 'Set Default' "
                        "on an enabled config."
                    ),
                }
            ]

        # Similar to summary, first extract text
        text_content = content.decode("utf-8", errors="ignore")[:8000]

        # Create messages for LLM
        system_prompt = "You are an assistant that analyzes documents for sensitive information."
        user_prompt = f"""Filename: {filename}
MIME Type: {mime_type}

Content:
{text_content}

Identify up to 5 items that might require redaction or attention, such as:
1. Personal information (names, addresses, phone numbers, emails)
2. Financial information (credit card numbers, account numbers)
3. Legal or sensitive business information
4. Health information

Format each suggestion as a JSON object with these fields:
- type: Category of info (personal, financial, legal, health, other)
- description: Brief description of what was found
- confidence: High, Medium, or Low

Return your response as a valid JSON array."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # Use configured LLM client
        text_response = await llm_client.chat_completion(messages, temperature=0.3, max_tokens=500)

        # Parse the response - expecting a JSON string containing an array
        import json

        try:
            # Try to extract JSON from the model output
            # Find JSON array in the response
            if "[" in text_response and "]" in text_response:
                start_idx = text_response.find("[")
                end_idx = text_response.rfind("]") + 1
                json_text = text_response[start_idx:end_idx]
                suggestions = json.loads(json_text)
                return suggestions
            else:
                return [{"type": "error", "description": "Could not parse AI response"}]
        except json.JSONDecodeError:
            logger.error("Failed to parse JSON from AI response")
            return [{"type": "error", "description": "Failed to parse AI response"}]

    except Exception as e:
        logger.error(f"Error generating AI suggestions: {str(e)}")
        return [{"type": "error", "description": f"Error generating suggestions: {str(e)}"}]


async def process_attachment(attachment: dict[str, Any]) -> dict[str, Any]:
    """
    Process an attachment by generating a summary and AI suggestions.

    Args:
        attachment: The attachment document from the database

    Returns:
        A dictionary with summary and suggestions
    """
    try:
        content = attachment.get("content", b"")
        filename = attachment.get("filename", "unknown")
        mime_type = attachment.get("mime_type", "application/octet-stream")

        # Generate summary and suggestions in parallel
        import asyncio

        summary_task = generate_document_summary(content, filename, mime_type)
        suggestions_task = generate_ai_suggestions(content, filename, mime_type)

        summary, suggestions = await asyncio.gather(summary_task, suggestions_task)

        return {
            "summary": summary,
            "ai_suggestions": suggestions,
            "processed": True,
            "processing_error": None,
        }
    except Exception as e:
        logger.error(f"Error processing attachment: {str(e)}")
        return {
            "summary": None,
            "ai_suggestions": [],
            "processed": True,  # Mark as processed even if there was an error
            "processing_error": str(e),
        }


async def process_attachment_async(attachment_id: str, document_id: str) -> None:
    """
    Process an attachment asynchronously by generating a summary and AI suggestions.

    Args:
        attachment_id: The ID of the attachment document in the database
        document_id: The ID of the parent document
    """
    try:
        logger.info(f"Starting background processing for attachment {attachment_id}")

        # Retrieve the attachment from the database
        attachment = await documents.find_one({"id": attachment_id})
        if not attachment:
            logger.error(f"Attachment {attachment_id} not found for processing")
            return

        # Process the attachment
        result = await process_attachment(attachment)

        # Update the attachment in the database with the processing result
        await documents.update_one(
            {"id": attachment_id},
            {
                "$set": {
                    "summary": result["summary"],
                    "ai_suggestions": result["ai_suggestions"],
                    "processed": result["processed"],
                    "processing_error": result["processing_error"],
                }
            },
        )

        # Update the parent document to increment processed_attachments counter
        await documents.update_one({"id": document_id}, {"$inc": {"processed_attachments": 1}})

        logger.info(f"Completed background processing for attachment {attachment_id}")
    except Exception as e:
        logger.error(f"Error processing attachment asynchronously: {str(e)}")
        # Try to update the attachment status even if processing failed
        try:
            await documents.update_one(
                {"id": attachment_id}, {"$set": {"processed": True, "processing_error": str(e)}}
            )
            # Still increment the counter since we've "processed" it (even with an error)
            await documents.update_one({"id": document_id}, {"$inc": {"processed_attachments": 1}})
        except Exception as update_error:
            logger.error(f"Failed to update attachment status: {str(update_error)}")
