"""Test helper: write a minimal valid .xlsx (shared strings) with the standard library."""
import zipfile
from xml.sax.saxutils import escape

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def column_letter(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def make_xlsx(path: str, sheets: dict) -> None:
    """sheets: {sheet name: [[cell, ...], ...]}; an empty-string cell is written as no cell."""
    shared, index = [], {}

    def sid(text):
        if text not in index:
            index[text] = len(shared)
            shared.append(text)
        return index[text]

    sheet_xml = []
    for rows in sheets.values():
        body = []
        for r, row in enumerate(rows, 1):
            cells = "".join(f'<c r="{column_letter(c)}{r}" t="s"><v>{sid(v)}</v></c>'
                            for c, v in enumerate(row) if v != "")
            body.append(f'<row r="{r}">{cells}</row>')
        sheet_xml.append(f'<worksheet xmlns="{MAIN}"><sheetData>{"".join(body)}</sheetData></worksheet>')
    names = list(sheets)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets>' + "".join(
            f'<sheet name="{escape(n)}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(names, 1)) + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels", f'<Relationships xmlns="{PKG_REL}">' + "".join(
            f'<Relationship Id="rId{i}" Type="{REL}/worksheet" Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, len(names) + 1)) + "</Relationships>")
        for i, xml in enumerate(sheet_xml, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", xml)
        z.writestr("xl/sharedStrings.xml", f'<sst xmlns="{MAIN}">' + "".join(
            f"<si><t>{escape(s)}</t></si>" for s in shared) + "</sst>")
