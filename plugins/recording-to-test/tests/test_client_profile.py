import datetime
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
SCRIPTS = os.path.join(PLUGIN, "scripts")
sys.path.insert(0, SCRIPTS)
import client_profile as cp  # noqa: E402

DEFAULTS = os.path.join(PLUGIN, "profile", "defaults.md")
TEMPLATE = os.path.join(PLUGIN, "profile", "template.md")
TODAY = datetime.date(2026, 11, 3)


def project(set_custom=0, data_key=0, project_exception=0, framework=0):
    return {
        "sharedValuesUsage": {"value": {"setCustom": set_custom, "dataKey": data_key, "reservedKeyMisuse": []}},
        "negativeProtocol": {"value": {"projectException": project_exception, "framework": framework}},
        "testLayout": {"value": {"folders": {"tests/pc/personalauto": 2}, "lobPrefixes": {"personalauto": "PA"}}},
        "testStyle": {"value": {"tests": 2, "methods": {"run": 2}, "roles": {"producer": 3}}},
        "build": {"value": {"compile": "./gradlew compileJava", "run": None, "profiles": ["qa"],
                            "bootRunProperties": []}},
        "guidance": {"value": ["CLAUDE.md"]},
        "clientPackage": {"value": "com.acme"},
    }


class ProfileCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def write_profile(self, text):
        os.makedirs(os.path.join(self.root, ".claude"), exist_ok=True)
        with open(os.path.join(self.root, ".claude", "client-profile.md"), "w", encoding="utf-8") as f:
            f.write(text)

    def resolve(self, proj=None):
        return cp.resolve(self.root, proj, DEFAULTS, TODAY)


class FrontMatterTest(unittest.TestCase):
    def test_flat_front_matter(self):
        text = '---\na: 1\n\nb: "two words"  # note\nc: \'x\'\nd: http://h#frag\ne:\n---\nbody\nline\n'
        values, body = cp.parse_front_matter(text)
        self.assertEqual({"a": "1", "b": "two words", "c": "x", "d": "http://h#frag", "e": ""}, values)
        self.assertEqual("body\nline\n", body)

    def test_no_front_matter(self):
        self.assertEqual(({}, "just text\n"), cp.parse_front_matter("just text\n"))

    def test_nested_yaml_rejected(self):
        for text, line in (("---\na:\n  b: 1\n---\n", 3), ("---\na: 1\n- item\n---\n", 3)):
            with self.subTest(text=text):
                with self.assertRaises(cp.ProfileError) as ctx:
                    cp.parse_front_matter(text)
                self.assertEqual(f"nested YAML is not supported: line {line}", str(ctx.exception))

    def test_trailing_colon_value_rejected(self):
        with self.assertRaises(cp.ProfileError) as ctx:
            cp.parse_front_matter("---\na: b:\n---\n")
        self.assertEqual("nested YAML is not supported: line 2", str(ctx.exception))


