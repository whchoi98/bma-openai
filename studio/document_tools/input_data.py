"""Bounded local input inspection and deterministic, source-backed aggregation.

The first physical row of each table is its header. Data rows retain their order
and blank cells; IDs refer to positions, never to executable expressions.
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
import stat
import zipfile
import zlib
from collections import OrderedDict
from datetime import date, datetime, time
from pathlib import PurePosixPath
from xml.etree import ElementTree

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring as safe_xml_fromstring
from openpyxl import load_workbook

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_TEXT_CHARACTERS = 50_000
MAX_SHEETS = 5
MAX_ROWS = 10_000
MAX_COLUMNS = 50
MAX_CELLS = 100_000
MAX_CATEGORIES = 50
MAX_ZIP_MEMBERS = 256
MAX_ZIP_MEMBER_BYTES = 12 * 1024 * 1024
MAX_ZIP_TOTAL_BYTES = 30 * 1024 * 1024
PROFILE_TEXT_CHARACTERS = 8_000
MAX_PROFILE_BYTES = 200_000

_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_CELL = re.compile(r"^([A-Z]{1,3})([1-9][0-9]*)$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ].*)?$")
_ALLOWED = {"xlsx", "csv", "txt", "md"}


def _finite(value):
    try:
        return math.isfinite(value)
    except (TypeError, ValueError, OverflowError):
        return False


def _text(value, label):
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text.")
    if "\x00" in value or any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ValueError(f"{label} contains unsupported binary or Unicode data.")
    return value


def _decode(data, warnings):
    try:
        result = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            result = data.decode("cp949")
        except UnicodeDecodeError as exc:
            raise ValueError("Text must use UTF-8 or Korean CP949 encoding.") from exc
        warnings.append("Decoded text using Korean CP949 encoding.")
    return _text(result, "Input")


def _parse_number(value):
    """Return a finite numeric value, or None; booleans are not measurements."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value if _finite(value) else None
    if isinstance(value, str):
        value = value.strip()
        if not _NUMBER.fullmatch(value):
            return None
        try:
            number = float(value) if any(char in value.lower() for char in ".e") else int(value)
        except (ValueError, OverflowError):
            return None
        return number if _finite(number) else None
    return None


def _csv_cell(value):
    if not value.strip():
        return None
    stripped = value.strip()
    # Preserve codes such as 001 rather than silently converting them to 1.
    unsigned = stripped.lstrip("+-")
    if len(unsigned) > 1 and unsigned[0] == "0" and unsigned[1].isdigit():
        return value
    number = _parse_number(stripped)
    return number if number is not None else value


def _json_cell(value, warnings):
    if value is None or isinstance(value, (str, bool)):
        if isinstance(value, str):
            if len(value) > MAX_TEXT_CHARACTERS:
                raise ValueError("A cell exceeds the text size limit.")
            return _text(value, "Cell")
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (int, float)):
        if _finite(value):
            return value
        warnings.append("A non-finite numeric cell was kept missing.")
        return None
    return str(value)


def _date_value(value):
    if not isinstance(value, str) or not _DATE.fullmatch(value.strip()):
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None


def _column_type(values):
    types = set()
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool):
            types.add("boolean")
        elif isinstance(value, (int, float)):
            types.add("number")
        elif _date_value(value) is not None:
            types.add("date")
        else:
            types.add("string")
    return next(iter(types)) if len(types) == 1 else "mixed" if types else "empty"


def _table(raw_rows, sheet_id, name, warnings):
    if not raw_rows:
        return {"id": sheet_id, "name": name, "columns": [], "rows": [], "row_count": 0, "warnings": warnings}
    width = max(map(len, raw_rows), default=0)
    if width > MAX_COLUMNS:
        raise ValueError(f"Each table is limited to {MAX_COLUMNS} columns.")
    if len(raw_rows) - 1 > MAX_ROWS:
        raise ValueError(f"Each table is limited to {MAX_ROWS} data rows.")
    rows = [row + [None] * (width - len(row)) for row in raw_rows]
    header, rows = rows[0], rows[1:]
    columns = [
        {"id": f"c{index}", "name": str(header[index]) if header[index] is not None else f"Column {index + 1}",
         "type": _column_type(row[index] for row in rows)}
        for index in range(width)
    ]
    return {"id": sheet_id, "name": name, "columns": columns, "rows": rows, "row_count": len(rows), "warnings": warnings}


