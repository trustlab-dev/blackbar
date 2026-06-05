"""
AI-powered redaction suggestions using configured LLM provider
Analyzes document text and suggests what should be redacted
Uses layered prompt system: global principles + jurisdiction-specific rules
Supports multiple providers: OpenAI, Claude, Cohere, etc.
"""

import json
import logging
import re
from pathlib import Path

import fitz  # PyMuPDF

from .llm_client import get_llm_client

logger = logging.getLogger(__name__)

# Cache for global prompts
_global_prompts_cache = None


def load_global_prompts() -> dict:
    """Load global AI prompt configuration from packs/global_prompts.json"""
    global _global_prompts_cache

    if _global_prompts_cache is not None:
        return _global_prompts_cache

    try:
        prompts_path = Path(__file__).parent.parent.parent / "packs" / "global_prompts.json"
        with open(prompts_path) as f:
            _global_prompts_cache = json.load(f)
        logger.info("Loaded global AI prompts successfully")
        return _global_prompts_cache
    except Exception as e:
        logger.error(f"Failed to load global prompts: {e}")
        return {}


def build_enhanced_system_prompt(jurisdiction_prompt: str, global_prompts: dict) -> str:
    """
    Build a comprehensive system prompt combining global principles with jurisdiction guidance.

    Args:
        jurisdiction_prompt: The jurisdiction-specific system prompt
        global_prompts: The global prompts configuration

    Returns:
        Enhanced system prompt string
    """
    # Extract key principles from global prompts
    core_principles = global_prompts.get("core_principles", {})
    behavior_rules = global_prompts.get("behavior_rules", {})

    # Build principle summary
    principles_text = "UNIVERSAL PRINCIPLES:\\n"
    for key, value in core_principles.items():
        principles_text += f"- {value}\\n"

    principles_text += "\\nBEHAVIOR REQUIREMENTS:\\n"
    for key, value in behavior_rules.items():
        principles_text += f"- {value}\\n"

    # Combine with jurisdiction-specific prompt
    enhanced_prompt = f"{jurisdiction_prompt}\\n\\n{principles_text}"

    return enhanced_prompt


# Common categories for FOI redactions mapped to sections
REDACTION_CATEGORIES = {
    "personal_info": "Personal Information (names, addresses, phone numbers, emails)",
    "financial": "Financial Information (account numbers, credit cards, salaries)",
    "medical": "Medical/Health Information",
    "legal": "Legal/Privileged Information",
    "security": "Security-Sensitive Information",
    "commercial": "Commercial/Trade Secrets",
    "internal": "Internal Deliberations/Advice",
    "third_party": "Third-Party Personal Information",
}

# Map AI categories to FOI section codes (Canadian FIPPA/FOIPPA)
CATEGORY_TO_SECTION = {
    "personal_info": "S22",  # Personal information
    "third_party": "S22",  # Third-party personal information
    "financial": "S21",  # Financial/commercial harm
    "commercial": "S21",  # Commercial/trade secrets
    "medical": "S22",  # Medical is personal info
    "legal": "S14",  # Solicitor-client privilege
    "security": "S15",  # Harm to law enforcement/security
    "internal": "S13",  # Policy advice/recommendations
}


