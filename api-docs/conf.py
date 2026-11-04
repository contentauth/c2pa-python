import os
import json
import posixpath
from pathlib import Path

# -- Project information -----------------------------------------------------

project = "c2pa-python"
author = "Content Authenticity Initiative (CAI)"

# -- General configuration ---------------------------------------------------

extensions = [
    "myst_parser",
    "autoapi.extension",
    "sphinx.ext.napoleon",
]

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "fieldlist",
    "strikethrough",
    "tasklist",
    "attrs_block",
    "attrs_inline",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- AutoAPI configuration ---------------------------------------------------

project_root = Path(__file__).resolve().parents[1]
autoapi_type = "python"
# Allow overriding the source path used by AutoAPI (for preprocessing)
autoapi_dirs = [
    os.environ.get(
        "C2PA_DOCS_SRC",
        str(project_root / "src" / "c2pa"),
    )
]
autoapi_root = "api"
autoapi_keep_files = True
autoapi_add_toctree_entry = True
autoapi_options = [
    "members",
    "undoc-members",
    "show-inheritance",
    "show-module-summary",
    "imported-members",
]

# -- Options for HTML output -------------------------------------------------

html_theme = "furo"
html_static_path = ["_static"]

docs_versions = json.loads(os.environ.get("C2PA_DOCS_VERSIONS", "[]"))
docs_tag = os.environ.get("C2PA_DOCS_TAG", "")
docs_prefix = os.environ.get("C2PA_DOCS_PREFIX", "")
if docs_versions:
    release = docs_tag
    version = docs_tag
    html_sidebars = {
        "**": [
            "sidebar/brand.html",
            "version-selector.html",
            "sidebar/search.html",
            "sidebar/scroll-start.html",
            "sidebar/navigation.html",
            "sidebar/scroll-end.html",
            "sidebar/variant-selector.html",
        ]
    }

# Avoid executing package imports during docs build
autodoc_typehints = "description"

# Napoleon (Google/Numpy docstring support)
napoleon_google_docstring = True
napoleon_numpy_docstring = False

# -- Global HTML meta tags ---------------------------------------------------

# Inject extra <meta> tags into the <head> of every generated HTML page,
# regardless of source format (.rst, .md, AutoAPI-generated, etc.).
html_meta_tags = [
    {"name": "algolia-site-verification", "content": "EA363696C40197CA"},
]


def _add_html_meta_tags(app, pagename, templatename, context, doctree):
    rendered = "".join(
        "<meta "
        + " ".join(f'{k}="{v}"' for k, v in tag.items())
        + " />\n"
        for tag in html_meta_tags
    )
    context["metatags"] = context.get("metatags", "") + rendered


def _add_version_selector(app, pagename, templatename, context, doctree):
    current_directory = posixpath.dirname(
        posixpath.join(docs_prefix, pagename + ".html")
    ) or "."
    context["docs_tag"] = docs_tag
    context["docs_versions"] = [
        {
            "tag": tag,
            "url": posixpath.relpath(f"versions/{tag}/index.html", current_directory),
        }
        for tag in docs_versions
    ]


def setup(app):
    app.connect("html-page-context", _add_html_meta_tags)
    if docs_versions:
        app.connect("html-page-context", _add_version_selector)
        app.add_js_file("version-selector.js")
    return {"parallel_read_safe": True, "parallel_write_safe": True}
