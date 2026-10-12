import io
import re
from datetime import datetime
from zipfile import ZipFile, ZIP_DEFLATED

import pytest

from app.core.exceptions import ApplicationError, ErrorCode as E
from app.schemas.batch import UploadOptions
from app.services.file_parser import FileParser
from tests.helpers import xlsx


@pytest.fixture
def parser():
    return FileParser(max_bytes=2*1024**2, max_records=100, max_text=5000, max_extracted=16*1024**2)


def parse(parser, content, *, options=None, filename="safe.csv", mime="text/csv"):
    return parser.parse(content, filename, mime, options or UploadOptions(text_column="review"))


def test_csv_bom_quotes_mapping_blank_rows_and_invalid_text(parser):
    result = parse(parser, b'\xef\xbb\xbfid,review,date\na,"late, again\nand again",2024/02/29\n,,\nb,,bad\n',
                   options=UploadOptions(text_column="review", id_column="id", date_column="date"))
    assert result.skipped_blank_rows == 1 and len(result.records) == 2
    assert result.records[0].text == "late, again\nand again"
    assert str(result.records[0].meta.normalized_date) == "2024-02-29"
    assert result.records[1].validation_error == E.BATCH_INVALID_TEXT
    assert result.records[1].meta.date_status == "INVALID"


@pytest.mark.parametrize("content,expected", [
    (b"", E.BATCH_INVALID_FILE), (b"review,review\na,b", E.BATCH_INVALID_COLUMNS),
    (b",other\na,b", E.BATCH_INVALID_COLUMNS), (b"other\na", E.BATCH_INVALID_COLUMNS),
    (b'review\n"unfinished', E.BATCH_INVALID_FILE), (b'review\na"b', E.BATCH_INVALID_FILE),
    (b'review\n"ok"bad', E.BATCH_INVALID_FILE), (b"review\na,b", E.BATCH_INVALID_FILE),
    (b"review\n\xff", E.BATCH_INVALID_ENCODING), (b"review\nx\x00", E.BATCH_INVALID_FILE),
    (b"review\n\n", E.BATCH_NO_VALID_RECORDS),
    (b"review\n" + b"x\n"*101, E.BATCH_TOO_MANY_RECORDS),
    (b"x"*(2*1024**2+1), E.BATCH_FILE_TOO_LARGE),
    (b"review\nx\n"+b"\n"*1100, E.BATCH_EXTRACTION_LIMIT),
])
def test_csv_rejections(parser, content, expected):
    with pytest.raises(ApplicationError) as caught:
        parse(parser, content)
    assert caught.value.code == expected


@pytest.mark.parametrize("identifier_rows", [b"x,a\nx,b", b",a", b"x"*101+b",a"])
def test_invalid_or_duplicate_ids(parser, identifier_rows):
    with pytest.raises(ApplicationError) as caught:
        parse(parser, b"id,review\n"+identifier_rows, options=UploadOptions(text_column="review", id_column="id"))
    assert caught.value.code == E.BATCH_INVALID_IDS


@pytest.mark.parametrize("filename,mime,expected", [
    ("bad.xls", "application/octet-stream", E.BATCH_UNSUPPORTED_FORMAT),
    ("safe.csv", "application/json", E.BATCH_UNSUPPORTED_FORMAT),
    ("safe.csv", "text/csv; charset=latin1", E.BATCH_INVALID_ENCODING),
])
def test_extension_mime_and_charset(parser, filename, mime, expected):
    with pytest.raises(ApplicationError) as caught:
        parse(parser, b"review\nfine", filename=filename, mime=mime)
    assert caught.value.code == expected


def test_exact_limits_and_stable_generated_ids(parser):
    assert len(parse(parser, b"review\n"+b"x\n"*100).records) == 100
    result = parse(parser, ("review\n"+"x"*5000+"\n\n"+"x"*5001).encode())
    assert result.records[0].text and result.records[1].validation_error == E.BATCH_INVALID_TEXT
    assert [r.meta.feedback_id for r in result.records] == ["row-2", "row-4"]


