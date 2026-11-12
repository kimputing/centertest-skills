"""Rules 21001-21006 (TestData) and 25001 (Config): a BAD fixture each rule must flag, a GOOD one it must not."""

import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

try:
    import javalang  # noqa: F401
    HAS_JAVALANG = True
except ImportError:
    HAS_JAVALANG = False

try:
    import openpyxl  # noqa: F401
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


ADD_VEHICLE = """package com.acme.reusable;
public class AddVehicle extends BaseScenarioPC {
  private static final String VIN = "1G1ZB5E05CF177399";
  private static final String YEAR = "2010";
  private static final String MAKE = "honda";
  private static final String MODEL = "test";
  private static final String BODY = "Hatchback";
  public void execute() {
    card.getVin().set(VIN);
    card.getYear().set(YEAR);
    card.getMake().set(MAKE);
    card.getModel().set(MODEL);
    card.getBodyType().set(BODY);
    card.getAntiTheft().set(true);
  }
}
"""

OTHER_VEHICLE = """package com.acme.reusable;
public class SubstituteVehicle extends BaseScenarioPC {
  private static final String VIN = "1G1ZB5E05CF177399";
  public void execute() { card.getVin().set(VIN); }
}
"""

DATA_DRIVEN_VEHICLE = """package com.acme.reusable;
import com.acme.generated.datadriven.reference.PersonalAutoData;
public class AddVehicleFromData extends BaseScenarioPC {
  private static final String RATE_SOURCE = "Manual";
  public void addVehicle(PersonalAutoData.Vehicle vehicle) {
    card.getVin().set(vehicle.getVin());
    card.getYear().set(vehicle.getModelyear());
    card.getMake().set(vehicle.getMake());
    card.getModel().set(vehicle.getModel());
    card.getBodyType().set(vehicle.getBodytype());
    card.getRateGroupSource().set(RATE_SOURCE);
    card.getBrokerClientID().set("1234");
    card.getAddressOverridenReason_IC().set("Needed");
    card.getPicker().set("New...");
    card.getHasAlarm().set("Yes");
    card.getCostNew().set("");
  }
  public void search() {
    page.getContactType().set("Person");
    page.getName().set(policyInfoDDT.getName());
  }
  public void noData() {
    page.getComment().set("4321");
  }
}
"""

JUNK = """package com.acme.reusable;
public class EditCoverages extends BaseScenarioPC {
  private static final String FREE_FORM = "vczxbvcxbgffghs";
  private static final String OVERRIDE_REASON = "test";
  private static final String ENVIRONMENT = "test";
  private static final String NOTE = "Address verified with insured";
  public void execute() {
    util.setCoverage("Free Form", "Description", FREE_FORM);
    page.getOverrideReason().set(OVERRIDE_REASON);
    page.getName().set("xxx");
    page.getDescription().set(NOTE);
    page.getInsured().set("Test Insured");
    page.getCity().set("Rhythms");
    if (ENVIRONMENT.equals(env)) { log.info("test"); }
    waitForPageTitle("test");
  }
}
"""

NUMBERS = """package com.acme.tests;
public final class WipTest {
  private static final String POLICY_NUMBER = "0149633879";
  public void run(ScenarioContext scenarioContext) {
    var jobNumber = "0149633878";
    page.getPolicyNumber().set("1234567890");
    page.getPhone().set("4165551234");
    page.getBankAccountNumber().set("123456789");
    // var accountNumber = "5555555555";
    var count = "123456789";
  }
}
"""

PINNED = """package com.acme.tests;
public final class PinnedTest {
  private static final String RENEWAL_CODE = "GoodDriver";
  private static final String MISSING_RENEWAL = "BadDriver";
  public void run(ScenarioContext scenarioContext) {
    var a = DDTHelper.getPA_SubmissionDC("Default");
    var b = DDTHelper.getPA_SubmissionDC("default");
    var c = DDTHelper.getPA_SubmissionDC("Defualt");
    var d = DDTHelper.getPA_RenewalDC(RENEWAL_CODE);
    var e = DDTHelper.getPA_RenewalDC(MISSING_RENEWAL);
    var f = DDTHelper.getSharedDataPerson("John");
    var g = DDTHelper.getSharedDataPerson("Nobody");
    var h = DDTHelper.getSharedDataPerson(code);
    var i = DDTHelper.getUnknownDC("Whatever");
    var j = DDTHelper.getPA_SubmissionDC(scenarioContext);
    var k = DDTHelper.getMissingWorkbookDC("Default");
    var l = DDTHelper.getPA_SubmissionDC("Coupe(2)");
  }
}
"""