def _extract_json_from_response(response_text: str):
    """Best-effort JSON extraction from an LLM response. Handles markdown
    code fences, leading/trailing prose, and `raw_decode`-able prefixes.
    Returns the parsed Python object or raises json.JSONDecodeError."""
    # Strip markdown code fences.
    if "```json" in response_text:
        m = re.search(r"```json\s*(.*?)\s*```", response_text, re.DOTALL)
        if m:
            response_text = m.group(1)
    elif "```" in response_text:
        m = re.search(r"```\s*(.*?)\s*```", response_text, re.DOTALL)
        if m:
            response_text = m.group(1)

    # If there's prose before/after, locate the first JSON object/array.
    stripped = response_text.strip()
    if not stripped.startswith("{") and not stripped.startswith("["):
        m = re.search(r"[\{\[].*[\}\]]", response_text, re.DOTALL)
        if m:
            response_text = m.group(0)

    try:
        return json.loads(response_text.strip())
    except json.JSONDecodeError:
        # Fall back to raw_decode (handles trailing junk after valid JSON).
        decoder = json.JSONDecoder()
        try:
            obj, _idx = decoder.raw_decode(response_text.strip())
            return obj
        except json.JSONDecodeError:
            # Last resort regex fallbacks for the most common shapes.
            arr = re.search(
                r"\[(?:[^\[\]]|\[(?:[^\[\]]|\[[^\[\]]*\])*\])*\]",
                response_text,
                re.DOTALL,
            )
            if arr:
                return json.loads(arr.group(0))
            ob = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", response_text, re.DOTALL)
            if ob:
                return json.loads(ob.group(0))
            raise


