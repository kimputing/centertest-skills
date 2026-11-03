import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)
import ct  # noqa: E402
import parse_recording as pr  # noqa: E402
import scrub_recording as sr  # noqa: E402

CSSIDS = os.path.join(HERE, "fixtures", "cssids")
EFFECTIVE = "PolicyChangeWizard-StartPolicyChange-PolicyChangeDV-EffectiveDate"
CONVICTED = "NewVehicleDV-DateConvicted"
HOST = "gw.example.test"


def change(widget, value, **extra):
    return dict({"type": "change", "widgetId": widget, "kind": "text", "label": "Name", "value": value}, **extra)


def session():
    return {
        "id": "2026-10-06_100000", "name": "Renewal", "startedAt": "2026-10-21T12:19:10.5+02:00",
        "endedAt": "2026-10-21T12:25:00.1+02:00", "startUrl": "https://client.acme-corp.com:8443/pc/PolicyCenter.do",
        "toolVersion": "1.4.0", "video": "video.webm", "audio": [{"f": "audio/0001.webm"}],
        "notes": [{"text": "top note for Jane Doe"}],
        "meta": {"version": 1, "testId": "T-1", "recorderName": "Pat Recorder",
                 "description": "renewal of Jane Doe", "expectedOutcome": "Jane Doe is seen"},
        "steps": [
            {"seq": 1, "time": "2026-10-21T12:19:11.000000000+02:00", "kind": "start", "app": "PolicyCenter",
             "url": "https://client.acme-corp.com:8443/pc/PolicyCenter.do?x=1", "title": "Login",
             "screenshot": "shots/1.png", "before": "shots/1b.png", "full": "shots/1f.png", "dom": "dom/1.html",
             "net": "net/1.json", "marks": [{"x": 1}], "beforeMarks": [{"x": 2}], "actions": []},
            {"seq": 2, "time": "2026-10-21T12:20:00.000000000+02:00", "app": "PolicyCenter", "title": "Account Jane Doe",
             "url": "https://other.client.net/pc/x", "messages": [{"text": "Saved Jane Doe", "level": "info"}, "plain"],
             "notes": [{"text": "type Jane Doe here"}],
             "actions": [change("A-Name", "Jane Doe"), change("A-Again", "Jane Doe"), change("A-Other", "Acme"),
                         change("A-Secret", "[redacted]"), change("A-Num", "1250"), change("A-Dec", "1,250.50"),
                         change(EFFECTIVE, "10/01/2026", kind="date"),
                         {"type": "click", "widgetId": "Row-Select", "text": "Select",
                          "rowKey": [{"header": "Name", "text": "Jane Doe"}]}],
             "requests": [{"method": "POST", "url": "https://client.acme-corp.com:8443/pc/post",
                           "fields": [{"name": "A-Name", "value": "Jane Doe"}, {"name": CONVICTED, "value": "10/02/2026"},
                                      {"name": "A-Cnt", "value": "3"}]}]},
            {"seq": 3, "time": "2026-10-21T12:21:00.000000000+02:00", "app": "PolicyCenter", "title": "Drivers",
             "notes": [{"text": "nothing sensitive"}],
             "actions": [{"type": "click", "widgetId": CONVICTED, "kind": "date", "label": "Date Convicted"}],
             "requests": [{"fields": [{"name": CONVICTED, "value": "10/02/2026"},
                                      {"name": "NewVehicleDV-MVRDate", "value": "2026-09-20"}]}]},
        ],
    }


def walk_strings(node):
    if isinstance(node, dict):
        for value in node.values():
            yield from walk_strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk_strings(value)
    elif isinstance(node, str):
        yield node


