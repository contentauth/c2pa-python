import io
import json
import os
from pathlib import Path
import posixpath
import runpy
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from scripts import generate_versioned_api_docs as docs


class VersionedDocsTests(unittest.TestCase):
    def test_version_list_preserves_default_and_order(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "versions.json"
            config.write_text('{"versions": ["v0.38.0", "v0.37.0"]}')
            self.assertEqual(docs.load_versions(config), ["v0.38.0", "v0.37.0"])

    def test_invalid_versions_are_rejected(self):
        invalid = [
            [], ["v0.38.0", "v0.38.0"], ["../../main"], ["--help"],
            ["main"], [38], [None], ["v0.38.0\n"],
        ]
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "versions.json"
            for versions in invalid:
                with self.subTest(versions=versions):
                    config.write_text(json.dumps({"versions": versions}))
                    with self.assertRaises(ValueError):
                        docs.load_versions(config)
            for value in [[], {}, {"versions": "v0.38.0"}]:
                config.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    docs.load_versions(config)

    @patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"})
    @patch.object(docs.requests, "get")
    def test_published_release_is_verified(self, get):
        get.return_value = Mock(
            status_code=200,
            json=Mock(return_value={"tag_name": "v0.38.0", "draft": False}),
        )
        docs.verify_release("v0.38.0")
        get.assert_called_once_with(
            f"{docs.RELEASES_URL}/v0.38.0",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": "Bearer test-token",
            },
            timeout=30, allow_redirects=False,
        )

    @patch.object(docs.requests, "get")
    def test_unpublished_or_mismatched_release_fails(self, get):
        for release in [
            {"tag_name": "v0.38.0", "draft": True},
            {"tag_name": "v0.37.0", "draft": False},
            {"tag_name": "v0.38.0"}, [],
        ]:
            with self.subTest(release=release):
                get.return_value = Mock(status_code=200, json=Mock(return_value=release))
                with self.assertRaises(ValueError):
                    docs.verify_release("v0.38.0")
        get.return_value = Mock(status_code=404)
        with self.assertRaisesRegex(RuntimeError, "HTTP 404"):
            docs.verify_release("v0.38.0")

    def make_archive(self, filename, mode=stat.S_IFREG):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("src/", b"")
            archive.writestr("src/c2pa/", b"")
            entry = zipfile.ZipInfo(filename)
            entry.external_attr = mode << 16
            archive.writestr(entry, b"TAGGED_SOURCE = True\n")
        return buffer.getvalue()

    @patch.object(docs.subprocess, "run")
    def test_tagged_sources_are_exported_without_running_release_code(self, run):
        run.side_effect = [
            subprocess.CompletedProcess([], 0, stdout="a" * 40 + "\n"),
            subprocess.CompletedProcess([], 0, stdout=self.make_archive("src/c2pa/api.py")),
        ]
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            docs.export_sources(docs.ROOT, "v0.37.0", destination)
            self.assertEqual(
                (destination / "src/c2pa/api.py").read_text(), "TAGGED_SOURCE = True\n"
            )
        self.assertEqual(
            run.call_args_list[0].args[0],
            ["git", "rev-parse", "--verify", "refs/tags/v0.37.0^{commit}"],
        )
        self.assertEqual(run.call_args_list[1].args[0][0:3], ["git", "archive", "--format=zip"])

    @patch.object(docs.subprocess, "run")
    def test_unsafe_or_empty_source_archives_fail(self, run):
        cases = [
            ("src/c2pa/../../escape.py", stat.S_IFREG),
            ("/src/c2pa/api.py", stat.S_IFREG),
            ("other/api.py", stat.S_IFREG),
            ("src/c2pa/..\\escape.py", stat.S_IFREG),
            ("src/c2pa/C:/escape.py", stat.S_IFREG),
            ("src/c2pa/api.py", stat.S_IFLNK),
            ("src/c2pa/README.md", stat.S_IFREG),
        ]
        with tempfile.TemporaryDirectory() as directory:
            for filename, mode in cases:
                with self.subTest(filename=filename, mode=mode):
                    run.side_effect = [
                        subprocess.CompletedProcess([], 0, stdout="a" * 40),
                        subprocess.CompletedProcess(
                            [], 0, stdout=self.make_archive(filename, mode)
                        ),
                    ]
                    with self.assertRaises(ValueError):
                        docs.export_sources(docs.ROOT, "v0.38.0", Path(directory))

    def test_switcher_links_resolve_from_root_and_nested_version_pages(self):
        versions = ["v0.38.0", "v0.37.0"]
        for prefix in ["", "versions/v0.38.0", "versions/v0.37.0"]:
            with self.subTest(prefix=prefix), patch.dict(
                os.environ,
                {
                    "C2PA_DOCS_TAG": "v0.38.0",
                    "C2PA_DOCS_VERSIONS": json.dumps(versions),
                    "C2PA_DOCS_PREFIX": prefix,
                },
            ):
                config = runpy.run_path(str(docs.ROOT / "api-docs/conf.py"))
                for page in ["index", "api/c2pa/index", "api/c2pa/c2pa/index"]:
                    context = {}
                    config["_add_version_selector"](None, page, None, context, None)
                    parent = posixpath.dirname(posixpath.join(prefix, page + ".html"))
                    for item in context["docs_versions"]:
                        self.assertEqual(
                            posixpath.normpath(posixpath.join(parent, item["url"])),
                            f"versions/{item['tag']}/index.html",
                        )

    @patch.dict(os.environ, {}, clear=True)
    def test_working_tree_build_has_no_version_switcher(self):
        config = runpy.run_path(str(docs.ROOT / "api-docs/conf.py"))
        app = Mock()
        config["setup"](app)
        self.assertEqual(app.connect.call_count, 1)
        app.add_js_file.assert_not_called()

    @patch.object(docs, "verify_release")
    @patch.object(docs, "export_sources")
    @patch.object(docs.subprocess, "run")
    def test_site_build_preserves_default_and_cleans_temporary_builds(self, run, export, verify):
        def build(*args, cwd, env, **kwargs):
            html = cwd / "api-docs/_build/html"
            html.mkdir(parents=True)
            (html / "index.html").write_text(
                f"{env['C2PA_DOCS_TAG']}:{env['C2PA_DOCS_PREFIX']}"
            )

        run.side_effect = build
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "api-docs").mkdir()
            (root / "api-docs/versions.json").write_text(
                '{"versions": ["v0.38.0", "v0.37.0"]}'
            )
            (root / "scripts").mkdir()
            (root / "scripts/generate_api_docs.py").touch()
            with patch.object(docs, "ROOT", root):
                site = docs.build_site()
            self.assertEqual((site / "index.html").read_text(), "v0.38.0:")
            for tag in ["v0.38.0", "v0.37.0"]:
                self.assertEqual(
                    (site / "versions" / tag / "index.html").read_text(),
                    f"{tag}:versions/{tag}",
                )
            self.assertTrue((site / ".nojekyll").is_file())
            self.assertEqual(list((root / "api-docs/_build").iterdir()), [site])
            self.assertFalse((root / "api-docs/api").exists())
        self.assertEqual(verify.call_count, 2)
        self.assertEqual(export.call_count, 2)
        self.assertEqual(run.call_count, 3)

    @patch.object(docs, "verify_release")
    @patch.object(docs, "export_sources")
    @patch.object(docs.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "sphinx"))
    def test_failed_build_leaves_previous_site_intact(self, run, export, verify):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "api-docs/_build/versioned"
            site.mkdir(parents=True)
            (site / "index.html").write_text("previous site")
            (root / "api-docs/versions.json").write_text('{"versions": ["v0.38.0"]}')
            (root / "scripts").mkdir()
            (root / "scripts/generate_api_docs.py").touch()
            with patch.object(docs, "ROOT", root):
                with self.assertRaises(subprocess.CalledProcessError):
                    docs.build_site()
            self.assertEqual((site / "index.html").read_text(), "previous site")
            self.assertEqual(list((root / "api-docs/_build").iterdir()), [site])


if __name__ == "__main__":
    unittest.main()
