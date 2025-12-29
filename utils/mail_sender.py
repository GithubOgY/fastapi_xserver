import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv

load_dotenv()

def send_email(subject: str, recipient: str, body: str) -> bool:
    """
    Send email using standard library smtplib
    
    Args:
        subject: Email subject
        recipient: Recipient email address
        body: Email body (HTML or plain text)
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # Get email settings from environment variables
        mail_username = os.getenv("MAIL_USERNAME")
        mail_password = os.getenv("MAIL_PASSWORD")
        mail_from = os.getenv("MAIL_FROM", mail_username)
        
        if not mail_username or not mail_password:
            print("Error: MAIL_USERNAME or MAIL_PASSWORD not set in .env")
            return False
        
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = mail_from
        msg['To'] = recipient
        
        # Attach HTML body
        html_part = MIMEText(body, 'html')
        msg.attach(html_part)
        
        # Send via Gmail SMTP
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(mail_username, mail_password)
            server.send_message(msg)
        
        print(f"Email sent successfully to {recipient}")
        return True
        
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False
