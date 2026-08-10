import unittest

from sentinel.errors import FetchHTTP, FetchRateLimited
from sentinel.httpclient import Transport
from sentinel.models import Observation, Source
from sentinel.monitors.github import GitHubMonitor, github_headers
from tests.fakes import FakeTransport, make_json_response

API = "https://api.github.com"


def source(config: dict) -> Source:
    return Source(id=1, kind="github", name="VS Code", config=config)


class GitHubFetchTests(unittest.TestCase):
    def setUp(self):
        self.transport = FakeTransport()

    def test_release_fetch(self):
        self.transport.route(
            f"{API}/repos/microsoft/vscode/releases/latest",
            make_json_response(200, {
                "tag_name": "1.103.0",
                "name": "1.103.0",
                "published_at": "2026-08-09T12:00:00Z",
                "html_url": "https://github.com/microsoft/vscode/releases/tag/1.103.0",
                "prerelease": False,
                "assets": [{"name": "code.deb", "size": 123, "browser_download_url": "https://x/code.deb"}],
            }),
        )
        obs = GitHubMonitor().fetch(source({"repo": "microsoft/vscode", "monitor": "release"}), self.transport)
        self.assertEqual(obs.value, "1.103.0")
        self.assertEqual(obs.state["tag"], "1.103.0")
        self.assertEqual(obs.state["assets"][0]["name"], "code.deb")
        self.assertEqual(obs.state["url"], "https://github.com/microsoft/vscode/releases/tag/1.103.0")

    def test_release_404_falls_back_to_releases_list(self):
        self.transport.route(
            f"{API}/repos/microsoft/vscode/releases/latest",
            FetchHTTP(404, b"", API),
        )
        self.transport.route(
            f"{API}/repos/microsoft/vscode/releases?per_page=1",
            make_json_response(200, [{"tag_name": "v1.2.0", "name": "v1.2.0"}]),
        )
        obs = GitHubMonitor().fetch(source({"repo": "microsoft/vscode", "monitor": "release"}), self.transport)
        self.assertEqual(obs.value, "v1.2.0")

    def test_no_releases(self):
        self.transport.route(
            f"{API}/repos/microsoft/vscode/releases?per_page=1", make_json_response(200, [])
        )
        self.transport.route(
            f"{API}/repos/microsoft/vscode/releases/latest", FetchHTTP(404, b"", API)
        )
        obs = GitHubMonitor().fetch(source({"repo": "microsoft/vscode", "monitor": "release"}), self.transport)
        self.assertIsNone(obs.value)

    def test_tags_fetch(self):
        self.transport.route(
            f"{API}/repos/microsoft/vscode/tags?per_page=1",
            make_json_response(200, [{"name": "1.103.0", "commit": {"sha": "abc123"}}]),
        )
        obs = GitHubMonitor().fetch(source({"repo": "microsoft/vscode", "monitor": "tags"}), self.transport)
        self.assertEqual(obs.value, "1.103.0")
        self.assertEqual(obs.state["sha"], "abc123")

    def test_commits_fetch(self):
        self.transport.route(
            f"{API}/repos/microsoft/vscode/commits?per_page=1",
            make_json_response(200, [{
                "sha": "deadbeef1234567",
                "html_url": "https://github.com/microsoft/vscode/commit/deadbeef",
                "commit": {"message": "Fix the thing\n\nDetails",
                           "author": {"name": "Ada", "date": "2026-08-09T10:00:00Z"}},
            }]),
        )
        obs = GitHubMonitor().fetch(source({"repo": "microsoft/vscode", "monitor": "commits"}), self.transport)
        self.assertEqual(obs.value, "deadbeef1234567")
        self.assertEqual(obs.state["short_sha"], "deadbeef")
        self.assertEqual(obs.state["message"], "Fix the thing")

    def test_invalid_repo_config(self):
        with self.assertRaises(Exception):
            GitHubMonitor().fetch(source({"repo": "not-a-repo"}), self.transport)

    def test_auth_header_sent(self):
        transport = Transport(github_token="ghp_test")
        fake = FakeTransport({
            f"{API}/repos/microsoft/vscode/releases/latest": make_json_response(200, {"tag_name": "1.0.0"}),
        })
        headers = github_headers(transport)
        fake.get(f"{API}/repos/microsoft/vscode/releases/latest", headers)
        self.assertEqual(fake.calls[0][1]["Authorization"], "Bearer ghp_test")

    def test_rate_limit_propagates(self):
        self.transport.route(
            f"{API}/repos/microsoft/vscode/releases/latest",
            FetchRateLimited(reset_epoch=1800000000),
        )
        with self.assertRaises(FetchRateLimited):
            GitHubMonitor().fetch(source({"repo": "microsoft/vscode"}), self.transport)


class GitHubDiffTests(unittest.TestCase):
    def setUp(self):
        self.monitor = GitHubMonitor()

    def test_new_release(self):
        prev = Observation("1.102.0", {"tag": "1.102.0"})
        cur = Observation("1.103.0", {"tag": "1.103.0"})
        changes = self.monitor.diff(source({"repo": "microsoft/vscode", "monitor": "release"}), prev, cur)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].kind, "version")
        self.assertEqual(changes[0].description, "New release detected")

    def test_same_release_no_change(self):
        prev = Observation("1.103.0", {"tag": "1.103.0"})
        cur = Observation("1.103.0", {"tag": "1.103.0"})
        self.assertEqual(self.monitor.diff(source({"repo": "microsoft/vscode"}), prev, cur), [])

    def test_rollback_is_warn(self):
        prev = Observation("1.103.0", {"tag": "1.103.0"})
        cur = Observation("1.102.0", {"tag": "1.102.0"})
        changes = self.monitor.diff(source({"repo": "microsoft/vscode"}), prev, cur)
        self.assertEqual(changes[0].severity, "warn")
        self.assertEqual(changes[0].description, "Release rolled back")

    def test_new_commit(self):
        prev = Observation("aaaaaaaaaaa", {"short_sha": "aaaaaaa"})
        cur = Observation("bbbbbbbbbbb", {"short_sha": "bbbbbbb", "message": "Add feature"})
        changes = self.monitor.diff(source({"repo": "microsoft/vscode", "monitor": "commits"}), prev, cur)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].kind, "commit")
        self.assertIn("Add feature", changes[0].description)

    def test_first_observation_is_baseline(self):
        cur = Observation("1.103.0", {"tag": "1.103.0"})
        self.assertEqual(self.monitor.diff(source({"repo": "microsoft/vscode"}), None, cur), [])


if __name__ == "__main__":
    unittest.main()