class ScrubTest(unittest.TestCase):
    def setUp(self):
        self.original = session()
        self.out, self.report = sr.scrub(copy.deepcopy(self.original))

    def test_hosts_replaced(self):
        text = json.dumps(self.out)
        for host in ("acme-corp.com", "other.client.net", "8443"):
            self.assertNotIn(host, text)
        self.assertEqual(self.out["startUrl"], f"https://{HOST}/pc/PolicyCenter.do")
        self.assertEqual(self.out["steps"][0]["url"], f"https://{HOST}/pc/PolicyCenter.do?x=1")
        self.assertEqual(self.out["steps"][1]["requests"][0]["url"], f"https://{HOST}/pc/post")
        self.assertEqual(self.report["hosts"], ["client.acme-corp.com:8443", "other.client.net"])

    def test_same_value_same_placeholder(self):
        actions = self.out["steps"][1]["actions"]
        first, again, other = actions[0]["value"], actions[1]["value"], actions[2]["value"]
        self.assertRegex(first, r"^V\d+$")
        self.assertEqual(first, again)
        self.assertNotEqual(first, other)
        self.assertEqual(actions[7]["rowKey"][0]["text"], first)
        self.assertEqual(self.out["steps"][1]["requests"][0]["fields"][0]["value"], first)
        self.assertEqual(self.out["meta"]["description"], f"renewal of {first}")
        self.assertEqual(self.out["steps"][1]["title"], f"Account {first}")
        self.assertNotIn("Jane Doe", json.dumps(self.out))
        self.assertEqual(self.out["meta"]["recorderName"], "Recorder")

    def test_value_inside_note_replaced_and_reported(self):
        first = self.out["steps"][1]["actions"][0]["value"]
        self.assertEqual(self.out["steps"][1]["notes"][0]["text"], f"type {first} here")
        self.assertEqual(self.out["steps"][1]["messages"][0]["text"], f"Saved {first}")
        self.assertEqual(self.out["notes"][0]["text"], f"top note for {first}")
        self.assertEqual(self.report["notesChanged"], [0, 2])
        self.assertEqual(self.out["steps"][2]["notes"][0]["text"], "nothing sensitive")

    def test_redacted_and_numbers_kept(self):
        actions = self.out["steps"][1]["actions"]
        self.assertEqual([a["value"] for a in actions[3:6]], ["[redacted]", "1250", "1,250.50"])
        self.assertEqual(self.out["steps"][1]["requests"][0]["fields"][2]["value"], "3")
        self.assertEqual(self.report["values"], 2)

    def test_dates_shifted_and_relations_kept(self):
        self.assertEqual(self.out["steps"][1]["actions"][6]["value"], "01/09/2027")
        fields = self.out["steps"][2]["requests"][0]["fields"]
        self.assertEqual([f["value"] for f in fields], ["01/10/2027", "2026-12-29"])
        self.assertEqual(fields[0]["name"], CONVICTED)
        self.assertEqual(self.out["startedAt"], "2027-01-29T12:19:10.5+02:00")
        self.assertEqual(self.out["steps"][0]["time"], "2027-01-29T12:19:11.000000000+02:00")
        self.assertEqual(self.report["datesShifted"], 10)
        self.assertEqual(self.relations(self.original), self.relations(self.out))
        self.assertTrue(self.relations(self.out))

    def relations(self, data):
        plan = pr.build_plan(copy.deepcopy(data), CSSIDS)
        return [r["text"] for s in plan["steps"] for a in s.get("actions", []) for r in a.get("dateRelations", [])]

    def test_day_shift_argument(self):
        out, _ = sr.scrub(copy.deepcopy(self.original), day_shift=1)
        self.assertEqual(out["steps"][1]["actions"][6]["value"], "10/02/2026")

    def test_media_references_removed(self):
        self.assertNotIn("video", self.out)
        self.assertNotIn("audio", self.out)
        for step in self.out["steps"]:
            for key in ("screenshot", "before", "full", "dom", "net", "marks", "beforeMarks"):
                self.assertNotIn(key, step)
        self.assertEqual(self.out["steps"][0]["seq"], 1)

    def test_scrubbed_plan_still_builds(self):
        plan = pr.build_plan(copy.deepcopy(self.out), CSSIDS)
        before = pr.build_plan(copy.deepcopy(self.original), CSSIDS)
        self.assertEqual([s["seq"] for s in plan["steps"]], [s["seq"] for s in before["steps"]])
        self.assertEqual([len(s["actions"]) for s in plan["steps"]], [len(s["actions"]) for s in before["steps"]])

    def test_original_untouched(self):
        source = session()
        sr.scrub(source)
        self.assertEqual(source, session())

    def test_no_string_keeps_a_client_value(self):
        for text in walk_strings(self.out):
            self.assertNotIn("Acme", text.replace("acme", ""))


