import filecmp
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
VENDORED = os.path.join(PLUGIN, "scripts", "find_getter.py")
SOURCE = os.path.join(os.path.dirname(PLUGIN), "cssid-finder", "scripts", "find_getter.py")


class VendoredFindGetterTest(unittest.TestCase):
    def test_vendored_copy_matches_cssid_finder(self):
        self.assertTrue(
            os.path.isfile(VENDORED) and filecmp.cmp(VENDORED, SOURCE, shallow=False),
            "plugins/recording-to-test/scripts/find_getter.py must be an unchanged copy of "
            "plugins/cssid-finder/scripts/find_getter.py; copy it again with: "
            "cp plugins/cssid-finder/scripts/find_getter.py plugins/recording-to-test/scripts/",
        )


if __name__ == "__main__":
    unittest.main()