class ResolveTest(ProfileCase):
    def test_missing_profile_resolves_to_defaults(self):
        result = self.resolve()
        self.assertFalse(result["exists"])
        self.assertEqual({"value": "data", "source": "defaults"}, result["switches"]["recordedValues"])
        self.assertEqual({"value": "phases", "source": "defaults"}, result["switches"]["gate"])
        self.assertEqual(set(cp.SWITCHES), set(result["switches"]))

    def test_repo_overrides_defaults(self):
        self.write_profile("---\nrecordedValues: constants\ncomments: javadoc\n---\nbody\n")
        result = self.resolve()
        self.assertTrue(result["exists"])
        self.assertEqual({"value": "constants", "source": "repo"}, result["switches"]["recordedValues"])
        self.assertEqual({"value": "javadoc", "source": "repo"}, result["switches"]["comments"])
        self.assertEqual("defaults", result["switches"]["gate"]["source"])

    def test_auto_shared_values_from_scan(self):
        self.assertEqual({"value": "dataKey", "source": "scan"},
                         self.resolve(project(set_custom=2, data_key=5))["switches"]["sharedValues"])
        self.assertEqual({"value": "setCustom", "source": "scan"},
                         self.resolve(project(set_custom=5, data_key=5))["switches"]["sharedValues"])
        self.assertEqual({"value": "project", "source": "scan"},
                         self.resolve(project(project_exception=3, framework=1))["switches"]["negativeProtocol"])
        self.assertEqual({"value": "framework", "source": "scan"},
                         self.resolve(project(project_exception=1, framework=3))["switches"]["negativeProtocol"])

    def test_auto_stays_without_scan_evidence(self):
        proj = project()
        proj["negativeProtocol"] = {"value": None, "reason": "none"}
        result = self.resolve(proj)
        self.assertEqual({"value": "auto", "source": "defaults"}, result["switches"]["sharedValues"])
        self.assertEqual("auto", result["switches"]["negativeProtocol"]["value"])
        self.assertEqual("auto", self.resolve()["switches"]["comments"]["value"])

    def test_repo_value_beats_scan(self):
        self.write_profile("---\nsharedValues: setCustom\n---\n")
        self.assertEqual({"value": "setCustom", "source": "repo"},
                         self.resolve(project(data_key=9))["switches"]["sharedValues"])

    def test_unknown_key_reported(self):
        self.write_profile("---\nfavouriteColour: blue\ngate: plan\n---\n")
        self.assertEqual(["favouriteColour"], self.resolve()["unknownKeys"])

    def test_invalid_value_reported(self):
        self.write_profile("---\ngate: sometimes\nstandardsSkill: any-skill\n---\n")
        result = self.resolve()
        self.assertEqual([{"key": "gate", "value": "sometimes", "allowed": ["phases", "plan", "single"]}],
                         result["invalid"])
        self.assertEqual({"value": "phases", "source": "defaults"}, result["switches"]["gate"])
        self.assertEqual({"value": "any-skill", "source": "repo"}, result["switches"]["standardsSkill"])

    def test_stale_fact_after_90_days(self):
        self.write_profile("---\ngate: plan\n---\n- old fact (verified 2026-07-01)\n- recent fact (verified 2026-10-01)\n"
                           "- undated fact\n")
        self.assertEqual([{"line": "- old fact (verified 2026-07-01)", "verified": "2026-07-01"}],
                         self.resolve()["staleFacts"])

    def test_malformed_profile_falls_back_to_defaults(self):
        self.write_profile("---\ngate: plan\na:\n  b: 1\n---\n")
        result = self.resolve(project(data_key=5))
        self.assertTrue(result["exists"])
        self.assertEqual("nested YAML is not supported: line 4", result["error"])
        self.assertEqual({"value": "phases", "source": "defaults"}, result["switches"]["gate"])
        self.assertEqual({"value": "dataKey", "source": "scan"}, result["switches"]["sharedValues"])

    def test_bad_verified_date_is_listed_not_raised(self):
        self.write_profile("---\ngate: plan\n---\n- x (verified 2026-13-99)\n- y (verified 2026-07-01)\n")
        result = self.resolve()
        self.assertEqual([{"key": "verified", "value": "2026-13-99", "allowed": "YYYY-MM-DD"}], result["invalid"])
        self.assertEqual(["2026-07-01"], [f["verified"] for f in result["staleFacts"]])
        self.assertNotIn("error", result)

    def test_cli_resolve_malformed_profile_exits_zero(self):
        self.write_profile("---\na:\n  b: 1\n---\n")
        run = subprocess.run([sys.executable, os.path.join(SCRIPTS, "ct.py"), "profile", "resolve",
                              "--root", self.root], capture_output=True, text=True)
        self.assertEqual(0, run.returncode)
        self.assertIn("nested YAML", json.loads(run.stdout)["error"])

    def test_cli_project_not_an_object_exits_two(self):
        proj = os.path.join(self.root, "project.json")
        with open(proj, "w") as f:
            f.write("[]")
        run = subprocess.run([sys.executable, os.path.join(SCRIPTS, "ct.py"), "profile", "resolve",
                              "--root", self.root, "--project", proj], capture_output=True, text=True)
        self.assertEqual(2, run.returncode)
        self.assertIn("Error:", run.stderr)
        self.assertNotIn("Traceback", run.stderr)

    def write_profile_bytes(self, data):
        os.makedirs(os.path.join(self.root, ".claude"), exist_ok=True)
        with open(os.path.join(self.root, ".claude", "client-profile.md"), "wb") as f:
            f.write(data)

    def test_utf8_bom_profile_keeps_its_front_matter(self):
        self.write_profile_bytes(b"\xef\xbb\xbf---\r\ngate: plan\r\n---\r\nbody\r\n")
        result = self.resolve()
        self.assertEqual(({"value": "plan", "source": "repo"}, None, None),
                         (result["switches"]["gate"], result.get("error"), result.get("warnings")))

    def test_utf16_profile_reports_error_and_uses_defaults(self):
        self.write_profile_bytes("---\ngate: plan\n---\n".encode("utf-16"))
        result = self.resolve()
        self.assertEqual((result["exists"], result["switches"]["gate"]["source"]), (True, "defaults"))
        self.assertIn("UTF-8", result["error"])

    def test_cli_resolve_utf16_profile_exits_zero(self):
        self.write_profile_bytes("---\ngate: plan\n---\n".encode("utf-16"))
        run = subprocess.run([sys.executable, os.path.join(SCRIPTS, "ct.py"), "profile", "resolve",
                              "--root", self.root], capture_output=True, text=True)
        self.assertEqual((run.returncode, "error" in json.loads(run.stdout)), (0, True))

    def test_unreadable_profile_reports_error(self):
        from unittest import mock
        self.write_profile("---\ngate: plan\n---\n")
        real = cp._read

        def read(path):
            if path.endswith("client-profile.md"):
                raise PermissionError("denied")
            return real(path)
        with mock.patch.object(cp, "_read", side_effect=read):
            result = self.resolve()
        self.assertEqual((result["switches"]["gate"]["source"], "denied" in result["error"]), ("defaults", True))

    def test_profile_without_front_matter_warns(self):
        self.write_profile("Just notes about the client.\n")
        self.assertEqual(["no front matter: switches use the defaults"], self.resolve()["warnings"])

    def test_no_warnings_key_when_front_matter_or_no_file(self):
        self.assertNotIn("warnings", self.resolve())
        self.write_profile("---\n---\nbody\n")
        self.assertNotIn("warnings", self.resolve())

    def test_defaults_body_is_universal(self):
        with open(DEFAULTS, encoding="utf-8") as f:
            text = f.read()
        for needle in ("PolicyExpirationDate", "UserName", "Password", "Premium", "upgradePages", "rebuildCode"):
            self.assertIn(needle, text)


