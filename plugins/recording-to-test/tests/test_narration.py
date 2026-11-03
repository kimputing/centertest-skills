import json
import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import narration  # noqa: E402
import parse_recording as pr  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RECORDINGS = os.path.join(HERE, "fixtures", "recordings")
CSSIDS = os.path.join(HERE, "fixtures", "cssids")
NARRATED = os.path.join(RECORDINGS, "narrated")
NO_TOOLS = {"ffmpeg": None, "whisper": None, "model": None}


def narrated_plan(path=NARRATED, tools=NO_TOOLS):
    return pr.build_plan(pr.load_session(path), CSSIDS, pr.file_reader(path), None, pr.file_bytes(path), tools)


class ToMsTest(unittest.TestCase):
    def test_to_ms_handles_z_offset_and_fraction(self):
        base = narration.to_ms("2026-10-01T18:04:18.123456+02:00")
        self.assertEqual(narration.to_ms("2026-10-01T16:04:18.123456Z"), base)
        self.assertEqual(narration.to_ms("2026-10-01T18:04:18.123456789+02:00"), base)
        self.assertEqual(narration.to_ms("2026-10-01T18:04:19.123456+02:00") - base, 1000)

    def test_to_ms_without_fraction(self):
        self.assertEqual(narration.to_ms("2026-10-01T00:00:01Z") - narration.to_ms("2026-10-01T00:00:00Z"), 1000)


class FileBytesTest(unittest.TestCase):
    def test_reads_bytes_and_blocks_traversal(self):
        read = pr.file_bytes(NARRATED)
        self.assertEqual(read("audio/0001.webm"), b"WEBM-DUMMY")
        self.assertIsNone(read("../real-180418/session.json"))
        self.assertIsNone(read("audio/missing.webm"))


class NarrateTest(unittest.TestCase):
    def test_transcript_file_wins(self):
        result = narrated_plan()["narration"]
        self.assertEqual(result["source"], "transcript")
        self.assertEqual([u["t"] for u in result["utterances"]], [4500, 13000])

    def test_utterance_mapped_to_step_on_screen(self):
        utterances = narrated_plan()["narration"]["utterances"]
        self.assertEqual([u["seq"] for u in utterances], [1, 2])

    def test_assign_steps_first_step_when_earlier(self):
        steps = [{"seq": 5, "time": "2026-10-02T09:00:10Z"}, {"seq": 6, "time": "2026-10-02T09:00:20Z"}]
        result = narration.assign_steps([{"t": 1, "text": "a"}, {"t": 25000, "text": "b"}], steps,
                                        "2026-10-02T09:00:00Z")
        self.assertEqual([u["seq"] for u in result], [5, 6])

    def test_no_audio_is_none(self):
        self.assertEqual(narration.narrate({"steps": []}, lambda rel: None, NO_TOOLS, "."),
                         {"source": "none", "segments": [], "utterances": []})

    def test_audio_without_read_bytes_is_unavailable(self):
        session = pr.load_session(NARRATED)
        result = narration.narrate(session, None, NO_TOOLS, ".")
        self.assertEqual(result["source"], "unavailable")
        self.assertEqual(result["reason"], "audio files are not readable from this input")

    def test_missing_tools_unavailable_with_install(self):
        with tempfile.TemporaryDirectory() as folder:
            session = {"startedAt": "2026-10-02T09:00:00Z", "audio": [{"f": "audio/0002.webm", "t": 0}], "steps": []}
            result = narration.narrate(session, lambda rel: b"x", NO_TOOLS, folder)
        self.assertEqual(result["source"], "unavailable")
        self.assertIn("windows", result["install"])
        self.assertIn("macos", result["install"])
        self.assertIn("linux", result["install"])
        self.assertIn("ggml", result["install"]["model"])

    @unittest.skipIf(os.name == "nt", "shebang scripts do not run on Windows")
    def test_whisper_path_with_fake_tools(self):
        with tempfile.TemporaryDirectory() as tools_dir:
            ffmpeg = write_script(tools_dir, "ffmpeg",
                                  "import sys\nopen(sys.argv[-1], 'wb').write(b'wav')\n")
            whisper = write_script(tools_dir, "whisper-cli", (
                "import sys, json\nbase = sys.argv[sys.argv.index('-of') + 1]\n"
                "assert sys.argv[sys.argv.index('-m') + 1] == 'model.bin'\n"
                "json.dump({'transcription': [{'offsets': {'from': 1000, 'to': 3000}, 'text': ' Confirm the total.'}]},"
                " open(base + '.json', 'w'))\n"))
            session = pr.load_session(NARRATED)
            session["audio"] = [{"f": "audio/0009.webm", "t": 9000}]  # no transcript file -> whisper
            with tempfile.TemporaryDirectory() as work:
                result = narration.narrate(session, lambda rel: b"webm",
                                           {"ffmpeg": ffmpeg, "whisper": whisper, "model": "model.bin"}, work)
                self.assertEqual(os.listdir(work), [])
        self.assertEqual(result["source"], "whisper")
        self.assertEqual(result["utterances"][0]["t"], 10000)
        self.assertEqual(result["utterances"][0]["text"], "Confirm the total.")

    @unittest.skipIf(os.name == "nt", "shebang scripts do not run on Windows")
    def test_failing_tool_skips_segment(self):
        with tempfile.TemporaryDirectory() as tools_dir:
            ffmpeg = write_script(tools_dir, "ffmpeg", "import sys\nsys.exit(1)\n")
            whisper = write_script(tools_dir, "whisper-cli", "pass\n")
            session = {"startedAt": "2026-10-02T09:00:00Z", "audio": [{"f": "audio/1.webm", "t": 0}], "steps": []}
            with tempfile.TemporaryDirectory() as work:
                result = narration.narrate(session, lambda rel: b"webm",
                                           {"ffmpeg": ffmpeg, "whisper": whisper, "model": "m"}, work)
        self.assertEqual(result["source"], "unavailable")
        self.assertIn("audio/1.webm", result["reason"])


