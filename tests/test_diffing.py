import unittest

from sentinel.diffing import ChangeDetector, render_change


class VersionDiffTests(unittest.TestCase):
    def test_new_release(self):
        c = ChangeDetector.version("1.102.0", "1.103.0", label="release")
        self.assertIsNotNone(c)
        self.assertEqual(c.kind, "version")
        self.assertEqual(c.previous, "1.102.0")
        self.assertEqual(c.current, "1.103.0")
        self.assertEqual(c.description, "New release detected")
        self.assertEqual(c.severity, "info")

    def test_rollback(self):
        c = ChangeDetector.version("1.103.0", "1.102.0", label="release")
        self.assertEqual(c.description, "Release rolled back")
        self.assertEqual(c.severity, "warn")

    def test_no_change(self):
        self.assertIsNone(ChangeDetector.version("1.2.3", "1.2.3"))

    def test_unparseable(self):
        c = ChangeDetector.version("abc", "def", label="release")
        self.assertEqual(c.description, "Release changed")
        self.assertEqual(c.severity, "info")


class StatusDiffTests(unittest.TestCase):
    def test_ok_to_404(self):
        c = ChangeDetector.status(200, 404)
        self.assertEqual(c.kind, "status")
        self.assertEqual(c.previous, "200")
        self.assertEqual(c.current, "404")
        self.assertEqual(c.severity, "warn")

    def test_recovery(self):
        c = ChangeDetector.status(404, 200)
        self.assertEqual(c.severity, "info")

    def test_no_change(self):
        self.assertIsNone(ChangeDetector.status(200, 200))


class JsonDiffTests(unittest.TestCase):
    def test_field_changed(self):
        c = ChangeDetector.json_field("$.version", "1.4.2", "1.5.0")
        self.assertEqual(c.kind, "json")
        self.assertEqual(c.data["field"], "$.version")
        self.assertEqual(c.previous, "1.4.2")

    def test_field_appeared(self):
        c = ChangeDetector.json_field("$.version", None, "1.5.0")
        self.assertEqual(c.previous, "(none)")

    def test_no_change(self):
        self.assertIsNone(ChangeDetector.json_field("$.version", "1.4.2", "1.4.2"))


class ContentDiffTests(unittest.TestCase):
    def test_hash_changed(self):
        c = ChangeDetector.content("a" * 64, "b" * 64)
        self.assertEqual(c.kind, "content")
        self.assertEqual(c.previous, "a" * 8)
        self.assertEqual(c.current, "b" * 8)
        self.assertEqual(c.description, "Page content changed")

    def test_no_change(self):
        self.assertIsNone(ChangeDetector.content("a" * 64, "a" * 64))


class ScalarDiffTests(unittest.TestCase):
    def test_price_drop(self):
        c = ChangeDetector.scalar("Price", "€99", "€79", unit="€")
        self.assertEqual(c.description, "Price dropped by €20")

    def test_increase(self):
        c = ChangeDetector.scalar("Price", "10", "15")
        self.assertEqual(c.description, "Price increased by 5")

    def test_no_change(self):
        self.assertIsNone(ChangeDetector.scalar("Price", "€99", "€99"))


class AvailabilityDiffTests(unittest.TestCase):
    def test_goes_offline(self):
        c = ChangeDetector.availability(True, False, error="Connection timeout")
        self.assertEqual(c.previous, "online")
        self.assertEqual(c.current, "offline")
        self.assertEqual(c.severity, "warn")
        self.assertIn("Connection timeout", c.description)

    def test_recovers(self):
        c = ChangeDetector.availability(False, True)
        self.assertEqual(c.description, "Source reachable again")

    def test_no_change(self):
        self.assertIsNone(ChangeDetector.availability(True, True))


class RenderTests(unittest.TestCase):
    def test_version_render(self):
        c = ChangeDetector.version("1.102.0", "1.103.0", label="release")
        self.assertEqual(render_change(c), ["  1.102.0 → 1.103.0", "  New release detected"])

    def test_status_render(self):
        c = ChangeDetector.status(200, 404)
        self.assertEqual(render_change(c), ["  HTTP 200 → 404"])

    def test_json_render(self):
        c = ChangeDetector.json_field("$.version", "1.4.2", "1.5.0")
        self.assertEqual(render_change(c), ["  $.version:", "  1.4.2 → 1.5.0"])


if __name__ == "__main__":
    unittest.main()
