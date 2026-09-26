import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import ApiError, RecallService, Store


class TransferArchiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.s = RecallService(Store(Path(self.tmp.name) / "r.db"))
        self.dealer_cn = self.s.register_dealer("reg", "regulator", "D-CN", "中国中心", "CN")
        self.dealer_sg = self.s.register_dealer("reg", "regulator", "D-SG", "新加坡中心", "SG")

    def tearDown(self): self.s.store.close(); self.tmp.cleanup()

    def make_recall(self):
        r = self.s.create_recall("maker", "manufacturer", "RC-1", "制动检查", {"models": ["X"], "model_years": [2018], "vin_prefixes": ["LX"], "countries": ["CN"]}, {"version": 1, "description": "更换软管"})
        r = self.s.submit_recall("maker", "manufacturer", r["id"], r["revision"])
        return self.s.review_recall("reg", "regulator", r["id"], "publish", r["revision"], "同意发布")

    def test_transfer_records_archive_and_duplicate_reuses_first(self):
        v = self.s.register_vehicle("maker", "manufacturer", "LX00001", "X", 2018, "CN", "张三")
        first = self.s.transfer_vehicle("dealer", "dealer", v["vin"], "SG", "Wang", idempotency_key="t-1", handover_at="2026-02-01T10:00:00Z")
        self.assertFalse(first["deduplicated"])
        t = first["transfer"]
        self.assertEqual(("张三", "CN", "Wang", "SG", "2026-02-01T10:00:00.000Z"),
                         (t["from_owner"], t["from_country"], t["to_owner"], t["to_country"], t["handover_at"]))
        again = self.s.transfer_vehicle("dealer", "dealer", v["vin"], "US", "Someone", idempotency_key="t-1")
        self.assertTrue(again["deduplicated"])
        self.assertEqual(t["id"], again["transfer"]["id"])
        self.assertEqual("Wang", again["vehicle"]["owner_name"])
        self.assertEqual(1, len(self.s.vehicle_history(v["vin"])["transfers"]))

    def test_in_progress_repair_stays_with_original_dealer(self):
        recall = self.make_recall()
        v = self.s.register_vehicle("maker", "manufacturer", "LX00002", "X", 2018, "CN", "张三")
        self.s.add_parts("maker", "manufacturer", recall["id"], self.dealer_cn["id"], 1, 1)
        report = self.s.report_repair("dealer", "dealer", recall["id"], v["vin"], self.dealer_cn["id"], 1, "abc", True, idempotency_key="r-1")
        moved = self.s.transfer_vehicle("dealer", "dealer", v["vin"], "SG", "Wang", idempotency_key="t-1")
        self.assertEqual([report["id"]], moved["transfer"]["in_progress_repairs"])
        confirmed = self.s.review_repair("reg", "regulator", report["id"], "confirm", "证据一致")
        self.assertEqual("confirmed", confirmed["status"])
        self.assertEqual(self.dealer_cn["id"], confirmed["dealer_id"])

    def test_confirmed_repair_attribution_survives_transfer(self):
        recall = self.make_recall()
        v = self.s.register_vehicle("maker", "manufacturer", "LX00003", "X", 2018, "CN", "张三")
        self.s.add_parts("maker", "manufacturer", recall["id"], self.dealer_cn["id"], 1, 1)
        report = self.s.report_repair("dealer", "dealer", recall["id"], v["vin"], self.dealer_cn["id"], 1, "abc", True, idempotency_key="r-1")
        self.s.review_repair("reg", "regulator", report["id"], "confirm")
        self.s.transfer_vehicle("dealer", "dealer", v["vin"], "SG", "Wang", idempotency_key="t-1")
        history = self.s.vehicle_history(v["vin"])
        self.assertEqual(self.dealer_cn["id"], history["repairs"][0]["dealer_id"])
        self.assertEqual("confirmed", history["repairs"][0]["status"])
        self.assertEqual("张三", history["repairs"][0]["owner_at_report"])
        self.assertEqual("CN", history["repairs"][0]["country_at_report"])

    def test_next_version_notice_goes_to_new_owner(self):
        v = self.s.register_vehicle("maker", "manufacturer", "LX00004", "X", 2018, "CN", "张三")
        recall = self.make_recall()
        v1 = [n for n in self.s.recall_detail(recall["id"])["notifications"] if n["vehicle_id"] == v["id"]]
        self.assertEqual(("张三", "CN"), (v1[0]["recipient_name"], v1[0]["recipient_country"]))
        self.s.transfer_vehicle("dealer", "dealer", v["vin"], "SG", "Wang", idempotency_key="t-1")
        self.s.change_scope("maker", "manufacturer", recall["id"], {"models": ["X"], "model_years": [2018], "vin_prefixes": ["LX"], "countries": ["CN"]}, recall["revision"])
        detail = self.s.recall_detail(recall["id"])
        v2 = [n for n in detail["notifications"] if n["vehicle_id"] == v["id"] and n["scope_version"] == 2]
        self.assertEqual(("Wang", "SG"), (v2[0]["recipient_name"], v2[0]["recipient_country"]))
        unfinished = self.s.unfinished("reg", "regulator", recall["id"])
        self.assertEqual("Wang", unfinished["vehicles"][0]["owner_name"])

    def test_history_shows_full_chain(self):
        v = self.s.register_vehicle("maker", "manufacturer", "LX00005", "X", 2018, "CN", "张三")
        self.s.transfer_vehicle("dealer", "dealer", v["vin"], "SG", "Wang", idempotency_key="t-1", handover_at="2026-01-01T00:00:00Z")
        self.s.transfer_vehicle("dealer", "dealer", v["vin"], "CN", "李四", idempotency_key="t-2", handover_at="2026-03-01T00:00:00Z")
        history = self.s.vehicle_history(v["vin"])
        self.assertEqual(2, len(history["transfers"]))
        owners = [(o["owner_name"], o["country"]) for o in history["ownership_timeline"]]
        self.assertEqual([("张三", "CN"), ("Wang", "SG"), ("李四", "CN")], owners)
        self.assertEqual("李四", history["vehicle"]["owner_name"])

    def test_handover_rules_reject_bad_requests(self):
        v = self.s.register_vehicle("maker", "manufacturer", "LX00006", "X", 2018, "CN", "张三")
        with self.assertRaises(ApiError):
            self.s.transfer_vehicle("dealer", "dealer", v["vin"], "SG", "Wang")
        with self.assertRaises(ApiError):
            self.s.transfer_vehicle("dealer", "dealer", v["vin"], "CN", "张三", idempotency_key="t-0")
        with self.assertRaises(ApiError):
            self.s.transfer_vehicle("dealer", "dealer", v["vin"], "SG", "Wang", idempotency_key="t-1", handover_at="not-a-date")


if __name__ == "__main__": unittest.main()
