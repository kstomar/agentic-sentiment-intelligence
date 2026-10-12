"""Bounded, non-executing CSV/XLSX ingestion with explicit row/date policies."""

import csv
import io
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from email.message import Message
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

import openpyxl
from pydantic import ValidationError

from app.core.exceptions import ApplicationError, ErrorCode
from app.schemas.batch import DateState, ParsedRecord, RecordMetadata, UploadOptions
from app.schemas.sentiment import SentimentRequest


@dataclass
class ParsedFile:
    records: list[ParsedRecord]
    skipped_blank_rows: int


def blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


class FileParser:
    def __init__(self, *, max_bytes: int, max_records: int, max_text: int, max_extracted: int) -> None:
        self.max_bytes = max_bytes
        self.max_records = max_records
        self.max_text = max_text
        self.max_extracted = max_extracted

    def parse(self, data: bytes, filename: str, content_type: str, options: UploadOptions) -> ParsedFile:
        if len(data) > self.max_bytes:
            raise ApplicationError(ErrorCode.BATCH_FILE_TOO_LARGE)
        if not data:
            raise ApplicationError(ErrorCode.BATCH_INVALID_FILE)
        extension = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
        mime = Message()
        mime["content-type"] = content_type or "application/octet-stream"
        allowed = {
            ".csv": {"text/csv", "application/csv", "text/plain", "application/vnd.ms-excel", "application/octet-stream"},
            ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/octet-stream"},
        }
        if extension not in allowed or mime.get_content_type() not in allowed[extension]:
            raise ApplicationError(ErrorCode.BATCH_UNSUPPORTED_FORMAT)
        if extension == ".csv":
            charset = mime.get_content_charset()
            if charset and charset.lower() not in {"utf-8", "utf8", "utf-8-sig"}:
                raise ApplicationError(ErrorCode.BATCH_INVALID_ENCODING)
            return self._csv(data, options)
        return self._xlsx(data, options)

    def _headers(self, values: list[object], options: UploadOptions) -> tuple[list[str], list[int]]:
        if not values or len(values) > 128 or any(not isinstance(x, str) or blank(x) for x in values):
            raise ApplicationError(ErrorCode.BATCH_INVALID_COLUMNS)
        headers = [str(x).strip() for x in values]
        if any(len(x) > 128 for x in headers) or len(set(headers)) != len(headers):
            raise ApplicationError(ErrorCode.BATCH_INVALID_COLUMNS)
        mappings = [options.text_column, options.id_column, options.date_column]
        if any(name is not None and name not in headers for name in mappings):
            raise ApplicationError(ErrorCode.BATCH_INVALID_COLUMNS)
        return headers, [headers.index(name) if name is not None else -1 for name in mappings]

    def _csv(self, data: bytes, options: UploadOptions) -> ParsedFile:
        try:
            decoded = data.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError:
            raise ApplicationError(ErrorCode.BATCH_INVALID_ENCODING) from None
        if "\x00" in decoded:
            raise ApplicationError(ErrorCode.BATCH_INVALID_FILE)
        self._csv_quotes(decoded)
        records: list[ParsedRecord] = []
        skipped = 0
        seen: set[str] = set()
        try:
            reader = csv.reader(io.StringIO(decoded, newline=""), strict=True)
            headers, columns = self._headers(next(reader, []), options)
            for row_number, values in enumerate(reader, start=2):
                if row_number > self.max_records + 1001:
                    raise ApplicationError(ErrorCode.BATCH_EXTRACTION_LIMIT)
                if all(blank(x) for x in values):
                    skipped += 1
                    continue
                if len(values) != len(headers):
                    raise ApplicationError(ErrorCode.BATCH_INVALID_FILE)
                self._append(records, seen, values, set(), columns, row_number, options)
        except csv.Error:
            raise ApplicationError(ErrorCode.BATCH_INVALID_FILE) from None
        return self._finish(records, skipped)

    @staticmethod
    def _csv_quotes(text: str) -> None:
        """Reject bare quotes and trailing content that csv.reader tolerates."""
        state = "start"
        for character in text:
            if state == "quoted":
                if character == '"':
                    state = "closed"
            elif state == "closed":
                if character == '"':
                    state = "quoted"
                elif character in ",\r\n":
                    state = "start"
                else:
                    raise ApplicationError(ErrorCode.BATCH_INVALID_FILE)
            elif character in ",\r\n":
                state = "start"
            elif character == '"':
                if state != "start":
                    raise ApplicationError(ErrorCode.BATCH_INVALID_FILE)
                state = "quoted"
            else:
                state = "unquoted"
        if state == "quoted":
            raise ApplicationError(ErrorCode.BATCH_INVALID_FILE)

    def _check_archive(self, data: bytes) -> None:
        try:
            with ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                if len(entries) > 256 or sum(x.file_size for x in entries) > self.max_extracted:
                    raise ApplicationError(ErrorCode.BATCH_EXTRACTION_LIMIT)
                names = [entry.filename for entry in entries]
                if len(names) != len(set(names)):
                    raise ApplicationError(ErrorCode.BATCH_INVALID_FILE)
                for entry in entries:
                    name = entry.filename.lower()
                    if entry.flag_bits & 1 or "vbaproject" in name or "macrosheets" in name:
                        raise ApplicationError(ErrorCode.BATCH_INVALID_FILE)
                    if entry.file_size > max(1, entry.compress_size) * 200:
                        raise ApplicationError(ErrorCode.BATCH_EXTRACTION_LIMIT)
                    if name.endswith((".xml", ".rels")):
                        with archive.open(entry) as stream:
                            previous = b""
                            remaining = self.max_extracted
                            while chunk := stream.read(min(65536, remaining + 1)):
                                remaining -= len(chunk)
                                if remaining < 0:
                                    raise ApplicationError(ErrorCode.BATCH_EXTRACTION_LIMIT)
                                block = (previous + chunk).upper()
                                if b"\x00" in block or b"<!DOCTYPE" in block or b"<!ENTITY" in block:
                                    raise ApplicationError(ErrorCode.BATCH_INVALID_FILE)
                                previous = block[-16:]
        except (BadZipFile, RuntimeError, OSError, ValueError):
            raise ApplicationError(ErrorCode.BATCH_INVALID_FILE) from None

    def _xlsx(self, data: bytes, options: UploadOptions) -> ParsedFile:
        self._check_archive(data)
        workbook = None
        try:
            workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=False, keep_links=False)
            sheet = workbook.worksheets[0]
            sheet.reset_dimensions()
            rows = sheet.iter_rows()
            first = list(next(rows, []))
            while first and blank(first[-1].value):
                first.pop()
            if any(cell.data_type == "f" for cell in first):
                raise ApplicationError(ErrorCode.BATCH_INVALID_COLUMNS)
            headers, columns = self._headers([cell.value for cell in first], options)
            records: list[ParsedRecord] = []
            seen: set[str] = set()
            skipped = 0
            for row_number, cells in enumerate(rows, start=2):
                if row_number > self.max_records + 1001:
                    raise ApplicationError(ErrorCode.BATCH_EXTRACTION_LIMIT)
                values = [cell.value for cell in cells]
                if all(blank(value) for value in values):
                    skipped += 1
                    continue
                if any(not blank(value) for value in values[len(headers):]):
                    raise ApplicationError(ErrorCode.BATCH_INVALID_COLUMNS)
                formulas = {index for index, cell in enumerate(cells) if cell.data_type == "f"}
                values = values[:len(headers)] + [None] * max(0, len(headers) - len(values))
                self._append(records, seen, values, formulas, columns, row_number, options)
            return self._finish(records, skipped)
        except ApplicationError:
            raise
        except Exception:
            raise ApplicationError(ErrorCode.BATCH_INVALID_FILE) from None
        finally:
            if workbook is not None:
                workbook.close()

    def _append(
        self, records: list[ParsedRecord], seen: set[str], values: list[object], formulas: set[int],
        columns: list[int], row_number: int, options: UploadOptions,
    ) -> None:
        if len(records) >= self.max_records:
            raise ApplicationError(ErrorCode.BATCH_TOO_MANY_RECORDS)
        text_index, id_index, date_index = columns
        identifier = f"row-{row_number}" if id_index < 0 else values[id_index]
        if id_index in formulas or isinstance(identifier, bool):
            raise ApplicationError(ErrorCode.BATCH_INVALID_IDS)
        if isinstance(identifier, (int, float)):
            if isinstance(identifier, float) and not math.isfinite(identifier):
                raise ApplicationError(ErrorCode.BATCH_INVALID_IDS)
            identifier = str(int(identifier)) if float(identifier).is_integer() else str(identifier)
        if not isinstance(identifier, str) or blank(identifier) or len(identifier) > 100 or identifier in seen:
            raise ApplicationError(ErrorCode.BATCH_INVALID_IDS)
        seen.add(identifier)
        normalized, date_state = self._date(values[date_index] if date_index >= 0 else None, date_index, formulas)
        text = values[text_index]
        error = None
        try:
            if text_index in formulas or not isinstance(text, str) or len(text) > self.max_text:
                raise ValueError("Invalid feedback text.")
            SentimentRequest(text=text, business_type=options.business_type)
        except (ValidationError, ValueError, TypeError):
            text = None
            error = ErrorCode.BATCH_INVALID_TEXT
        records.append(ParsedRecord(
            meta=RecordMetadata(feedback_id=identifier, source_row=row_number, normalized_date=normalized, date_status=date_state),
            text=text, validation_error=error,
        ))

    @staticmethod
    def _date(value: object, index: int, formulas: set[int]) -> tuple[date | None, DateState]:
        if index < 0:
            return None, DateState.NOT_PROVIDED
        if blank(value):
            return None, DateState.MISSING
        if index in formulas:
            return None, DateState.INVALID
        if isinstance(value, datetime):
            return value.date(), DateState.VALID
        if isinstance(value, date):
            return value, DateState.VALID
        if isinstance(value, str):
            value = value.strip()
            try:
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    return date.fromisoformat(value), DateState.VALID
                if re.fullmatch(r"\d{4}/\d{2}/\d{2}", value):
                    return datetime.strptime(value, "%Y/%m/%d").date(), DateState.VALID
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?", value):
                    return datetime.fromisoformat(value.replace("Z", "+00:00")).date(), DateState.VALID
            except ValueError:
                pass
        return None, DateState.INVALID

    @staticmethod
    def _finish(records: list[ParsedRecord], skipped: int) -> ParsedFile:
        if not records or not any(record.validation_error is None for record in records):
            raise ApplicationError(ErrorCode.BATCH_NO_VALID_RECORDS)
        return ParsedFile(records, skipped)