class InitTest(ProfileCase):
    def test_init_contains_layout_and_dates(self):
        text = cp.init_profile(project(data_key=4), TODAY, TEMPLATE)
        front, body = cp.parse_front_matter(text)
        self.assertEqual("dataKey", front["sharedValues"])
        self.assertEqual("phases", front["gate"])
        self.assertIn("personalauto: test class prefix PA_ (verified 2026-11-03)", body)
        self.assertIn("producer", body)
        self.assertIn("compile: ./gradlew compileJava (verified 2026-11-03)", body)
        self.assertIn("CLAUDE.md (verified 2026-11-03)", body)
        self.assertNotIn("{", body)

    def test_init_mixed_shared_values_writes_auto_and_the_counts(self):
        text = cp.init_profile(project(set_custom=53, data_key=156), TODAY, TEMPLATE)
        front, body = cp.parse_front_matter(text)
        self.assertEqual("auto", front["sharedValues"])
        self.assertIn("## Shared values", body)
        self.assertIn("- setCustom used 53 times, generated DataKey 156 times: mixed, "
                      "the wizard asks per scenario (verified 2026-11-03)", body)

    def test_init_only_one_shared_values_style_keeps_that_value(self):
        text = cp.init_profile(project(data_key=156), TODAY, TEMPLATE)
        front, body = cp.parse_front_matter(text)
        self.assertEqual("dataKey", front["sharedValues"])
        self.assertNotIn("mixed", body)

    def test_init_with_missing_facts(self):
        text = cp.init_profile({"testLayout": {"value": None, "reason": "x"}}, TODAY, TEMPLATE)
        self.assertIn("none found (verified 2026-11-03)", text)

    def test_init_refuses_existing_file(self):
        proj = os.path.join(self.root, "project.json")
        with open(proj, "w") as f:
            json.dump(project(), f)
        out = os.path.join(self.root, "client-profile.md")
        with open(out, "w") as f:
            f.write("keep me")
        run = subprocess.run([sys.executable, os.path.join(SCRIPTS, "ct.py"), "profile", "init",
                              "--project", proj, "--out", out], capture_output=True, text=True)
        self.assertEqual(2, run.returncode)
        self.assertIn("exists", run.stderr)
        with open(out) as f:
            self.assertEqual("keep me", f.read())

    def test_init_writes_new_file_and_resolve_cli(self):
        proj = os.path.join(self.root, "project.json")
        with open(proj, "w") as f:
            json.dump(project(data_key=4), f)
        out = os.path.join(self.root, ".claude", "client-profile.md")
        os.makedirs(os.path.dirname(out))
        ct = os.path.join(SCRIPTS, "ct.py")
        self.assertEqual(0, subprocess.run([sys.executable, ct, "profile", "init", "--project", proj, "--out", out],
                                           capture_output=True).returncode)
        run = subprocess.run([sys.executable, ct, "profile", "resolve", "--root", self.root, "--project", proj],
                             capture_output=True, text=True)
        self.assertEqual(0, run.returncode)
        result = json.loads(run.stdout)
        self.assertTrue(result["exists"])
        self.assertEqual("dataKey", result["switches"]["sharedValues"]["value"])
        self.assertEqual([], result["invalid"])


if __name__ == "__main__":
    unittest.main()