async def get_redaction_suggestions(document_text: str, context: str = None) -> dict:
    """
    Analyze document text and suggest redactions using configured LLM provider.
    Uses jurisdiction-specific prompts from active pack.

    Args:
        document_text: The full text of the document
        context: Optional context about the document/case

    Returns:
        Dict with suggestions:
        {
            "suggestions": [
                {
                    "text": "text to redact",
                    "category": "personal_info",
                    "reason": "Contains personal name",
                    "confidence": "high"
                }
            ],
            "summary": "Overall analysis summary"
        }
    """
    # Get LLM client (works with any configured provider)
    llm_client = await get_llm_client()

    if not llm_client:
        logger.warning("No default LLM configured, returning empty suggestions")
        return {
            "suggestions": [],
            "summary": (
                "AI redaction suggestions unavailable - no default LLM is set. "
                "Visit Admin → LLM Configuration and click 'Set Default' on an enabled config."
            ),
            "error": "No default LLM configured",
        }

    try:
        # Load global prompts
        global_prompts = load_global_prompts()

        # Get AI prompts from active jurisdiction pack. Two pack shapes
        # are supported:
        #   - Legacy single-pass (Ontario MFIPPA, pre-2026-05 BC FIPPA):
        #     ai_prompts.redaction_analysis
        #   - Single-shot classification (BC FIPPA v2):
        #     ai_prompts.classification_pass (detection_pass is retained
        #     in the pack for documentation but not currently invoked —
        #     real two-pass was tried and reverted in 2026-05 because
        #     the doubled latency wasn't worth the recall improvement
        #     given how often operators iterate on prompts).
        from src.packs.loader import get_pack_ai_prompts

        ai_prompts = get_pack_ai_prompts()
        if "redaction_analysis" in ai_prompts:
            redaction_prompt = ai_prompts["redaction_analysis"]
        elif "classification_pass" in ai_prompts:
            redaction_prompt = ai_prompts["classification_pass"]
        else:
            redaction_prompt = {}

        # Get jurisdiction-specific system prompt
        jurisdiction_system_prompt = redaction_prompt.get(
            "system_prompt",
            "You are an expert FOI analyst. Analyze documents and identify information that should be redacted. "
            "You must respond with valid JSON only, no other text.",
        )

        # Build enhanced system prompt combining global + jurisdiction
        if global_prompts:
            system_prompt = build_enhanced_system_prompt(jurisdiction_system_prompt, global_prompts)
            logger.info("Using enhanced system prompt with global principles")
        else:
            system_prompt = jurisdiction_system_prompt
            logger.warning("Global prompts not loaded, using jurisdiction prompt only")

        # CRITICAL: Ensure JSON response is explicitly requested
        system_prompt += "\n\nCRITICAL: You MUST respond with ONLY valid JSON. No other text, explanations, or markdown. Just the raw JSON array."

        user_prompt_template = redaction_prompt.get(
            "user_prompt_template",
            "Analyze this document and suggest redactions. Return ONLY valid JSON in this format:\n"
            '{"suggestions": [{"text": "text to redact", "category": "personal_info", "reason": "explanation", "confidence": "high|medium|low"}], "summary": "overall analysis"}\n\n'
            "Document text:\n{document_text}",
        )

        # Build the user prompt with document text. Single-shot mode:
        # the {candidates} placeholder (if any) gets a short note —
        # detection is folded into the classification pass.
        user_prompt = user_prompt_template.replace("{document_text}", document_text[:4000])
        if "{candidates}" in user_prompt:
            user_prompt = user_prompt.replace("{candidates}", "")

        # Add context if provided
        if context:
            user_prompt += f"\n\nAdditional Context: {context}"

        # Reinforce JSON requirement at end of user prompt (must be last!)
        user_prompt += "\n\nREMINDER: Return ONLY the JSON array. Do not include any explanatory text before or after the JSON."

        # Get temperature and max_tokens from pack
        temperature = redaction_prompt.get("temperature", 0.3)
        max_tokens = redaction_prompt.get("max_tokens", 2000)

        # Call LLM API with configured provider
        logger.info(f"Using LLM provider: {llm_client.provider}, model: {llm_client.model}")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response_text = await llm_client.chat_completion(
            messages=messages, temperature=temperature, max_tokens=max_tokens
        )

        # Parse response
        logger.info(f"Raw LLM response length: {len(response_text)} chars")
        logger.info(f"Response preview: {response_text[:300]}...")
        result = _extract_json_from_response(response_text)

        # Handle both array and object responses
        if isinstance(result, list):
            # Some LLMs return an array directly instead of wrapped in an object
            logger.info("LLM returned array format, wrapping in expected structure")
            suggestions = result
            result = {
                "suggestions": suggestions,
                "summary": f"AI identified {len(suggestions)} potential redactions",
            }
        elif "suggestions" not in result and "text" in result:
            # LLM returned a single suggestion object instead of wrapped format
            logger.info("LLM returned single suggestion object, wrapping in array")
            suggestions = [result]
            result = {
                "suggestions": suggestions,
                "summary": f"AI identified {len(suggestions)} potential redaction",
            }
        else:
            suggestions = result.get("suggestions", [])

        # Normalize new-pack classification-pass schema to the legacy shape
        # the rest of the pipeline expects.
        #
        # New pack returns category="DISCLOSE" for audit-trail items the
        # model decided NOT to redact — strip those before passing to the
        # UI (they're not redaction suggestions).
        #
        # New pack returns reasoning_chain (list) + section_subsection
        # instead of a flat `reason` field; synthesize a `reason` for
        # downstream consumers, but preserve the rich fields for any
        # future UI that wants to surface them.
        disclosed_count = 0
        redaction_suggestions = []
        for s in suggestions:
            cat = (s.get("category") or "").upper()
            if cat == "DISCLOSE":
                disclosed_count += 1
                continue
            if "reason" not in s:
                chain = s.get("reasoning_chain") or []
                subsection = s.get("section_subsection") or ""
                severance = s.get("severance_note") or ""
                parts = [
                    p for p in (subsection, " | ".join(chain) if chain else "", severance) if p
                ]
                s["reason"] = " — ".join(parts) or "Exemption applies per FIPPA analysis"
            redaction_suggestions.append(s)
        if disclosed_count:
            logger.info(
                f"Classification pass disclosed {disclosed_count} candidate(s); "
                f"{len(redaction_suggestions)} redaction(s) remain"
            )
        suggestions = redaction_suggestions
        result["suggestions"] = suggestions

        # Add section codes to suggestions
        for suggestion in suggestions:
            category = suggestion.get("category", "personal_info")
            section_code = CATEGORY_TO_SECTION.get(category, "S22")
            suggestion["section"] = section_code
            suggestion["category_label"] = REDACTION_CATEGORIES.get(category, category)

        logger.info(f"Generated {len(suggestions)} redaction suggestions")

        return result

    except Exception as e:
        logger.error(f"Error getting AI redaction suggestions: {str(e)}")
        return {
            "suggestions": [],
            "summary": f"Error generating suggestions: {str(e)}",
            "error": str(e),
        }


