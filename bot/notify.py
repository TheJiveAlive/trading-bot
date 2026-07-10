"""Email notifications via SMTP (Gmail app password).

Credentials live in data/secrets.json (see data/secrets.example.json).
If secrets are missing, notifications are logged to logs/notify_skipped.log
instead of failing the scan.
"""
import datetime as dt
import json
import os
import smtplib
import ssl
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from bot.config import DATA_DIR, LOG_DIR

SECRETS_PATH = os.path.join(DATA_DIR, "secrets.json")
REQUIRED = ("smtp_host", "smtp_port", "smtp_user", "smtp_app_password", "email_to")


def _secrets():
    if not os.path.exists(SECRETS_PATH):
        return None
    with open(SECRETS_PATH) as f:
        s = json.load(f)
    if any(k not in s or not s[k] for k in REQUIRED):
        return None
    return s


def _deliver(msg, subject):
    s = _secrets()
    if s is None:
        with open(os.path.join(LOG_DIR, "notify_skipped.log"), "a") as f:
            f.write("{} | {}\n".format(
                dt.datetime.now().isoformat(timespec="seconds"), subject))
        return False
    msg["Subject"] = subject
    msg["From"] = "RobinHood Bot <{}>".format(s["smtp_user"])
    msg["To"] = s["email_to"]
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(s["smtp_host"], int(s["smtp_port"]), context=ctx, timeout=30) as srv:
            srv.login(s["smtp_user"], s["smtp_app_password"])
            srv.send_message(msg)
        return True
    except Exception as e:
        with open(os.path.join(LOG_DIR, "notify_errors.log"), "a") as f:
            f.write("{} | {} | {}\n".format(
                dt.datetime.now().isoformat(timespec="seconds"), subject, e))
        return False


def send_email(subject, body):
    """Report email (research/review/health/learnings): branded dark card with
    the body in monospace, plus a plain-text alternative for old clients."""
    esc = (body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    html = """
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:24px 0;">
<tr><td align="center">
<table width="640" cellpadding="0" cellspacing="0" style="max-width:640px;width:100%;">
  <tr><td style="background:#0f172a;border-radius:12px 12px 0 0;padding:14px 22px;
    font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;">
    <span style="font-size:15px;font-weight:800;color:#fff;">&#9889; RobinHood Bot</span>
    <span style="float:right;color:#94a3b8;font-size:11px;padding-top:3px;">{subj}</span>
  </td></tr>
  <tr><td style="background:#ffffff;padding:18px 22px;border:1px solid #e2e8f0;border-top:none;">
    <pre style="margin:0;font-family:ui-monospace,SF Mono,Menlo,Consolas,monospace;
      font-size:12px;line-height:1.55;color:#0f172a;white-space:pre-wrap;
      word-wrap:break-word;">{body}</pre>
  </td></tr>
  <tr><td style="background:#0f172a;border-radius:0 0 12px 12px;padding:10px 22px;"
    align="center"><span style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;
    font-size:10px;color:#94a3b8;">Automated report &middot; not financial advice</span>
  </td></tr>
</table></td></tr></table>""".format(subj=subject[:60], body=esc)
    msg = MIMEMultipart("alternative")
    msg.attach(MIMEText(body))
    msg.attach(MIMEText(html, "html"))
    return _deliver(msg, subject)


def send_html_email(subject, html, text, images=None):
    """HTML email with plain-text alternative and optional inline PNGs.

    images: {content_id: png_bytes} referenced in html as src="cid:content_id".
    """
    msg = MIMEMultipart("related")
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(text))
    alt.attach(MIMEText(html, "html"))
    msg.attach(alt)
    for cid, png in (images or {}).items():
        if not png:
            continue
        img = MIMEImage(png)
        img.add_header("Content-ID", "<{}>".format(cid))
        img.add_header("Content-Disposition", "inline")
        msg.attach(img)
    return _deliver(msg, subject)
