# openrct2-actiongen

Parses OpenRCT2 C++ source to extract game action signatures into a structured `actions.json`. This IR feeds Jinja2 templates to generate JS plugin handlers and Python Pydantic models.

## Usage

```bash
uv run openrct2-actiongen generate --openrct2-version v0.4.32
```
