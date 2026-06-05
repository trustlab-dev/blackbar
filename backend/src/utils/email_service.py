"""
Email Service for sending magic links via SendGrid (RFC-007)
"""

import logging
import os

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Content, Email, Mail, To

from src.utils.log_utils import hash_email_for_logs

logger = logging.getLogger(__name__)


class EmailService:
    """Service for sending emails via SendGrid"""

    def __init__(self):
        self.api_key = os.getenv("SENDGRID_API_KEY")
        self.from_email = os.getenv("SENDGRID_FROM_EMAIL", "noreply@blackbar.app")
        self.from_name = os.getenv("SENDGRID_FROM_NAME", "Blackbar FOI System")

        if not self.api_key:
            logger.warning("SENDGRID_API_KEY not set - emails will not be sent")
            self.client = None
        else:
            self.client = SendGridAPIClient(self.api_key)

    def send_magic_link(
        self,
        to_email: str,
        magic_link_url: str,
        org_name: str = "Blackbar",
        expires_minutes: int = 15,
    ) -> bool:
        """
        Send magic link email to user

        Args:
            to_email: Recipient email address
            magic_link_url: Full magic link URL
            org_name: Name of the organization
            expires_minutes: Minutes until link expires

        Returns:
            True if email sent successfully, False otherwise
        """
        if not self.client:
            logger.error("SendGrid client not initialized - cannot send email")
            # In development, log the magic link (with hashed email)
            email_hash = hash_email_for_logs(to_email)
            logger.info(
                f"DEV MODE - Magic link generated for {email_hash} (check application logs)"
            )
            return False

        try:
            # Create email content
            subject = f"Sign in to {org_name}"

            html_content = self._build_html_template(
                magic_link_url=magic_link_url, org_name=org_name, expires_minutes=expires_minutes
            )

            text_content = self._build_text_template(
                magic_link_url=magic_link_url, org_name=org_name, expires_minutes=expires_minutes
            )

            # Create message
            message = Mail(
                from_email=Email(self.from_email, self.from_name),
                to_emails=To(to_email),
                subject=subject,
                plain_text_content=Content("text/plain", text_content),
                html_content=Content("text/html", html_content),
            )

            # Send email
            response = self.client.send(message)

            if response.status_code >= 200 and response.status_code < 300:
                email_hash = hash_email_for_logs(to_email)
                logger.info(f"Magic link email sent to {email_hash}")
                return True
            else:
                logger.error(f"Failed to send email: {response.status_code} - {response.body}")
                return False

        except Exception as e:
            logger.error(f"Error sending magic link email: {str(e)}")
            return False

    def _build_html_template(self, magic_link_url: str, org_name: str, expires_minutes: int) -> str:
        """Build HTML email template"""
        return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            margin: 0;
            padding: 0;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 600px;
            margin: 0 auto;
            background-color: #ffffff;
        }}
        .header {{
            background-color: #1976d2;
            color: #ffffff;
            padding: 30px 20px;
            text-align: center;
        }}
        .content {{
            padding: 40px 20px;
        }}
        .button {{
            display: inline-block;
            background-color: #1976d2;
            color: #ffffff;
            text-decoration: none;
            padding: 14px 40px;
            border-radius: 5px;
            font-weight: 500;
            margin: 20px 0;
        }}
        .button:hover {{
            background-color: #1565c0;
        }}
        .footer {{
            background-color: #f5f5f5;
            padding: 20px;
            text-align: center;
            font-size: 12px;
            color: #666;
        }}
        .warning {{
            background-color: #fff3cd;
            border-left: 4px solid #ffc107;
            padding: 12px;
            margin: 20px 0;
            font-size: 14px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 style="margin: 0; font-size: 24px;">Sign in to {org_name}</h1>
        </div>

        <div class="content">
            <p style="font-size: 16px;">Hello,</p>

            <p style="font-size: 16px;">
                Click the button below to sign in to your {org_name} account:
            </p>
            
            <div style="text-align: center; margin: 30px 0;">
                <a href="{magic_link_url}" class="button">
                    Sign In
                </a>
            </div>
            
            <div class="warning">
                <strong>⏱️ This link will expire in {expires_minutes} minutes</strong> and can only be used once.
            </div>
            
            <p style="font-size: 14px; color: #666;">
                If you didn't request this email, you can safely ignore it.
            </p>
            
            <p style="font-size: 14px; color: #666;">
                For security reasons, please do not forward this email to anyone.
            </p>
        </div>
        
        <div class="footer">
            <p style="margin: 0;">
                {org_name}<br>
                This is an automated message, please do not reply.
            </p>
        </div>
    </div>
</body>
</html>
"""

    def _build_text_template(self, magic_link_url: str, org_name: str, expires_minutes: int) -> str:
        """Build plain text email template"""
        return f"""
Sign in to {org_name}

Hello,

Click the link below to sign in to your {org_name} account:

{magic_link_url}

This link will expire in {expires_minutes} minutes and can only be used once.

If you didn't request this email, you can safely ignore it.

For security reasons, please do not forward this email to anyone.

---
{org_name}
This is an automated message, please do not reply.
"""

    def send_contributor_invitation(
        self,
        to_email: str,
        contributor_name: str,
        upload_url: str,
        case_tracking_number: str,
        org_name: str = "Blackbar",
        expires_days: int = 30,
    ) -> bool:
        """
        Send contributor invitation email with upload link (RFC-010)

        Args:
            to_email: Recipient email address
            contributor_name: Name of the contributor
            upload_url: Full upload URL with token
            case_tracking_number: Case tracking number for reference
            org_name: Name of the organization
            expires_days: Days until link expires

        Returns:
            True if email sent successfully, False otherwise
        """
        if not self.client:
            logger.warning("SendGrid client not initialized - cannot send contributor invitation")
            email_hash = hash_email_for_logs(to_email)
            logger.info(f"DEV MODE - Contributor invitation generated for {email_hash}")
            return False

        try:
            subject = f"Request for Records - {case_tracking_number}"

            html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 0; background-color: #f5f5f5; }}
        .container {{ max-width: 600px; margin: 0 auto; background-color: #ffffff; }}
        .header {{ background-color: #1976d2; color: #ffffff; padding: 30px 20px; text-align: center; }}
        .content {{ padding: 40px 20px; }}
        .button {{ display: inline-block; background-color: #1976d2; color: #ffffff; text-decoration: none; padding: 14px 40px; border-radius: 5px; font-weight: 500; margin: 20px 0; }}
        .footer {{ background-color: #f5f5f5; padding: 20px; text-align: center; font-size: 12px; color: #666; }}
        .info-box {{ background-color: #e3f2fd; border-left: 4px solid #1976d2; padding: 12px; margin: 20px 0; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 style="margin: 0; font-size: 24px;">Request for Records</h1>
        </div>
        <div class="content">
            <p>Hello {contributor_name},</p>
            <p>You have been identified as someone who may have records relevant to FOI request <strong>{case_tracking_number}</strong>.</p>
            <p>Please use the secure link below to upload any responsive records:</p>
            <div style="text-align: center; margin: 30px 0;">
                <a href="{upload_url}" class="button">Upload Records</a>
            </div>
            <div class="info-box">
                <strong>📋 Instructions:</strong>
                <ul style="margin: 10px 0; padding-left: 20px;">
                    <li>Click the button above to access your secure upload portal</li>
                    <li>Upload all documents that may be relevant to this request</li>
                    <li>Once complete, click "Confirm All Records Submitted"</li>
                </ul>
            </div>
            <p style="font-size: 14px; color: #666;">This link expires in {expires_days} days. If you have questions, please contact the FOI coordinator.</p>
        </div>
        <div class="footer">
            <p style="margin: 0;">{org_name}<br>This is an automated message.</p>
        </div>
    </div>
</body>
</html>
"""

            text_content = f"""
Request for Records - {case_tracking_number}

Hello {contributor_name},

You have been identified as someone who may have records relevant to FOI request {case_tracking_number}.

Please use the secure link below to upload any responsive records:

{upload_url}

Instructions:
- Click the link above to access your secure upload portal
- Upload all documents that may be relevant to this request
- Once complete, click "Confirm All Records Submitted"

This link expires in {expires_days} days.

---
{org_name}
"""

            message = Mail(
                from_email=Email(self.from_email, self.from_name),
                to_emails=To(to_email),
                subject=subject,
                plain_text_content=Content("text/plain", text_content),
                html_content=Content("text/html", html_content),
            )

            response = self.client.send(message)

            if response.status_code >= 200 and response.status_code < 300:
                email_hash = hash_email_for_logs(to_email)
                logger.info(
                    f"Contributor invitation sent to {email_hash} for case {case_tracking_number}"
                )
                return True
            else:
                logger.error(f"Failed to send contributor invitation: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"Error sending contributor invitation: {str(e)}")
            return False

    def send_transfer_notification(
        self,
        to_email: str,
        recipient_name: str,
        recipient_organization: str,
        transfer_url: str,
        case_tracking_number: str,
        transfer_reason: str,
        sender_organization: str = "Blackbar",
        expires_days: int = 30,
    ) -> bool:
        """
        Send transfer notification email to recipient organization (RFC-010)

        Args:
            to_email: Recipient email address
            recipient_name: Name of the recipient (if known)
            recipient_organization: Name of recipient organization
            transfer_url: Full transfer URL with token
            case_tracking_number: Case tracking number
            transfer_reason: Reason for the transfer
            sender_organization: Name of sending organization
            expires_days: Days until link expires

        Returns:
            True if email sent successfully, False otherwise
        """
        if not self.client:
            logger.warning("SendGrid client not initialized - cannot send transfer notification")
            email_hash = hash_email_for_logs(to_email)
            logger.info(f"DEV MODE - Transfer notification generated for {email_hash}")
            return False

        try:
            subject = f"FOI Request Transfer - {case_tracking_number}"
            greeting = f"Hello {recipient_name}," if recipient_name else "Hello,"

            html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 0; background-color: #f5f5f5; }}
        .container {{ max-width: 600px; margin: 0 auto; background-color: #ffffff; }}
        .header {{ background-color: #ff9800; color: #ffffff; padding: 30px 20px; text-align: center; }}
        .content {{ padding: 40px 20px; }}
        .button {{ display: inline-block; background-color: #ff9800; color: #ffffff; text-decoration: none; padding: 14px 40px; border-radius: 5px; font-weight: 500; margin: 20px 0; }}
        .footer {{ background-color: #f5f5f5; padding: 20px; text-align: center; font-size: 12px; color: #666; }}
        .reason-box {{ background-color: #fff3e0; border-left: 4px solid #ff9800; padding: 12px; margin: 20px 0; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 style="margin: 0; font-size: 24px;">FOI Request Transfer</h1>
        </div>
        <div class="content">
            <p>{greeting}</p>
            <p>An FOI request has been transferred to <strong>{recipient_organization}</strong> from {sender_organization}.</p>
            <p><strong>Request Reference:</strong> {case_tracking_number}</p>
            <div class="reason-box">
                <strong>Reason for Transfer:</strong><br>
                {transfer_reason}
            </div>
            <p>Please use the secure link below to access the request details and any included documents:</p>
            <div style="text-align: center; margin: 30px 0;">
                <a href="{transfer_url}" class="button">Access Transfer Package</a>
            </div>
            <p style="font-size: 14px; color: #666;">This link expires in {expires_days} days. Please download any documents before expiration.</p>
        </div>
        <div class="footer">
            <p style="margin: 0;">Transferred from {sender_organization}<br>This is an automated message.</p>
        </div>
    </div>
</body>
</html>
"""

            text_content = f"""
FOI Request Transfer - {case_tracking_number}

{greeting}

An FOI request has been transferred to {recipient_organization} from {sender_organization}.

Request Reference: {case_tracking_number}

Reason for Transfer:
{transfer_reason}

Please use the secure link below to access the request details:

{transfer_url}

This link expires in {expires_days} days.

---
Transferred from {sender_organization}
"""

            message = Mail(
                from_email=Email(self.from_email, self.from_name),
                to_emails=To(to_email),
                subject=subject,
                plain_text_content=Content("text/plain", text_content),
                html_content=Content("text/html", html_content),
            )

            response = self.client.send(message)

            if response.status_code >= 200 and response.status_code < 300:
                email_hash = hash_email_for_logs(to_email)
                logger.info(
                    f"Transfer notification sent to {email_hash} for case {case_tracking_number}"
                )
                return True
            else:
                logger.error(f"Failed to send transfer notification: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"Error sending transfer notification: {str(e)}")
            return False

    def send_contributor_reminder(
        self,
        to_email: str,
        contributor_name: str,
        upload_url: str,
        case_tracking_number: str,
        org_name: str = "Blackbar",
        expires_days: int = 30,
    ) -> bool:
        """
        Send reminder email to contributor who hasn't uploaded yet (RFC-010)

        Args:
            to_email: Recipient email address
            contributor_name: Name of the contributor
            upload_url: Full upload URL with token
            case_tracking_number: Case tracking number for reference
            org_name: Name of the organization
            expires_days: Days until link expires

        Returns:
            True if email sent successfully, False otherwise
        """
        if not self.client:
            logger.warning("SendGrid client not initialized - cannot send contributor reminder")
            email_hash = hash_email_for_logs(to_email)
            logger.info(f"DEV MODE - Contributor reminder generated for {email_hash}")
            return False

        try:
            subject = f"Reminder: Records Request - {case_tracking_number}"

            html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 0; background-color: #f5f5f5; }}
        .container {{ max-width: 600px; margin: 0 auto; background-color: #ffffff; }}
        .header {{ background-color: #f57c00; color: #ffffff; padding: 30px 20px; text-align: center; }}
        .content {{ padding: 40px 20px; }}
        .button {{ display: inline-block; background-color: #1976d2; color: #ffffff; text-decoration: none; padding: 14px 40px; border-radius: 5px; font-weight: 500; margin: 20px 0; }}
        .footer {{ background-color: #f5f5f5; padding: 20px; text-align: center; font-size: 12px; color: #666; }}
        .reminder-box {{ background-color: #fff3e0; border-left: 4px solid #f57c00; padding: 12px; margin: 20px 0; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 style="margin: 0; font-size: 24px;">⏰ Reminder: Records Request</h1>
        </div>
        <div class="content">
            <p>Hello {contributor_name},</p>
            <div class="reminder-box">
                <strong>This is a friendly reminder</strong> that we are still waiting for your records related to FOI request <strong>{case_tracking_number}</strong>.
            </div>
            <p>Please use the secure link below to upload any responsive records at your earliest convenience:</p>
            <div style="text-align: center; margin: 30px 0;">
                <a href="{upload_url}" class="button">Upload Records Now</a>
            </div>
            <p style="font-size: 14px; color: #666;">Your upload link expires in {expires_days} days. If you have already submitted your records, please disregard this message.</p>
            <p style="font-size: 14px; color: #666;">If you have questions or need assistance, please contact the FOI coordinator.</p>
        </div>
        <div class="footer">
            <p style="margin: 0;">{org_name}<br>This is an automated reminder.</p>
        </div>
    </div>
</body>
</html>
"""

            text_content = f"""
Reminder: Records Request - {case_tracking_number}

Hello {contributor_name},

This is a friendly reminder that we are still waiting for your records related to FOI request {case_tracking_number}.

Please use the secure link below to upload any responsive records:

{upload_url}

Your upload link expires in {expires_days} days. If you have already submitted your records, please disregard this message.

If you have questions, please contact the FOI coordinator.

---
{org_name}
"""

            message = Mail(
                from_email=Email(self.from_email, self.from_name),
                to_emails=To(to_email),
                subject=subject,
                plain_text_content=Content("text/plain", text_content),
                html_content=Content("text/html", html_content),
            )

            response = self.client.send(message)

            if response.status_code >= 200 and response.status_code < 300:
                email_hash = hash_email_for_logs(to_email)
                logger.info(
                    f"Contributor reminder email sent successfully to {email_hash} for case {case_tracking_number}"
                )
                return True
            else:
                logger.error(
                    f"Failed to send contributor reminder: status_code={response.status_code}"
                )
                return False

        except Exception as e:
            logger.error(f"Error sending contributor reminder: {str(e)}")
            return False
