import unittest

from sentinel.versions import compare, parse_version


class ParseTests(unittest.TestCase):
    def test_basic(self):
        v = parse_version("1.2.3")
        self.assertEqual(v.core, (1, 2, 3))
        self.assertIsNone(v.pre)

    def test_leading_v(self):
        v = parse_version("v1.2.3")
        self.assertEqual(v.core, (1, 2, 3))
        self.assertEqual(v.raw, "v1.2.3")

    def test_prerelease(self):
        v = parse_version("1.2.3-beta.1")
        self.assertEqual(v.core, (1, 2, 3))
        self.assertEqual(v.pre, ("beta", 1))
        self.assertTrue(v.is_prerelease)

    def test_build_metadata_ignored(self):
        self.assertEqual(parse_version("1.2.3+build7").core, (1, 2, 3))

    def test_not_version_like(self):
        self.assertIsNone(parse_version("abc"))
        self.assertIsNone(parse_version(""))
        self.assertIsNone(parse_version(None))
        self.assertIsNone(parse_version("!!!"))
        self.assertIsNone(parse_version("release"))


class CompareTests(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(compare("1.2.3", "1.2.4"), -1)
        self.assertEqual(compare("1.2.4", "1.2.3"), 1)
        self.assertEqual(compare("1.2.3", "1.2.3"), 0)

    def test_numeric_not_lexicographic(self):
        self.assertEqual(compare("1.102.0", "1.103.0"), -1)
        self.assertEqual(compare("2024.1.2", "2024.1.10"), -1)
        self.assertEqual(compare("1.9", "1.10"), -1)

    def test_leading_v(self):
        self.assertEqual(compare("v1.4.0", "v1.5.0"), -1)

    def test_padded_core(self):
        self.assertEqual(compare("1.0", "1.0.0"), 0)
        self.assertEqual(compare("1.2", "1.2.1"), -1)
        self.assertEqual(compare("1.2.3.4", "1.2.3"), 1)

    def test_prerelease_ordering(self):
        self.assertEqual(compare("1.0.0-beta", "1.0.0"), -1)
        self.assertEqual(compare("1.0.0", "1.0.0-beta"), 1)
        self.assertEqual(compare("1.0.0-alpha", "1.0.0-beta"), -1)
        self.assertEqual(compare("1.0.0-rc.1", "1.0.0-rc.2"), -1)

    def test_python_versions(self):
        self.assertEqual(compare("3.13.7", "3.13.8"), -1)
        self.assertEqual(compare("3.13.7", "3.14.0"), -1)

    def test_unparseable_falls_back_to_none(self):
        self.assertIsNone(compare("1.2.3", "abc"))
        self.assertIsNone(compare("abc", "def"))


if __name__ == "__main__":
    unittest.main()