def _csv_table(text):
    # Limit individual fields before parsing. The process-wide default is already
    # smaller, but do not enlarge it: huge cells are not useful document inputs.
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = []
    width = 0
    try:
        for row in csv.reader(io.StringIO(text, newline=""), dialect=dialect, strict=True):
            if len(row) > MAX_COLUMNS:
                raise ValueError(f"Each table is limited to {MAX_COLUMNS} columns.")
            width = max(width, len(row))
            if len(rows) >= MAX_ROWS + 1:
                raise ValueError(f"Each table is limited to {MAX_ROWS} data rows.")
            if (len(rows) + 1) * width > MAX_CELLS:
                raise ValueError(f"Input is limited to {MAX_CELLS} total cells including headers.")
            if any(len(cell) > MAX_TEXT_CHARACTERS for cell in row):
                raise ValueError("A cell exceeds the text size limit.")
            rows.append([_csv_cell(cell) for cell in row])
    except csv.Error as exc:
        raise ValueError("CSV is malformed or contains an oversized field.") from exc
    if not rows or not any(any(cell is not None for cell in row) for row in rows):
        raise ValueError("CSV contains no table data.")
    return _table(rows, "sheet_0", "CSV", [])


def _safe_member(name):
    if not name or len(name) > 512 or "\\" in name or "\x00" in name or ":" in name:
        return False
    path = PurePosixPath(name)
    return not path.is_absolute() and all(part not in {"", ".", ".."} for part in name.rstrip("/").split("/"))


def _xml_payload(data):
    """Check declarations in every ZIP part, independent of its filename.

    XML consumed by Expat begins with '<' after BOM/whitespace normalization.
    Removing NUL interleaving also recognizes UTF-16/32 XML parts. Content-based
    recognition includes worksheet/shared-string parts renamed by OOXML links.
    """
    normalized = data.replace(b"\x00", b"")
    lower = normalized.lower()
    if b"<!doctype" in lower or b"<!entity" in lower:
        raise ValueError("XML entity declarations and document types are not supported.")
    return normalized.lstrip(b"\xef\xbb\xbf\xff\xfe \t\r\n").startswith(b"<")


def _xml_root(data):
    _xml_payload(data)
    try:
        return safe_xml_fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise ValueError("Workbook contains malformed or unsafe XML.") from exc


def _local_name(tag):
    return tag.rsplit("}", 1)[-1]


