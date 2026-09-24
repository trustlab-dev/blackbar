# backend/src/utils/conversion.py
import email
import hashlib
import io
import logging
import mimetypes
import os
import re
import subprocess
import tempfile
import unicodedata
import uuid
from email.header import Header
from email.message import Message
from typing import Any

import fitz  # PyMuPDF
import pytesseract
from PIL import Image
from reportlab.pdfgen import canvas

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Configure pytesseract path if needed (especially on Windows)
def configure_tesseract():
    """Configure Tesseract OCR path based on environment or common locations"""
    tesseract_path = os.getenv("TESSERACT_PATH")
    if tesseract_path and os.path.exists(tesseract_path):
        pytesseract.pytesseract.tesseract_cmd = tesseract_path
    elif os.path.exists(r"C:\Program Files\Tesseract-OCR\tesseract.exe"):
        pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    elif os.path.exists(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
        pytesseract.pytesseract.tesseract_cmd = (
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"
        )


# Call this at module initialization
configure_tesseract()


# =============================================================================
# Attachment storage (DOC-01 / DOC-18)
# =============================================================================

# Extensions `convert_to_pdf` knows how to handle. An extracted attachment is
# written to disk as `<uuid><ext>` where `ext` is taken from this allow-list;
# anything else is stored as `.bin` (and later reported as unsupported).
SUPPORTED_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".eml",
        ".msg",
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".bmp",
        ".tiff",
        ".tif",
        ".webp",
    }
)
MAX_DISPLAY_NAME_LENGTH = 200


def safe_display_name(name: object, fallback: str) -> str:
    """Return a sender-supplied attachment name that is safe to display.

    The result is only ever shown to users and stored as metadata; it is
    never used as a filesystem path. Directory components (POSIX and
    Windows separators) and control characters are removed and the length
    is capped, keeping the extension.
    """
    if not isinstance(name, str):
        return fallback
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C").strip()
    if name in ("", ".", ".."):
        return fallback
    if len(name) > MAX_DISPLAY_NAME_LENGTH:
        stem, ext = os.path.splitext(name)
        ext = ext[:16]
        name = stem[: MAX_DISPLAY_NAME_LENGTH - len(ext)] + ext
    return name


def _safe_extension(display_name: str, content_type: str | None) -> str:
    ext = os.path.splitext(display_name)[1].lower()
    if ext in SUPPORTED_EXTENSIONS:
        return ext
    if content_type:
        guessed = (mimetypes.guess_extension(content_type) or "").lower()
        if guessed in SUPPORTED_EXTENSIONS:
            return guessed
    return ".bin"


def write_attachment(
    output_dir: str, display_name: str, data: bytes, content_type: str | None
) -> str:
    """Write attachment bytes under a generated name inside `output_dir`.

    The sender-controlled filename never reaches the filesystem, so `../`,
    absolute and Windows-style names cannot escape the work directory and
    two attachments with the same name cannot overwrite each other.
    """
    base = os.path.realpath(output_dir)
    path = os.path.join(base, f"{uuid.uuid4().hex}{_safe_extension(display_name, content_type)}")
    # Defence in depth: the generated path must stay inside the work dir.
    if os.path.commonpath([base, os.path.realpath(path)]) != base:
        raise ValueError(f"Refusing to write attachment outside {base}")
    with open(path, "xb") as f:
        f.write(data)
    return path


def _header_value(value: object) -> str | None:
    """Collapse a header value to one line; None for missing/non-string values."""
    if isinstance(value, Header):
        value = str(value)
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value or None


