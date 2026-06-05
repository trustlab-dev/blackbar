"""
Welcome Email Service for Owner Activation
Sends welcome emails with activation links for new organization owners
"""

import logging
import os
import secrets
from urllib.parse import quote

import bcrypt

from src.utils.log_utils import hash_email_for_logs

logger = logging.getLogger(__name__)


class WelcomeEmailService:
    """Service for sending welcome emails to organization owners"""

    def __init__(self, email_service):
        """
        Initialize welcome email service

        Args:
            email_service: EmailService instance for sending emails
        """
        self.email_service = email_service
        self.token_expiration_hours = 48  # 48 hours for activation

    def generate_activation_token(self) -> str:
        """
        Generate a cryptographically secure activation token
        Returns 32-byte URL-safe token (256 bits of entropy)
        """
        return secrets.token_urlsafe(32)

    def hash_token(self, token: str) -> str:
        """Hash token with bcrypt for secure storage"""
        return bcrypt.hashpw(token.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    def verify_token(self, token: str, token_hash: str) -> bool:
        """Verify token against stored hash"""
        try:
            return bcrypt.checkpw(token.encode("utf-8"), token_hash.encode("utf-8"))
        except Exception as e:
            logger.error(f"Token verification failed: {str(e)}")
            return False

    def send_owner_welcome(
        self, owner_email: str, owner_name: str, org_name: str, activation_token: str
    ) -> bool:
        """
        Send welcome email to organization owner with activation link

        Args:
            owner_email: Owner's email address
            owner_name: Owner's full name
            org_name: Name of the organization
            activation_token: Activation token (unhashed)

        Returns:
            True if email sent successfully, False otherwise
        """
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")

        encoded_token = quote(activation_token)
        encoded_email = quote(owner_email)
        activation_url = f"{frontend_url}/activate?token={encoded_token}&email={encoded_email}"

        # Build email content
        subject = f"Welcome to {org_name} - Activate Your Account"

        html_content = self._build_html_template(
            owner_name=owner_name,
            org_name=org_name,
            activation_url=activation_url,
            expires_hours=self.token_expiration_hours,
        )

        text_content = self._build_text_template(
            owner_name=owner_name,
            org_name=org_name,
            activation_url=activation_url,
            expires_hours=self.token_expiration_hours,
        )

        # Send email using existing email service infrastructure
        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Content, Email, Mail, To

            api_key = os.getenv("SENDGRID_API_KEY")
            from_email = os.getenv("SENDGRID_FROM_EMAIL", "noreply@blackbar.app")
            from_name = os.getenv("SENDGRID_FROM_NAME", "Blackbar FOI System")

            if not api_key:
                logger.warning("SENDGRID_API_KEY not set - email will not be sent")
                # In development, log the activation link (with hashed email)
                email_hash = hash_email_for_logs(owner_email)
                if os.getenv("ENVIRONMENT") != "production":
                    logger.info(
                        f"DEV MODE - Activation link generated for {email_hash} (token omitted from logs)"
                    )
                return False

            client = SendGridAPIClient(api_key)

            message = Mail(
                from_email=Email(from_email, from_name),
                to_emails=To(owner_email),
                subject=subject,
                plain_text_content=Content("text/plain", text_content),
                html_content=Content("text/html", html_content),
            )

            response = client.send(message)

            if response.status_code >= 200 and response.status_code < 300:
                email_hash = hash_email_for_logs(owner_email)
                logger.info(f"Welcome email sent to {email_hash}")
                return True
            else:
                logger.error(
                    f"Failed to send welcome email: {response.status_code} - {response.body}"
                )
                return False

        except Exception as e:
            logger.error(f"Error sending welcome email: {str(e)}")
            return False

    def _build_html_template(
        self, owner_name: str, org_name: str, activation_url: str, expires_hours: int
    ) -> str:
        """Build HTML email template for welcome email"""
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
        .info-box {{
            background-color: #e3f2fd;
            border-left: 4px solid #1976d2;
            padding: 15px;
            margin: 20px 0;
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
            <h1 style="margin: 0; font-size: 24px;">Welcome to {org_name}!</h1>
        </div>

        <div class="content">
            <p style="font-size: 16px;">Hello {owner_name},</p>

            <p style="font-size: 16px;">
                Your organization's account has been created on the Blackbar FOI Management System.
                You have been designated as the <strong>Owner</strong> for <strong>{org_name}</strong>.
            </p>
            
            <div class="info-box">
                <strong>What's Next?</strong>
                <ul style="margin: 10px 0; padding-left: 20px;">
                    <li>Click the button below to activate your account</li>
                    <li>Set your secure password</li>
                    <li>Access your organization's FOI management portal</li>
                    <li>Invite team members and configure settings</li>
                </ul>
            </div>
            
            <div style="text-align: center; margin: 30px 0;">
                <a href="{activation_url}" class="button">
                    Activate Your Account
                </a>
            </div>
            
            <div class="warning">
                <strong>⏱️ This activation link will expire in {expires_hours} hours</strong> and can only be used once.
            </div>
            
            <p style="font-size: 14px; color: #666;">
                If you didn't expect this email or believe it was sent in error, please contact your system administrator.
            </p>
            
            <p style="font-size: 14px; color: #666;">
                For security reasons, please do not forward this email to anyone.
            </p>
        </div>
        
        <div class="footer">
            <p style="margin: 0;">
                <strong>{org_name}</strong><br>
                Powered by Blackbar FOI Management System<br>
                This is an automated message, please do not reply.
            </p>
        </div>
    </div>
</body>
</html>
"""

    def _build_text_template(
        self, owner_name: str, org_name: str, activation_url: str, expires_hours: int
    ) -> str:
        """Build plain text email template for welcome email"""
        return f"""
Welcome to {org_name}!

Hello {owner_name},

Your organization's account has been created on the Blackbar FOI Management System.
You have been designated as the Owner for {org_name}.

WHAT'S NEXT:
- Click the link below to activate your account
- Set your secure password
- Access your organization's FOI management portal
- Invite team members and configure settings

ACTIVATION LINK:
{activation_url}

IMPORTANT: This activation link will expire in {expires_hours} hours and can only be used once.

If you didn't expect this email or believe it was sent in error, please contact your system administrator.

For security reasons, please do not forward this email to anyone.

---
{org_name}
Powered by Blackbar FOI Management System
This is an automated message, please do not reply.
"""

    def send_public_request_confirmation(
        self,
        requester_email: str,
        requester_name: str,
        tracking_number: str,
        request_title: str,
        org_name: str,
        contact_email: str = None,
    ) -> bool:
        """
        Send confirmation email to public requester after FOI request submission

        Args:
            requester_email: Requester's email address
            requester_name: Requester's name
            tracking_number: Case tracking number
            request_title: Title of the request
            org_name: Organization name
            contact_email: Contact email for questions (optional)

        Returns:
            True if email sent successfully, False otherwise
        """
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")

        tracking_url = f"{frontend_url}/track/{tracking_number}"

        subject = f"FOI Request Received - {tracking_number}"

        html_content = self._build_confirmation_html(
            requester_name=requester_name,
            tracking_number=tracking_number,
            request_title=request_title,
            org_name=org_name,
            tracking_url=tracking_url,
            contact_email=contact_email,
        )

        text_content = self._build_confirmation_text(
            requester_name=requester_name,
            tracking_number=tracking_number,
            request_title=request_title,
            org_name=org_name,
            tracking_url=tracking_url,
            contact_email=contact_email,
        )

        try:
            response = self.email_service.send_email(
                to=requester_email,
                subject=subject,
                html_content=html_content,
                text_content=text_content,
            )

            if response.status_code >= 200 and response.status_code < 300:
                email_hash = hash_email_for_logs(requester_email)
                logger.info(f"Confirmation email sent to {email_hash} for {tracking_number}")
                return True
            else:
                logger.error(f"Failed to send confirmation email: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"Error sending confirmation email: {str(e)}")
            return False

    def _build_confirmation_html(
        self,
        requester_name: str,
        tracking_number: str,
        request_title: str,
        org_name: str,
        tracking_url: str,
        contact_email: str,
    ) -> str:
        """Build HTML email template for request confirmation"""
        contact_section = (
            f"<p>If you have questions, please contact us at <a href='mailto:{contact_email}'>{contact_email}</a>.</p>"
            if contact_email
            else ""
        )

        return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            margin: 0;
            padding: 0;
            background-color: #f5f5f5;
        }}
        .container {{ max-width: 600px; margin: 0 auto; background-color: #ffffff; }}
        .header {{ background-color: #2e7d32; color: #ffffff; padding: 30px 20px; text-align: center; }}
        .content {{ padding: 40px 20px; }}
        .tracking-box {{
            background-color: #e8f5e9;
            border: 2px solid #2e7d32;
            border-radius: 8px;
            padding: 20px;
            text-align: center;
            margin: 20px 0;
        }}
        .tracking-number {{
            font-size: 24px;
            font-weight: bold;
            color: #2e7d32;
            letter-spacing: 2px;
        }}
        .button {{
            display: inline-block;
            background-color: #2e7d32;
            color: #ffffff;
            padding: 12px 30px;
            text-decoration: none;
            border-radius: 5px;
            margin: 20px 0;
        }}
        .footer {{ background-color: #f5f5f5; padding: 20px; text-align: center; font-size: 12px; color: #777; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Request Received</h1>
        </div>
        <div class="content">
            <p>Dear {requester_name},</p>
            <p>Thank you for submitting your Freedom of Information request to <strong>{org_name}</strong>.</p>
            
            <div class="tracking-box">
                <p style="margin: 0; color: #555;">Your Tracking Number</p>
                <div class="tracking-number">{tracking_number}</div>
            </div>
            
            <p><strong>Request Summary:</strong></p>
            <p style="background-color: #f5f5f5; padding: 15px; border-radius: 5px;">{request_title}</p>
            
            <h3>What Happens Next?</h3>
            <ul>
                <li>Your request will be reviewed within 30 business days</li>
                <li>You will receive updates as your request is processed</li>
                <li>You can track your request status anytime using the button below</li>
            </ul>
            
            <p style="text-align: center;">
                <a href="{tracking_url}" class="button">Track Your Request</a>
            </p>
            
            {contact_section}
        </div>
        <div class="footer">
            <p>{org_name}<br>This is an automated message.</p>
        </div>
    </div>
</body>
</html>
"""

    def _build_confirmation_text(
        self,
        requester_name: str,
        tracking_number: str,
        request_title: str,
        org_name: str,
        tracking_url: str,
        contact_email: str,
    ) -> str:
        """Build plain text email template for request confirmation"""
        contact_section = (
            f"\nIf you have questions, please contact us at {contact_email}.\n"
            if contact_email
            else ""
        )

        return f"""
FOI Request Received - {tracking_number}

Dear {requester_name},

Thank you for submitting your Freedom of Information request to {org_name}.

YOUR TRACKING NUMBER: {tracking_number}

REQUEST SUMMARY:
{request_title}

WHAT HAPPENS NEXT:
- Your request will be reviewed within 30 business days
- You will receive updates as your request is processed
- You can track your request status at: {tracking_url}

{contact_section}
---
{org_name}
This is an automated message.
"""
