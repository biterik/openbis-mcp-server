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

`*` write tools require `OPENBIS_MCP_ALLOW_WRITE=1`. See
[Enabling write access](#enabling-write-access) below.

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

## Register with Claude Desktop (macOS)

The Claude Desktop app launches the MCP server as a stdio subprocess. On macOS
there is one non-obvious trap to avoid before configuring it; please read the
next section first.

### ⚠️ Do not install under `~/Desktop`, `~/Documents`, or `~/Downloads`

macOS protects those three folders with **TCC** (Transparency, Consent &
Control). The Claude Desktop app is not granted access to them by default, and
that denial is inherited by every MCP subprocess it spawns. The result is that
Python can't even read its own `pyvenv.cfg` from a virtualenv placed there:

```
PermissionError: [Errno 1] Operation not permitted:
  '/Users/you/Desktop/.../.venv/pyvenv.cfg'
Fatal Python error: init_import_site: Failed to import the site module
```

The interpreter dies before any of this server's code runs, the stdio
transport closes, and Claude Desktop reports "Server disconnected" with no
useful UI-level error. Install the project somewhere else — for example
`~/Codes/`, `~/dev/`, or `~/src/`. The walkthrough below uses `~/Codes/`.

(If you really need the project on Desktop you can grant access in
**System Settings → Privacy & Security → Files & Folders → Claude →
Desktop Folder**, then fully quit and relaunch Claude. The relocated install
is the more robust fix because it survives macOS upgrades and TCC resets.)

### Step-by-step setup on macOS

1. **Clone and install** into a non-protected directory:

   ```bash
   mkdir -p ~/Codes
   cd ~/Codes
   git clone https://github.com/biterik/openbis-mcp-server.git
   cd openbis-mcp-server
   python3 -m venv .venv
   .venv/bin/pip install --upgrade pip
   .venv/bin/pip install -e .
   ```

   This creates the console script at
   `/Users/<you>/Codes/openbis-mcp-server/.venv/bin/openbis-mcp-server`.
   Note the absolute path — you'll need it in the next step.

2. **Create a personal access token** in the openBIS web UI
   (**User menu → Personal Access Tokens → Create**). Save it to a single-line
   file, matching the pyBIS convention:

   ```bash
   mkdir -p ~/.pybis
   printf '%s' 'PASTE-YOUR-TOKEN-HERE' > ~/.pybis/openbis.imm.rwth-aachen.de.token
   chmod 600 ~/.pybis/openbis.imm.rwth-aachen.de.token
   ```

   Replace the host portion of the filename if your openBIS lives elsewhere.

3. **Edit Claude Desktop's config** at
   `~/Library/Application Support/Claude/claude_desktop_config.json`. If the
   file already exists, merge the `mcpServers` entry into the existing JSON;
   otherwise create it with this content (substitute your real username for
   `<you>` and your openBIS host for the URL):

   ```json
   {
     "mcpServers": {
       "openbis": {
         "command": "/Users/<you>/Codes/openbis-mcp-server/.venv/bin/openbis-mcp-server",
         "env": {
           "OPENBIS_URL": "https://openbis.imm.rwth-aachen.de",
           "OPENBIS_TOKEN_FILE": "/Users/<you>/.pybis/openbis.imm.rwth-aachen.de.token"
         }
       }
     }
   }
   ```

   Use **absolute paths** in `command` and `OPENBIS_TOKEN_FILE`. Tilde
   (`~`) expansion is not guaranteed in this context, and the MCP subprocess
   does not inherit your interactive shell's `PATH`.

   To enable the write tools (`create_*`, `update_*`, `delete_entity`), add
   `"OPENBIS_MCP_ALLOW_WRITE": "1"` to the `env` block. Leave it out for
   read-only.

4. **Fully quit Claude Desktop** with **⌘Q** — closing the window is not
   enough; the menu-bar process and any running MCP subprocesses must exit so
   the new config is read on relaunch. Then reopen the app.

5. **Verify** by asking the agent to call `get_server_info`. It should return
   the openBIS URL, server version, and `"write_enabled": true|false`.

### Troubleshooting on macOS

The Claude Desktop log for this server lives at
`~/Library/Logs/Claude/mcp-server-openbis.log`. Tail it while restarting the
app:

```bash
tail -f ~/Library/Logs/Claude/mcp-server-openbis.log
```

Common failure modes:

- `PermissionError: [Errno 1] Operation not permitted: '.../pyvenv.cfg'` —
  the install path is under `~/Desktop`, `~/Documents`, or `~/Downloads`
  and TCC is blocking access. Move the project (see the warning above);
  recreating the venv at the new location is required because shebangs and
  `pyvenv.cfg` hard-code absolute paths.
- `Server transport closed unexpectedly` with no other log lines — the
  command path in `claude_desktop_config.json` is wrong, or the venv was
  created elsewhere and copied in. Check
  `head -1 /Users/<you>/Codes/openbis-mcp-server/.venv/bin/openbis-mcp-server`;
  the shebang must point at the same `.venv/bin/python3` that exists today.
- `connection: ...` in the `get_server_info` response — credentials or URL
  are wrong, or the openBIS server is unreachable. Test the token outside
  Claude with `openbis-mcp-server` from the venv and the same env vars.

## Project structure

```
openbis-mcp-server/
  src/openbis_mcp_server/
    __init__.py
    __main__.py        # entry point — `python -m openbis_mcp_server`
    server.py          # FastMCP server, all tool definitions
    openbis_client.py  # pyBIS connection wrapper, lazy login
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
- [ ] Higher-level workflows (e.g. `ingest_lammps_run(folder)` combining
  schema lookup, file consolidation, and upload)
- [ ] Bulk operations (multi-sample / multi-dataset create in one call)
- [ ] Search predicates richer than equality (`>=`, `contains`, date ranges)

## License

Currently unlicensed (all rights reserved by default). A permissive license
will be added before any external contributions are accepted.