def test_xlsx_first_sheet_dates_and_formulas(parser):
    content = xlsx([["id", "review", "date"], [1, "fine", datetime(2024, 1, 2)],
                    [2, "=1+1", "=TODAY()"], [None, None, None], [3, "ok", "bad"]],
                   second_sheet=[["wrong"], ["never analyzed"]])
    result = parse(parser, content, filename="safe.xlsx", mime="application/octet-stream",
                   options=UploadOptions(text_column="review", id_column="id", date_column="date"))
    assert len(result.records) == 3 and result.skipped_blank_rows == 1
    assert result.records[0].meta.feedback_id == "1"
    assert str(result.records[0].meta.normalized_date) == "2024-01-02"
    assert result.records[1].text is None and result.records[1].meta.date_status == "INVALID"


@pytest.mark.parametrize("rows,options,expected", [
    ([["wrong"], ["a"]], UploadOptions(text_column="review"), E.BATCH_INVALID_COLUMNS),
    ([["id", "review"], ["x", "a"], ["x", "b"]], UploadOptions(text_column="review", id_column="id"), E.BATCH_INVALID_IDS),
    ([["id", "review"], ["=1", "a"]], UploadOptions(text_column="review", id_column="id"), E.BATCH_INVALID_IDS),
    ([["review"], [12]], UploadOptions(text_column="review"), E.BATCH_NO_VALID_RECORDS),
])
def test_xlsx_mapping_ids_and_nontext(parser, rows, options, expected):
    with pytest.raises(ApplicationError) as caught:
        parse(parser, xlsx(rows), options=options, filename="safe.xlsx", mime="application/octet-stream")
    assert caught.value.code == expected


def rewrite(content, transform=lambda name,data:data, extra=None):
    output = io.BytesIO()
    with ZipFile(io.BytesIO(content)) as source, ZipFile(output, "w", ZIP_DEFLATED) as destination:
        for entry in source.infolist():
            destination.writestr(entry.filename, transform(entry.filename, source.read(entry)))
        if extra:
            destination.writestr(*extra)
    return output.getvalue()


@pytest.mark.parametrize("variant,expected", [
    ("not-zip", E.BATCH_INVALID_FILE), ("truncated", E.BATCH_INVALID_FILE),
    ("macro", E.BATCH_INVALID_FILE), ("doctype", E.BATCH_INVALID_FILE),
    ("compressed", E.BATCH_EXTRACTION_LIMIT),
])
def test_xlsx_corruption_macros_entities_and_expansion(parser, variant, expected):
    content = xlsx([["review"], ["fine"]])
    if variant == "not-zip": content = b"not a workbook"
    if variant == "truncated": content = content[:100]
    if variant == "macro": content = rewrite(content, extra=("xl/vbaProject.bin", b"never execute"))
    if variant == "doctype": content = rewrite(content, lambda n,b:b"<!DOCTYPE x>"+b if n=="xl/workbook.xml" else b)
    if variant == "compressed": content = rewrite(content, extra=("bomb.xml", b" "*100000))
    with pytest.raises(ApplicationError) as caught:
        parse(parser, content, filename="safe.xlsx", mime="application/octet-stream")
    assert caught.value.code == expected


def test_xlsx_untrusted_declared_dimensions_are_reset(parser):
    content = rewrite(xlsx([["review"], ["fine"]]), lambda n,b:
        re.sub(rb'<dimension ref="[^"]+"', b'<dimension ref="A1:A1"', b) if n=="xl/worksheets/sheet1.xml" else b)
    assert parse(parser, content, filename="safe.xlsx", mime="application/octet-stream").records[0].text == "fine"


def test_optional_dates_never_invent_missing_values(parser):
    result = parse(parser, b"review,date\na,2024-02-29T23:01:00-05:00\nb,2023-02-29\nc,\nd,10/02/2024",
                   options=UploadOptions(text_column="review", date_column="date"))
    assert [r.meta.date_status.value for r in result.records] == ["VALID", "INVALID", "MISSING", "INVALID"]
    assert str(result.records[0].meta.normalized_date) == "2024-02-29"
    assert all(r.meta.normalized_date is None for r in result.records[1:])
