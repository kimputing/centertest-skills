import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from rules.rule_methods import _is_extractable, _longest, _parse_prefixes

BODY = """{
if (scenarioContext.restart(RestartPoints.POLICY)) {
  Helper.getBC(underwriter).getBatchJobs().runInvoice(true).execute();
  scenarioContext.restartComplete(RestartPoints.POLICY);
}
if (scenarioContext.restart(RestartPoints.BILLING)) {
  Helper.getBC(underwriter).getBatchJobs().runInvoice(true).execute();
  scenarioContext.restartComplete(RestartPoints.BILLING);
}
page.getLEFT().getNavigate().getForms().click();
page.getLEFT().getNavigate().getQuote().click();
CenterTestAssertion.withContext(getContext()).withDescription("a").assertThat(() -> x());
CenterTestAssertion.withContext(getContext()).withDescription("b").assertThat(() -> y());
}"""


class Rule4001Test(unittest.TestCase):
    def test_only_extractable_expressions_longest_first(self):
        counts = _parse_prefixes(BODY, mode="overall")
        got = _longest({p: c for p, c in counts.items() if c >= 2 and _is_extractable(p)})
        self.assertEqual(got, {"Helper.getBC(underwriter).getBatchJobs().runInvoice(true)": 2,
                               "page.getLEFT().getNavigate()": 2})

    def test_noise_is_not_a_candidate(self):
        for p in ("if (scenarioContext.restart(RestartPoints", "scenarioContext.restartComplete(RestartPoints",
                  ".assertThat(() -> Assertions", "this.matches", "boxed.add(border);",
                  "PC.loginToPC(producer).execute();", "CenterTestAssertion.withContext(getContext())"):
            self.assertFalse(_is_extractable(p), p)


if __name__ == "__main__":
    unittest.main()
