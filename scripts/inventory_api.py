"""Inventory the existing FastAPI service from its OpenAPI document.

Milestone 1, part 2. Lists every endpoint, its parameters, its request body and
its response shape, so we can decide what is worth wrapping as an agent tool.

Usage:
    python scripts/inventory_api.py [--url https://svc.onrender.com] [--out reports/api_inventory.md]

Reads EXISTING_API_BASE_URL and EXISTING_API_BEARER_TOKEN from .env.
Uses only the standard library — no HTTP dependency for a one-shot script.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

CANDIDATE_PATHS = ("/openapi.json", "/api/openapi.json", "/v1/openapi.json", "/docs/openapi.json")


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def fetch(url: str, token: str | None) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def resolve(ref: str, spec: dict) -> dict:
    """Resolve a local $ref like '#/components/schemas/Foo'."""
    node: object = spec
    for part in ref.lstrip("#/").split("/"):
        if not isinstance(node, dict) or part not in node:
            return {}
        node = node[part]
    return node if isinstance(node, dict) else {}


def type_of(schema: dict, spec: dict, depth: int = 0) -> str:
    """Render a schema as a compact one-line type description."""
    if not schema or depth > 4:
        return "any"
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        return name
    if "anyOf" in schema or "oneOf" in schema:
        opts = schema.get("anyOf") or schema.get("oneOf")
        parts = [type_of(o, spec, depth + 1) for o in opts]
        parts = [p for p in parts if p != "null"] or parts
        return " | ".join(dict.fromkeys(parts))
    if "enum" in schema:
        return "enum{" + ", ".join(json.dumps(v) for v in schema["enum"]) + "}"
    t = schema.get("type")
    if t == "array":
        return f"array<{type_of(schema.get('items', {}), spec, depth + 1)}>"
    if t == "object":
        props = schema.get("properties") or {}
        if props:
            inner = ", ".join(f"{k}: {type_of(v, spec, depth + 1)}" for k, v in list(props.items())[:12])
            return "{" + inner + "}"
        return "object"
    return t or "any"


def describe_schema_block(name: str, schema: dict, spec: dict) -> list[str]:
    """Expand a named component schema into a small field table."""
    out = [f"**`{name}`**", "", "| field | type | required |", "| --- | --- | --- |"]
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    if not props:
        return [f"**`{name}`**: {type_of(schema, spec)}", ""]
    for field, sub in props.items():
        out.append(f"| `{field}` | {type_of(sub, spec)} | {'yes' if field in required else ''} |")
    out.append("")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=None, help="Base URL or a direct openapi.json URL")
    ap.add_argument("--out", default="reports/api_inventory.md")
    args = ap.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    base = (args.url or os.environ.get("EXISTING_API_BASE_URL") or "").rstrip("/")
    token = os.environ.get("EXISTING_API_BEARER_TOKEN") or None

    if not base:
        print(
            "ERROR: no service URL. Pass --url or set EXISTING_API_BASE_URL in .env "
            "(see .env.example).",
            file=sys.stderr,
        )
        return 2

    urls = [base] if base.endswith(".json") else [base + p for p in CANDIDATE_PATHS]
    spec: dict | None = None
    errors: list[str] = []
    for url in urls:
        try:
            spec = fetch(url, token)
            source = url
            break
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError) as exc:
            errors.append(f"{url} -> {exc}")
    else:
        print("ERROR: could not fetch an OpenAPI document. Tried:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    assert spec is not None
    lines: list[str] = []

    def w(line: str = "") -> None:
        lines.append(line)
        print(line, flush=True)

    info = spec.get("info", {})
    w(f"# Existing FastAPI service — endpoint inventory")
    w()
    w(f"- Generated: {datetime.now().isoformat(timespec='seconds')}")
    w(f"- Source: `{source}`")
    w(f"- Title: {info.get('title', '?')}  ·  version {info.get('version', '?')}")
    if info.get("description"):
        w(f"- Description: {info['description']}")
    servers = spec.get("servers") or []
    if servers:
        w(f"- Servers: " + ", ".join(f"`{s.get('url')}`" for s in servers))
    w()

    paths = spec.get("paths") or {}
    w(f"## Endpoints ({sum(1 for p in paths.values() for m in p if m.lower() in ('get','post','put','patch','delete'))} operations)")
    w()

    for path, ops in sorted(paths.items()):
        for method, op in ops.items():
            if method.lower() not in ("get", "post", "put", "patch", "delete"):
                continue
            w(f"### `{method.upper()} {path}`")
            w()
            summary = op.get("summary") or op.get("operationId") or ""
            if summary:
                w(f"{summary}")
                w()
            if op.get("description"):
                w(f"{op['description']}")
                w()

            params = op.get("parameters") or []
            if params:
                w("**Parameters**")
                w()
                w("| name | in | type | required | default | description |")
                w("| --- | --- | --- | --- | --- | --- |")
                for p in params:
                    sch = p.get("schema") or {}
                    if "$ref" in sch:
                        sch = resolve(sch["$ref"], spec)
                    default = sch.get("default")
                    w(
                        f"| `{p.get('name')}` | {p.get('in')} | {type_of(sch, spec)} | "
                        f"{'yes' if p.get('required') else ''} | "
                        f"{'' if default is None else f'`{default}`'} | {p.get('description', '')} |"
                    )
                w()

            body = op.get("requestBody")
            if body:
                content = (body.get("content") or {}).get("application/json") or {}
                sch = content.get("schema") or {}
                if "$ref" in sch:
                    name = sch["$ref"].rsplit("/", 1)[-1]
                    w("**Request body**")
                    w()
                    for line in describe_schema_block(name, resolve(sch["$ref"], spec), spec):
                        w(line)
                else:
                    w(f"**Request body**: {type_of(sch, spec)}")
                    w()

            responses = op.get("responses") or {}
            w("**Responses**")
            w()
            w("| status | type | description |")
            w("| --- | --- | --- |")
            for status, resp in sorted(responses.items()):
                content = (resp.get("content") or {}).get("application/json") or {}
                sch = content.get("schema") or {}
                w(f"| {status} | {type_of(sch, spec) if sch else ''} | {resp.get('description', '')} |")
            w()

    schemas = (spec.get("components") or {}).get("schemas") or {}
    if schemas:
        w("## Component schemas")
        w()
        for name, sch in sorted(schemas.items()):
            for line in describe_schema_block(name, sch, spec):
                w(line)

    out_path = REPO_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n\n[written] {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