class ScrubLeakTest(unittest.TestCase):
    def base(self):
        data = session()
        data["meta"].update({"testId": "tc123", "featureIds": ["AD-123"], "defectIds": ["JIRA-321"],
                             "description": "see AD-123 for 7879422213"})
        data["steps"][2]["title"] = "Account Summary: Pat Example"
        data["steps"][2]["url"] = "https://h.test/acct/7879422213"
        data["steps"][2]["actions"].append({"type": "check", "widgetId": "Acct-Number", "seen": "7879422213"})
        data["steps"][2]["actions"].append({"type": "check", "widgetId": "Acct-Amount", "seen": "1250000"})
        return data

    def test_also_replaces_displayed_name(self):
        out, _ = sr.scrub(self.base(), also=["Pat Example"])
        self.assertEqual(out["steps"][2]["title"], "Account Summary: V1")
        self.assertNotIn("Pat Example", json.dumps(out))

    def test_long_numbers_become_n_placeholders_everywhere(self):
        out, report = sr.scrub(self.base())
        step = out["steps"][2]
        self.assertEqual(step["actions"][1]["seen"], "N1")
        self.assertTrue(step["url"].endswith("/acct/N1"))
        self.assertIn("for N1", out["meta"]["description"])
        self.assertNotIn("7879422213", json.dumps(out))
        self.assertEqual(step["actions"][2]["seen"], "1250000")
        self.assertEqual(report["needsReview"]["numbers"], ["1250000"])

    def test_issue_keys_and_meta_ids_neutral(self):
        out, _ = sr.scrub(self.base())
        self.assertEqual(out["meta"]["testId"], "T1")
        self.assertEqual(out["meta"]["featureIds"], ["F1"])
        self.assertEqual(out["meta"]["defectIds"], ["D1"])
        self.assertEqual(out["meta"]["description"], "see F1 for N1")
        self.assertEqual((out["id"], out["name"]), ("rec-1", "recording"))
        data = self.base()
        data["steps"][2]["notes"] = [{"text": "see PROJ-42"}]
        self.assertEqual(sr.scrub(data)[0]["steps"][2]["notes"][0]["text"], "see KEY-1")

    def test_needs_review_lists_surviving_title(self):
        _, report = sr.scrub(self.base())
        self.assertIn("Account Summary: Pat Example", report["needsReview"]["titles"])
        self.assertNotIn("Account Jane Doe", report["needsReview"]["titles"])

    def test_short_value_leaves_ids_and_other_labels_alone(self):
        data = {"id": "x", "name": "n", "steps": [{"seq": 1, "title": "A", "actions": [
            {"type": "change", "widgetId": "A-Panel-A", "label": "Panel", "kind": "text", "value": "A"}]}]}
        out, report = sr.scrub(data)
        action = out["steps"][0]["actions"][0]
        self.assertEqual((action["widgetId"], action["label"]), ("A-Panel-A", "Panel"))
        self.assertEqual((action["value"], out["steps"][0]["title"]), ("V1", "V1"))
        self.assertEqual(report["needsReview"]["leftovers"], ["A"])

    def test_real_recording_lists_displayed_row_text(self):
        data = pr.load_session(os.path.join(HERE, "fixtures", "recordings", "real-174907"))
        business = next(k["text"] for s in data["steps"] for a in s.get("actions") or []
                        for k in a.get("rowKey") or [] if k.get("header") == "Organization Name")
        display = next(a["display"] for s in data["steps"] for a in s.get("actions") or [] if a.get("display"))
        _, report = sr.scrub(data)
        self.assertIn(business, report["needsReview"]["rowKeys"])
        self.assertIn(display, report["needsReview"]["displayed"])

    def test_real_recording_scrubbed_with_also_has_no_name(self):
        data = pr.load_session(os.path.join(HERE, "fixtures", "recordings", "real-180418"))
        title = next(s["title"] for s in data["steps"] if ": " in (s.get("title") or ""))
        name = title.split(": ", 1)[1]
        out, report = sr.scrub(data, also=[name])
        self.assertNotIn(name, json.dumps(out))
        self.assertNotIn("7879422213", json.dumps(out))
        self.assertEqual(out["meta"]["featureIds"], ["F1"])