def _zip_preflight(data):
    """Inspect every bounded ZIP member before openpyxl allocates workbook data."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError("XLSX must be an unencrypted, valid Office ZIP workbook.") from exc
    with archive:
        members = archive.infolist()
        if len(members) > MAX_ZIP_MEMBERS:
            raise ValueError("Workbook contains too many ZIP members.")
        seen = set()
        total = 0
        for item in members:
            name = item.filename
            folded = name.casefold()
            mode = (item.external_attr >> 16) & 0xFFFF
            if not _safe_member(name) or stat.S_ISLNK(mode):
                raise ValueError("Workbook contains an unsafe ZIP member path.")
            if folded in seen:
                raise ValueError("Workbook contains duplicate ZIP members.")
            seen.add(folded)
            if item.flag_bits & 1:
                raise ValueError("Encrypted workbooks are not supported.")
            if item.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise ValueError("Unsupported workbook compression.")
            total += item.file_size
            if item.file_size > MAX_ZIP_MEMBER_BYTES or total > MAX_ZIP_TOTAL_BYTES:
                raise ValueError("Expanded workbook exceeds the ZIP size limit.")
            if item.file_size > 1024 * 1024 and item.file_size / max(item.compress_size, 1) > 200:
                raise ValueError("Workbook compression ratio exceeds the safety limit.")
            if any(token in folded for token in ("vbaproject", "vbadata", "externallink", "macrosheet", "activex/", "embeddings/", "connections.xml", "querytables/")):
                raise ValueError("Macros, embedded objects, and external references are not supported.")
        if "[content_types].xml" not in seen or "xl/workbook.xml" not in seen:
            raise ValueError("ZIP is not a supported XLSX workbook.")
        actual_cells = 0
        sheets = 0
        try:
            for item in members:
                # Reading every member validates CRCs and local ZIP headers,
                # including unused parts, within the prevalidated size budget.
                payload = archive.read(item)
                xml_content = _xml_payload(payload)
                if not xml_content and not item.filename.lower().endswith((".xml", ".rels")):
                    continue
                root = _xml_root(payload)
                for node in root.iter():
                    if node.attrib.get("TargetMode", "").lower() == "external":
                        raise ValueError("External workbook references are not supported.")
                    if _local_name(node.tag) in {"Override", "Default"}:
                        content_type = node.attrib.get("ContentType", "").lower()
                        if any(token in content_type for token in ("macroenabled", "vbaproject", "macrosheet", "activex")):
                            raise ValueError("Macro-enabled workbook content is not supported.")
                    if _local_name(node.tag) == "Relationship":
                        relation = node.attrib.get("Type", "").lower()
                        target = node.attrib.get("Target", "")
                        if any(token in relation for token in ("externallink", "vbaproject", "oleobject", "activex", "macrosheet")):
                            raise ValueError("Unsafe workbook relationships are not supported.")
                        if "://" in target or target.startswith("//") or "\\" in target:
                            raise ValueError("Remote workbook relationships are not supported.")
                    if _local_name(node.tag) == "t" and node.text and len(node.text) > MAX_TEXT_CHARACTERS:
                        raise ValueError("A cell exceeds the text size limit.")
                if _local_name(root.tag) == "workbook":
                    if sum(_local_name(node.tag) == "sheet" for node in root.iter()) > MAX_SHEETS:
                        raise ValueError(f"Workbooks are limited to {MAX_SHEETS} sheets.")
                if _local_name(root.tag) != "worksheet":
                    continue
                sheets += 1
                if sheets > MAX_SHEETS:
                    raise ValueError(f"Workbooks are limited to {MAX_SHEETS} sheets.")
                previous_row = 0
                for row_node in (node for node in root.iter() if _local_name(node.tag) == "row"):
                    row_id = row_node.attrib.get("r", str(previous_row + 1))
                    if not row_id.isdecimal() or not previous_row < int(row_id) <= MAX_ROWS + 1:
                        raise ValueError("Workbook contains unordered or invalid rows.")
                    previous_row = int(row_id)
                    previous_column = 0
                    for cell in row_node:
                        if _local_name(cell.tag) != "c":
                            continue
                        coordinate = cell.attrib.get("r")
                        column = previous_column + 1
                        if coordinate:
                            match = _CELL.fullmatch(coordinate)
                            if not match or int(match.group(2)) != previous_row:
                                raise ValueError("Workbook contains an ambiguous cell reference.")
                            column = 0
                            for char in match.group(1):
                                column = column * 26 + ord(char) - ord("A") + 1
                        if not previous_column < column <= MAX_COLUMNS:
                            raise ValueError("Workbook contains unordered, duplicate, or excessive columns.")
                        previous_column = column
                physical_rows = 0
                for node in root.iter():
                    tag = _local_name(node.tag)
                    if tag == "row":
                        physical_rows += 1
                        if physical_rows > MAX_ROWS + 1:
                            raise ValueError("Workbook exceeds the row limit.")
                        row_index = node.attrib.get("r")
                        if row_index and (not row_index.isdecimal() or int(row_index) > MAX_ROWS + 1):
                            raise ValueError("Workbook exceeds the row limit.")
                    if tag != "c":
                        continue
                    actual_cells += 1
                    if actual_cells > MAX_CELLS:
                        raise ValueError("Workbook exceeds the total cell limit.")
                    coordinate = node.attrib.get("r")
                    if coordinate:
                        match = _CELL.fullmatch(coordinate)
                        if not match:
                            raise ValueError("Workbook contains an invalid cell reference.")
                        column = 0
                        for char in match.group(1):
                            column = column * 26 + ord(char) - ord("A") + 1
                        if column > MAX_COLUMNS or int(match.group(2)) > MAX_ROWS + 1:
                            raise ValueError("Workbook exceeds the row or column limit.")
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, zlib.error) as exc:
            raise ValueError("Workbook has invalid or unsupported ZIP content.") from exc


def _xlsx_tables(data, warnings):
    _zip_preflight(data)
    values_book = None
    formula_book = None
    try:
        values_book = load_workbook(io.BytesIO(data), read_only=True, data_only=True, keep_links=False)
        formula_book = load_workbook(io.BytesIO(data), read_only=True, data_only=False, keep_links=False)
        if len(values_book.sheetnames) > MAX_SHEETS:
            raise ValueError(f"Workbooks are limited to {MAX_SHEETS} sheets.")
        tables = []
        total_cells = 0
        for index, (sheet, formulas) in enumerate(zip(values_book.worksheets, formula_book.worksheets)):
            sheet.reset_dimensions()
            formulas.reset_dimensions()
            rows = []
            width = 0
            missing_caches = 0
            errors = 0
            table_warnings = []
            for value_row, formula_row in zip(sheet.iter_rows(), formulas.iter_rows()):
                if len(value_row) > MAX_COLUMNS or len(rows) >= MAX_ROWS + 1:
                    raise ValueError("Workbook exceeds the row or column limit.")
                width = max(width, len(value_row))
                if total_cells + (len(rows) + 1) * width > MAX_CELLS:
                    raise ValueError("Workbook exceeds the total cell limit including headers.")
                row = []
                for cell, formula in zip(value_row, formula_row):
                    if formula.data_type == "f" and cell.value is None:
                        missing_caches += 1
                    if cell.data_type == "e":
                        errors += 1
                        row.append(None)
                    else:
                        row.append(_json_cell(cell.value, table_warnings))
                rows.append(row)
            if missing_caches:
                table_warnings.append(f"{missing_caches} formula cell(s) have no saved cache; values remain missing. Formulas were not evaluated.")
            if errors:
                table_warnings.append(f"{errors} spreadsheet error cell(s) were kept missing.")
            table_warnings = list(dict.fromkeys(table_warnings))
            total_cells += len(rows) * width
            tables.append(_table(rows, f"sheet_{index}", sheet.title, table_warnings))
            warnings.extend(f"{sheet.title}: {warning}" for warning in table_warnings)
        if not tables:
            raise ValueError("Workbook contains no worksheets.")
        return tables
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Unable to read this XLSX workbook; it may be malformed or encrypted.") from exc
    finally:
        if values_book is not None:
            values_book.close()
        if formula_book is not None:
            formula_book.close()


def inspect_source(data: bytes | None, filename: str | None, notes: str = "") -> dict:
    """Parse one supported file and notes, rejecting input outside fixed limits."""
    notes = _text(notes, "Notes")
    if len(notes) > MAX_TEXT_CHARACTERS:
        raise ValueError(f"Notes/text is limited to {MAX_TEXT_CHARACTERS} characters.")
    source = {"filename": None, "kind": "notes", "text": "", "notes": notes, "warnings": [], "sheets": []}
    if data is None:
        if filename:
            raise ValueError("A filename was supplied without file data.")
        return source
    if not isinstance(data, bytes):
        raise ValueError("File data must be bytes.")
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("Upload must contain data and cannot exceed 5 MiB.")
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("A filename with a supported extension is required.")
    _text(filename, "Filename")
    filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    if len(filename) > 255 or any(ord(char) < 32 for char in filename):
        raise ValueError("Filename is invalid.")
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in _ALLOWED:
        raise ValueError("Supported file types are XLSX, CSV, TXT, and MD; XLS/XLSM are not supported.")
    source.update(filename=filename, kind=extension)
    if extension == "xlsx":
        source["sheets"] = _xlsx_tables(data, source["warnings"])
    else:
        text = _decode(data, source["warnings"])
        if extension == "csv":
            source["sheets"] = [_csv_table(text)]
        else:
            if len(text) + len(notes) > MAX_TEXT_CHARACTERS:
                raise ValueError(f"Combined notes/text is limited to {MAX_TEXT_CHARACTERS} characters.")
            source["text"] = text
    return source


def _profile_with_limits(source, *, cell_limit, name_limit, text_limit, row_limit):
    text, notes = source.get("text", ""), source.get("notes", "")
    profile = {
        "filename": source.get("filename"), "kind": source.get("kind"),
        "text": text[:text_limit], "notes": notes[:text_limit],
        "text_characters": len(text), "notes_characters": len(notes),
        "text_truncated": len(text) > text_limit, "notes_truncated": len(notes) > text_limit,
        "warnings": list(source.get("warnings", [])), "sheets": [],
        "sheet_count": len(source.get("sheets", [])), "byte_limit": MAX_PROFILE_BYTES,
    }
    truncated = profile["text_truncated"] or profile["notes_truncated"]
    for sheet in source.get("sheets", []):
        columns = [
            {**column, "name": column["name"][:name_limit],
             "name_characters": len(column["name"]), "name_truncated": len(column["name"]) > name_limit}
            for column in sheet["columns"]
        ]
        sample = sheet["rows"][:row_limit]
        rows = [[cell[:cell_limit] if isinstance(cell, str) else cell for cell in row] for row in sample]
        text_truncated = any(isinstance(cell, str) and len(cell) > cell_limit for row in sample for cell in row)
        rows_truncated = len(rows) < sheet["row_count"]
        profile["sheets"].append({
            "id": sheet["id"], "name": sheet["name"], "columns": columns, "rows": rows,
            "row_count": sheet["row_count"], "column_count": len(columns),
            "sample_row_count": len(rows), "sample_rows_truncated": rows_truncated,
            "sample_text_truncated": text_truncated, "sample_text_limit": cell_limit,
            "warnings": list(sheet.get("warnings", [])),
        })
        truncated |= rows_truncated or text_truncated or any(column["name_truncated"] for column in columns)
    profile["truncated"] = truncated
    return profile


def source_profile(source) -> dict:
    """Return metadata and samples within one global UTF-8 JSON byte budget.

    All sheet/column IDs and source counts remain visible. Display names, cell
    excerpts and text excerpts may shrink, then sample row counts may decrease.
    Numeric cells are either preserved exactly or omitted with the whole sample
    row. The authoritative internal source is never modified.
    """
    limits = {"cell_limit": 128, "name_limit": 160, "text_limit": PROFILE_TEXT_CHARACTERS, "row_limit": 8}
    while True:
        profile = _profile_with_limits(source, **limits)
        # Default JSON separators are deliberately counted as well, providing
        # enough space for either compact Node JSON or default Python JSON.
        size = len(json.dumps(profile, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        if size <= MAX_PROFILE_BYTES:
            return profile
        if limits["cell_limit"] > 16:
            limits["cell_limit"] //= 2
        elif limits["text_limit"] > 1000:
            limits["text_limit"] //= 2
        elif limits["name_limit"] > 32:
            limits["name_limit"] = max(32, limits["name_limit"] // 2)
        elif limits["row_limit"]:
            limits["row_limit"] //= 2
        else:
            # Valid inspected inputs have bounded metadata and cannot reach
            # this branch. Refuse an invalid hand-built source rather than
            # silently dropping the identifiers needed to read its data.
            raise ValueError("Source metadata exceeds the profile byte budget.")


def _missing(value):
    return value is None or isinstance(value, str) and not value.strip()


def _group(value, group_by):
    if group_by != "value":
        parsed = _date_value(value)
        if parsed is None:
            return None
        category = parsed.strftime("%Y-%m" if group_by == "month" else "%Y")
        return ("date", category), category
    if isinstance(value, bool):
        return ("boolean", value), str(value).lower()
    if isinstance(value, (int, float)) and _finite(value):
        return ("number", value), str(value)
    if isinstance(value, str):
        return ("string", value), value
    return None


def _sum(values):
    try:
        result = sum(values) if all(isinstance(value, int) for value in values) else math.fsum(values)
    except (OverflowError, ValueError) as exc:
        raise ValueError("Numeric aggregation overflowed; reduce the selected data range.") from exc
    if not _finite(result):
        raise ValueError("Numeric aggregation overflowed; reduce the selected data range.")
    return result


def aggregate_chart(source, sheet_id, x_column, y_column=None, aggregation="sum", chart_type="bar", group_by="value") -> dict:
    """Aggregate measured data without filling missing measurements with zeros.

    Count without y counts rows. Count with y counts present values of any type.
    Missing/invalid counters count excluded cells, or the first unusable cell in
    an otherwise excluded row. Unaggregated charts preserve duplicate categories.
    """
    if chart_type not in {"bar", "line", "pie", "scatter"}:
        raise ValueError("Chart type must be bar, line, pie, or scatter.")
    if aggregation not in {"sum", "mean", "count", "none"}:
        raise ValueError("Aggregation must be sum, mean, count, or none.")
    if group_by not in {"value", "month", "year"}:
        raise ValueError("Grouping must be value, month, or year.")
    if chart_type == "scatter" and (aggregation != "none" or group_by != "value"):
        raise ValueError("Scatter charts require aggregation none and numeric value grouping.")
    sheet = next((sheet for sheet in source.get("sheets", []) if sheet["id"] == sheet_id), None)
    if sheet is None:
        raise ValueError("Selected sheet does not exist.")
    column_map = {column["id"]: (index, column) for index, column in enumerate(sheet["columns"])}
    if x_column not in column_map or (y_column is not None and y_column not in column_map):
        raise ValueError("Select columns using the IDs from the source profile.")
    if y_column is None and aggregation != "count":
        raise ValueError("This chart requires a numeric y column.")
    x_index, x_schema = column_map[x_column]
    y_index, y_schema = column_map[y_column] if y_column is not None else (None, None)
    groups = OrderedDict()
    points = []
    missing = 0
    invalid = 0
    numeric_count = 0
    for row in sheet["rows"]:
        x_value = row[x_index] if x_index < len(row) else None
        y_value = row[y_index] if y_index is not None and y_index < len(row) else None
        if _missing(x_value):
            missing += 1
            continue
        if chart_type == "scatter":
            x_number = _parse_number(x_value)
            if x_number is None:
                invalid += 1
                continue
            if _missing(y_value):
                missing += 1
                continue
            y_number = _parse_number(y_value)
            if y_number is None:
                invalid += 1
                continue
            points.append((str(x_value), y_number, x_number))
            numeric_count += 1
            continue
        grouped = _group(x_value, group_by)
        if grouped is None:
            invalid += 1
            continue
        key, category = grouped
        if aggregation == "none":
            values = []
        else:
            if key not in groups:
                groups[key] = {"category": category, "values": [], "count": 0}
            values = groups[key]["values"]
        number = None
        if aggregation == "count":
            if y_index is None or not _missing(y_value):
                groups[key]["count"] += 1
            else:
                missing += 1
        elif _missing(y_value):
            missing += 1
        else:
            number = _parse_number(y_value)
            if number is None:
                invalid += 1
            else:
                values.append(number)
                numeric_count += 1
        if aggregation == "none":
            points.append((category, number, None))
    if aggregation != "none":
        entries = list(groups.values())
        if group_by in {"month", "year"}:
            entries.sort(key=lambda entry: entry["category"])
        for entry in entries:
            values = entry["values"]
            if aggregation == "count":
                number = entry["count"]
            elif not values:
                number = None
            elif aggregation == "mean":
                # Scaling before summation avoids overflow for finite means,
                # for example the mean of two 1e308 observations.
                number = _sum([value / len(values) for value in values])
            else:
                number = _sum(values)
            points.append((entry["category"], number, None))
    if not points or aggregation != "count" and numeric_count == 0:
        raise ValueError("No usable numeric data is available for this chart.")
    if aggregation == "count" and not any(point[1] for point in points):
        raise ValueError("No present values are available to count.")
    if chart_type == "pie":
        numbers = [value for _, value, _ in points if value is not None]
        if any(value < 0 for value in numbers) or not any(value > 0 for value in numbers):
            raise ValueError("Pie charts require nonnegative values and at least one positive value.")
    omitted = max(0, len(points) - MAX_CATEGORIES)
    points = points[:MAX_CATEGORIES]
    if not any(value is not None for _, value, _ in points):
        raise ValueError("No usable numeric data occurs within the plotted category limit.")
    if chart_type == "pie" and not any(value is not None and value > 0 for _, value, _ in points):
        raise ValueError("The plotted pie categories contain no positive values; select another chart.")
    warnings = list(source.get("warnings", []))
    if missing:
        warnings.append(f"{missing} missing value(s) were excluded from calculations; missing measurements remain null.")
    if invalid:
        warnings.append(f"{invalid} invalid value(s) were excluded from calculations.")
    if omitted:
        warnings.append(f"Only the first {MAX_CATEGORIES} categories/points are plotted; {omitted} were omitted, without an invented other category.")
    y_name = y_schema["name"] if y_schema else "Rows"
    result = {
        "chart_type": chart_type, "categories": [category for category, _, _ in points],
        "values": [value for _, value, _ in points], "x_label": x_schema["name"],
        "y_label": f"Count of {y_name}" if aggregation == "count" else y_name,
        "source": {"file": source.get("filename"), "sheet": sheet["name"], "sheet_id": sheet["id"],
                   "x_column": dict(x_schema), "y_column": dict(y_schema) if y_schema else None,
                   "aggregation": aggregation, "group_by": group_by, "row_count": sheet["row_count"]},
        "missing_values": missing, "invalid_values": invalid, "omitted_categories": omitted,
        "warnings": list(dict.fromkeys(warnings)),
    }
    if chart_type == "scatter":
        result["x_values"] = [x_value for _, _, x_value in points]
    return result
