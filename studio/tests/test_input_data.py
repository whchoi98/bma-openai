"""Behavior tests for bounded, local document inputs and authoritative charts."""
import io
import json
import unittest
import zipfile
from datetime import date
from unittest.mock import patch

from openpyxl import Workbook

try:
    from studio.document_tools import input_data
except ImportError:
    input_data = None


def workbook_bytes(rows=None, sheets=1):
    book = Workbook()
    book.active.title = "매출"
    for row in rows or [["지역", "매출"], ["서울", 12], ["부산", 3]]:
        book.active.append(row)
    for number in range(1, sheets):
        book.create_sheet(f"Sheet {number + 1}").append(["Header"])
    output = io.BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def rewrite_zip(data, additions=None, replacements=None):
    target = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as original:
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as rewritten:
            for item in original.infolist():
                body = original.read(item)
                if replacements and item.filename in replacements:
                    body = replacements[item.filename](body)
                rewritten.writestr(item.filename, body)
            for name, body in (additions or {}).items():
                rewritten.writestr(name, body)
    return target.getvalue()


def renamed_worksheet(data, transform=lambda body: body):
    """A valid OOXML part may use a nonstandard filename suffix."""
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as original, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as modified:
        for item in original.infolist():
            body = original.read(item)
            name = item.filename
            if name == "xl/worksheets/sheet1.xml":
                name = "xl/worksheets/sheet1.payload"
                body = transform(body)
            elif name in {"[Content_Types].xml", "xl/_rels/workbook.xml.rels"}:
                body = body.replace(b"sheet1.xml", b"sheet1.payload")
            modified.writestr(name, body)
    return output.getvalue()


class InputDataTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(input_data, "The bounded input parser must exist")

    def csv(self, text):
        return input_data.inspect_source(text.encode(), "data.csv")

    def test_notes_and_markdown_are_preserved_as_untrusted_text(self):
        result = input_data.inspect_source(None, None, "메모 <script>x</script>")
        self.assertEqual(result["notes"], "메모 <script>x</script>")
        self.assertEqual(result["sheets"], [])
        result = input_data.inspect_source(b"# title\nhello", "memo.md", "notes")
        self.assertEqual(result["kind"], "md")
        self.assertEqual(result["text"], "# title\nhello")

    def test_csv_bom_headers_numbers_and_missing_values(self):
        source = input_data.inspect_source("\ufeff지역,매출,매출,\n서울,12,,x\n부산,3.5,0,\n".encode(), "매출.csv")
        table = source["sheets"][0]
        self.assertEqual(table["id"], "sheet_0")
        self.assertEqual([col["id"] for col in table["columns"]], ["c0", "c1", "c2", "c3"])
        self.assertEqual(table["rows"], [["서울", 12, None, "x"], ["부산", 3.5, 0, None]])
        self.assertEqual(table["columns"][1]["type"], "number")
        json.dumps(source, allow_nan=False)

    def test_korean_cp949_csv_and_semicolon_dialect(self):
        source = input_data.inspect_source("지역;금액\n서울;12\n부산;3\n".encode("cp949"), "korean.csv")
        self.assertEqual(source["sheets"][0]["rows"], [["서울", 12], ["부산", 3]])
        self.assertTrue(any("cp949" in str(item).lower() for item in source["warnings"]))

    def test_csv_preserves_leading_zero_identifiers(self):
        self.assertEqual(self.csv("code,n\n001,2\n")["sheets"][0]["rows"][0], ["001", 2])

    def test_xlsx_preserves_types_and_actual_dimensions(self):
        raw = workbook_bytes([["Date", "N", "Enabled", "Blank"], [date(2025, 1, 2), 2.5, True, None]])
        # A lying dimension must not silently hide numeric source rows.
        raw = rewrite_zip(raw, replacements={"xl/worksheets/sheet1.xml": lambda body: body.replace(b'A1:D2', b'A1:A1')})
        table = input_data.inspect_source(raw, "sales.xlsx")["sheets"][0]
        self.assertEqual(table["rows"], [["2025-01-02T00:00:00", 2.5, True, None]])
        self.assertEqual(table["columns"][0]["type"], "date")

    def test_formula_only_uses_saved_cache_and_reports_missing(self):
        raw = workbook_bytes([["Region", "N"], ["A", "=1+2"], ["B", "=4+5"]])
        raw = rewrite_zip(raw, replacements={"xl/worksheets/sheet1.xml": lambda body: body.replace(b'<f>1+2</f><v></v>', b'<f>1+2</f><v>3</v>')})
        source = input_data.inspect_source(raw, "formula.xlsx")
        self.assertEqual(source["sheets"][0]["rows"], [["A", 3], ["B", None]])
        self.assertTrue(any("cache" in str(item).lower() for item in source["warnings"]))
        chart = input_data.aggregate_chart(source, "sheet_0", "c0", "c1")
        self.assertEqual(chart["values"], [3, None])
        self.assertEqual(chart["missing_values"], 1)

    def test_profiles_expose_only_eight_rows_and_bounded_text(self):
        source = self.csv("name,n\n" + "A,1\n" * 12)
        profile = input_data.source_profile(source)
        self.assertEqual(profile["sheets"][0]["row_count"], 12)
        self.assertEqual(len(profile["sheets"][0]["rows"]), 8)
        text_profile = input_data.source_profile(input_data.inspect_source(None, None, "x" * 20000))
        self.assertLess(len(text_profile["notes"]), 20000)

    def test_file_notes_combined_text_and_upload_limits(self):
        for data, name, notes in [(b"x" * (5 * 1024 * 1024 + 1), "a.txt", ""), (None, None, "x" * 50001), (b"x" * 30000, "a.txt", "x" * 30000)]:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    input_data.inspect_source(data, name, notes)

    def test_unsupported_and_encrypted_workbooks_are_rejected(self):
        for name, data in [("old.xls", b"not excel"), ("macro.xlsm", workbook_bytes()), ("bad.xlsx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1encrypted"), ("data.html", b"<html>")]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                input_data.inspect_source(data, name)

    def test_empty_invalid_and_nul_inputs_are_rejected(self):
        for data, name in [(b"", "empty.csv"), (b"PK nonsense", "broken.xlsx"), (b"x\x00y", "binary.txt"), (b"a,b\n\"unterminated", "bad.csv")]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                input_data.inspect_source(data, name)

    def test_csv_row_column_and_total_cell_limits(self):
        cases = ["h\n" + "v\n" * 10001, ",".join(["h"] * 51), ",".join(["h"] * 50) + "\n" + (",".join(["v"] * 50) + "\n") * 2001]
        for text in cases:
            with self.subTest(size=len(text)), self.assertRaises(ValueError):
                self.csv(text)

    def test_xlsx_sheet_and_sparse_dimension_limits(self):
        with self.assertRaises(ValueError):
            input_data.inspect_source(workbook_bytes(sheets=6), "many.xlsx")
        for target in [b"AY2", b"A10002"]:
            raw = rewrite_zip(workbook_bytes(), replacements={"xl/worksheets/sheet1.xml": lambda body, target=target: body.replace(b'r="A2"', b'r="' + target + b'"')})
            with self.subTest(target=target), self.assertRaises(ValueError):
                input_data.inspect_source(raw, "sparse.xlsx")

    def test_zip_unsafe_paths_macros_external_links_and_dtd_are_rejected(self):
        additions = [{"../outside.xml": b"x"}, {"/absolute.xml": b"x"}, {"xl\\evil.xml": b"x"}, {"xl/vbaProject.bin": b"macro"}, {"xl/externalLinks/externalLink1.xml": b"x"}, {"evil.xml": b'<!DOCTYPE a [<!ENTITY x "evil">]><a>&x;</a>'}, {"xl/unsafe.rels": b'<Relationships><Relationship TargetMode="External" Target="https://example.test"/></Relationships>'}]
        for addition in additions:
            with self.subTest(name=next(iter(addition))), self.assertRaises(ValueError):
                input_data.inspect_source(rewrite_zip(workbook_bytes(), additions=addition), "unsafe.xlsx")

    def test_nonstandard_worksheet_suffix_still_receives_xml_preflight(self):
        raw = renamed_worksheet(workbook_bytes())
        source = input_data.inspect_source(raw, "renamed.xlsx")
        self.assertEqual(source["sheets"][0]["rows"], [["서울", 12], ["부산", 3]])
        declaration = '<!DOCTYPE worksheet [<!ENTITY example "expanded">]>'
        for encoding in ("utf-8", "utf-16"):
            raw = renamed_worksheet(workbook_bytes(), lambda body: (declaration + body.decode()).encode(encoding))
            with self.subTest(encoding=encoding), patch.object(input_data, "load_workbook", side_effect=AssertionError("Preflight did not reject unsafe XML")), self.assertRaisesRegex(ValueError, "XML"):
                input_data.inspect_source(raw, "unsafe.xlsx")

    def test_nonstandard_xml_part_enforces_row_limits_before_workbook_load(self):
        raw = renamed_worksheet(workbook_bytes(), lambda body: body.replace(b'r="A2"', b'r="A10002"'))
        with self.assertRaisesRegex(ValueError, "ambiguous|limit"):
            input_data.inspect_source(raw, "oversized.xlsx")

    def test_zip_bomb_duplicate_members_and_member_count_are_rejected(self):
        cases = [{"xl/bomb.bin": b"0" * (12 * 1024 * 1024)}, {f"extra/{index}.bin": b"x" for index in range(260)}]
        for additions in cases:
            with self.assertRaises(ValueError):
                input_data.inspect_source(rewrite_zip(workbook_bytes(), additions=additions), "bomb.xlsx")
        raw = rewrite_zip(workbook_bytes(), additions={"XL/WORKBOOK.XML": b"invalid duplicate"})
        with self.assertRaises(ValueError):
            input_data.inspect_source(raw, "duplicate.xlsx")

    def test_sum_mean_and_counts_never_turn_missing_into_zero(self):
        source = self.csv("region,n\nA,2\nB,\nA,4\nC,oops\nD,0\n")
        result = input_data.aggregate_chart(source, "sheet_0", "c0", "c1")
        self.assertEqual(result["categories"], ["A", "B", "C", "D"])
        self.assertEqual(result["values"], [6, None, None, 0])
        self.assertEqual((result["missing_values"], result["invalid_values"]), (1, 1))
        self.assertEqual(input_data.aggregate_chart(source, "sheet_0", "c0", "c1", "mean")["values"], [3, None, None, 0])
        self.assertEqual(input_data.aggregate_chart(source, "sheet_0", "c0", aggregation="count")["values"], [2, 1, 1, 1])
        self.assertEqual(input_data.aggregate_chart(source, "sheet_0", "c0", "c1", "count")["values"], [2, 0, 1, 1])
        self.assertEqual(result["source"]["file"], "data.csv")
        self.assertEqual(result["source"]["sheet_id"], "sheet_0")
        self.assertEqual(result["source"]["y_column"]["id"], "c1")

    def test_none_keeps_repeated_categories_and_line_missing_gaps(self):
        source = self.csv("label,n\nA,3\nA,\nA,4\n")
        result = input_data.aggregate_chart(source, "sheet_0", "c0", "c1", "none", "line")
        self.assertEqual(result["categories"], ["A", "A", "A"])
        self.assertEqual(result["values"], [3, None, 4])

    def test_date_groups_are_chronological_and_invalid_dates_reported(self):
        source = self.csv("date,n\n2025-02-03,2\n2024-12-01,3\n2025-02-20,4\nnotdate,9\n")
        monthly = input_data.aggregate_chart(source, "sheet_0", "c0", "c1", group_by="month")
        self.assertEqual(monthly["categories"], ["2024-12", "2025-02"])
        self.assertEqual(monthly["values"], [3, 6])
        self.assertEqual(monthly["invalid_values"], 1)
        yearly = input_data.aggregate_chart(source, "sheet_0", "c0", "c1", group_by="year")
        self.assertEqual(yearly["categories"], ["2024", "2025"])
        self.assertEqual(yearly["values"], [3, 6])

    def test_numeric_group_keys_do_not_merge_booleans_or_text(self):
        source = input_data.inspect_source(workbook_bytes([["x", "y"], [1, 2], [1.0, 3], [True, 4], ["1", 5]]), "groups.xlsx")
        result = input_data.aggregate_chart(source, "sheet_0", "c0", "c1")
        self.assertEqual(result["values"], [5, 4, 5])

    def test_scatter_filters_invalid_pairs_and_has_real_x_values(self):
        source = self.csv("x,y\n1,3\n2,\nbad,4\n4,5\n")
        result = input_data.aggregate_chart(source, "sheet_0", "c0", "c1", "none", "scatter")
        self.assertEqual(result["x_values"], [1, 4])
        self.assertEqual(result["values"], [3, 5])
        self.assertEqual((result["missing_values"], result["invalid_values"]), (1, 1))
        with self.assertRaises(ValueError):
            input_data.aggregate_chart(source, "sheet_0", "c0", "c1", "sum", "scatter")

    def test_pie_rejects_negative_and_all_zero_data(self):
        for text in ["x,y\nA,-1\nB,2\n", "x,y\nA,0\nB,\n"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                input_data.aggregate_chart(self.csv(text), "sheet_0", "c0", "c1", chart_type="pie")

    def test_non_numeric_data_nonfinite_values_and_overflow_are_not_charted(self):
        for text in ["x,y\nA,NaN\nB,Infinity\n", "x,y\nA,1e309\n", "x,y\nA,1e308\nA,1e308\n"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                input_data.aggregate_chart(self.csv(text), "sheet_0", "c0", "c1")

    def test_category_cap_does_not_create_other_or_silently_drop_counts(self):
        source = self.csv("x,y\n" + "\n".join(f"c{index},{index + 1}" for index in range(55)))
        result = input_data.aggregate_chart(source, "sheet_0", "c0", "c1")
        self.assertEqual(len(result["categories"]), 50)
        self.assertEqual(result["omitted_categories"], 5)
        self.assertEqual(result["values"][-1], 50)
        self.assertTrue(result["warnings"])

    def test_profile_has_global_utf8_budget_and_retains_all_table_ids(self):
        workbook = Workbook()
        for number in range(5):
            sheet = workbook.active if number == 0 else workbook.create_sheet()
            sheet.title = f"시트{number}"
            sheet.append([f"제목{column}" + "긴이름" * 60 for column in range(50)])
            for row in range(8):
                sheet.append([f"행{row}열{column}:" + "한글내용" * 75 for column in range(50)])
        output = io.BytesIO()
        workbook.save(output)
        workbook.close()
        source = input_data.inspect_source(output.getvalue(), "wide.xlsx", "메모" * 10000)
        before = source["sheets"][0]["rows"][0][0]
        profile = input_data.source_profile(source)
        self.assertLessEqual(len(json.dumps(profile, ensure_ascii=False).encode()), 200000)
        self.assertEqual([sheet["id"] for sheet in profile["sheets"]], [f"sheet_{i}" for i in range(5)])
        self.assertTrue(profile["truncated"])
        for sheet in profile["sheets"]:
            self.assertEqual([column["id"] for column in sheet["columns"]], [f"c{i}" for i in range(50)])
            self.assertEqual(sheet["row_count"], 8)
            self.assertEqual(sheet["column_count"], 50)
            self.assertEqual(sheet["sample_row_count"], len(sheet["rows"]))
            self.assertTrue(sheet["sample_text_truncated"])
            self.assertTrue(sheet["columns"][0]["name_truncated"])
            self.assertGreater(sheet["columns"][0]["name_characters"], len(sheet["columns"][0]["name"]))
        self.assertEqual(source["sheets"][0]["rows"][0][0], before)

    def test_profile_budget_preserves_numeric_samples_or_reports_fewer_rows(self):
        source = self.csv("group,n\nA,1\nB,2\nC,3")
        profile = input_data.source_profile(source)
        self.assertEqual(profile["sheets"][0]["rows"], [["A", 1], ["B", 2], ["C", 3]])
        self.assertFalse(profile["truncated"])
        self.assertFalse(profile["text_truncated"])
        self.assertFalse(profile["notes_truncated"])

    def test_profile_bounds_long_header_names_without_changing_source(self):
        source = self.csv("x" * 10000 + ",n\nA,1")
        profile = input_data.source_profile(source)
        self.assertLessEqual(len(profile["sheets"][0]["columns"][0]["name"]), 300)
        self.assertEqual(len(source["sheets"][0]["columns"][0]["name"]), 10000)

    def test_profile_bounds_long_cell_excerpts(self):
        source = self.csv("name,value\nA," + "x" * 30000)
        profile = input_data.source_profile(source)
        self.assertLessEqual(len(profile["sheets"][0]["rows"][0][1]), 1000)
        self.assertEqual(len(source["sheets"][0]["rows"][0][1]), 30000)

    def test_xlsx_rejects_disordered_duplicate_and_mismatched_cells(self):
        for transform in [
            lambda body: body.replace(b'r="B2"', b'r="A2"'),
            lambda body: body.replace(b'r="B2"', b'r="B3"'),
            lambda body: body.replace(b'<row r="2">', b'<row r="0">'),
            lambda body: body.replace(b'<row r="3">', b'<row r="2">'),
        ]:
            raw = rewrite_zip(workbook_bytes(), replacements={"xl/worksheets/sheet1.xml": transform})
            with self.assertRaises(ValueError):
                input_data.inspect_source(raw, "ambiguous.xlsx")

    def test_no_numeric_values_within_category_limit_is_visible_error(self):
        source = self.csv("x,y\n" + "\n".join(f"c{i}," for i in range(50)) + "\nlast,9")
        with self.assertRaises(ValueError):
            input_data.aggregate_chart(source, "sheet_0", "c0", "c1")

    def test_date_mean_and_zero_are_preserved(self):
        source = self.csv("x,y\nA,1e308\nA,1e308\nB,0")
        result = input_data.aggregate_chart(source, "sheet_0", "c0", "c1", "mean")
        self.assertEqual(result["values"], [1e308, 0])
        json.dumps(result, allow_nan=False)

    def test_invalid_selections_and_unsupported_operations_rejected(self):
        source = self.csv("x,y\nA,1\n")
        cases = [("sheet_9", "c0", "c1", "sum", "bar", "value"), ("sheet_0", "__class__", "c1", "sum", "bar", "value"), ("sheet_0", "c0", None, "sum", "bar", "value"), ("sheet_0", "c0", "c1", "eval", "bar", "value"), ("sheet_0", "c0", "c1", "sum", "html", "value"), ("sheet_0", "c0", "c1", "sum", "bar", "quarter")]
        for arguments in cases:
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                input_data.aggregate_chart(source, *arguments)


if __name__ == "__main__":
    unittest.main()