class FindToolsTest(unittest.TestCase):
    def test_env_model_beats_config(self):
        with tempfile.TemporaryDirectory() as folder:
            env_model, cfg_model = (os.path.join(folder, n) for n in ("env.bin", "cfg.bin"))
            for p in (env_model, cfg_model):
                open(p, "w").close()
            cfg = os.path.join(folder, "c.json")
            with open(cfg, "w") as f:
                json.dump({"whisperModel": cfg_model}, f)
            self.assertEqual(narration.find_tools({"RECORDING_TO_TEST_WHISPER_MODEL": env_model}, cfg)["model"],
                             env_model)
            self.assertEqual(narration.find_tools({}, cfg)["model"], cfg_model)

    def test_missing_model_file_and_bad_config_are_none(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = os.path.join(folder, "c.json")
            with open(cfg, "w") as f:
                f.write("{not json")
            self.assertIsNone(narration.find_tools({}, cfg)["model"])
            self.assertIsNone(narration.find_tools({"RECORDING_TO_TEST_WHISPER_MODEL": "/no/such"}, cfg)["model"])
            self.assertIsNone(narration.find_tools({}, os.path.join(folder, "absent.json"))["model"])


class PlanIntegrationTest(unittest.TestCase):
    def test_utterances_join_notes_with_source(self):
        plan = narrated_plan()
        spoken = [n for n in plan["notes"] if n.get("source") == "narration"]
        self.assertEqual([n["seq"] for n in spoken], [1, 2])
        self.assertTrue(spoken[1]["asksCheck"])
        self.assertNotIn("asksCheck", spoken[0])
        self.assertTrue(plan["narration"]["utterances"][1]["asksCheck"])

    def test_existing_fixtures_unchanged(self):
        path = os.path.join(RECORDINGS, "real-180418")
        session = pr.load_session(path)
        before = [pr.note_entry(None, n.get("text", "")) for n in session.get("notes") or []]
        before += [pr.note_entry(s.get("seq"), n.get("text", "")) for s in session["steps"]
                   for n in s.get("notes") or []]
        plan = narrated_plan(path)
        self.assertEqual(plan["narration"], {"source": "none", "segments": [], "utterances": []})
        self.assertEqual(plan["notes"], before)


class CliTest(unittest.TestCase):
    def test_main_narrate_writes_out(self):
        with tempfile.TemporaryDirectory() as folder:
            out = os.path.join(folder, "n.json")
            self.assertEqual(narration.main_narrate([NARRATED, "--out", out]), 0)
            with open(out, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["source"], "transcript")

    def test_main_tools_prints_json(self):
        import contextlib
        import io
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.assertEqual(narration.main_tools([]), 0)
        self.assertEqual(set(json.loads(buffer.getvalue())), {"ffmpeg", "whisper", "model"})


def write_script(folder, name, body):
    path = os.path.join(folder, name)
    with open(path, "w") as f:
        f.write(f"#!{sys.executable}\n{body}")
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


if __name__ == "__main__":
    unittest.main()
