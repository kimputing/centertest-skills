import contextlib
import io
import os
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
sys.path.insert(0, HERE)
import xlsx_read  # noqa: E402
from xlsx_fixture import make_xlsx  # noqa: E402

SHEETS = {
    "DC": [["Code", "#Person", "Note"], ["Default", "Adult", "x"], ["Other", "", "y"]],
    "Person": [["Code", "Age"], ["Adult", "40"]],
}


class XlsxReadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "book.xlsx")
        make_xlsx(self.path, SHEETS)

    def test_rows_keyed_by_header(self):
        rows = xlsx_read.read_workbook(self.path)["DC"]
        self.assertEqual(rows[0], {"Code": "Default", "#Person": "Adult", "Note": "x"})

    def test_blank_cells_omitted(self):
        self.assertEqual(xlsx_read.read_workbook(self.path)["DC"][1], {"Code": "Other", "Note": "y"})

    def test_sheet_filter(self):
        self.assertEqual(list(xlsx_read.read_workbook(self.path, sheet="^Pers")), ["Person"])
        self.assertEqual(xlsx_read.headers(self.path, sheet="^DC$"), {"DC": ["Code", "#Person", "Note"]})

    def test_max_rows_limits_data_rows(self):
        self.assertEqual(len(xlsx_read.read_workbook(self.path, max_rows=1)["DC"]), 1)

    def test_inline_and_shared_strings(self):
        path = os.path.join(self.tmp.name, "inline.xlsx")
        make_xlsx(path, {"S": [["Code"], ["shared"]]})
        with zipfile.ZipFile(path) as z:
            parts = {n: z.read(n) for n in z.namelist()}
        parts["xl/worksheets/sheet1.xml"] = parts["xl/worksheets/sheet1.xml"].replace(
            b"</sheetData>", b'<row r="3"><c r="A3" t="inlineStr"><is><t>inline</t></is></c></row></sheetData>')
        with zipfile.ZipFile(path, "w") as z:
            for n, data in parts.items():
                z.writestr(n, data)
        self.assertEqual(xlsx_read.read_workbook(path)["S"], [{"Code": "shared"}, {"Code": "inline"}])

    def without_sheet_name(self, name):
        """A copy of the workbook whose <sheet name="..."> attribute for `name` is dropped."""
        nameless = os.path.join(self.tmp.name, "nameless.xlsx")
        with zipfile.ZipFile(self.path) as src, zipfile.ZipFile(nameless, "w") as dst:
            for item in src.infolist():
                data = src.read(item)
                if item.filename == "xl/workbook.xml":
                    data = data.replace(f'name="{name}" '.encode(), b"")
                dst.writestr(item, data)
        return nameless

    def test_sheet_without_name_is_read_as_empty_name(self):
        result = xlsx_read.read_workbook(self.without_sheet_name("Person"))
        self.assertEqual((sorted(result), result[""]), (["", "DC"], [{"Code": "Adult", "Age": "40"}]))

    def test_sheet_without_name_skipped_by_a_sheet_filter(self):
        self.assertEqual(list(xlsx_read.headers(self.without_sheet_name("Person"), "^Person$")), [])

    def test_not_a_zip_raises_workbook_error(self):
        bad = os.path.join(self.tmp.name, "bad.xlsx")
        with open(bad, "w") as f:
            f.write("not a zip")
        with self.assertRaises(xlsx_read.WorkbookError):
            xlsx_read.read_workbook(bad)

    def test_missing_file_and_missing_part_raise_workbook_error(self):
        with self.assertRaises(xlsx_read.WorkbookError):
            xlsx_read.read_workbook(os.path.join(self.tmp.name, "nope.xlsx"))
        empty = os.path.join(self.tmp.name, "empty.xlsx")
        with zipfile.ZipFile(empty, "w") as z:
            z.writestr("readme.txt", "x")
        with self.assertRaises(xlsx_read.WorkbookError):
            xlsx_read.read_workbook(empty)

    def test_cli_prints_header_and_counts(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = xlsx_read.main([self.path, "--sheet", "^DC$"])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue().splitlines(), [
            "--- [DC]  data rows: 2",
            "   A=Code | B=#Person | C=Note",
            "   A=Default | B=Adult | C=x",
            "   A=Other | C=y"])

    def test_cli_error_on_bad_file(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = xlsx_read.main([os.path.join(self.tmp.name, "nope.xlsx")])
        self.assertEqual(code, 2)
        self.assertIn("Error:", err.getvalue())


if __name__ == "__main__":
    unittest.main()
