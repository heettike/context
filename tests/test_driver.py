"""Exports with the owner in the passenger seat, against a made-up site: what is done without the owner, the one reminder,
the downloads page, the arrival. No browser, no network."""
import json, os, unittest
from unittest import mock
from tests import fixture  # noqa: F401  (sets CTX_HOME before ctx is imported)
from ctx import driver

DAY = 86400
T0 = 1800000000.0


class FakeSite:
    def __init__(self, **states):
        self.states = {k: dict({"state": "idle", "requested_at": None, "url": "https://made.up/" + k}, **v) for k, v in states.items()}
        self.answers, self.asked, self.reminded, self.opened, self.landed = {}, [], [], [], set()

    def known(self):
        return [("kiln", "Kiln", "hours", "password"), ("glaze", "Glaze", "minutes", "nothing")]

    def state(self, sid):
        return self.states.get(sid, {"state": "idle"})

    def ask(self, sid):
        self.asked.append(sid)
        got = self.answers.get(sid, [{"state": "requested"}])
        return got.pop(0) if len(got) > 1 else got[0]

    def remind(self, sid, text):
        self.reminded.append((sid, text))

    def arrived(self, sid, since):
        return sid in self.landed

    def open_page(self, url):
        self.opened.append(url)
        return True


class Driver(unittest.TestCase):
    def setUp(self):
        self.addCleanup(lambda: os.path.exists(driver.STATE) and os.remove(driver.STATE))
        if os.path.exists(driver.STATE):
            os.remove(driver.STATE)
        p = mock.patch.dict(driver.DOWNLOADS, {"kiln": "https://made.up/kiln/downloads", "glaze": ""})
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.dict(driver.CADENCE, {"kiln": "monthly", "glaze": "weekly"})
        p.start()
        self.addCleanup(p.stop)

    def asked_before(self, **more):
        from datetime import datetime, timezone
        at = datetime.fromtimestamp(T0, timezone.utc).isoformat(timespec="seconds")
        return FakeSite(kiln=dict({"state": "arrived", "requested_at": at}, **more), glaze={"state": "arrived", "requested_at": at})

    def test_a_service_never_asked_for_or_declined_is_left_alone(self):
        site = FakeSite(kiln={"state": "idle"}, glaze={"state": "declined"})
        for d in range(0, 400, 20):
            self.assertEqual(driver.tick(T0 + d * DAY, site=site), {})
        self.assertEqual((site.asked, site.reminded, site.opened), ([], [], []))
        self.assertEqual({s["id"]: s["stage"] for s in driver.status(T0, site)["services"]}, {"kiln": "idle", "glaze": "declined"})

    def test_a_cycle_with_nothing_needed_until_the_download(self):
        site = self.asked_before()
        self.assertEqual(driver.tick(T0 + DAY, site=site), {})                       # the clock starts at the export the owner asked for themselves
        self.assertEqual(driver.tick(T0 + 29 * DAY, site=site).get("asked"), ["glaze"])      # the weekly one is due; the monthly one is not
        site.asked.clear()
        self.assertEqual(driver.tick(T0 + 30 * DAY + 60, site=site), {"asked": ["kiln"]})
        self.assertEqual(driver.tick(T0 + 30 * DAY + 3600, site=site), {})           # asked: nothing to do until it should be ready
        did = driver.tick(T0 + 30 * DAY + 5 * 3600, site=site)
        self.assertEqual((did["opened"], did["reminded"], site.opened), (["kiln"], ["kiln"], ["https://made.up/kiln/downloads"]))
        self.assertIn("press it (it asks for your password first)", site.reminded[-1][1])
        for h in (6, 10, 18, 30, 60, 200):                                            # looked at again later, never said again
            driver.tick(T0 + 30 * DAY + h * 3600, site=site)
        self.assertEqual((len([r for r in site.reminded if r[0] == "kiln"]), len(site.opened)), (1, 3))
        self.assertEqual([r["service"] for r in driver.status(T0 + 31 * DAY, site)["reminders"]], ["kiln"])
        site.landed.add("kiln")
        self.assertEqual(driver.tick(T0 + 40 * DAY, site=site).get("in"), ["kiln"])
        st = driver.status(T0 + 40 * DAY, site)
        self.assertEqual((st["reminders"], st["done"][-1]["text"]), ([], "your kiln export is in"))
        site.landed.clear()
        asked = len(site.asked)
        driver.tick(T0 + 59 * DAY, site=site)
        self.assertEqual(len([a for a in site.asked[asked:] if a == "kiln"]), 0)      # the next one is due a month after this one began
        driver.tick(T0 + 60 * DAY + 120, site=site)
        self.assertEqual(site.asked[-1], "kiln")

    def test_a_password_at_the_request_is_one_reminder_that_names_the_one_step(self):
        site = self.asked_before()
        site.answers["kiln"] = [{"state": "needs_you", "detail": "kiln is asking for your password in the dia tab that just opened"}]
        driver.tick(T0 + DAY, site=site)
        did = driver.tick(T0 + 31 * DAY, site=site)
        self.assertEqual(did.get("reminded"), ["kiln"])
        text = [t for s, t in site.reminded if s == "kiln"][0]
        self.assertEqual(text, "kiln wants your password to make your export: open the kiln tab that is waiting, do that one step, and context does the rest")
        for h in range(1, 80, 3):
            driver.tick(T0 + 31 * DAY + h * 3600, site=site)
        self.assertEqual(len([1 for s, _ in site.reminded if s == "kiln"]), 1)        # never a second one in the same cycle
        self.assertEqual(site.asked.count("kiln"), 1)                                 # and the button is not pressed again
        self.assertTrue(site.opened)                                                  # the downloads page is still opened when it should be ready
        site.landed.add("kiln")
        self.assertEqual(driver.tick(T0 + 36 * DAY, site=site).get("in"), ["kiln"])

    def test_a_page_that_cannot_be_driven_is_tried_three_days_then_said_once(self):
        site = self.asked_before()
        site.answers["kiln"] = [{"state": "failed", "detail": "the page did not get to the next step"}]
        driver.tick(T0 + DAY, site=site)
        for h in range(0, 24 * 6, 2):
            driver.tick(T0 + 31 * DAY + h * 3600, site=site)
        self.assertEqual(site.asked.count("kiln"), 3)
        said = [t for s, t in site.reminded if s == "kiln"]
        self.assertEqual(len(said), 1)
        self.assertIn("could not press the button", said[0])

    def test_a_code_is_named_as_a_code_and_a_zip_seen_by_ingest_ends_the_cycle(self):
        site = self.asked_before()
        site.answers["glaze"] = [{"state": "needs_you", "detail": "glaze is asking for your code in the tab"}]
        driver.tick(T0 + DAY, site=site)
        driver.tick(T0 + 8 * DAY, site=site)
        self.assertIn("glaze wants the code it sent you", dict(site.reminded)["glaze"])
        self.assertEqual(driver.tick(T0 + 9 * DAY, arrived=["glaze"], site=site).get("in"), ["glaze"])

    def test_the_cadence_can_be_changed_or_switched_off(self):
        site = self.asked_before()
        driver.tick(T0 + DAY, site=site)
        self.assertEqual((driver.every("kiln"), driver.every("kiln", "weekly")), ("monthly", "weekly"))
        self.assertEqual(driver.tick(T0 + 8 * DAY, site=site).get("asked"), ["kiln", "glaze"])
        driver.every("glaze", "off")
        site.asked.clear()
        site.landed.update(("kiln", "glaze"))
        driver.tick(T0 + 9 * DAY, site=site)
        site.landed.clear()
        driver.tick(T0 + 40 * DAY, site=site)
        self.assertEqual(site.asked, ["kiln"])
        with self.assertRaises(ValueError):
            driver.every("kiln", "hourly")
        st = {s["id"]: s for s in driver.status(T0 + 41 * DAY, site)["services"]}
        self.assertEqual((st["glaze"]["every"], st["glaze"]["next_in"], st["kiln"]["every"]), ("off", None, "weekly"))

    def test_the_real_services_all_have_a_cadence(self):
        from ctx import request
        for s in request.SERVICES:
            self.assertIn(driver.CADENCE.get(s["id"]), ("weekly", "monthly"), s["id"])
            self.assertIn(s["id"], driver.DOWNLOADS)


if __name__ == "__main__":
    unittest.main()
