"""Pure bounded MIME extraction: no renderer, external resources or attachment decoding."""

import base64
import binascii
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.header import decode_header
from email.message import Message
from email.utils import parseaddr
from html.parser import HTMLParser

from app.core.exceptions import ApplicationError, ErrorCode as E


@dataclass(repr=False)
class ExtractedEmail:
    text: str
    subject: str | None
    sender: str | None
    timestamp: str | None


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in {'script', 'style', 'head', 'template', 'noscript', 'svg', 'math'}:
            self.hidden += 1
        elif not self.hidden and tag in {'br', 'p', 'div', 'li', 'tr'}:
            self.text.append('\n')

    def handle_endtag(self, tag: str) -> None:
        if tag in {'script', 'style', 'head', 'template', 'noscript', 'svg', 'math'} and self.hidden:
            self.hidden -= 1
        elif not self.hidden and tag in {'p', 'div', 'li', 'tr'}:
            self.text.append('\n')

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.text.append(data)


def headers(part: dict) -> dict[str, str]:
    values = part.get('headers', [])
    if not isinstance(values, list) or len(values) > 100:
        raise ApplicationError(E.GMAIL_MESSAGE_INVALID)
    result = {}
    for item in values:
        if not isinstance(item, dict) or not isinstance(item.get('name'), str) or not isinstance(item.get('value'), str):
            raise ApplicationError(E.GMAIL_MESSAGE_INVALID)
        key, value = item['name'].lower(), item['value']
        if len(key) > 100 or len(value) > 8192:
            raise ApplicationError(E.GMAIL_MESSAGE_INVALID)
        if key in {'content-type', 'content-disposition', 'subject', 'from'}:
            if key in result:
                raise ApplicationError(E.GMAIL_MESSAGE_INVALID)
            result[key] = value
    return result


def leaves(payload: object) -> list[dict]:
    stack = [(payload, 0)]
    result = []
    count = 0
    while stack:
        part, depth = stack.pop()
        count += 1
        if not isinstance(part, dict) or depth > 4 or count > 64:
            raise ApplicationError(E.GMAIL_MESSAGE_INVALID)
        mime = part.get('mimeType')
        if not isinstance(mime, str) or len(mime) > 100:
            raise ApplicationError(E.GMAIL_MESSAGE_INVALID)
        metadata = headers(part)
        if part.get('filename') or metadata.get('content-disposition', '').lower().startswith('attachment'):
            raise ApplicationError(E.GMAIL_ATTACHMENTS_SKIPPED)
        children = part.get('parts', [])
        if not isinstance(children, list) or len(children) > 64:
            raise ApplicationError(E.GMAIL_MESSAGE_INVALID)
        if mime.lower().startswith('multipart/'):
            if not children:
                raise ApplicationError(E.GMAIL_MESSAGE_INVALID)
            stack.extend((child, depth + 1) for child in reversed(children))
        else:
            if children:
                raise ApplicationError(E.GMAIL_MESSAGE_INVALID)
            if mime.lower() not in {'text/plain', 'text/html'}:
                raise ApplicationError(E.GMAIL_ATTACHMENTS_SKIPPED)
            body = part.get('body')
            if not isinstance(body, dict) or body.get('attachmentId'):
                raise ApplicationError(E.GMAIL_MESSAGE_INVALID)
            result.append(part)
    return result


def preflight(message: dict, label: str, limit: int) -> list[dict]:
    labels = message.get('labelIds')
    if not isinstance(labels, list) or any(not isinstance(x, str) or len(x) > 128 for x in labels) or label not in labels or {'SENT', 'SPAM', 'TRASH'} & set(labels):
        raise ApplicationError(E.GMAIL_SELECTION_INVALID)
    parts = leaves(message.get('payload'))
    for part in parts:
        size = part['body'].get('size')
        if type(size) is not int or size < 0:
            raise ApplicationError(E.GMAIL_MESSAGE_INVALID)
    selected = [part for part in parts if part['mimeType'].lower() == 'text/plain' and part['body']['size'] > 0]
    selected = selected or [part for part in parts if part['mimeType'].lower() == 'text/html' and part['body']['size'] > 0]
    if not selected:
        raise ApplicationError(E.GMAIL_MESSAGE_INVALID)
    total = sum(part['body']['size'] for part in selected)
    if total > limit:
        raise ApplicationError(E.GMAIL_MESSAGE_TOO_LARGE)
    return selected


def _decode(part: dict, limit: int) -> str:
    body = part['body']
    encoded = body.get('data')
    if not isinstance(encoded, str):
        raise ApplicationError(E.GMAIL_MESSAGE_INVALID)
    if len(encoded) > 4 * ((limit + 2) // 3) + 4:
        raise ApplicationError(E.GMAIL_MESSAGE_TOO_LARGE)
    try:
        if re.fullmatch(r'[A-Za-z0-9_-]*={0,2}', encoded) is None:
            raise ValueError
        raw = base64.b64decode(encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True)
        if len(raw) > limit:
            raise ApplicationError(E.GMAIL_MESSAGE_TOO_LARGE)
        if len(raw) != body['size']:
            raise ValueError
        metadata = headers(part)
        content_type = Message()
        content_type['Content-Type'] = metadata.get('content-type', part['mimeType'])
        charset = content_type.get_content_charset('utf-8').lower()
        aliases = {'utf-8': 'utf-8', 'utf8': 'utf-8', 'us-ascii': 'ascii', 'ascii': 'ascii',
                   'iso-8859-1': 'latin-1', 'latin-1': 'latin-1', 'windows-1252': 'cp1252', 'cp1252': 'cp1252'}
        if charset not in aliases:
            raise ValueError
        text = raw.decode(aliases[charset], errors='strict')
    except (ValueError, UnicodeError, binascii.Error):
        raise ApplicationError(E.GMAIL_MESSAGE_INVALID) from None
    if part['mimeType'].lower() == 'text/html':
        parser = _HTMLText()
        parser.feed(text)
        parser.close()
        text = ''.join(parser.text)
    return text


def extract(message: dict, label: str, limit: int) -> ExtractedEmail:
    selected = preflight(message, label, limit)
    text = '\n'.join(_decode(part, limit) for part in selected).strip()
    if not text or any(ord(c) < 32 and c not in '\r\n\t' for c in text):
        raise ApplicationError(E.GMAIL_MESSAGE_INVALID)
    if len(text) > 5000 or len(text.encode('utf-8')) > limit:
        raise ApplicationError(E.GMAIL_MESSAGE_TOO_LARGE)
    meta = headers(message['payload'])
    subject = None
    try:
        subject = ''.join(value.decode(charset or 'utf-8') if isinstance(value, bytes) else value
                          for value, charset in decode_header(meta.get('subject', '')))
        if not subject or len(subject) > 256:
            subject = None
    except (ValueError, LookupError, UnicodeError):
        pass
    sender = parseaddr(meta.get('from', ''))[1]
    sender = sender if sender and len(sender) <= 320 else None
    stamp = message.get('internalDate')
    timestamp = None
    if stamp is not None:
        try:
            if not isinstance(stamp, str) or re.fullmatch(r'[0-9]{1,16}', stamp) is None:
                raise ValueError
            timestamp = datetime.fromtimestamp(int(stamp) / 1000, timezone.utc).isoformat()
        except (ValueError, OverflowError, OSError):
            raise ApplicationError(E.GMAIL_MESSAGE_INVALID) from None
    return ExtractedEmail(text, subject, sender, timestamp)
