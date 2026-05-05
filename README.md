# openbis-mcp-server

A [Model Context Protocol](https://modelcontextprotocol.io) server that exposes
[openBIS](https://openbis.ch) functionality (via [pyBIS](https://pypi.org/project/PyBIS/))
to LLM-based agents.

**Status:** early scaffold. Connection + one smoke-test tool only. Not yet usable
for real work.

## Goal

Let an agent go from "survey a project folder" to "draft and execute an openBIS
upload" in one session — with the user approving each step. The MCP server is
the substrate: it wraps the pyBIS API as a set of typed tools (`search_objects`,
`create_object`, `upload_dataset`, `get_vocabulary_terms`, ...), and the LLM
orchestrates them.

## Configuration

The server reads connection details from environment variables. Either
provide a personal access token (preferred) or username/password.

| Variable           | Purpose                                              |
|--------------------|------------------------------------------------------|
| `OPENBIS_URL`      | Base URL, e.g. `https://openbis.imm.rwth-aachen.de`  |
| `OPENBIS_TOKEN`    | Personal access token (PAT). Preferred.              |
| `OPENBIS_USERNAME` | Used if `OPENBIS_TOKEN` is not set.                  |
| `OPENBIS_PASSWORD` | Used if `OPENBIS_TOKEN` is not set.                  |
| `OPENBIS_VERIFY_CERTIFICATES` | `false` to skip TLS verification (dev only). |

See `.env.example` for a template. Never commit a populated `.env`.

## Install (development)

Requires Python 3.10+.

```bash
git clone https://github.com/biterik/openbis-mcp-server.git
cd openbis-mcp-server
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Run

```bash
export OPENBIS_URL=https://openbis.imm.rwth-aachen.de
export OPENBIS_TOKEN=...
openbis-mcp-server
```

The server speaks MCP over stdio. Wire it into your MCP client (Claude Desktop,
Claude Code, etc.) per that client's instructions.

### Claude Desktop example

In `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "openbis": {
      "command": "/absolute/path/to/.venv/bin/openbis-mcp-server",
      "env": {
        "OPENBIS_URL": "https://openbis.imm.rwth-aachen.de",
        "OPENBIS_TOKEN": "..."
      }
    }
  }
}
```

## Currently implemented tools

| Tool             | What it does                                          |
|------------------|-------------------------------------------------------|
| `get_server_info`| Return openBIS server version + URL. Smoke test.      |
| `list_spaces`    | List all spaces visible to the authenticated user.    |

## Roadmap

Loosely in priority order:

1. **Read-only browsing** — `list_projects`, `list_experiments`, `search_objects`,
   `get_object`, `get_object_type_schema`, `list_vocabularies`,
   `get_vocabulary_terms`, `list_dataset_types`.
2. **Schema introspection** — surface property definitions so the agent can
   produce valid uploads without trial and error.
3. **Write operations** — `create_object`, `update_object`, `create_experiment`,
   `upload_dataset` (with explicit user confirmation in the agent loop).
4. **Dataset upload helpers** — HDF5 and tar archive handling tailored to the
   simulation-data use case.
5. **Higher-level workflows** — e.g. `ingest_lammps_run(folder)` that combines
   schema lookup, file consolidation, and upload.

## Project structure

```
openbis-mcp-server/
  src/openbis_mcp_server/
    __init__.py
    __main__.py        # entry point
    server.py          # FastMCP server, tool definitions
    openbis_client.py  # pyBIS connection wrapper
  tests/
  pyproject.toml
  README.md
  .env.example
  .gitignore
```

## License

Currently unlicensed (all rights reserved by default). A permissive license
will be added before any external contributions are accepted.
