"""Outgoing email. One function, three backends:

- "ses": Amazon SES (production)
- "file": writes a .eml file to <files_dir>/outbox so you can open it locally
- "disabled": sends nothing

Callers never let an email failure undo saved work: they record the outcome in email_log and
tell the mechanic ("Invoice was saved but the email couldn't be sent").
"""

from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

from app.config import get_settings


class EmailError(Exception):
    pass


@dataclass
class Attachment:
    filename: str
    content: bytes
    mime: str = "application/pdf"


@dataclass
class OutgoingEmail:
    to: str
    subject: str
    text: str
    reply_to: str | None = None
    attachments: list[Attachment] = field(default_factory=list)


def _build(msg: OutgoingEmail, sender: str) -> EmailMessage:
    m = EmailMessage()
    m["From"] = sender
    m["To"] = msg.to
    m["Subject"] = msg.subject
    m["Message-ID"] = make_msgid(domain="shop.local")
    if msg.reply_to:
        m["Reply-To"] = msg.reply_to
    m.set_content(msg.text)
    for a in msg.attachments:
        maintype, subtype = a.mime.split("/", 1)
        m.add_attachment(a.content, maintype=maintype, subtype=subtype, filename=a.filename)
    return m


def send_email(msg: OutgoingEmail) -> str | None:
    """Send and return a provider message id. Raises EmailError on failure."""
    s = get_settings()
    if "\n" in msg.to or "\r" in msg.to or "\n" in msg.subject or "\r" in msg.subject:
        raise EmailError("Invalid address or subject.")
    built = _build(msg, s.email_from)
    if s.email_backend == "disabled":
        return None
    if s.email_backend == "file":
        outbox = Path(s.files_dir) / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        mid = built["Message-ID"].strip("<>").split("@")[0]
        (outbox / f"{mid}.eml").write_bytes(built.as_bytes())
        return mid
    if s.email_backend == "ses":
        try:
            import boto3

            client = boto3.client("sesv2", region_name=s.aws_region)
            resp = client.send_email(
                FromEmailAddress=s.email_from,
                Destination={"ToAddresses": [msg.to]},
                Content={"Raw": {"Data": built.as_bytes()}},
            )
            return resp.get("MessageId")
        except Exception as exc:  # network, throttling, sandbox restrictions
            raise EmailError(str(exc)) from exc
    raise EmailError(f"Unknown EMAIL_BACKEND {s.email_backend!r}")