def _email_text_header(
    from_address: str,
    to_address: str,
    date: str,
    subject: str,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> str:
    text = f"From: {from_address}\nTo: {to_address}\nDate: {date}\nSubject: {subject}\n"
    # Threading headers go into the extracted text so
    # `email_threads.extract_thread_identifiers` can populate them.
    if in_reply_to:
        text += f"In-Reply-To: {in_reply_to}\n"
    if references:
        text += f"References: {references}\n"
    return text + "\n"


def _dropped_attachment_marker(display_name: str, reason: str) -> str:
    logger.warning(f"Attachment not extracted: {display_name!r} ({reason})")
    return f"\n[ATTACHMENT NOT EXTRACTED: {display_name} ({reason})]\n"


# =============================================================================
# Email PDF layout (DOC-06)
# =============================================================================


def _printable(text: str) -> str:
    """Replace tabs and control characters so they render as spacing."""
    text = text.replace("\t", "    ")
    return "".join(" " if unicodedata.category(ch) == "Cc" else ch for ch in text)


def _wrap_to_width(text: str, fontname: str, fontsize: float, max_width: float) -> list[str]:
    """Greedy word wrap measured in points; overlong words are split."""

    def width(s: str) -> float:
        return fitz.get_text_length(s, fontname=fontname, fontsize=fontsize)

    lines: list[str] = []
    current, current_w = "", 0.0
    for token in re.findall(r"\S+|\s+", text):
        token_w = width(token)
        if current_w + token_w <= max_width:
            current += token
            current_w += token_w
            continue
        if token.isspace():
            lines.append(current.rstrip())
            current, current_w = "", 0.0
            continue
        if current.strip():
            lines.append(current.rstrip())
        current, current_w = "", 0.0
        for ch in token:
            ch_w = width(ch)
            if current and current_w + ch_w > max_width:
                lines.append(current)
                current, current_w = "", 0.0
            current += ch
            current_w += ch_w
    lines.append(current.rstrip())
    return lines


class EmailPdfWriter:
    """Lays out email text on Letter pages without writing past any edge.

    Every line is wrapped to the printable width and a new page is started
    before the baseline would cross the bottom margin, so all text in the
    content stream is visible (and therefore reviewable and redactable).
    """

    PAGE_WIDTH = 612
    PAGE_HEIGHT = 792
    MARGIN = 40

    def __init__(self) -> None:
        self.doc = fitz.open()
        self.page = self.doc.new_page(width=self.PAGE_WIDTH, height=self.PAGE_HEIGHT)
        self.y = float(self.MARGIN)

    @property
    def max_width(self) -> float:
        return self.PAGE_WIDTH - 2 * self.MARGIN

    @property
    def bottom(self) -> float:
        return self.PAGE_HEIGHT - self.MARGIN

    def _new_page(self) -> None:
        self.page = self.doc.new_page(width=self.PAGE_WIDTH, height=self.PAGE_HEIGHT)
        self.y = float(self.MARGIN)

    def new_page(self) -> None:
        self._new_page()

    def space(self, height: float) -> None:
        self.y += height

    def ensure_space(self, height: float) -> None:
        if self.y + height > self.bottom:
            self._new_page()

    def write(
        self,
        text: str,
        fontsize: float = 10,
        fontname: str = "helv",
        line_height: float = 14,
    ) -> None:
        """Write text (may contain newlines), wrapping and paginating."""
        for source_line in text.split("\n"):
            for line in _wrap_to_width(_printable(source_line), fontname, fontsize, self.max_width):
                if self.y > self.bottom:
                    self._new_page()
                if line:
                    self.page.insert_text(
                        (self.MARGIN, self.y), line, fontsize=fontsize, fontname=fontname
                    )
                self.y += line_height

    def insert_image(self, width: float, height: float, filename: str) -> None:
        self.ensure_space(height)
        rect = fitz.Rect(self.MARGIN, self.y, self.MARGIN + width, self.y + height)
        self.page.insert_image(rect, filename=filename)
        self.y += height + 10

    def save(self, output_file: str) -> None:
        self.doc.save(output_file)
        self.doc.close()


def _write_attachment_summary(writer: EmailPdfWriter, attachment_info: list[dict]) -> None:
    writer.new_page()
    writer.write("Attachments:", fontsize=12, fontname="hebo", line_height=20)
    for i, attachment in enumerate(attachment_info, 1):
        size_kb = attachment["size"] / 1024
        writer.write(
            f"{i}. {attachment['filename']} ({attachment['mime_type']}, {size_kb:.1f} KB)",
            line_height=15,
        )


def convert_office_to_pdf(input_file: str, output_dir: str) -> str:
    """
    Converts Office files (DOCX, PPTX, XLSX, DOC, PPT, XLS) to PDF using LibreOffice in headless mode.
    """
    try:
        command = [
            "libreoffice",
            "--headless",
            "--convert-to",
            "pdf",
            input_file,
            "--outdir",
            output_dir,
        ]
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
        base = os.path.splitext(os.path.basename(input_file))[0]
        pdf_path = os.path.join(output_dir, base + ".pdf")
        if not os.path.exists(pdf_path):
            raise Exception(f"Office to PDF conversion failed. Output: {result.stderr}")
        return pdf_path
    except subprocess.TimeoutExpired:
        raise Exception("Office to PDF conversion timed out after 60 seconds")
    except Exception as e:
        logger.error(f"Error converting Office file to PDF: {str(e)}")
        raise


# Keep old function for backward compatibility
def convert_docx_to_pdf(input_file: str, output_dir: str) -> str:
    """
    Converts a DOCX file to PDF using LibreOffice in headless mode.
    (Wrapper for convert_office_to_pdf for backward compatibility)
    """
    return convert_office_to_pdf(input_file, output_dir)


def convert_image_to_pdf(input_file: str, output_dir: str) -> str:
    """
    Converts an image file (JPG, PNG, GIF, BMP, TIFF) to PDF.
    Maintains aspect ratio and fits to letter size.
    """
    try:
        from reportlab.lib.pagesizes import letter

        # Open and process the image. Phase 4 Batch 4.4 (audit B51):
        # use a `with` block so Pillow closes the file handle eagerly
        # instead of relying on GC. Only the dimensions are needed
        # outside the block since `c.drawImage(input_file, ...)` below
        # reads from the path directly.
        with Image.open(input_file) as img:
            # Convert to RGB if necessary (for PNG with transparency, etc.)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

            # Get image dimensions
            img_width, img_height = img.size

        # Letter size dimensions
        page_width, page_height = letter

        # Calculate scaling to fit image on page while maintaining aspect ratio
        width_ratio = page_width / img_width
        height_ratio = page_height / img_height
        scale = min(width_ratio, height_ratio) * 0.95  # 95% to add small margin

        new_width = img_width * scale
        new_height = img_height * scale

        # Center the image on the page
        x_offset = (page_width - new_width) / 2
        y_offset = (page_height - new_height) / 2

        # Create PDF
        base = os.path.splitext(os.path.basename(input_file))[0]
        pdf_path = os.path.join(output_dir, base + ".pdf")

        c = canvas.Canvas(pdf_path, pagesize=letter)
        c.drawImage(input_file, x_offset, y_offset, width=new_width, height=new_height)
        c.save()

        logger.info(f"Converted image {input_file} to PDF: {pdf_path}")
        return pdf_path

    except Exception as e:
        logger.error(f"Error converting image to PDF: {str(e)}")
        raise


def convert_eml_to_pdf(input_file: str, output_file: str) -> tuple:
    """
    Converts an EML file to PDF by extracting its text content and writing it to a PDF using ReportLab.
    Also extracts any attachments and returns their paths.

    Returns:
        tuple: (pdf_path, [attachment_paths], extracted_text)
    """
    from html.parser import HTMLParser

    class HTMLStripper(HTMLParser):
        def __init__(self):
            super().__init__()
            self.reset()
            self.strict = False
            self.convert_charrefs = True
            self.text = []
            self.in_style = False
            self.in_script = False

        def handle_starttag(self, tag, attrs):
            if tag.lower() == "style":
                self.in_style = True
            elif tag.lower() == "script":
                self.in_script = True
            elif tag.lower() == "br":
                self.text.append("\n")
            elif tag.lower() == "p":
                self.text.append("\n")
            elif tag.lower() == "img":
                # Preserve image markers
                attrs_dict = dict(attrs)
                src = attrs_dict.get("src", "")
                if "[[IMAGE:" in src:
                    # Already marked, preserve it
                    self.text.append(src)

        def handle_endtag(self, tag):
            if tag.lower() == "style":
                self.in_style = False
            elif tag.lower() == "script":
                self.in_script = False
            elif tag.lower() in ["p", "div"]:
                self.text.append("\n")

        def handle_data(self, d):
            if not self.in_style and not self.in_script:
                self.text.append(d)

        def get_data(self):
            # Clean up multiple newlines
            text = "".join(self.text)
            text = re.sub(r"\n\s*\n+", "\n\n", text)
            return text.strip()

    def strip_html(html_text):
        """Remove HTML tags and CSS from text"""
        s = HTMLStripper()
        try:
            s.feed(html_text)
            return s.get_data()
        except:
            return html_text

    with open(input_file, "rb") as f:
        msg = email.message_from_binary_file(f)

    # Extract email headers
    from_address = msg.get("From", "Unknown")
    to_address = msg.get("To", "Unknown")
    subject = msg.get("Subject", "No Subject")
    date = msg.get("Date", "Unknown")
    message_id = msg.get("Message-ID", None)  # For deduplication

    # Start with email metadata
    text = _email_text_header(
        from_address,
        to_address,
        date,
        subject,
        in_reply_to=_header_value(msg.get("In-Reply-To")),
        references=_header_value(msg.get("References")),
    )

    # Extract attachments and inline images
    attachment_info = []
    inline_images = {}  # Map Content-ID to image data
    output_dir = os.path.dirname(output_file)
    body_found = False
    html_body = None

    def walk_parts(part: Any):
        """Like Message.walk(), but a forwarded message (message/rfc822) is
        yielded as one part instead of being flattened into this email."""
        yield part
        if part.get_content_type() == "message/rfc822":
            return
        if part.is_multipart():
            for sub in part.get_payload():
                yield from walk_parts(sub)

    def save_attachment(display: str, data: bytes, mime: str) -> None:
        path = write_attachment(output_dir, display, data, mime)
        attachment_info.append(
            {
                "filename": display,
                "path": path,
                "mime_type": mime,
                "size": len(data),
            }
        )

    # Process message parts
    if msg.is_multipart():
        for part in walk_parts(msg):
            content_disposition = part.get("Content-Disposition", "")
            content_type = part.get_content_type()
            content_id = part.get("Content-ID", "").strip("<>")

            # Forwarded message: keep it whole as an .eml attachment so it is
            # converted (and its own attachments extracted) as a child record.
            if content_type == "message/rfc822":
                payload = part.get_payload()
                inner = payload[0] if isinstance(payload, list) and payload else None
                inner_subject = _header_value(inner.get("Subject")) if inner is not None else None
                display = safe_display_name(
                    part.get_filename(),
                    safe_display_name(inner_subject, "forwarded_message") + ".eml",
                )
                if not display.lower().endswith(".eml"):
                    display += ".eml"
                try:
                    if inner is None:
                        raise ValueError("empty message/rfc822 part")
                    save_attachment(display, inner.as_bytes(), "message/rfc822")
                    text += f"\n[ATTACHMENT: {display}]\n"
                except Exception as e:
                    text += _dropped_attachment_marker(display, str(e))
                continue

            # Handle text/plain parts (email body)
            if content_type == "text/plain" and "attachment" not in content_disposition:
                charset = part.get_content_charset() or "utf-8"
                body_text = part.get_payload(decode=True).decode(charset, errors="ignore")
                text += body_text + "\n"
                body_found = True

            # Handle text/html parts - save for inline image processing
            elif content_type == "text/html" and "attachment" not in content_disposition:
                charset = part.get_content_charset() or "utf-8"
                html_body = part.get_payload(decode=True).decode(charset, errors="ignore")
                if not body_found:
                    # Strip HTML tags for text version
                    body_text = strip_html(html_body)
                    text += body_text + "\n"

                # Extract base64-encoded inline images from HTML
                import base64

                base64_pattern = r'<img[^>]+src="data:image/([^;]+);base64,([^"]+)"'
                for match in re.finditer(base64_pattern, html_body):
                    img_format = match.group(1)
                    img_data_b64 = match.group(2)
                    try:
                        img_data = base64.b64decode(img_data_b64)
                        img_id = f"base64_{len(inline_images)}"
                        inline_images[img_id] = {
                            "data": img_data,
                            "mime_type": f"image/{img_format}",
                        }
                        logger.info(f"Found base64 inline image: {img_id}")
                    except Exception as e:
                        logger.warning(f"Could not decode base64 image: {e}")

            # Handle inline images (multipart/related with Content-ID)
            elif content_type.startswith("image/") and content_id:
                try:
                    image_data = part.get_payload(decode=True)
                    inline_images[content_id] = {"data": image_data, "mime_type": content_type}
                    logger.info(f"Found inline image with CID: {content_id}")
                except Exception as e:
                    logger.warning(f"Could not extract inline image {content_id}: {e}")

            # Handle attachments
            elif "attachment" in content_disposition or (
                content_type.startswith("application/")
                or (content_type.startswith("image/") and not content_id)
            ):
                # The sender-supplied name is display metadata only; the
                # bytes are written under a generated name (DOC-01).
                display = safe_display_name(
                    part.get_filename(), f"unknown_attachment_{uuid.uuid4()}"
                )
                data = part.get_payload(decode=True)
                if data is None:
                    text += _dropped_attachment_marker(display, "no decodable content")
                    continue
                save_attachment(display, data, content_type)

                # Add attachment info to email text
                text += f"\n[ATTACHMENT: {display}]\n"
    else:
        # Non-multipart email - just get the body
        charset = msg.get_content_charset() or "utf-8"
        body_text = msg.get_payload(decode=True).decode(charset, errors="ignore")
        # Check if it's HTML and strip tags
        if msg.get_content_type() == "text/html":
            body_text = strip_html(body_text)
        text += body_text

    # Render the PDF. EmailPdfWriter wraps every line to the page width and
    # paginates, so no text is placed outside the visible page (DOC-06).
    writer = EmailPdfWriter()
    writer.write(f"From: {from_address}")
    writer.write(f"To: {to_address}")
    writer.write(f"Date: {date}")
    writer.write(f"Subject: {subject}")
    writer.space(14)  # Extra space before body

    # If we have HTML with inline images, parse and render with images
    if html_body and inline_images:
        # Replace CID references with placeholders
        for cid in inline_images.keys():
            if not cid.startswith("base64_"):
                html_body = html_body.replace(f'src="cid:{cid}"', f'src="[[IMAGE:{cid}]]"')

        # Parse HTML and insert text/images
        # Strip HTML but keep image markers
        text_with_markers = strip_html(html_body)

        # Split by image markers and insert text + images
        parts = re.split(r"\[\[IMAGE:([^\]]+)\]\]", text_with_markers)

        for i, part in enumerate(parts):
            if i % 2 == 0:
                # Text part
                if part.strip():
                    writer.write(part.strip())
            else:
                # Image marker - insert actual image
                img_id = part
                if img_id in inline_images:
                    try:
                        img_bytes = io.BytesIO(inline_images[img_id]["data"])
                        img = Image.open(img_bytes)

                        # Convert to RGB if necessary
                        if img.mode not in ("RGB", "L"):
                            img = img.convert("RGB")

                        # Run OCR on the image to extract text
                        try:
                            img_text = pytesseract.image_to_string(img)
                            if img_text.strip():
                                logger.info(
                                    f"Extracted {len(img_text)} characters from inline image {img_id}"
                                )
                                # Add OCR text to the email text so it's searchable
                                text += f"\n[Image text: {img_text.strip()}]\n"
                        except Exception as ocr_err:
                            logger.warning(f"Could not OCR inline image {img_id}: {ocr_err}")

                        # Calculate scaling
                        img_width, img_height = img.size
                        max_width = writer.max_width
                        max_height = 400

                        width_ratio = max_width / img_width
                        height_ratio = max_height / img_height
                        scale = min(width_ratio, height_ratio, 1.0)

                        new_width = img_width * scale
                        new_height = img_height * scale

                        # Save temp image
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                            img.save(tmp.name, "PNG")
                            temp_img_path = tmp.name

                        try:
                            writer.insert_image(new_width, new_height, temp_img_path)
                        finally:
                            os.unlink(temp_img_path)

                    except Exception as e:
                        logger.warning(f"Could not embed inline image {img_id}: {e}")
                        writer.write(f"[Image: {img_id}]")
    else:
        # No inline images or no HTML - just render text
        writer.write(text)

    # Add attachment summary at the end
    if attachment_info:
        _write_attachment_summary(writer, attachment_info)

    # Save the PDF
    writer.save(output_file)

    if not os.path.exists(output_file):
        raise Exception("EML to PDF conversion failed.")

    # Return PDF path, attachments, extracted text, and message_id
    return (output_file, attachment_info, text, message_id)


def extract_text_from_pdf(pdf_content: bytes) -> str:
    """Extract text from PDF using both native text extraction and OCR if needed.

    Args:
        pdf_content: Binary PDF content

    Returns:
        Extracted text from the PDF
    """
    try:
        # Try native text extraction first
        doc = fitz.open(stream=pdf_content, filetype="pdf")
        text = ""
        has_text = False

        # First pass - try to extract text directly
        for page_num, page in enumerate(doc):
            page_text = page.get_text()
            if page_text.strip():
                has_text = True
                text += f"\n--- Page {page_num + 1} ---\n{page_text}"

        # If no text was extracted, try OCR
        if not has_text or len(text.strip()) < 100:  # Assume it's an image PDF if very little text
            logger.info("No text found in PDF or very little text, attempting OCR...")
            text = ""
            for page_num, page in enumerate(doc):
                # Render page to image at higher DPI for better OCR results
                pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                img = Image.open(io.BytesIO(pix.pil_tobytes(format="PNG")))

                # Use pytesseract for OCR
                page_text = pytesseract.image_to_string(img)
                if page_text.strip():
                    text += f"\n--- Page {page_num + 1} ---\n{page_text}"

        doc.close()
        return text if text.strip() else "No text could be extracted from this document."

    except Exception as e:
        logger.error(f"Error extracting text from PDF: {str(e)}")
        return f"Error extracting text: {str(e)}"


def convert_msg_to_pdf(input_file: str, output_file: str) -> tuple:
    """
    Converts an MSG (Outlook) file to PDF by extracting its content.
    Also extracts any attachments and returns their paths.

    Returns:
        tuple: (pdf_path, [attachment_paths], extracted_text)
    """
    try:
        import extract_msg
    except ImportError:
        raise Exception("extract-msg library not installed. Run: pip install extract-msg")

    from html.parser import HTMLParser

    class HTMLStripper(HTMLParser):
        def __init__(self):
            super().__init__()
            self.reset()
            self.strict = False
            self.convert_charrefs = True
            self.text = []
            self.in_style = False
            self.in_script = False

        def handle_starttag(self, tag, attrs):
            if tag.lower() == "style":
                self.in_style = True
            elif tag.lower() == "script":
                self.in_script = True
            elif tag.lower() == "br":
                self.text.append("\n")
            elif tag.lower() == "p":
                self.text.append("\n")

        def handle_endtag(self, tag):
            if tag.lower() == "style":
                self.in_style = False
            elif tag.lower() == "script":
                self.in_script = False
            elif tag.lower() in ["p", "div"]:
                self.text.append("\n")

        def handle_data(self, d):
            if not self.in_style and not self.in_script:
                self.text.append(d)

        def get_data(self):
            # Clean up multiple newlines
            text = "".join(self.text)
            text = re.sub(r"\n\s*\n+", "\n\n", text)
            return text.strip()

    def strip_html(html_text):
        """Remove HTML tags and CSS from text"""
        s = HTMLStripper()
        try:
            s.feed(html_text)
            return s.get_data()
        except:
            return html_text

    try:
        msg = extract_msg.Message(input_file)

        # Extract email metadata
        from_address = msg.sender or "Unknown"
        to_address = msg.to or "Unknown"
        subject = msg.subject or "No Subject"
        date = str(msg.date) if msg.date else "Unknown"
        message_id = msg.messageId if hasattr(msg, "messageId") else None  # For deduplication

        # Threading headers: extract_msg exposes In-Reply-To directly; the
        # References header is only available from the transport headers.
        transport_headers = getattr(msg, "header", None)
        in_reply_to = _header_value(getattr(msg, "inReplyTo", None))
        references = None
        if isinstance(transport_headers, Message):
            references = _header_value(transport_headers.get("References"))
            in_reply_to = in_reply_to or _header_value(transport_headers.get("In-Reply-To"))

        # Start with email metadata
        text = _email_text_header(from_address, to_address, date, subject, in_reply_to, references)

        # Try to get body - prefer plain text, fall back to HTML
        body = ""
        if msg.body:
            body = msg.body
        elif hasattr(msg, "htmlBody") and msg.htmlBody:
            # htmlBody is bytes, need to decode it first
            try:
                html_content = msg.htmlBody
                if isinstance(html_content, bytes):
                    html_content = html_content.decode("utf-8", errors="ignore")
                # Strip HTML tags from HTML body
                body = strip_html(html_content)
            except Exception as e:
                logger.error(f"Error processing HTML body: {str(e)}")
                body = "[HTML content could not be processed]"
        elif hasattr(msg, "rtfBody") and msg.rtfBody:
            # RTF body - just note it exists
            body = "[RTF formatted email - content may not display correctly]"

        if body:
            text += body + "\n"

        # Extract attachments. The sender-supplied name is display metadata
        # only; bytes are written under a generated name (DOC-01).
        attachment_info = []
        output_dir = os.path.dirname(output_file)

        for attachment in msg.attachments:
            display = safe_display_name(
                getattr(attachment, "longFilename", None)
                or getattr(attachment, "shortFilename", None),
                f"attachment_{uuid.uuid4()}",
            )
            try:
                data = attachment.data
                mime = getattr(attachment, "mimeType", None)
                if not isinstance(mime, str) or not mime:
                    mime = "application/octet-stream"
                if isinstance(data, (bytes, bytearray)):
                    payload = bytes(data)
                elif data is not None and hasattr(data, "exportBytes"):
                    # Embedded Outlook message: keep it as a child .msg record.
                    payload = data.exportBytes()
                    if not display.lower().endswith(".msg"):
                        inner_subject = safe_display_name(
                            getattr(data, "subject", None), "embedded_message"
                        )
                        display = (
                            inner_subject if display.startswith("attachment_") else display
                        ) + ".msg"
                    mime = "application/vnd.ms-outlook"
                else:
                    text += _dropped_attachment_marker(display, "no extractable data")
                    continue

                attachment_path = write_attachment(output_dir, display, payload, mime)
                attachment_info.append(
                    {
                        "filename": display,
                        "path": attachment_path,
                        "mime_type": mime,
                        "size": len(payload),
                    }
                )

                # Add attachment info to email text
                text += f"\n[ATTACHMENT: {display}]\n"
            except Exception as e:
                logger.error(f"Error extracting attachment from MSG: {str(e)}")
                text += _dropped_attachment_marker(display, "extraction error")
                continue

        msg.close()

        # Create PDF from email content (same layout engine as EML, DOC-06)
        try:
            writer = EmailPdfWriter()
            writer.write(subject or "No Subject", fontsize=12, fontname="hebo", line_height=20)
            writer.write(text)

            # Add attachment summary
            if attachment_info:
                _write_attachment_summary(writer, attachment_info)

            writer.save(output_file)

            if not os.path.exists(output_file):
                raise Exception("MSG to PDF conversion failed - output file not created")

            # Verify the PDF is valid by checking file size
            if os.path.getsize(output_file) < 100:
                raise Exception("MSG to PDF conversion failed - output file too small")

            # Return PDF path, attachments, extracted text, and message_id
            return (output_file, attachment_info, text, message_id)
        except Exception as pdf_error:
            logger.error(f"Error creating PDF from MSG: {str(pdf_error)}")
            raise Exception(f"Failed to create PDF from MSG file: {str(pdf_error)}")

    except Exception as e:
        logger.error(f"Error converting MSG to PDF: {str(e)}")
        raise


def calculate_file_hash(file_content: bytes) -> str:
    """Calculate SHA-256 hash of file content for deduplication"""
    return hashlib.sha256(file_content).hexdigest()


def convert_to_pdf(input_file: str, output_dir: str = None) -> dict:
    """
    Universal converter - automatically detects file type and converts to PDF.
    Stores both original and converted PDF.

    Args:
        input_file: Path to input file
        output_dir: Directory for output (optional, uses temp if not provided)

    Returns:
        dict with conversion results:
        {
            "success": bool,
            "pdf_path": str,
            "original_format": str,
            "attachments": list,
            "error": str (if failed)
        }
    """
    if output_dir is None:
        output_dir = tempfile.mkdtemp()

    filename = os.path.basename(input_file)
    name, ext = os.path.splitext(filename)
    ext = ext.lower()

    result = {
        "success": False,
        "pdf_path": None,
        "original_format": ext[1:] if ext else "unknown",
        "attachments": [],
        "extracted_text": None,
        "message_id": None,
        "file_hash": None,
        "error": None,
    }

    try:
        # PDF - no conversion needed, but extract text
        if ext == ".pdf":
            result["success"] = True
            result["pdf_path"] = input_file
            # Extract text from PDF
            with open(input_file, "rb") as f:
                pdf_content = f.read()
            result["extracted_text"] = extract_text_from_pdf(pdf_content)
            return result

        # Office formats - use LibreOffice
        if ext in [".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls"]:
            pdf_path = convert_office_to_pdf(input_file, output_dir)
            result["success"] = True
            result["pdf_path"] = pdf_path
            # Extract text from converted PDF
            with open(pdf_path, "rb") as f:
                pdf_content = f.read()
            result["extracted_text"] = extract_text_from_pdf(pdf_content)
            return result

        # Email formats - return text directly from conversion
        if ext == ".eml":
            output_pdf = os.path.join(output_dir, f"{name}.pdf")
            pdf_path, attachments, extracted_text, message_id = convert_eml_to_pdf(
                input_file, output_pdf
            )
            result["success"] = True
            result["pdf_path"] = pdf_path
            result["attachments"] = attachments
            result["extracted_text"] = extracted_text
            result["message_id"] = message_id
            return result

        if ext == ".msg":
            output_pdf = os.path.join(output_dir, f"{name}.pdf")
            pdf_path, attachments, extracted_text, message_id = convert_msg_to_pdf(
                input_file, output_pdf
            )
            result["success"] = True
            result["pdf_path"] = pdf_path
            result["attachments"] = attachments
            result["extracted_text"] = extracted_text
            result["message_id"] = message_id
            return result

        # Image formats - convert to PDF
        if ext in [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp"]:
            pdf_path = convert_image_to_pdf(input_file, output_dir)
            result["success"] = True
            result["pdf_path"] = pdf_path
            # Extract text from converted PDF (will use OCR since it's an image)
            with open(pdf_path, "rb") as f:
                pdf_content = f.read()
            result["extracted_text"] = extract_text_from_pdf(pdf_content)
            return result

        # Unsupported format
        result["error"] = f"Unsupported file format: {ext}"
        return result

    except Exception as e:
        logger.error(f"Conversion failed for {filename}: {str(e)}")
        result["error"] = str(e)
        return result
