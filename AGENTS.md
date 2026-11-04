# Agent Guidelines

Before working in this repository, read [AI_WORKFLOW.md](AI_WORKFLOW.md) and follow its guidance.

- For library behavior or implementation changes, read all of Part 1: Using the library and Part 2: Developing c2pa-python. For documentation, test, or tooling changes, read Part 2 and relevant Part 1 sections.
- For changes to the binding layer, follow the binding-layer rules and decision tree in AI_WORKFLOW.md.
- Before finishing code changes, run `make test` and `make check-format`. If prerequisites prevent a check from running, report the blocker and the results of checks that did run.
- Bump the Python package version only for release-ready changes, and ask the user for confirmation before changing it.
