"""Candidates for the wizard's data-driven step: which workbook column each recorded value belongs to
and which existing rows already hold those values. The engine only proposes; the wizard asks."""
import datetime
import os
import re
import sys
import zipfile
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import xlsx_read  # noqa: E402

REDACTED = "[redacted]"
STOPWORDS = {"the", "of", "a"}
GENERIC = {"name", "code", "type", "date", "number"}
MAX_ROWS = 3
WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
US_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
SERIAL = re.compile(r"^\d+(\.\d+)?$")
EXCEL_EPOCH = datetime.date(1899, 12, 30)
READ_ERRORS = (xlsx_read.WorkbookError, zipfile.BadZipFile, zlib.error, NotImplementedError, OSError, ValueError)


def tokens(text: str) -> set:
    """Lower-case words of a label or header: camel case split, '#', '@', '.' and other separators dropped."""
    return {w.lower() for w in WORD.findall(text or "")} - STOPWORDS


def _best_column(label_tokens: set, label_is_single: bool, columns: list):
    """(overlap, column) of the header sharing the most tokens with the label; ties keep the first."""
    best = None
    for column in columns:
        head = tokens(column)
        if not head or not label_tokens or not (label_tokens <= head or head <= label_tokens):
            continue
        shared = label_tokens & head
        if len(shared) == 1 and shared <= GENERIC and not (label_is_single and label_tokens == shared):
            continue
        if best is None or len(shared) > best[0]:
            best = (len(shared), column)
    return best


def dc_columns(plan: dict, workbooks: list) -> list:
    """For every recorded (non-redacted) value, the best column per workbook whose header tokens contain
    the label's tokens or the reverse."""
    found = []
    for step in plan.get("steps") or []:
        for action in step.get("actions") or []:
            value = action.get("value")
            if action.get("type") != "change" or not isinstance(value, str) or value == REDACTED or not value:
                continue
            label = action.get("label") or ""
            label_tokens = tokens(label)
            for book in workbooks:
                best = None
                for sheet, info in (book.get("sheets") or {}).items():
                    pick = _best_column(label_tokens, len(label_tokens) == 1, info.get("columns") or [])
                    if pick and (best is None or pick[0] > best[0]):
                        best = (pick[0], sheet, pick[1])
                if best:
                    found.append({"seq": step.get("seq"), "label": label, "value": value,
                                  "workbook": book["path"], "sheet": best[1], "column": best[2],
                                  "why": "label '%s' shares %d token(s) with header '%s'" % (label, best[0], best[2])})
    return found


def _date(text: str):
    """A date from MM/DD/YYYY or YYYY-MM-DD, else None."""
    for pattern, order in ((US_DATE, (3, 1, 2)), (ISO_DATE, (1, 2, 3))):
        m = pattern.match(text)
        if m:
            try:
                return datetime.date(*(int(m.group(i)) for i in order))
            except ValueError:
                return None
    return None


def _number(text: str):
    """The digits of a number written with thousands separators, a leading currency sign or a trailing '.0'."""
    cleaned = re.sub(r"^\$", "", text.replace(",", ""))
    cleaned = re.sub(r"\.0+$", "", cleaned)
    return cleaned if re.fullmatch(r"-?\d+(\.\d+)?", cleaned) else None


def same_value(recorded: str, cell: str) -> bool:
    """Trimmed case-folded equality, the same date in either format or as an Excel serial, the same number."""
    a, b = recorded.strip(), cell.strip()
    if a.casefold() == b.casefold():
        return True
    day = _date(a)
    if day is not None:
        other = _date(b)
        if other is not None:
            return day == other
        if SERIAL.match(b):
            return EXCEL_EPOCH + datetime.timedelta(days=int(float(b))) == day
        return False
    na, nb = _number(a), _number(b)
    return na is not None and na == nb


def data_row_candidates(columns: list, root: str, read=xlsx_read.read_workbook) -> list:
    """Per workbook, up to three rows with the most recorded values matching: {workbook, sheet, code, matched, total}."""
    cache = {}

    def sheets_of(path):
        if path not in cache:
            try:
                cache[path] = read(os.path.join(root, path))
            except READ_ERRORS:
                cache[path] = {}
        return cache[path]

    groups = {}
    for column in columns:
        groups.setdefault((column["workbook"], column["sheet"]), []).append(column)
    ranked = {}
    for (path, sheet), group in groups.items():
        for row in sheets_of(path).get(sheet) or []:
            matched = sum(1 for c in group if c["column"] in row and same_value(c["value"], row[c["column"]]))
            if matched:
                ranked.setdefault(path, []).append(
                    {"workbook": path, "sheet": sheet, "code": row.get("Code"), "matched": matched, "total": len(group)})
    result = []
    for path in ranked:
        result += sorted(ranked[path], key=lambda r: -r["matched"])[:MAX_ROWS]
    return result
