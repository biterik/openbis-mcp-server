# openbis-mcp-server

A [Model Context Protocol](https://modelcontextprotocol.io) server that exposes
[openBIS](https://openbis.ch) (via [pyBIS](https://pypi.org/project/PyBIS/))
to LLM-based agents such as Claude.

The agent can browse spaces / projects / experiments / samples / datasets,
inspect the schema (sample types, dataset types, vocabularies, property types),
list and download dataset files, and — if explicitly enabled — create, update,
and delete entities.

## Status

Read-only operation works against a real openBIS instance today (tested
against `openbis.imm.rwth-aachen.de`). Write operations are implemented but
disabled by default; enable them with `OPENBIS_MCP_ALLOW_WRITE=1` once you've
verified the agent's behaviour on a non-production space.

## Tools

| Group   | Tool | Purpose |
|---------|------|---------|
| session | `get_server_info` | URL, server version, MCP server version, write state |
| session | `whoami` | Authenticated user + session active flag |
| browse  | `list_spaces` | All spaces visible to the user |
| browse  | `list_projects` | Filter by space |
| browse  | `list_experiments` | Filter by space / project / type |
| browse  | `list_samples` | Filter by space / project / experiment / type |
| browse  | `list_datasets` | Filter by space / project / experiment / sample / type |
| browse  | `get_entity` | Full metadata for one entity (any kind) |
| search  | `search_samples` | Property-based search with optional type/space restriction |
| search  | `search_datasets` | Same shape, for datasets |
| schema  | `list_sample_types` | All sample (object) types |
| schema  | `list_dataset_types` | All dataset types |
| schema  | `list_experiment_types` | All experiment (collection) types |
| schema  | `list_vocabularies` | Controlled vocabularies |
| schema  | `get_property_types` | Global list, or properties assigned to one type |
| files   | `list_dataset_files` | File listing inside a dataset (no download) |
| files   | `download_dataset_file` | Download one file to a local directory |
| write*  | `create_project` | New project under a space |
| write*  | `create_experiment` | New experiment under a project |
| write*  | `create_sample` | New sample, optionally with parents/properties |
| write*  | `create_dataset` | Upload local files as a new dataset |
| write*  | `update_sample` | Update properties / add or remove parent–child links |
| write*  | `update_dataset` | Update properties |
| write*  | `delete_entity` | Delete by kind+identifier; non-empty `reason` required |
| s3      | `get_s3_status` | S3 configuration status (bucket, region, DMS code) |
| s3†     | `create_s3_linked_dataset` | Upload file to S3; register as LINK-kind dataset |
| s3      | `generate_s3_download_url` | Fresh presigned S3 GET URL for a given object key |

`*` write tools require `OPENBIS_MCP_ALLOW_WRITE=1`. See
[Enabling write access](#enabling-write-access) below.

`†` also requires `OPENBIS_MCP_ALLOW_WRITE=1`.

## Configuration

The server reads connection details from environment variables. Provide credentials
in one of three ways: a personal access token, a file containing one, or
username + password.

| Variable | Required? | Purpose |
|----------|-----------|---------|
| `OPENBIS_URL` | yes | Base URL, e.g. `https://openbis.imm.rwth-aachen.de` |
| `OPENBIS_TOKEN` | one of the three | Personal access token (PAT). Preferred. |
| `OPENBIS_TOKEN_FILE` | credential options | Path to a file holding the raw token (e.g. `~/.pybis/<host>.token`). Used only if `OPENBIS_TOKEN` is empty. |
| `OPENBIS_USERNAME` + `OPENBIS_PASSWORD` | is required | Used only if neither token variable is set. |
| `OPENBIS_VERIFY_CERTIFICATES` | no | Set to `false` for self-signed dev certs. Default `true`. |
| `OPENBIS_MCP_ALLOW_WRITE` | no | Set to `1` to enable create/update/delete tools. Default off. |

### S3 storage configuration

S3 storage support enables storing dataset files in an S3-compatible object
store while only keeping metadata (and a presigned download URL) in openBIS.
This follows the approach of [pybis_aixtended](https://github.com/pyiron/pyiron_rdm/tree/main/pybis_aixtended)
from pyiron/pyiron_rdm.

Install the extra dependencies first:

```bash
pip install -e ".[s3]"
```

Then configure via environment variables **or** an INI config file:

**Environment variables:**

| Variable | Required? | Purpose |
|----------|-----------|---------|
| `S3_ACCESS_KEY` | yes | S3 access key ID |
| `S3_ACCESS_SECRET` | yes | S3 secret access key |
| `S3_BUCKET` | yes | Bucket name |
| `S3_DMS_CODE` | yes | openBIS External Data Management System code (set up by admin) |
| `S3_REGION` | no | AWS region (default: `eu-central-1`) |
| `S3_ENDPOINT_URL` | no | Custom endpoint for non-AWS stores |
| `S3_ENDPOINT_PORT` | no | Optional port suffix for the endpoint |
| `S3_CONFIG_FILE` | no | Path to an INI config file (overrides individual env vars) |

**INI config file** (same format as pybis_aixtended):

```ini
[s3]
s3_region = eu-central-1
s3_endpoint_url = https://s3.example.com
s3_endpoint_port = 443
s3_access_key = AKID...
s3_access_secret = secret
s3_bucket = my-bucket

[openbis]
dms_code = MY_DMS
```

Point to it with `S3_CONFIG_FILE=/path/to/s3_config.ini`.

> **Note:** The S3 DMS must be registered in openBIS by an instance admin
> before datasets can be linked.  `get_s3_status` shows whether the server
> can see it; `create_s3_linked_dataset` requires `OPENBIS_MCP_ALLOW_WRITE=1`.

A template lives in [`.env.example`](.env.example). Never commit a populated
`.env` — `.gitignore` excludes it.

### Setting the variables

**One-shot, in your shell** (the agent will inherit them):

```bash
export OPENBIS_URL=https://openbis.imm.rwth-aachen.de
export OPENBIS_TOKEN=your-token-here
```

**From a token file** (matches pyBIS's own convention — `pybis` saves tokens to
`~/.pybis/<host>.token` after `o.login(..., save_token=True)`):

```bash
export OPENBIS_URL=https://openbis.imm.rwth-aachen.de
export OPENBIS_TOKEN_FILE=~/.pybis/openbis.imm.rwth-aachen.de.token
```

**Inside the MCP client config** — preferred, because the env vars are scoped
to the MCP server process and don't leak into your interactive shell. Example
for Claude Code is shown below; Claude Desktop syntax is similar.

### Getting a personal access token

In the openBIS web UI: **User menu → Personal Access Tokens → Create**. Choose
a generous expiry (e.g. 90 days) and copy the resulting string — it is shown
only once. Place it in `OPENBIS_TOKEN`, or write it to
`~/.pybis/<host>.token` (single line, no quotes) and use `OPENBIS_TOKEN_FILE`.

## Install

Requires Python 3.10+.

```bash
git clone https://github.com/biterik/openbis-mcp-server.git
cd openbis-mcp-server
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

This installs the `openbis-mcp-server` console script.

## Run

Stand-alone (for testing — speaks MCP over stdio, expects an MCP client on the
other end):

```bash
export OPENBIS_URL=https://openbis.imm.rwth-aachen.de
export OPENBIS_TOKEN=...
openbis-mcp-server
```

In normal use you don't run it manually; an MCP client (Claude Code, Claude
Desktop, ...) launches it as a subprocess.

## Register with Claude Code

Claude Code's CLI manages MCP servers in `~/.claude.json` (user scope) or in
the per-project `.mcp.json`. Use the `claude mcp add` command rather than
editing the JSON by hand.

**Read-only registration** (recommended starting point):

```bash
claude mcp add openbis --scope user \
  --env OPENBIS_URL=https://openbis.imm.rwth-aachen.de \
  --env OPENBIS_TOKEN_FILE=$HOME/.pybis/openbis.imm.rwth-aachen.de.token \
  -- /absolute/path/to/.venv/bin/openbis-mcp-server
```

The `--` separates Claude Code's flags from the command Claude Code will
launch. Use the absolute path to the `openbis-mcp-server` executable in your
virtualenv so Claude Code doesn't depend on your shell's `PATH`.

**Verify**:

```bash
claude mcp list
# openbis: /abs/path/.venv/bin/openbis-mcp-server - ✓ Connected
```

Restart Claude Code after registration so it picks up the new server. The
tools then appear under names like `mcp__openbis__list_spaces`,
`mcp__openbis__get_entity`, etc.

### Enabling write access

Write tools (`create_*`, `update_*`, `delete_entity`) raise an error unless
`OPENBIS_MCP_ALLOW_WRITE=1` is set in the server's environment. To enable,
re-register with the extra env var:

```bash
claude mcp remove openbis --scope user
claude mcp add openbis --scope user \
  --env OPENBIS_URL=https://openbis.imm.rwth-aachen.de \
  --env OPENBIS_TOKEN_FILE=$HOME/.pybis/openbis.imm.rwth-aachen.de.token \
  --env OPENBIS_MCP_ALLOW_WRITE=1 \
  -- /absolute/path/to/.venv/bin/openbis-mcp-server
```

Confirm with `mcp__openbis__get_server_info` — the response includes
`"write_enabled": true`. Until you do this, the read tools work but every
write tool returns an error explaining how to enable it.

## Register with Claude Desktop

In `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "openbis": {
      "command": "/absolute/path/to/.venv/bin/openbis-mcp-server",
      "env": {
        "OPENBIS_URL": "https://openbis.imm.rwth-aachen.de",
        "OPENBIS_TOKEN_FILE": "/Users/you/.pybis/openbis.imm.rwth-aachen.de.token"
      }
    }
  }
}
```

Add `"OPENBIS_MCP_ALLOW_WRITE": "1"` to the `env` block to enable writes.
Restart Claude Desktop after edits.

## Project structure

```
openbis-mcp-server/
  src/openbis_mcp_server/
    __init__.py
    __main__.py        # entry point — `python -m openbis_mcp_server`
    server.py          # FastMCP server, all tool definitions
    openbis_client.py  # pyBIS connection wrapper, lazy login
    s3_support.py      # S3 config, upload helpers, linked-dataset registration
  tests/
    test_smoke.py      # offline tests (no live openBIS needed)
  pyproject.toml
  README.md
  .env.example
  .gitignore
```

## Roadmap

- [x] Read-only browsing
- [x] Schema introspection (sample/dataset/experiment types, vocabularies)
- [x] Dataset file listing + single-file download
- [x] Write operations behind explicit env-var gate
- [x] S3-linked dataset support (upload to S3, register LINK-kind dataset, presigned URLs)
- [ ] Higher-level workflows (e.g. `ingest_lammps_run(folder)` combining
  schema lookup, file consolidation, and upload)
- [ ] Bulk operations (multi-sample / multi-dataset create in one call)
- [ ] Search predicates richer than equality (`>=`, `contains`, date ranges)

## License

Currently unlicensed (all rights reserved by default). A permissive license
will be added before any external contributions are accepted.
