import base64

import pytest

from app.core.exceptions import ApplicationError, ErrorCode as E
from app.integrations.gmail_mime import extract, preflight
from tests.t08_helpers import message, part


@pytest.mark.parametrize('text,charset', [('Fine delivery.', 'utf-8'), ('好评 😀', 'utf-8'), ('Café', 'iso-8859-1'), ('Café €', 'cp1252'), ('Plain ASCII', 'us-ascii')])
def test_plain_text_charset_and_minimal_metadata(text, charset):
    value = message(payload=part(text, charset=charset))
    result = extract(value, 'Label_feedback', 16384)
    assert result.text == text
    assert result.subject == 'Fabricated subject private sentinel'
    assert result.sender == 'sender@example.test'
    assert result.timestamp.endswith('+00:00')


def test_plaintext_preferred_to_html_alternative_without_duplicate_record():
    value = message(payload={'mimeType': 'multipart/alternative', 'parts': [part('Plain feedback.'), part('<p>HTML alternative.</p>', mime='text/html')]})
    assert extract(value, 'Label_feedback', 16384).text == 'Plain feedback.'


def test_empty_plaintext_alternative_uses_nonempty_html_without_inventing_content():
    value = message(payload={'mimeType': 'multipart/alternative', 'parts': [part(''), part('<p>Actual feedback.</p>', mime='text/html')]})
    assert extract(value, 'Label_feedback', 16384).text == 'Actual feedback.'


def test_html_only_is_inert_text_without_scripts_resources_or_rendering():
    text = '<html><head><style>private-style</style></head><body><script>private-script</script><p>Delivery &amp; quality.</p><img src="https://untrusted.invalid/tracker"><a href="https://untrusted.invalid">Helpful support.</a></body></html>'
    result = extract(message(payload=part(text, mime='text/html')), 'Label_feedback', 16384)
    assert 'Delivery & quality.' in result.text and 'Helpful support.' in result.text
    assert 'private-script' not in result.text and 'private-style' not in result.text
    assert 'https://' not in result.text


@pytest.mark.parametrize('kind', ['missing_body', 'missing_data', 'empty', 'bad_base64', 'bad_utf8', 'bad_charset', 'bad_size', 'bad_headers', 'bad_mime', 'bad_parts', 'bad_timestamp', 'control'])
def test_malformed_or_missing_content_is_controlled(kind):
    value = message()
    p = value['payload']
    if kind == 'missing_body': p.pop('body')
    elif kind == 'missing_data': p['body'].pop('data')
    elif kind == 'empty': p['body'] = {'size': 0, 'data': ''}
    elif kind == 'bad_base64': p['body']['data'] = '$invalid'
    elif kind == 'bad_utf8': p['body'] = {'size': 1, 'data': '_w'}
    elif kind == 'bad_charset': p['headers'][0]['value'] = 'text/plain; charset=unknown-charset'
    elif kind == 'bad_size': p['body']['size'] = True
    elif kind == 'bad_headers': p['headers'] = [{'name': 'From', 'value': 12}]
    elif kind == 'bad_mime': p['mimeType'] = None
    elif kind == 'bad_parts': p['parts'] = 'not-list'
    elif kind == 'bad_timestamp': value['internalDate'] = 'not-a-date'
    elif kind == 'control': value = message('Bad\x00text')
    with pytest.raises(ApplicationError) as error:
        extract(value, 'Label_feedback', 16384)
    assert error.value.code == E.GMAIL_MESSAGE_INVALID


@pytest.mark.parametrize('kind', ['filename', 'disposition', 'binary', 'external_body'])
def test_attachment_or_external_body_is_not_decoded(kind):
    p = part()
    if kind == 'filename': p['filename'] = 'private.pdf'
    elif kind == 'disposition': p['headers'].append({'name': 'Content-Disposition', 'value': 'attachment'})
    elif kind == 'binary': p['mimeType'] = 'application/pdf'
    elif kind == 'external_body': p['body']['attachmentId'] = 'not-to-be-fetched'
    p['body']['data'] = '$must-not-be-decoded'
    with pytest.raises(ApplicationError) as error: preflight(message(payload=p), 'Label_feedback', 16384)
    assert error.value.code in {E.GMAIL_ATTACHMENTS_SKIPPED, E.GMAIL_MESSAGE_INVALID}


@pytest.mark.parametrize('value,limit', [(message('x'*5001), 16384), (message('x'*100), 99), (message('好'*100), 299)])
def test_byte_and_character_bounds_reject_without_truncation(value, limit):
    with pytest.raises(ApplicationError) as error: extract(value, 'Label_feedback', limit)
    assert error.value.code == E.GMAIL_MESSAGE_TOO_LARGE


@pytest.mark.parametrize('labels', [[], ['Label_feedback', 'SPAM'], ['Label_feedback', 'TRASH']])
def test_selection_is_verified_against_actual_message_labels(labels):
    with pytest.raises(ApplicationError) as error: extract(message(labelIds=labels), 'Label_feedback', 16384)
    assert error.value.code == E.GMAIL_SELECTION_INVALID


def test_mime_depth_and_part_count_are_bounded():
    deep = part()
    for _ in range(6): deep = {'mimeType': 'multipart/mixed', 'parts': [deep]}
    wide = {'mimeType': 'multipart/mixed', 'parts': [part()] * 65}
    for payload in [deep, wide]:
        with pytest.raises(ApplicationError): extract(message(payload=payload), 'Label_feedback', 16384)
