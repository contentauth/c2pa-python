import os
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

# Avoid executing package imports during docs build
autodoc_typehints = "description"

# Napoleon (Google/Numpy docstring support)
napoleon_google_docstring = True
napoleon_numpy_docstring = False


