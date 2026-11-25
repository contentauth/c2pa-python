import base64
import copy
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from scripts.docs_versions import promote, validate_manifest
from scripts import promote_docs_release as writer


def selection():
    return {
        "versions": ["v1.10.2", "v1.9.4"],
        "retiredLines": ["0.38"],
        "aliases": {"v1.10.2": "1.10", "v1.9.4": "1.9", "v1.9.0": "1.9"},
    }


class DocsVersionTests(unittest.TestCase):
    def test_patch_promotion_is_idempotent_and_preserves_aliases(self):
        original = selection()
        updated = promote(original, "v1.9.5")
        self.assertEqual(updated["versions"], ["v1.10.2", "v1.9.5"])
        self.assertEqual(updated["aliases"]["v1.9.4"], "1.9")
        self.assertEqual(updated["aliases"]["v1.9.5"], "1.9")
        self.assertEqual(promote(updated, "v1.9.5"), updated)
        self.assertEqual(promote(updated, "v1.9.3"), updated)
        self.assertEqual(original, selection())

    def test_new_lines_sort_numerically_without_resurrecting_retired_lines(self):
        self.assertEqual(promote(selection(), "v0.38.99"), selection())
        self.assertEqual(
            promote(selection(), "v2.0.0")["versions"],
            ["v2.0.0", "v1.10.2", "v1.9.4"],
        )
        self.assertEqual(promote(selection(), "v1.8.9"), selection())
        retired_future = selection()
        retired_future["retiredLines"].append("3.0")
        self.assertEqual(promote(retired_future, "v2.0.0"), retired_future)

    def test_invalid_manifests_and_release_tags_fail(self):
        bad = []
        for versions in [
            [], ["v1.9.4", "v1.10.2"], ["v1.10.2", "v1.10.1"],
            ["v1.0.0-rc.1"], ["v01.0.0"], ["1.0.0"], [None],
        ]:
            config = selection()
            config["versions"] = versions
            bad.append(config)
        for field, value in [
            ("retiredLines", ["1.10"]), ("retiredLines", ["0.38", "0.38"]),
            ("retiredLines", ["v0.38"]), ("retiredLines", "0.38"),
            ("aliases", []), ("aliases", {"../escape": "1.9"}),
            ("aliases", {"v1.9.4": "1.10"}), ("aliases", {"v0.38.0": "0.38"}),
            ("aliases", {"v1.9.5": "1.9"}), ("aliases", {}),
        ]:
            config = selection()
            config[field] = value
            bad.append(config)
        for config in bad:
            with self.subTest(config=config), self.assertRaises(ValueError):
                validate_manifest(config)
        for tag in ["v2.0.0-rc.1", "v2.0.0+build", "../main"]:
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                promote(selection(), tag)

    @patch.object(writer, "api")
    @patch.object(writer.time, "sleep")
    def test_conflict_recomputes_from_live_manifest_and_only_writes_allowlisted_file(self, sleep, api):
        concurrent = promote(selection(), "v2.0.0")

        def encoded(config, sha):
            return {"content": base64.b64encode(json.dumps(config).encode()).decode(), "sha": sha}

        conflict = HTTPError("url", 409, "conflict", {}, None)
        self.addCleanup(conflict.close)
        api.side_effect = [
            {"id": 123, "tag_name": "v1.9.5", "draft": False,
             "prerelease": False, "published_at": "2026-01-01"},
            [],
            encoded(selection(), "first"),
            conflict,
            encoded(concurrent, "second"),
            {"commit": {"sha": "committed"}},
        ]
        writer.promote_release("v1.9.5", "123", "read", "write")
        writes = [call for call in api.call_args_list if call.args[0] == "PUT"]
        self.assertEqual(len(writes), 2)
        for call in writes:
            self.assertEqual(call.args[1:3], ("contents/api-docs/versions.json", "write"))
        payload = writes[-1].args[3]
        self.assertEqual(payload["sha"], "second")
        self.assertEqual(payload["branch"], "main")
        updated = json.loads(base64.b64decode(payload["content"]))
        self.assertEqual(updated["versions"], ["v2.0.0", "v1.10.2", "v1.9.5"])

    @patch.object(writer, "api")
    def test_release_metadata_must_match_event_before_any_manifest_access(self, api):
        valid = {"id": 123, "tag_name": "v1.9.5", "draft": False,
                 "prerelease": False, "published_at": "2026-01-01"}
        for key, value in [
            ("id", 456), ("tag_name", "v1.9.4"), ("draft", True),
            ("prerelease", True), ("published_at", None),
        ]:
            release = copy.deepcopy(valid)
            release[key] = value
            api.reset_mock()
            api.return_value = release
            with self.subTest(key=key), self.assertRaises(ValueError):
                writer.promote_release("v1.9.5", "123", "read", "write")
            self.assertEqual(api.call_count, 1)

    @patch.object(writer, "api")
    @patch.object(writer.time, "sleep")
    def test_retries_are_bounded_and_permission_errors_fail_immediately(self, sleep, api):
        release = {"id": 123, "tag_name": "v1.9.5", "draft": False,
                   "prerelease": False, "published_at": "2026-01-01"}
        current = {"content": base64.b64encode(json.dumps(selection()).encode()).decode(), "sha": "sha"}
        for code, attempts in [(403, 1), (409, 5)]:
            api.reset_mock()
            error = HTTPError("url", code, "failure", {}, None)
            self.addCleanup(error.close)
            api.side_effect = [release, []] + [item for _ in range(attempts) for item in (current, error)]
            with self.subTest(code=code), self.assertRaises(HTTPError):
                writer.promote_release("v1.9.5", "123", "read", "write")
            self.assertEqual(api.call_count, 2 + attempts * 2)

    @patch.object(writer, "api")
    def test_release_burst_reconciliation_preserves_selection_and_ignores_historical_lines(self, api):
        release = {"id": 123, "tag_name": "v1.9.5", "draft": False,
                   "prerelease": False, "published_at": "2026-01-01"}
        releases = [
            dict(release, tag_name=tag) for tag in
            ["v1.9.6", "v2.0.0", "v2.0.1", "v1.8.7", "v0.38.99", "v3.0.0-rc.1"]
        ]
        releases.append(dict(release, tag_name="v4.0.0", prerelease=True))
        current = {"content": base64.b64encode(json.dumps(selection()).encode()).decode(), "sha": "sha"}
        api.side_effect = [release, releases, current, {}]
        writer.promote_release("v1.9.5", "123", "read", "write")
        payload = api.call_args_list[-1].args[3]
        updated = json.loads(base64.b64decode(payload["content"]))
        self.assertEqual(updated["versions"], ["v2.0.1", "v1.10.2", "v1.9.6"])
        self.assertNotIn("v1.8.7", updated["aliases"])

    @patch.object(writer, "api")
    def test_unchanged_reconciliation_never_writes(self, api):
        release = {"id": 123, "tag_name": "v1.9.4", "draft": False,
                   "prerelease": False, "published_at": "2026-01-01"}
        current = {"content": base64.b64encode(json.dumps(selection()).encode()).decode(), "sha": "sha"}
        api.side_effect = [release, [], current]
        writer.promote_release("v1.9.4", "123", "read", "write")
        self.assertEqual(api.call_count, 3)

    @patch.object(writer, "api")
    def test_release_reconciliation_reads_all_pages(self, api):
        release = {"id": 123, "tag_name": "v1.9.4", "draft": False,
                   "prerelease": False, "published_at": "2026-01-01"}
        current = {"content": base64.b64encode(json.dumps(selection()).encode()).decode(), "sha": "sha"}
        api.side_effect = [
            release, [release] * 100, [dict(release, tag_name="v2.0.0")], current, {},
        ]
        writer.promote_release("v1.9.4", "123", "read", "write")
        self.assertEqual(api.call_args_list[2].args[1], "releases?per_page=100&page=2")
        updated = json.loads(base64.b64decode(api.call_args_list[-1].args[3]["content"]))
        self.assertEqual(updated["versions"][0], "v2.0.0")

    @patch.object(writer, "api")
    @patch.object(writer.time, "sleep")
    def test_concurrent_human_retirement_is_not_reversed(self, sleep, api):
        release = {"id": 123, "tag_name": "v1.9.5", "draft": False,
                   "prerelease": False, "published_at": "2026-01-01"}
        retired = selection()
        retired["versions"].remove("v1.9.4")
        retired["retiredLines"].append("1.9")
        retired["aliases"] = {"v1.10.2": "1.10"}

        def encoded(config):
            return {"content": base64.b64encode(json.dumps(config).encode()).decode(), "sha": "sha"}

        conflict = HTTPError("url", 409, "conflict", {}, None)
        self.addCleanup(conflict.close)
        api.side_effect = [release, [], encoded(selection()), conflict, encoded(retired)]
        writer.promote_release("v1.9.5", "123", "read", "write")
        self.assertEqual(sum(call.args[0] == "PUT" for call in api.call_args_list), 1)


if __name__ == "__main__":
    unittest.main()
