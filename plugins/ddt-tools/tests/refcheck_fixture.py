"""A tiny CenterTest project exercising every DataCombination header form."""
import json
import os



def make_xlsx(path, sheets):
    """sheets: {sheet name: rows}; an empty-string cell is left empty. Needs openpyxl."""
    from openpyxl import Workbook
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r, row in enumerate(rows, start=1):
            for c, value in enumerate(row, start=1):
                if value != "":
                    ws.cell(row=r, column=c, value=value)
    wb.save(path)

HIERARCHY = {
    "$references": {"testdata/SharedData.xlsx": ["testdata/.*DC\\.xlsx", "testdata/wc/.*DC\\.xlsx"]},
    "$identifiers": {"WC": ["testdata/wc/.*"]},
    "$relationships": {"Submission": {"WC": "testdata/wc/WC_SubmissionDC.xlsx"}},
}

POLICY_CHANGE_HEADERS = ["Code", "@Submission", "@Submission.#Coverage",
                         "@Submission.#Policy.EffectiveDate", "#Company.Name",
                         "#Company<>#Address", "#Company"]


def build_project(root):
    """Write the project under root. Three findings are expected, all in WC_PolicyChangeDC.xlsx:
    row 3 hop code 'Terrorism', row 4 relationship code 'Missing', row 4 #Company 'Nope'."""
    os.makedirs(os.path.join(root, "testdata", "wc"))
    with open(os.path.join(root, "testdata", "DataDrivenHierarchy.json"), "w") as fh:
        json.dump(HIERARCHY, fh)
    make_xlsx(os.path.join(root, "testdata", "SharedData.xlsx"), {
        "Company": [["Code", "Name"], ["Acme", "Acme Inc"]],
        "Address": [["Code", "City"], ["CA-LA", "Los Angeles"]],
    })
    # Coverage exists only in the submission DC's own scope: a policy change reaches it
    # through the @Submission hop, never through its own references.
    make_xlsx(os.path.join(root, "testdata", "wc", "WC_SubmissionDC.xlsx"), {
        "DataCombination": [["Code", "#Company", "#Address"], ["Default", "Acme", "CA-LA"]],
        "Coverage": [["Code", "Limit"], ["Liability", "1000000"]],
    })
    make_xlsx(os.path.join(root, "testdata", "wc", "WC_PolicyChangeDC.xlsx"), {
        "DataCombination": [
            POLICY_CHANGE_HEADERS,
            ["Ok", "Default", "Liability", "P-2M", "Renamed Inc", "Acme:CA-LA", "<blank>"],
            ["BadHop", "Default", "Terrorism", "", "", "", "Acme"],
            ["BadRel", "Missing", "", "", "", "", "Nope"],
        ],
    })