def get_quick_pii_suggestions(document_text: str) -> list[dict]:
    """
    Enhanced PII detection using pattern matching.
    Detects emails, phones, addresses, names, IDs, and more.

    Returns list of suggestions with text, category, reason.
    """
    import re

    suggestions = []
    seen = set()  # Track what we've already found

    # Email pattern
    emails = re.findall(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", document_text)
    for email in set(emails):
        if email not in seen:
            suggestions.append(
                {
                    "text": email,
                    "category": "personal_info",
                    "section": "S22",
                    "reason": "Email address",
                    "confidence": "high",
                }
            )
            seen.add(email)

    # Phone numbers (North American format)
    phones = re.findall(
        r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}\b", document_text
    )
    for phone in set(phones):
        if (
            phone not in seen
            and len(
                phone.replace("-", "")
                .replace(".", "")
                .replace(" ", "")
                .replace("(", "")
                .replace(")", "")
            )
            >= 10
        ):
            suggestions.append(
                {
                    "text": phone,
                    "category": "personal_info",
                    "section": "S22",
                    "reason": "Phone number",
                    "confidence": "medium",
                }
            )
            seen.add(phone)

    # Canadian postal codes (A1A 1A1)
    postal_codes = re.findall(r"\b[A-Z]\d[A-Z]\s?\d[A-Z]\d\b", document_text, re.IGNORECASE)
    for postal in set(postal_codes):
        if postal not in seen:
            suggestions.append(
                {
                    "text": postal,
                    "category": "personal_info",
                    "section": "S22",
                    "reason": "Postal code",
                    "confidence": "high",
                }
            )
            seen.add(postal)

    # US ZIP codes (5 digits or ZIP+4)
    zip_codes = re.findall(r"\b\d{5}(?:-\d{4})?\b", document_text)
    for zip_code in set(zip_codes):
        if zip_code not in seen:
            suggestions.append(
                {
                    "text": zip_code,
                    "category": "personal_info",
                    "section": "S22",
                    "reason": "ZIP code",
                    "confidence": "medium",
                }
            )
            seen.add(zip_code)

    # Street addresses (number + street name pattern)
    # Matches: "123 Main Street", "900 Villa Street", "488 Maple Avenue"
    addresses = re.findall(
        r"\b\d+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Boulevard|Blvd|Way|Court|Ct|Circle|Cir)\b",
        document_text,
        re.IGNORECASE,
    )
    for address in set(addresses):
        if address not in seen:
            suggestions.append(
                {
                    "text": address,
                    "category": "personal_info",
                    "section": "S22",
                    "reason": "Street address",
                    "confidence": "high",
                }
            )
            seen.add(address)

    # Social Insurance Number (Canadian) - XXX-XXX-XXX
    sins = re.findall(r"\b\d{3}-\d{3}-\d{3}\b", document_text)
    for sin in set(sins):
        if sin not in seen:
            suggestions.append(
                {
                    "text": sin,
                    "category": "personal_info",
                    "section": "S22",
                    "reason": "Possible SIN",
                    "confidence": "high",
                }
            )
            seen.add(sin)

    # Credit card numbers (simplified)
    cards = re.findall(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b", document_text)
    for card in set(cards):
        if card not in seen:
            suggestions.append(
                {
                    "text": card,
                    "category": "financial",
                    "section": "S21",
                    "reason": "Possible credit card number",
                    "confidence": "medium",
                }
            )
            seen.add(card)

    # Tax/VAT IDs (various formats)
    # EU VAT: 2 letters + 8-12 digits
    vat_ids = re.findall(r"\b[A-Z]{2}\s?\d{8,12}\b", document_text)
    for vat in set(vat_ids):
        if vat not in seen:
            suggestions.append(
                {
                    "text": vat,
                    "category": "financial",
                    "section": "S21",
                    "reason": "Possible VAT/Tax ID",
                    "confidence": "medium",
                }
            )
            seen.add(vat)

    # Invoice/Receipt numbers (alphanumeric with dashes)
    invoice_ids = re.findall(r"\b[A-Z0-9]{4,}-[A-Z0-9]{4,}\b", document_text)
    for inv_id in set(invoice_ids):
        if inv_id not in seen:
            suggestions.append(
                {
                    "text": inv_id,
                    "category": "business",
                    "section": "S21",
                    "reason": "Invoice/Receipt number",
                    "confidence": "low",
                }
            )
            seen.add(inv_id)

    # Person names (Title + First + Last pattern)
    # Matches: "Mr. John Smith", "Dr. Jane Doe", etc.
    names_with_title = re.findall(
        r"\b(?:Mr|Mrs|Ms|Dr|Prof)\.?\s+[A-Z][a-z]+\s+[A-Z][a-z]+\b", document_text
    )
    for name in set(names_with_title):
        if name not in seen:
            suggestions.append(
                {
                    "text": name,
                    "category": "personal_info",
                    "section": "S22",
                    "reason": "Person name",
                    "confidence": "high",
                }
            )
            seen.add(name)

    # Capitalized names (First Last pattern) - more conservative
    # Only suggest if it appears in context like "Bill to:", "From:", etc.
    name_contexts = re.findall(
        r"(?:Bill to|From|To|Name|Contact):\s*([A-Z][a-z]+\s+[A-Z][a-z]+)",
        document_text,
        re.IGNORECASE,
    )
    for name in set(name_contexts):
        if name not in seen and len(name.split()) == 2:
            suggestions.append(
                {
                    "text": name,
                    "category": "personal_info",
                    "section": "S22",
                    "reason": "Person name",
                    "confidence": "medium",
                }
            )
            seen.add(name)

    return suggestions


def find_text_coordinates_in_pdf(pdf_content: bytes, search_text: str) -> list[dict]:
    """
    Find all occurrences of text in PDF and return their coordinates.
    Uses multiple strategies: exact match, normalized whitespace, and word-by-word.

    Args:
        pdf_content: Binary PDF content
        search_text: Text to search for

    Returns:
        List of dicts with page, x, y, width, height for each occurrence
    """
    try:
        doc = fitz.open(stream=pdf_content, filetype="pdf")
        results = []

        # Clean search text
        search_text = search_text.strip()

        # Log what we're searching for
        logger.info(
            f"Searching for text (length={len(search_text)}): {search_text[:100]}{'...' if len(search_text) > 100 else ''}"
        )

        for page_num in range(len(doc)):
            page = doc[page_num]

            # For debugging: show sample of PDF text on first page
            if page_num == 0:
                page_text = page.get_text()
                logger.info(f"PDF page 1 text sample (first 200 chars): {page_text[:200]}")

            # Strategy 1: Try exact match first
            text_instances = page.search_for(search_text, flags=fitz.TEXT_PRESERVE_WHITESPACE)

            if text_instances:
                for inst in text_instances:
                    results.append(
                        {
                            "page": page_num + 1,
                            "x": float(inst.x0),
                            "y": float(inst.y0),
                            "width": float(inst.x1 - inst.x0),
                            "height": float(inst.y1 - inst.y0),
                        }
                    )
                continue

            # Strategy 2: Try with normalized whitespace (collapse multiple spaces/newlines)
            normalized_search = " ".join(search_text.split())
            text_instances = page.search_for(normalized_search)

            if text_instances:
                for inst in text_instances:
                    results.append(
                        {
                            "page": page_num + 1,
                            "x": float(inst.x0),
                            "y": float(inst.y0),
                            "width": float(inst.x1 - inst.x0),
                            "height": float(inst.y1 - inst.y0),
                        }
                    )
                continue

            # Strategy 3: For multi-line suggestions, try splitting and finding each line
            if "\n" in search_text:
                lines = [line.strip() for line in search_text.split("\n") if line.strip()]
                if len(lines) > 1:
                    logger.info(f"Multi-line text detected. Lines: {lines}")

                    # Find first and last line
                    first_line_rects = page.search_for(lines[0])
                    last_line_rects = page.search_for(lines[-1])

                    logger.info(
                        f"Line matching results - First: {len(first_line_rects)} matches, Last: {len(last_line_rects)} matches"
                    )

                    if first_line_rects and last_line_rects:
                        # Create a bounding box from first to last line
                        first_rect = first_line_rects[0]
                        last_rect = last_line_rects[-1]

                        results.append(
                            {
                                "page": page_num + 1,
                                "x": float(min(first_rect.x0, last_rect.x0)),
                                "y": float(first_rect.y0),
                                "width": float(
                                    max(first_rect.x1, last_rect.x1)
                                    - min(first_rect.x0, last_rect.x0)
                                ),
                                "height": float(last_rect.y1 - first_rect.y0),
                            }
                        )
                        logger.info("Found multi-line text using line-by-line strategy")
                        continue

        doc.close()

        if results:
            logger.info(f"Found {len(results)} occurrences of text in PDF")
        else:
            logger.warning(
                "Text not found in PDF - likely a scanned/image-only document. Text was extracted via OCR but cannot be located for automatic redaction. Manual redaction required."
            )

        return results

    except Exception as e:
        logger.error(f"Error finding text coordinates: {str(e)}")
        return []


def enrich_suggestions_with_coordinates(
    suggestions: list[dict], pdf_content: bytes, text_data: dict = None
) -> list[dict]:
    """
    Add coordinates to AI suggestions by searching for text in PDF.
    Falls back to OCR text_data for image-based PDFs.

    Args:
        suggestions: List of AI suggestions
        pdf_content: Binary PDF content
        text_data: Optional OCR text data with coordinates (for image-based PDFs)

    Returns:
        Suggestions enriched with coordinates
    """
    enriched = []

    for suggestion in suggestions:
        text = suggestion.get("text", "")

        # Strategy 1: Try to find in PDF text
        coords = find_text_coordinates_in_pdf(pdf_content, text)

        # Strategy 2: If not found and we have OCR data, search there
        if not coords and text_data:
            coords = find_text_in_ocr_data(text, text_data)

        if coords:
            # Add each occurrence as a separate suggestion
            for coord in coords:
                enriched_suggestion = suggestion.copy()
                enriched_suggestion.update(
                    {
                        "page": coord["page"],
                        "coordinates": {
                            "x": coord["x"],
                            "y": coord["y"],
                            "width": coord["width"],
                            "height": coord["height"],
                        },
                        "has_coordinates": True,
                    }
                )
                enriched.append(enriched_suggestion)
        else:
            # Keep suggestion but mark as no coordinates found
            suggestion["has_coordinates"] = False
            suggestion["page"] = 1  # Default to page 1
            enriched.append(suggestion)

    return enriched


def find_text_in_ocr_data(search_text: str, text_data: dict) -> list[dict]:
    """
    Search for text in OCR data and return coordinates.
    Used for image-based PDFs where text isn't embedded.

    Args:
        search_text: Text to search for
        text_data: OCR data with pages, blocks, and coordinates

    Returns:
        List of coordinate dicts (one per occurrence)
    """
    import re

    # OCR words often carry trailing punctuation glued on by the tokenizer
    # ("555-0188." for a phone at the end of a sentence) and surrounding
    # brackets/quotes. Strip them so an AI suggestion of "555-0188" still
    # matches the OCR word "555-0188.".
    _edge_punct_re = re.compile(r'(?:^[(\[{"\'""]+|[.,;:!?)\]}"\'""]+$)')

    def _strip_edge_punct(s: str) -> str:
        return _edge_punct_re.sub("", s)

    results: list[dict] = []
    search_lower = search_text.lower().strip()
    if not search_lower:
        return results

    for page_data in text_data.get("pages", []):
        page_num = page_data.get("page_num", 1)
        page_text = (page_data.get("text") or "").lower()

        # Quick reject: text isn't on this page at all.
        if search_lower not in page_text:
            continue

        words = page_data.get("words", [])
        blocks = page_data.get("blocks", [])

        page_hits: list[dict] = []

        # Pass 1: single-word exact match (after edge-punctuation strip).
        # Catches the common case — phones, SSNs, emails, single names — and
        # avoids the multi-word algorithm's over-greedy substring trap.
        if words:
            for w in words:
                wt = _strip_edge_punct((w.get("text") or "").lower())
                if wt == search_lower:
                    bbox = w["bbox"]
                    page_hits.append(
                        {
                            "page": page_num,
                            "x": float(bbox[0]),
                            "y": float(bbox[1]),
                            "width": float(bbox[2] - bbox[0]),
                            "height": float(bbox[3] - bbox[1]),
                        }
                    )

            # Pass 2: multi-word exact match — find the smallest consecutive
            # window of words whose space-joined edge-stripped text equals
            # the search text. Only runs if Pass 1 returned nothing.
            if not page_hits:
                for i in range(len(words)):
                    combined = ""
                    min_x = min_y = float("inf")
                    max_x = max_y = float("-inf")
                    for j in range(i, len(words)):
                        wt = _strip_edge_punct((words[j].get("text") or "").lower())
                        combined = f"{combined} {wt}".strip() if combined else wt
                        bbox = words[j]["bbox"]
                        min_x, min_y = min(min_x, bbox[0]), min(min_y, bbox[1])
                        max_x, max_y = max(max_x, bbox[2]), max(max_y, bbox[3])
                        if combined == search_lower:
                            page_hits.append(
                                {
                                    "page": page_num,
                                    "x": float(min_x),
                                    "y": float(min_y),
                                    "width": float(max_x - min_x),
                                    "height": float(max_y - min_y),
                                }
                            )
                            break
                        if len(combined) >= len(search_lower):
                            break

            # Pass 3: single-word substring match (OCR glued chars on one
            # side that edge-strip missed). Lower-confidence than Pass 1/2.
            if not page_hits:
                for w in words:
                    wt = _strip_edge_punct((w.get("text") or "").lower())
                    if search_lower in wt:
                        bbox = w["bbox"]
                        page_hits.append(
                            {
                                "page": page_num,
                                "x": float(bbox[0]),
                                "y": float(bbox[1]),
                                "width": float(bbox[2] - bbox[0]),
                                "height": float(bbox[3] - bbox[1]),
                            }
                        )
                        break

        # Fallback: no word-level data — return a block bbox. This is
        # coarse (whole paragraph) but better than nothing for review.
        if not page_hits and blocks:
            for block in blocks:
                block_text = (block.get("text") or "").lower()
                if search_lower in block_text:
                    bbox = block.get("bbox") or []
                    if len(bbox) == 4:
                        page_hits.append(
                            {
                                "page": page_num,
                                "x": float(bbox[0]),
                                "y": float(bbox[1]),
                                "width": float(bbox[2] - bbox[0]),
                                "height": float(bbox[3] - bbox[1]),
                            }
                        )

        results.extend(page_hits)

    if results:
        logger.info(f"Found {len(results)} occurrences of '{search_text}' in OCR data")
    else:
        logger.warning(f"Text '{search_text}' not found in OCR data")

    return results