DDT_HELPER = """package com.acme.generated.datadriven;
public final class DDTHelper {
public static com.acme.X getPA_SubmissionDC(String code) {return new com.acme.X(new TestDataProvider().getExcelInputFileByCode("testdata/pa/PA_SubmissionDC.xlsx", code));}
public static com.acme.X getPA_SubmissionDC(ScenarioContext scenarioContext) {return new com.acme.X(scenarioContext.getTestData());}
public static com.acme.Y getPA_RenewalDC(String code) {return new com.acme.Y(new TestDataProvider().getExcelInputFileByCode("testdata/pa/PA_RenewalDC.xlsx", code));}
public static com.acme.Z getMissingWorkbookDC(String code) {return new com.acme.Z(new TestDataProvider().getExcelInputFileByCode("testdata/pa/NoSuchDC.xlsx", code));}
public static com.acme.S.Person getSharedDataPerson(String code) {return new com.acme.S(new TestDataProvider().provideDataRecordAsExcelInput("testdata/SharedData.xlsx", "person", code)).getPerson();}
}
"""

JURISDICTION = """package com.acme.reusable;
public class AddDriver extends BaseScenarioPC {
  private static final String LICENCE_PROVINCE = "Alberta";
  private static final String CITY = "Victoria";
  public void execute() {
    card.getLicenseProvince().set(LICENCE_PROVINCE);
    vehicle.withProvince("ON");
    card.getCity().set(CITY);
    card.getEstateName().set("Alberta");
    card.getLicenseProvince().set(addressDDT.getState());
  }
}
"""

JURISDICTION_SPECIFIC = """package com.acme.reusable;
public class CreateSubmissionON extends BaseScenarioPC {
  private static final String PROVINCE = "Ontario";
  public void execute() { card.getProvince().set(PROVINCE); }
}
"""

ROLES = """package com.acme.tests;
public final class RolesTest {
  private static final String UNDERWRITER = "underwriter";
  public void run(ScenarioContext scenarioContext) {
    var producer = scenarioContext.getInvocationContext("producer");
    var uw = scenarioContext.getInvocationContext(UNDERWRITER);
    var api = scenarioContext.getInvocationContext("api");
    var api2 = scenarioContext.getInvocationContext("api");
    var su = scenarioContext.getInvocationContext("SU");
    var dynamic = scenarioContext.getInvocationContext(role);
  }
}
"""


class _Project:
    def __init__(self):
        self.tmp = tempfile.mkdtemp()

    def java(self, rel, text):
        path = os.path.join(self.tmp, "src", "main", "java", rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)

    def file(self, rel, text):
        path = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)

    def workbook(self, rel, sheets):
        from openpyxl import Workbook
        path = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        wb = Workbook()
        wb.remove(wb.active)
        for name, rows in sheets.items():
            ws = wb.create_sheet(name)
            for row in rows:
                ws.append(row)
        wb.save(path)

    def commits(self):
        from eir_models import LOCAL_COMMIT
        from eir_parser import parse_directory
        return {LOCAL_COMMIT: parse_directory(self.tmp, "src/main/java", [], [], True, None)}

    def config(self):
        return SimpleNamespace(repository_dir=self.tmp, source_root="src/main/java", cssids=None)

    def close(self):
        shutil.rmtree(self.tmp)


def _by(rows, col=0):
    return sorted(r[col] for r in rows)