class ScrubEveryKeyTest(unittest.TestCase):
    NAME = "Jane Roe"

    def data(self):
        return {"id": "r", "name": "n", "startedAt": "2026-10-21T12:19:10.123456789+02:00",
                "meta": {"version": 1, "tags": [f"customer {self.NAME}"],
                         "links": ["https://tracker.client.net/browse/PROJ-77", "see PROJ-78"]},
                "steps": [{"seq": 1, "time": "2026-10-21T12:19:11.000000000+02:00", "title": "Summary",
                           "screen": "AccountFile_Summary", "app": "PolicyCenter", "actions": [
                               {"type": "click", "widgetId": "Acct-Name", "kind": "text",
                                "label": f"Contact {self.NAME}", "context": [f"Details of {self.NAME}", "Policy"]},
                               {"type": "dialog", "kind": "dialog", "label": f"Delete {self.NAME}?"},
                               {"type": "check", "widgetId": "Acct-Status", "kind": "text", "display": "Active",
                                "rowKey": [{"header": "Status", "text": "Bound"}],
                                "context": ["Policy"]},
                               {"type": "dialog", "kind": "dialog", "label": "Are you sure?"}]}]}

    def test_also_name_replaced_in_label_context_dialog_and_tags(self):
        out, _ = sr.scrub(self.data(), also=[self.NAME])
        first, dialog = out["steps"][0]["actions"][0], out["steps"][0]["actions"][1]
        self.assertEqual(first["label"], "Contact V1")
        self.assertEqual(first["context"], ["Details of V1", "Policy"])
        self.assertEqual(dialog["label"], "Delete V1?")
        self.assertEqual(out["meta"]["tags"], ["customer V1"])
        self.assertNotIn(self.NAME, json.dumps(out))

    def test_issue_keys_and_hosts_in_links_replaced(self):
        out, _ = sr.scrub(self.data())
        self.assertEqual(out["meta"]["links"], [f"https://{HOST}/browse/KEY-1", "see KEY-2"])

    def test_structure_and_times_kept(self):
        out, _ = sr.scrub(self.data(), also=["Summary", "Acct"])
        step = out["steps"][0]
        self.assertEqual((step["screen"], step["actions"][0]["widgetId"]), ("AccountFile_Summary", "Acct-Name"))
        self.assertEqual(step["time"], "2027-01-29T12:19:11.000000000+02:00")
        self.assertEqual(out["startedAt"], "2027-01-29T12:19:10.123456789+02:00")

    def test_needs_review_lists_displayed_row_context_and_dialog_text(self):
        _, report = sr.scrub(self.data(), also=[self.NAME])
        review = report["needsReview"]
        self.assertEqual(review["displayed"], ["Active"])
        self.assertEqual(review["rowKeys"], ["Bound"])
        self.assertEqual(review["context"], ["Policy"])
        self.assertEqual(review["dialogs"], ["Are you sure?"])

    def test_leftovers_found_in_structural_keys_and_other_case(self):
        data = self.data()
        data["steps"][0]["screen"] = "JaneRoe_Screen"
        data["steps"][0]["title"] = self.NAME.upper()
        _, report = sr.scrub(data, also=[self.NAME, "JaneRoe"])
        self.assertEqual(report["needsReview"]["leftovers"], [self.NAME, "JaneRoe"])

    def test_leftovers_find_original_host_outside_urls(self):
        data = self.data()
        data["steps"][0]["actions"][0]["text"] = "server tracker.client.net is down"
        _, report = sr.scrub(data)
        self.assertEqual(report["needsReview"]["leftovers"], ["tracker.client.net"])

    def test_no_leftovers_when_everything_replaced(self):
        _, report = sr.scrub(self.data(), also=[self.NAME])
        self.assertEqual(report["needsReview"]["leftovers"], [])


class ScrubCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = os.path.join(self.tmp.name, "rec")
        os.makedirs(self.src)
        with open(os.path.join(self.src, "session.json"), "w", encoding="utf-8") as f:
            json.dump(session(), f)
        self.out = os.path.join(self.tmp.name, "out")

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ct.main(["scrub", *args])
        return code, out.getvalue(), err.getvalue()

    def test_writes_only_session_json_and_prints_report(self):
        code, out, _ = self.run_cli(self.src, "--out", self.out, "--day-shift", "1")
        self.assertEqual(code, 0)
        self.assertEqual(os.listdir(self.out), ["session.json"])
        self.assertEqual(json.loads(out)["values"], 2)
        with open(os.path.join(self.out, "session.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["steps"][1]["actions"][6]["value"], "10/02/2026")

    def test_warns_on_stderr_when_review_needed(self):
        code, out, err = self.run_cli(self.src, "--out", self.out, "--also", "Acme")
        self.assertEqual(code, 0)
        self.assertIn("Warning", err)
        self.assertTrue(json.loads(out)["needsReview"]["titles"])

    def test_leftovers_always_warn(self):
        data = session()
        data["steps"][1]["screen"] = "Jane Doe_Screen"
        with open(os.path.join(self.src, "session.json"), "w", encoding="utf-8") as f:
            json.dump(data, f)
        code, out, err = self.run_cli(self.src, "--out", self.out)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["needsReview"]["leftovers"], ["Jane Doe"])
        self.assertIn("leftovers", err)

    def test_writes_ascii_json(self):
        data = session()
        data["steps"][2]["title"] = "Fahrer übersicht ≈"
        with open(os.path.join(self.src, "session.json"), "w", encoding="utf-8") as f:
            json.dump(data, f)
        self.assertEqual(self.run_cli(self.src, "--out", self.out)[0], 0)
        with open(os.path.join(self.out, "session.json"), "rb") as f:
            raw = f.read()
        self.assertTrue(raw.isascii())
        self.assertEqual(json.loads(raw.decode("ascii"))["steps"][2]["title"], "Fahrer übersicht ≈")

    def test_refuses_to_overwrite(self):
        self.assertEqual(self.run_cli(self.src, "--out", self.out)[0], 0)
        code, out, err = self.run_cli(self.src, "--out", self.out)
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("already exists", err)

    def test_unreadable_recording_exits_2(self):
        code, _, err = self.run_cli(os.path.join(self.tmp.name, "missing"), "--out", self.out)
        self.assertEqual(code, 2)
        self.assertIn("Error", err)


class ScrubNarrationTest(unittest.TestCase):
    """Scrubbed copies keep narration: transcripts are written scrubbed, audio files never copied."""
    NARRATED = os.path.join(HERE, "fixtures", "recordings", "narrated")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = os.path.join(self.tmp.name, "out")
        with open(os.path.join(self.NARRATED, "audio", "0001.transcript.json"), encoding="utf-8") as f:
            self.segments = json.load(f)["segments"]
        self.word = self.segments[-1]["text"].split()[2]

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ct.main(["scrub", *args])
        return code, json.loads(out.getvalue()) if out.getvalue() else None

    def narrate(self, folder):
        return pr.narrate(pr.load_session(folder), pr.file_bytes(folder), {})

    def test_scrubbed_copy_keeps_transcript_narration_without_audio(self):
        code, report = self.run_cli(self.NARRATED, "--out", self.out)
        self.assertEqual(code, 0)
        self.assertEqual(sorted(os.listdir(os.path.join(self.out, "audio"))), ["0001.transcript.json"])
        narration = self.narrate(self.out)
        self.assertEqual(narration["source"], "transcript")
        self.assertEqual([u["text"] for u in narration["utterances"]],
                         [u["text"] for u in self.narrate(self.NARRATED)["utterances"]])
        self.assertEqual(report["narration"], {"transcripts": ["audio/0001.transcript.json"], "dropped": []})

    def test_utterances_are_scrubbed(self):
        code, report = self.run_cli(self.NARRATED, "--out", self.out, "--also", self.word)
        self.assertEqual(code, 0)
        texts = [u["text"] for u in self.narrate(self.out)["utterances"]]
        self.assertTrue(any("V1" in t for t in texts), texts)
        self.assertFalse(any(self.word in t for t in texts), texts)
        self.assertEqual(report["needsReview"]["leftovers"], [])

    def test_leftovers_searched_in_transcripts(self):
        _, out_transcripts, report = sr.scrub_all(
            pr.load_session(self.NARRATED), {"audio/0001.webm": self.segments}, also=[self.word.upper()])
        self.assertEqual(report["needsReview"]["leftovers"], [self.word.upper()])
        self.assertEqual(len(out_transcripts["audio/0001.webm"]), len(self.segments))

    def test_audio_without_transcript_dropped_and_reported(self):
        src = os.path.join(self.tmp.name, "rec")
        os.makedirs(src)
        data = pr.load_session(self.NARRATED)
        data["audio"].append({"f": "audio/0002.webm", "t": 9000})
        with open(os.path.join(src, "session.json"), "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.makedirs(os.path.join(src, "audio"))
        with open(os.path.join(src, "audio", "0001.transcript.json"), "w", encoding="utf-8") as f:
            json.dump({"segments": self.segments}, f)
        code, report = self.run_cli(src, "--out", self.out)
        self.assertEqual(code, 0)
        self.assertEqual(report["narration"]["dropped"], ["audio/0002.webm"])
        self.assertEqual(pr.load_session(self.out)["audio"], [{"f": "audio/0001.webm", "t": 4000}])

    def test_transcript_path_outside_out_is_not_written(self):
        src = os.path.join(self.tmp.name, "rec")
        os.makedirs(os.path.join(src, "audio"))
        data = pr.load_session(self.NARRATED)
        data["audio"] = [{"f": "../escape.webm", "t": 0}]
        with open(os.path.join(src, "session.json"), "w", encoding="utf-8") as f:
            json.dump(data, f)
        code, report = self.run_cli(src, "--out", self.out)
        self.assertEqual(code, 0)
        self.assertEqual(report["narration"]["dropped"], ["../escape.webm"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "escape.transcript.json")))


if __name__ == "__main__":
    unittest.main()
