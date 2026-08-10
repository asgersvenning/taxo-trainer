---
trigger: always_on
description: Mandatory uv package management standards, execution rules, and Python docstring conventions
globs: ["**/*.py", "pyproject.toml"]
---

# AGENT RULESET: Python & Package Management (`.agents/rules/uv.md`)

Always use `uv` for Python and package management. Never try to run Python files or scripts except via `uv run`.

Use best-practices and standards for Python development in the style of a modern Python developer using `uv` standards.

Docstrings should use Google style.

Create sensible and minimal unit-tests where possible using pytest, and include a CI pipeline via Github Actions.