@unittest.skipUnless(HAS_JAVALANG, "javalang not installed")
class TestDataRulesTest(unittest.TestCase):
    def setUp(self):
        self.p = _Project()
        self.addCleanup(self.p.close)

    def test_21001_constant_heavy_step_flagged_data_driven_step_not(self):
        import rules.rule_testdata as rt
        self.p.java("com/acme/reusable/AddVehicle.java", ADD_VEHICLE)
        self.p.java("com/acme/reusable/SubstituteVehicle.java", OTHER_VEHICLE)
        self.p.java("com/acme/reusable/AddVehicleFromData.java", DATA_DRIVEN_VEHICLE)
        self.p.java("com/acme/generated/pages/Generated.java", ADD_VEHICLE.replace("com.acme.reusable", "com.acme.generated.pages")
                    .replace("class AddVehicle", "class Generated"))
        rows = rt.hardcoded_step_data(self.p.commits(), self.p.config()).rows
        self.assertEqual(_by(rows), ["AddVehicle"])
        row = rows[0]
        self.assertIn("5 of 5", row[3])  # set(true) is neutral
        self.assertIn('"1G1ZB5E05CF177399" is also hardcoded in SubstituteVehicle', row[3])
        self.assertEqual(row[2], "card.getVin().set(VIN);")
        self.assertTrue(row[4].endswith("AddVehicle.java:9"))

    def test_21001_threshold_is_configurable(self):
        import rules.rule_testdata as rt
        self.p.java("com/acme/reusable/AddVehicle.java", ADD_VEHICLE)
        config = self.p.config()
        config.get_threshold = lambda rid, default: {"21001": 6}.get(rid, default)
        self.assertEqual(rt.hardcoded_step_data(self.p.commits(), config).rows, [])

    def test_21002_literal_beside_data_driven_lines(self):
        import rules.rule_testdata as rt
        self.p.java("com/acme/reusable/AddVehicleFromData.java", DATA_DRIVEN_VEHICLE)
        rows = rt.literal_beside_data(self.p.commits(), self.p.config()).rows
        # constant RATE_SOURCE (21001's), Reason widgets, picker choices, Yes/No, "" and a method without
        # data-driven sets are not reported; "Person" in a class without Person in its name is
        self.assertEqual([(r[1], r[2]) for r in rows],
                         [("addVehicle", 'card.getBrokerClientID().set("1234");'),
                          ("search", 'page.getContactType().set("Person");')])

    def test_21002_value_named_by_the_class_is_its_purpose(self):
        import rules.rule_testdata as rt
        self.p.java("com/acme/reusable/SearchForPerson.java",
                    DATA_DRIVEN_VEHICLE.replace("AddVehicleFromData", "SearchForPerson"))
        rows = rt.literal_beside_data(self.p.commits(), self.p.config()).rows
        self.assertEqual([r[1] for r in rows], ["addVehicle"])

    def test_21003_placeholder_values(self):
        import rules.rule_testdata as rt
        self.p.java("com/acme/reusable/EditCoverages.java", JUNK)
        rows = rt.placeholder_values(self.p.commits(), self.p.config()).rows
        snippets = [r[2] for r in rows]
        self.assertEqual(snippets, ['private static final String FREE_FORM = "vczxbvcxbgffghs";',
                                    'private static final String OVERRIDE_REASON = "test";',
                                    'page.getName().set("xxx");'])

    def test_21003_keyboard_mash(self):
        from rules.rule_testdata import _junk
        for bad in ("vczxbvcxbgffghs", "asdfgh", "qwerty", "TEST", "testing", "test1", "dummy", "TBD", "xxxx"):
            self.assertTrue(_junk(bad), bad)
        for good in ("Hatchback", "rhythms", "strengths", "Test Insured", "contest", "property", "Toronto", "AAA"):
            self.assertFalse(_junk(good), good)

    def test_21004_hardcoded_business_numbers(self):
        import rules.rule_testdata as rt
        self.p.java("com/acme/tests/WipTest.java", NUMBERS)
        rows = rt.hardcoded_business_number(self.p.commits(), self.p.config()).rows
        self.assertEqual([r[2] for r in rows], ['private static final String POLICY_NUMBER = "0149633879";',
                                                'var jobNumber = "0149633878";',
                                                'page.getPolicyNumber().set("1234567890");'])

    @unittest.skipUnless(HAS_OPENPYXL, "openpyxl not installed")
    def test_21005_pinned_code_missing(self):
        import rules.rule_testdata as rt
        self.p.java("com/acme/tests/PinnedTest.java", PINNED)
        self.p.java("com/acme/generated/datadriven/DDTHelper.java", DDT_HELPER)
        self.p.workbook("testdata/pa/PA_SubmissionDC.xlsx",
                        {"DataCombination": [["Code", "Description"], ["Default", "d"], ["Coupe", "c"]],
                         "Other": [["Code"], ["Defualt"]]})
        self.p.workbook("testdata/pa/PA_RenewalDC.xlsx", {"DataCombination": [["Code "], ["GoodDriver"]]})
        self.p.workbook("testdata/SharedData.xlsx", {"Person": [["Code", "Name"], ["John", "J"]]})
        rows = rt.pinned_code_missing(self.p.commits(), self.p.config()).rows
        self.assertEqual([r[2] for r in rows], ['var c = DDTHelper.getPA_SubmissionDC("Defualt");',
                                                "var e = DDTHelper.getPA_RenewalDC(MISSING_RENEWAL);",
                                                'var g = DDTHelper.getSharedDataPerson("Nobody");'])
        self.assertIn("testdata/pa/PA_RenewalDC.xlsx", rows[1][3])
        self.assertIn("(MISSING_RENEWAL)", rows[1][3])
        self.assertTrue(rows[0][4].endswith("PinnedTest.java:8"))

    @unittest.skipUnless(HAS_OPENPYXL, "openpyxl not installed")
    def test_21005_reference_code_found_in_another_workbook_is_not_missing(self):
        import rules.rule_testdata as rt
        self.p.java("com/acme/tests/PinnedTest.java", PINNED)
        self.p.java("com/acme/generated/datadriven/DDTHelper.java", DDT_HELPER)
        self.p.workbook("testdata/pa/PA_SubmissionDC.xlsx",
                        {"DataCombination": [["Code"], ["Default"], ["Defualt"], ["Coupe"]]})
        self.p.workbook("testdata/pa/PA_RenewalDC.xlsx", {"DataCombination": [["Code"], ["GoodDriver"], ["BadDriver"]]})
        self.p.workbook("testdata/SharedData.xlsx", {"person": [["Code"], ["John"]]})
        self.p.workbook("testdata/MoreData.xlsx", {"Person": [["Code"], ["Nobody"]]})
        self.assertEqual(rt.pinned_code_missing(self.p.commits(), self.p.config()).rows, [])

    def test_21005_without_ddthelper_reports_nothing(self):
        import rules.rule_testdata as rt
        self.p.java("com/acme/tests/PinnedTest.java", PINNED)
        self.assertEqual(rt.pinned_code_missing(self.p.commits(), self.p.config()).rows, [])

    def test_21006_hardcoded_jurisdiction(self):
        import rules.rule_testdata as rt
        self.p.java("com/acme/reusable/AddDriver.java", JURISDICTION)
        self.p.java("com/acme/reusable/CreateSubmissionON.java", JURISDICTION_SPECIFIC)
        codes = {"alberta": "AB", "ab": "AB", "ontario": "ON", "on": "ON", "victoria": "AU_VIC", "au_vic": "AU_VIC"}
        with mock.patch.object(rt, "_covered_jurisdictions", return_value=(codes, {"AB", "ON"})):
            rows = rt.hardcoded_jurisdiction(self.p.commits(), self.p.config()).rows
        self.assertEqual([r[2] for r in rows], ['private static final String LICENCE_PROVINCE = "Alberta";',
                                                'vehicle.withProvince("ON");'])
        with mock.patch.object(rt, "_covered_jurisdictions", return_value=(codes, {"AB"})):
            self.assertEqual(rt.hardcoded_jurisdiction(self.p.commits(), self.p.config()).rows, [])


