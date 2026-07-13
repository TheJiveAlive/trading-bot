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
    msg["From"] = "Trading Bot <{}>".format(s["smtp_user"])
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


def _md_to_html(md):
    """Tiny Markdown → HTML for report emails (headings, bold, bullets, paras)."""
    import re
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    def inline(s):
        s = esc(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"`(.+?)`", r'<code style="background:#eef2f7;padding:1px 4px;'
                   r'border-radius:3px;font-size:12px">\1</code>', s)
        return s
    out, in_list = [], False
    for line in md.split("\n"):
        s = line.rstrip()
        if not s:
            if in_list:
                out.append("</ul>"); in_list = False
            continue
        if s.startswith("### "):
            if in_list: out.append("</ul>"); in_list = False
            out.append('<h4 style="margin:14px 0 4px;font-size:14px;color:#0f172a">{}</h4>'.format(inline(s[4:])))
        elif s.startswith("## "):
            if in_list: out.append("</ul>"); in_list = False
            out.append('<h3 style="margin:18px 0 6px;font-size:16px;color:#0f172a;'
                       'border-bottom:1px solid #e2e8f0;padding-bottom:4px">{}</h3>'.format(inline(s[3:])))
        elif s.startswith("# "):
            if in_list: out.append("</ul>"); in_list = False
            out.append('<h2 style="margin:8px 0 8px;font-size:19px;color:#0f172a">{}</h2>'.format(inline(s[2:])))
        elif s.lstrip().startswith(("- ", "* ")):
            if not in_list: out.append('<ul style="margin:4px 0 8px 4px;padding-left:18px">'); in_list = True
            out.append('<li style="margin:3px 0;line-height:1.5">{}</li>'.format(inline(s.lstrip()[2:])))
        else:
            if in_list: out.append("</ul>"); in_list = False
            out.append('<p style="margin:6px 0;line-height:1.55">{}</p>'.format(inline(s)))
    if in_list: out.append("</ul>")
    return "".join(out)


def send_email(subject, body, markdown=False):
    """Report email (research/review/health/learnings): branded dark card.
    markdown=True renders the body as formatted HTML (headings/bold/bullets);
    otherwise the body is shown verbatim in monospace (good for aligned text)."""
    if markdown:
        inner = ('<div style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;'
                 'font-size:13.5px;color:#0f172a">{}</div>').format(_md_to_html(body))
        return _deliver_report(subject, inner, body)
    esc = (body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    inner = ('<pre style="margin:0;font-family:ui-monospace,SF Mono,Menlo,Consolas,monospace;'
             'font-size:12px;line-height:1.55;color:#0f172a;white-space:pre-wrap;'
             'word-wrap:break-word;">{}</pre>').format(esc)
    return _deliver_report(subject, inner, body)


def _deliver_report(subject, inner_html, text_body):
    html = """
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:24px 0;">
<tr><td align="center">
<table width="640" cellpadding="0" cellspacing="0" style="max-width:640px;width:100%;">
  <tr><td style="background:#0f172a;border-radius:12px 12px 0 0;padding:14px 22px;
    font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;">
    <span style="font-size:15px;font-weight:800;color:#fff;">&#9889; Trading Bot</span>
    <span style="float:right;color:#94a3b8;font-size:11px;padding-top:3px;">{subj}</span>
  </td></tr>
  <tr><td style="background:#ffffff;padding:18px 22px;border:1px solid #e2e8f0;border-top:none;">
    {inner}
  </td></tr>
  <tr><td style="background:#0f172a;border-radius:0 0 12px 12px;padding:10px 22px;"
    align="center"><span style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;
    font-size:10px;color:#94a3b8;">Automated report &middot; not financial advice</span>
  </td></tr>
</table></td></tr></table>""".format(subj=subject[:60], inner=inner_html)
    msg = MIMEMultipart("alternative")
    msg.attach(MIMEText(text_body))
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
