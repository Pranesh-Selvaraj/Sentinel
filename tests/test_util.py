import unittest

from sentinel.util import mask_secrets, parse_interval, resolve_jpath


class JPathTests(unittest.TestCase):
    def test_root(self):
        data = {"a": 1}
        self.assertEqual(resolve_jpath(data, "$"), data)

    def test_simple_field(self):
        self.assertEqual(resolve_jpath({"version": "1.4.2"}, "$.version"), "1.4.2")

    def test_nested_and_array(self):
        data = {"a": {"b": [{"c": 42}]}}
        self.assertEqual(resolve_jpath(data, "$.a.b[0].c"), 42)

    def test_array_root(self):
        self.assertEqual(resolve_jpath([10, 20], "$[1]"), 20)

    def test_bare_path(self):
        self.assertEqual(resolve_jpath({"a": {"b": 1}}, "a.b"), 1)

    def test_missing(self):
        with self.assertRaises(KeyError):
            resolve_jpath({"a": 1}, "$.b")


class IntervalTests(unittest.TestCase):
    def test_units(self):
        self.assertEqual(parse_interval("30s"), 30)
        self.assertEqual(parse_interval("10m"), 600)
        self.assertEqual(parse_interval("1h"), 3600)
        self.assertEqual(parse_interval("1d"), 86400)

    def test_compound(self):
        self.assertEqual(parse_interval("1h30m"), 5400)

    def test_plain_seconds(self):
        self.assertEqual(parse_interval("90"), 90)

    def test_invalid(self):
        for bad in ("", "soon", "0", "-5"):
            with self.assertRaises(ValueError):
                parse_interval(bad)


class MaskTests(unittest.TestCase):
    def test_masks_secrets_keeps_rest(self):
        config = {
            "api_key": "secret-1",
            "name": "My API",
            "headers": {
                "Authorization": "Bearer tok",
                "X-Api-Key": "abc",
                "Accept": "application/json",
                "Ref": "${TOKEN}",  # env references are not secrets
            },
        }
        masked = mask_secrets(config)
        self.assertEqual(masked["api_key"], "***")
        self.assertEqual(masked["name"], "My API")
        self.assertEqual(masked["headers"]["Authorization"], "***")
        self.assertEqual(masked["headers"]["X-Api-Key"], "***")
        self.assertEqual(masked["headers"]["Accept"], "application/json")
        self.assertEqual(masked["headers"]["Ref"], "${TOKEN}")


if __name__ == "__main__":
    unittest.main()