@unittest.skipUnless(HAS_JAVALANG, "javalang not installed")
class ConfigRuleTest(unittest.TestCase):
    def setUp(self):
        self.p = _Project()
        self.addCleanup(self.p.close)
        self.p.java("com/acme/tests/RolesTest.java", ROLES)

    def _rows(self):
        import rules.rule_config as rc
        return rc.undefined_role(self.p.commits(), self.p.config()).rows

    def test_25001_role_without_user(self):
        self.p.file("src/main/resources/runtime_environments.properties",
                    "qa.pc.url=http://pc\n"
                    "centertest.user.producer.qa=bob|secret1\n"
                    "# centertest.user.api.qa=commented|out\n"
                    "centertest.user.underwriter.*.secret=vault-name\n")
        self.p.file("src/main/resources/profile.ci.properties", "centertest.user.su : admin|pw\n")
        rows = self._rows()
        self.assertEqual([(r[0], r[2]) for r in rows],
                         [("RolesTest", 'var api = scenarioContext.getInvocationContext("api");')])
        self.assertIn('Role "api"', rows[0][3])
        self.assertNotIn("secret1", rows[0][3])
        self.assertNotIn("bob", rows[0][3])

    def test_25001_wildcard_defines_every_role(self):
        self.p.file("src/main/resources/runtime_environments.properties",
                    "centertest.user.producer.qa=bob|pw\ncentertest.user.*.*=any|pw\n")
        self.assertEqual(self._rows(), [])

    def test_25001_users_defined_outside_the_project(self):
        self.p.file("src/main/resources/runtime_environments.properties", "qa.pc.url=http://pc\n")
        self.assertEqual(self._rows(), [])
        self.p.file("src/main/resources/customer.centertest.properties",
                    "centertest.user.producer.qa=bob|pw\ncentertest.runtime.path.customurl=/etc/ct\n")
        self.assertEqual(self._rows(), [])


if __name__ == "__main__":
    unittest.main()
