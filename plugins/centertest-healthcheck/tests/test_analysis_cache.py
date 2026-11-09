import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import eir_review  # noqa: E402


class AnalysisCacheTest(unittest.TestCase):
    """A cached analysis is reused only by the same implementation: any change to the plugin's scripts
    (a rule, the engine) gives a new key, so results always come from the current code."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        home = mock.patch.dict(os.environ, {"HOME": self.tmp.name})
        home.start()
        self.addCleanup(home.stop)
        self.addCleanup(self.tmp.cleanup)
        self.calls = []
        patch = mock.patch.object(eir_review, "analyze_tree", side_effect=lambda *a: (self.calls.append(1) or ([], 7)))
        patch.start()
        self.addCleanup(patch.stop)
        self.config = type("C", (), {"ruleset": "CenterTestFull", "rules": None, "source_root": "src"})()

    def test_same_commit_and_code_reuses_a_changed_implementation_does_not(self):
        args = ("/repo", "abc123", "/tmp/tree", self.config, None)
        self.assertEqual(eir_review.analyze_commit(*args), ([], 7))
        self.assertEqual(eir_review.analyze_commit(*args), ([], 7))
        self.assertEqual(len(self.calls), 1)  # second time from the cache
        with mock.patch.object(eir_review, "_fingerprint", return_value="new-code"):
            eir_review.analyze_commit(*args)
        self.assertEqual(len(self.calls), 2)  # a different implementation never reads the old result

    def test_the_fingerprint_covers_every_script(self):
        eir_review._FINGERPRINT.clear()
        first = eir_review._fingerprint()
        eir_review._FINGERPRINT.clear()
        real_open = open

        def changed(path, mode="r", *a, **k):
            fh = real_open(path, mode, *a, **k)
            if path.endswith("rule_ddt.py") and "b" in mode:
                data = fh.read() + b"# edited"
                fh.close()
                import io
                return io.BytesIO(data)
            return fh
        with mock.patch("builtins.open", side_effect=changed):
            second = eir_review._fingerprint()
        eir_review._FINGERPRINT.clear()
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
