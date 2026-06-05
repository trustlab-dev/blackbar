import logging

import fitz  # PyMuPDF
import pytesseract
from PIL import Image

logger = logging.getLogger(__name__)


async def extract_text_with_coordinates(pdf_content: bytes) -> dict:
    """
    Extract text from PDF with page and coordinate information.
    Enhanced to return word-level and line-level data for text selection.

    Returns: {
        "pages": [
            {
                "page_num": 1,
                "text": "full page text",
                "width": 612.0,  # NEW: Page dimensions
                "height": 792.0,
                "blocks": [{"text": "word", "bbox": [x0, y0, x1, y1], "confidence": 0.95}],
                "words": [  # NEW: Word-level data for text selection
                    {"text": "word", "bbox": [x0, y0, x1, y1], "confidence": 0.95,
                     "line_num": 1, "word_num": 1}
                ],
                "lines": [  # NEW: Line-level grouping
                    {"text": "full line text", "bbox": [x0, y0, x1, y1], "line_num": 1}
                ]
            }
        ],
        "full_text": "entire document text"
    }
    """
    pdf_document = fitz.open("pdf", pdf_content)
    result = {"pages": [], "full_text": ""}

    for page_num, page in enumerate(pdf_document, 1):
        # Get page dimensions
        page_rect = page.rect

        page_data = {
            "page_num": page_num,
            "text": "",
            "width": float(page_rect.width),
            "height": float(page_rect.height),
            "blocks": [],
            "words": [],  # NEW: Word-level data
            "lines": [],  # NEW: Line-level data
        }

        # Try native text extraction first
        text_dict = page.get_text("dict")

        # Check if there's meaningful native text
        has_native_text = False
        if text_dict.get("blocks"):
            for block in text_dict["blocks"]:
                if block.get("lines"):
                    has_native_text = True
                    break

        if has_native_text:
            # Has native text - extract with coordinates at word and line level
            line_num = 0
            word_num = 0

            for block in text_dict["blocks"]:
                if "lines" in block:
                    for line in block["lines"]:
                        line_num += 1
                        line_text = ""
                        line_bbox = None
                        line_words = []

                        for span in line["spans"]:
                            span_text = span["text"]
                            span_bbox = span["bbox"]

                            # Add to blocks (legacy format)
                            page_data["blocks"].append(
                                {
                                    "text": span_text,
                                    "bbox": list(span_bbox),
                                    "font": span.get("font", ""),
                                    "size": span.get("size", 0),
                                    "confidence": 1.0,
                                }
                            )

                            # NEW: Split span into words for word-level data
                            words_in_span = span_text.split()
                            span_width = span_bbox[2] - span_bbox[0]
                            avg_word_width = (
                                span_width / len(words_in_span) if words_in_span else span_width
                            )

                            for i, word in enumerate(words_in_span):
                                word_num += 1
                                # Approximate word bbox (PDF.js doesn't give us word-level natively)
                                word_x0 = span_bbox[0] + (i * avg_word_width)
                                word_x1 = word_x0 + avg_word_width
                                word_bbox = [word_x0, span_bbox[1], word_x1, span_bbox[3]]

                                word_data = {
                                    "text": word,
                                    "bbox": word_bbox,
                                    "confidence": 1.0,
                                    "line_num": line_num,
                                    "word_num": word_num,
                                }
                                page_data["words"].append(word_data)
                                line_words.append(word_data)

                            line_text += span_text + " "

                            # Expand line bbox
                            if line_bbox is None:
                                line_bbox = list(span_bbox)
                            else:
                                line_bbox[0] = min(line_bbox[0], span_bbox[0])
                                line_bbox[1] = min(line_bbox[1], span_bbox[1])
                                line_bbox[2] = max(line_bbox[2], span_bbox[2])
                                line_bbox[3] = max(line_bbox[3], span_bbox[3])

                        # NEW: Add line-level data
                        if line_bbox:
                            page_data["lines"].append(
                                {
                                    "text": line_text.strip(),
                                    "bbox": line_bbox,
                                    "line_num": line_num,
                                    "words": line_words,
                                }
                            )

                        page_data["text"] += line_text
        else:
            # No native text - use OCR
            logger.info(f"No native text on page {page_num}, using OCR")

            # Get page dimensions in PDF points
            page_rect = page.rect
            pdf_width = page_rect.width
            pdf_height = page_rect.height

            # Render at 300 DPI for better OCR
            pix = page.get_pixmap(dpi=300)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            # Calculate scale factor to convert OCR coords back to PDF points
            # OCR coordinates are in pixels at 300 DPI, PDF is at 72 DPI
            scale_x = pdf_width / pix.width
            scale_y = pdf_height / pix.height

            # OCR with detailed output
            ocr_data = pytesseract.image_to_data(
                img, output_type=pytesseract.Output.DICT, lang="eng"
            )

            # Group OCR results by line
            current_line_num = None
            line_words = []
            line_text = ""
            line_bbox = None
            line_num = 0
            word_num = 0

            for i, text in enumerate(ocr_data["text"]):
                if text.strip():
                    confidence = float(ocr_data["conf"][i]) / 100.0
                    if confidence > 0.5:  # Only include confident results
                        # Convert OCR pixel coordinates to PDF points
                        bbox = [
                            ocr_data["left"][i] * scale_x,
                            ocr_data["top"][i] * scale_y,
                            (ocr_data["left"][i] + ocr_data["width"][i]) * scale_x,
                            (ocr_data["top"][i] + ocr_data["height"][i]) * scale_y,
                        ]

                        # Add to blocks (legacy format)
                        page_data["blocks"].append(
                            {"text": text, "bbox": bbox, "confidence": confidence}
                        )

                        # Track line changes
                        this_line_num = ocr_data["line_num"][i]
                        if current_line_num != this_line_num:
                            # Save previous line if exists
                            if line_words and line_bbox:
                                line_num += 1
                                page_data["lines"].append(
                                    {
                                        "text": line_text.strip(),
                                        "bbox": line_bbox,
                                        "line_num": line_num,
                                        "words": line_words,
                                    }
                                )

                            # Start new line
                            current_line_num = this_line_num
                            line_words = []
                            line_text = ""
                            line_bbox = None

                        # NEW: Add word-level data
                        word_num += 1
                        word_data = {
                            "text": text,
                            "bbox": bbox,
                            "confidence": confidence,
                            "line_num": line_num + 1,  # Next line number
                            "word_num": word_num,
                        }
                        page_data["words"].append(word_data)
                        line_words.append(word_data)
                        line_text += text + " "

                        # Expand line bbox
                        if line_bbox is None:
                            line_bbox = list(bbox)
                        else:
                            line_bbox[0] = min(line_bbox[0], bbox[0])
                            line_bbox[1] = min(line_bbox[1], bbox[1])
                            line_bbox[2] = max(line_bbox[2], bbox[2])
                            line_bbox[3] = max(line_bbox[3], bbox[3])

                        page_data["text"] += text + " "

            # Add final line
            if line_words and line_bbox:
                line_num += 1
                page_data["lines"].append(
                    {
                        "text": line_text.strip(),
                        "bbox": line_bbox,
                        "line_num": line_num,
                        "words": line_words,
                    }
                )

        result["pages"].append(page_data)
        result["full_text"] += page_data["text"] + "\n"

    pdf_document.close()
    return result


def get_text_summary(text_data: dict) -> str:
    """Generate a brief summary of extracted text."""
    full_text = text_data.get("full_text", "")
    word_count = len(full_text.split())
    page_count = len(text_data.get("pages", []))

    if word_count == 0:
        return "No text extracted from document"
    elif word_count < 50:
        return f"Short document: {word_count} words across {page_count} page(s)"
    else:
        # Return first 200 characters as preview
        preview = full_text[:200].strip()
        return f"{preview}... ({word_count} words, {page_count} pages)"
