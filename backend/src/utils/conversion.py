# backend/src/utils/conversion.py
import email
import hashlib
import io
import logging
import os
import subprocess
import tempfile
import uuid

import fitz  # PyMuPDF
import pytesseract
from PIL import Image
from reportlab.lib.pagesizes import letter
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
    import re
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
    text = f"From: {from_address}\nTo: {to_address}\nDate: {date}\nSubject: {subject}\n\n"

    # Extract attachments and inline images
    attachment_info = []
    inline_images = {}  # Map Content-ID to image data
    output_dir = os.path.dirname(output_file)
    body_found = False
    html_body = None

    # Process message parts
    if msg.is_multipart():
        for part in msg.walk():
            content_disposition = part.get("Content-Disposition", "")
            content_type = part.get_content_type()
            content_id = part.get("Content-ID", "").strip("<>")

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
                import re

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
                filename = part.get_filename()
                if not filename:
                    filename = f"unknown_attachment_{uuid.uuid4()}"

                # Save attachment
                attachment_path = os.path.join(output_dir, filename)
                with open(attachment_path, "wb") as f:
                    f.write(part.get_payload(decode=True))

                # Add to list of attachments
                attachment_info.append(
                    {
                        "filename": filename,
                        "path": attachment_path,
                        "mime_type": content_type,
                        "size": os.path.getsize(attachment_path),
                    }
                )

                # Add attachment info to email text
                text += f"\n[ATTACHMENT: {filename}]\n"
    else:
        # Non-multipart email - just get the body
        charset = msg.get_content_charset() or "utf-8"
        body_text = msg.get_payload(decode=True).decode(charset, errors="ignore")
        # Check if it's HTML and strip tags
        if msg.get_content_type() == "text/html":
            body_text = strip_html(body_text)
        text += body_text

    # Create PDF from email content using PyMuPDF for better HTML/image handling
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)  # Letter size

    # Set up text insertion
    y_position = 40
    line_height = 14

    # Add header line by line to avoid overlap
    page.insert_text((40, y_position), f"From: {from_address}", fontsize=10, fontname="helv")
    y_position += line_height
    page.insert_text((40, y_position), f"To: {to_address}", fontsize=10, fontname="helv")
    y_position += line_height
    page.insert_text((40, y_position), f"Date: {date}", fontsize=10, fontname="helv")
    y_position += line_height
    page.insert_text((40, y_position), f"Subject: {subject}", fontsize=10, fontname="helv")
    y_position += line_height * 2  # Extra space before body

    # If we have HTML with inline images, parse and render with images
    if html_body and inline_images:
        import base64
        import re

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
                    lines = part.strip().split("\n")
                    for line in lines:
                        if y_position > 740:  # Near bottom of page
                            page = doc.new_page(width=612, height=792)
                            y_position = 40

                        # Wrap long lines
                        if len(line) > 90:
                            wrapped = [line[j : j + 90] for j in range(0, len(line), 90)]
                            for wrapped_line in wrapped:
                                page.insert_text(
                                    (40, y_position), wrapped_line, fontsize=10, fontname="helv"
                                )
                                y_position += line_height
                        else:
                            page.insert_text((40, y_position), line, fontsize=10, fontname="helv")
                            y_position += line_height
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
                        max_width = 532  # Page width minus margins
                        max_height = 400

                        width_ratio = max_width / img_width
                        height_ratio = max_height / img_height
                        scale = min(width_ratio, height_ratio, 1.0)

                        new_width = img_width * scale
                        new_height = img_height * scale

                        # Check if we need a new page
                        if y_position + new_height > 740:
                            page = doc.new_page(width=612, height=792)
                            y_position = 40

                        # Save temp image
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                            img.save(tmp.name, "PNG")
                            temp_img_path = tmp.name

                        try:
                            img_rect = fitz.Rect(
                                40, y_position, 40 + new_width, y_position + new_height
                            )
                            page.insert_image(img_rect, filename=temp_img_path)
                            y_position += new_height + 10
                        finally:
                            os.unlink(temp_img_path)

                    except Exception as e:
                        logger.warning(f"Could not embed inline image {img_id}: {e}")
                        page.insert_text(
                            (40, y_position), f"[Image: {img_id}]", fontsize=10, fontname="helv"
                        )
                        y_position += line_height
    else:
        # No inline images or no HTML - just render text
        for line in text.splitlines():
            if y_position > 740:
                page = doc.new_page(width=612, height=792)
                y_position = 40

            # Wrap long lines
            if len(line) > 90:
                wrapped = [line[i : i + 90] for i in range(0, len(line), 90)]
                for wrapped_line in wrapped:
                    page.insert_text((40, y_position), wrapped_line, fontsize=10, fontname="helv")
                    y_position += line_height
            else:
                page.insert_text((40, y_position), line, fontsize=10, fontname="helv")
                y_position += line_height

    # Add attachment summary at the end
    if attachment_info:
        # New page for attachments
        page = doc.new_page(width=612, height=792)
        y_position = 40

        page.insert_text((40, y_position), "Attachments:", fontsize=12, fontname="hebo")
        y_position += 20

        for i, attachment in enumerate(attachment_info, 1):
            size_kb = attachment["size"] / 1024
            att_text = (
                f"{i}. {attachment['filename']} ({attachment['mime_type']}, {size_kb:.1f} KB)"
            )
            page.insert_text((40, y_position), att_text, fontsize=10, fontname="helv")
            y_position += 15

            if y_position > 740:
                page = doc.new_page(width=612, height=792)
                y_position = 40

    # Save the PDF
    doc.save(output_file)
    doc.close()

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

    import re
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

        # Start with email metadata
        text = f"From: {from_address}\nTo: {to_address}\nDate: {date}\nSubject: {subject}\n\n"

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

        # Extract attachments
        attachment_info = []
        output_dir = os.path.dirname(output_file)

        for attachment in msg.attachments:
            try:
                filename = (
                    attachment.longFilename
                    or attachment.shortFilename
                    or f"attachment_{uuid.uuid4()}"
                )
                attachment_path = os.path.join(output_dir, filename)

                # Save attachment
                with open(attachment_path, "wb") as f:
                    f.write(attachment.data)

                attachment_info.append(
                    {
                        "filename": filename,
                        "path": attachment_path,
                        "mime_type": getattr(attachment, "mimeType", "application/octet-stream"),
                        "size": len(attachment.data),
                    }
                )

                # Add attachment info to email text
                text += f"\n[ATTACHMENT: {filename}]\n"
            except Exception as e:
                logger.error(f"Error extracting attachment from MSG: {str(e)}")
                continue

        msg.close()

        # Create PDF from email content (same as EML)
        try:
            c = canvas.Canvas(output_file, pagesize=letter)
            width, height = letter
            c.setFont("Helvetica", 10)
            x, y = 40, height - 40

            # Add header
            c.setFont("Helvetica-Bold", 12)
            # Escape any problematic characters in subject
            safe_subject = subject[:100] if subject else "No Subject"
            c.drawString(x, y, safe_subject)
            y -= 20
            c.setFont("Helvetica", 10)

            # Add body text
            for line in text.splitlines():
                # Skip empty lines that might cause issues
                if not line.strip():
                    y -= 12
                    if y < 40:
                        c.showPage()
                        c.setFont("Helvetica", 10)
                        y = height - 40
                    continue

                # Handle long lines
                if len(line) > 90:
                    wrapped_lines = [line[i : i + 90] for i in range(0, len(line), 90)]
                    for wrapped in wrapped_lines:
                        try:
                            # Remove any non-printable characters
                            safe_line = "".join(
                                char if ord(char) >= 32 or char == "\t" else " " for char in wrapped
                            )
                            c.drawString(x, y, safe_line)
                        except:
                            c.drawString(x, y, "[Content could not be displayed]")
                        y -= 12
                        if y < 40:
                            c.showPage()
                            c.setFont("Helvetica", 10)
                            y = height - 40
                else:
                    try:
                        # Remove any non-printable characters
                        safe_line = "".join(
                            char if ord(char) >= 32 or char == "\t" else " " for char in line
                        )
                        c.drawString(x, y, safe_line)
                    except:
                        c.drawString(x, y, "[Content could not be displayed]")
                    y -= 12
                    if y < 40:
                        c.showPage()
                        c.setFont("Helvetica", 10)
                        y = height - 40

            # Add attachment summary
            if attachment_info:
                c.showPage()
                y = height - 40
                c.setFont("Helvetica-Bold", 12)
                c.drawString(x, y, "Attachments:")
                y -= 20
                c.setFont("Helvetica", 10)

                for i, attachment in enumerate(attachment_info, 1):
                    size_kb = attachment["size"] / 1024
                    safe_filename = attachment["filename"][:80]
                    c.drawString(
                        x, y, f"{i}. {safe_filename} ({attachment['mime_type']}, {size_kb:.1f} KB)"
                    )
                    y -= 15
                    if y < 40:
                        c.showPage()
                        c.setFont("Helvetica", 10)
                        y = height - 40

            c.save()

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
