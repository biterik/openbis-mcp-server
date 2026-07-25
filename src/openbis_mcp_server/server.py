# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Erik Bitzek and Niklas Siemer.
#
# Authors:
#   Erik Bitzek    <e.bitzek@mpi-susmat.de>
#   Niklas Siemer
#
# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at https://mozilla.org/MPL/2.0/.
#
# Implemented with assistance from Claude Code (Anthropic).
"""FastMCP server definition for openbis-mcp-server.

Tools are organised into groups:

* session         — connectivity smoke tests
* browse          — list/get spaces, projects, experiments, samples, datasets
* search          — property-based search of samples / datasets
* schema          — sample / dataset / experiment types, vocabularies, property types
* files           — list and download dataset file contents (no upload)
* write (gated)   — create / update / delete; disabled unless OPENBIS_MCP_ALLOW_WRITE=1

All read tools return plain Python types (dict / list[dict]) that serialize
cleanly to MCP clients. Write tools raise immediately if the gate env var is
not set, so the server can be safely registered with read-only intent.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import __version__
from .openbis_client import (
    ConnectionManager,
    OpenbisAuthError,
    OpenbisConfigError,
    pat_setup_instructions,
)
from .s3_support import (
    S3ConfigError,
    generate_presigned_url,
    get_s3_config,
    upload_and_register_s3_linked_dataset,
)

mcp = FastMCP("openbis-mcp-server")

# One manager owns a client per configured openBIS instance. Clients connect
# lazily on first use, so importing this module never touches the network.
_manager_instance: ConnectionManager | None = None


def _manager() -> ConnectionManager:
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = ConnectionManager()
    return _manager_instance


def _get_client(instance: str | None = None):
    """Return the OpenbisClient for ``instance`` (or the default), creating it lazily."""
    return _manager().client(instance)


def _connection_error_payload(e: Exception, instance: str | None = None) -> dict[str, Any]:
    """Convert a connection/auth failure into a structured, help-bearing dict.

    Auth failures carry verbatim setup instructions in ``help`` so an agent can
    relay exactly how to mint and store a fresh personal access token.
    """
    payload: dict[str, Any] = {"ok": False}
    if instance is not None:
        payload["instance"] = instance
    if isinstance(e, OpenbisConfigError):
        url = os.environ.get("OPENBIS_URL") or "<your openBIS URL>"
        payload.update(
            error="configuration",
            detail=str(e),
            help=pat_setup_instructions(url, instance),
        )
        return payload
    if isinstance(e, OpenbisAuthError):
        # The message already contains the full set-up instructions.
        payload.update(error="authentication", help=str(e))
        return payload
    payload.update(error="connection", detail=str(e))
    return payload


def _write_enabled() -> bool:
    return os.environ.get("OPENBIS_MCP_ALLOW_WRITE", "").strip() == "1"


def _require_write() -> None:
    if not _write_enabled():
        raise RuntimeError(
            "Write operations are disabled. Restart the MCP server with "
            "OPENBIS_MCP_ALLOW_WRITE=1 to enable create/update/delete."
        )


def _stringify(value: Any) -> Any:
    """Make pandas/openBIS values JSON-friendly without losing useful info."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        try:
            return iso()
        except Exception:  # noqa: BLE001
            pass
    return value


def _records(things, limit: int | None = None) -> list[dict[str, Any]]:
    """Convert a pyBIS Things result (DataFrame-backed) to a list of plain dicts."""
    if things is None:
        return []
    df = getattr(things, "df", None)
    if df is None:
        items = list(things)
        return items[:limit] if limit else items
    if limit:
        df = df.head(limit)
    rows = df.to_dict(orient="records")
    return [{str(k): _stringify(v) for k, v in row.items()} for row in rows]


def _entity_to_dict(e: Any, include_relations: bool = True) -> dict[str, Any]:
    """Serialize a single pyBIS entity (space/project/experiment/sample/dataset)."""
    out: dict[str, Any] = {}
    try:
        out.update({k: _stringify(v) for k, v in e.attrs.all().items()})
    except Exception:  # noqa: BLE001
        pass
    try:
        out["properties"] = {k: _stringify(v) for k, v in e.props.all().items()}
    except Exception:  # noqa: BLE001
        pass
    if hasattr(e, "type") and e.type is not None:
        try:
            out["type"] = e.type.code
        except Exception:  # noqa: BLE001
            pass
    if include_relations:
        for rel in ("parents", "children"):
            try:
                out[rel] = list(getattr(e, rel))
            except Exception:  # noqa: BLE001
                pass
    return out


# ---------------- session ----------------


@mcp.tool()
def list_instances() -> dict[str, Any]:
    """List the configured openBIS instances and which one is the default.

    Every other tool accepts an optional ``instance`` argument naming one of
    these; omitting it uses the default. Tokens are never returned.
    """
    mgr = _manager()
    return {"instances": mgr.names(), "default": mgr.default}


def _check_one(instance: str | None) -> dict[str, Any]:
    """Validate a single instance's credentials and return a structured result."""
    try:
        ob = _get_client(instance).connect()
    except Exception as e:  # noqa: BLE001 — surfaced as structured help below
        return _connection_error_payload(e, instance)

    client = _get_client(instance)
    result: dict[str, Any] = {
        "ok": True,
        "instance": client.name,
        "url": client.url,
        "message": "openBIS credentials are valid.",
    }
    try:
        result["session_active"] = bool(ob.is_session_active())
    except Exception:  # noqa: BLE001 — metadata only
        pass
    return result


@mcp.tool()
def check_authentication(instance: str | None = None) -> dict[str, Any]:
    """Verify that openBIS credentials are still valid.

    Call this once at the start of a session before doing real work. With no
    ``instance``, every configured instance is checked; pass a name to check
    just one. If a personal access token has expired or is otherwise rejected,
    the per-instance ``help`` field contains step-by-step instructions for
    creating a new token and where to store it.
    """
    if instance is not None:
        return _check_one(instance)

    names = _manager().names()
    if not names:
        return _check_one(None)  # surfaces the "no instance configured" help
    results = {name: _check_one(name) for name in names}
    return {
        "ok": all(r.get("ok") for r in results.values()),
        "instances": results,
    }


@mcp.tool()
def get_server_info(instance: str | None = None) -> dict[str, Any]:
    """Return openBIS server URL, version, and this MCP server's version + write state.

    Use this as a smoke test to verify connectivity and authentication before
    issuing any other calls. ``instance`` selects a configured server (default
    if omitted); see list_instances.
    """
    try:
        client = _get_client(instance)
        ob = client.connect()
    except Exception as e:  # config/auth/connection — formatted with help below
        return _connection_error_payload(e, instance)

    info: dict[str, Any] = {
        "ok": True,
        "instance": client.name,
        "url": client.url,
        "mcp_server_version": __version__,
        "write_enabled": _write_enabled(),
    }
    for attr in ("get_server_information", "server_information"):
        fn_or_val = getattr(ob, attr, None)
        if fn_or_val is None:
            continue
        try:
            server_info = fn_or_val() if callable(fn_or_val) else fn_or_val
            # ServerInformation object isn't JSON serializable; extract its _info dict
            if hasattr(server_info, "_info"):
                info["server_information"] = server_info._info
            elif hasattr(server_info, "__dict__"):
                info["server_information"] = server_info.__dict__
            else:
                info["server_information"] = str(server_info)
            break
        except Exception:  # noqa: BLE001
            continue
    return info


@mcp.tool()
def whoami(instance: str | None = None) -> dict[str, Any]:
    """Return the authenticated user (parsed from the session token) and session state."""
    ob = _get_client(instance).connect()
    token = getattr(ob, "token", None) or ""
    return {
        "user": token.split("-")[0] if token else None,
        "session_active": bool(ob.is_session_active()),
        "url": _get_client(instance).url,
        "write_enabled": _write_enabled(),
    }


# ---------------- browse ----------------


@mcp.tool()
def list_spaces(instance: str | None = None) -> list[dict[str, Any]]:
    """List all openBIS spaces visible to the authenticated user."""
    return _records(_get_client(instance).connect().get_spaces())


@mcp.tool()
def list_projects(
    space: str | None = None, instance: str | None = None
) -> list[dict[str, Any]]:
    """List projects, optionally restricted to one space code."""
    ob = _get_client(instance).connect()
    return _records(ob.get_projects(space=space) if space else ob.get_projects())


@mcp.tool()
def list_experiments(
    space: str | None = None,
    project: str | None = None,
    type: str | None = None,
    limit: int = 200,
    instance: str | None = None,
) -> list[dict[str, Any]]:
    """List experiments (collections). Filter by space, project identifier, and/or type code."""
    kwargs: dict[str, Any] = {}
    if space:
        kwargs["space"] = space
    if project:
        kwargs["project"] = project
    if type:
        kwargs["type"] = type
    return _records(_get_client(instance).connect().get_experiments(**kwargs), limit=limit)


@mcp.tool()
def list_samples(
    space: str | None = None,
    project: str | None = None,
    experiment: str | None = None,
    type: str | None = None,
    limit: int = 200,
    instance: str | None = None,
) -> list[dict[str, Any]]:
    """List samples (objects). Filter by space, project, experiment identifier, and/or type code."""
    kwargs: dict[str, Any] = {}
    if space:
        kwargs["space"] = space
    if project:
        kwargs["project"] = project
    if experiment:
        kwargs["experiment"] = experiment
    if type:
        kwargs["type"] = type
    return _records(_get_client(instance).connect().get_samples(**kwargs), limit=limit)


@mcp.tool()
def list_datasets(
    space: str | None = None,
    project: str | None = None,
    experiment: str | None = None,
    sample: str | None = None,
    type: str | None = None,
    limit: int = 200,
    instance: str | None = None,
) -> list[dict[str, Any]]:
    """List datasets. Filter by space, project, experiment, sample, and/or dataset type code."""
    kwargs: dict[str, Any] = {}
    if space:
        kwargs["space"] = space
    if project:
        kwargs["project"] = project
    if experiment:
        kwargs["experiment"] = experiment
    if sample:
        kwargs["sample"] = sample
    if type:
        kwargs["type"] = type
    return _records(_get_client(instance).connect().get_datasets(**kwargs), limit=limit)


@mcp.tool()
def get_entity(
    kind: str, identifier: str, instance: str | None = None
) -> dict[str, Any]:
    """Fetch full metadata for one entity.

    kind: one of "space", "project", "experiment", "sample", "dataset"
    identifier: openBIS identifier (e.g. "/SPACE/PROJ/EXP", "/SPACE/SAMPLE_CODE")
                or permId (datasets are typically referenced by permId).
    """
    ob = _get_client(instance).connect()
    fetch = {
        "space": ob.get_space,
        "project": ob.get_project,
        "experiment": ob.get_experiment,
        "collection": ob.get_experiment,
        "sample": ob.get_sample,
        "object": ob.get_sample,
        "dataset": ob.get_dataset,
    }.get(kind.lower())
    if not fetch:
        raise ValueError(
            f"Unknown entity kind '{kind}'. Use space/project/experiment/sample/dataset."
        )
    return _entity_to_dict(fetch(identifier))


# ---------------- search ----------------


@mcp.tool()
def search_samples(
    where: dict[str, Any] | None = None,
    type: str | None = None,
    space: str | None = None,
    limit: int = 100,
    instance: str | None = None,
) -> list[dict[str, Any]]:
    """Search samples by property values.

    where: dict of {property_code: value} — matches samples whose properties equal the given values.
    type/space: optional restriction to a sample type code or space code.
    """
    kwargs: dict[str, Any] = {}
    if where:
        kwargs["where"] = where
    if type:
        kwargs["type"] = type
    if space:
        kwargs["space"] = space
    return _records(_get_client(instance).connect().get_samples(**kwargs), limit=limit)


@mcp.tool()
def search_datasets(
    where: dict[str, Any] | None = None,
    type: str | None = None,
    space: str | None = None,
    limit: int = 100,
    instance: str | None = None,
) -> list[dict[str, Any]]:
    """Search datasets by property values. See search_samples for argument shape."""
    kwargs: dict[str, Any] = {}
    if where:
        kwargs["where"] = where
    if type:
        kwargs["type"] = type
    if space:
        kwargs["space"] = space
    return _records(_get_client(instance).connect().get_datasets(**kwargs), limit=limit)


# ---------------- schema / vocab ----------------


@mcp.tool()
def list_sample_types(instance: str | None = None) -> list[dict[str, Any]]:
    """List all sample (object) types defined on the server."""
    return _records(_get_client(instance).connect().get_sample_types())


@mcp.tool()
def list_dataset_types(instance: str | None = None) -> list[dict[str, Any]]:
    """List all dataset types defined on the server."""
    return _records(_get_client(instance).connect().get_dataset_types())


@mcp.tool()
def list_experiment_types(instance: str | None = None) -> list[dict[str, Any]]:
    """List all experiment (collection) types defined on the server."""
    return _records(_get_client(instance).connect().get_experiment_types())


@mcp.tool()
def list_vocabularies(instance: str | None = None) -> list[dict[str, Any]]:
    """List all controlled vocabularies."""
    return _records(_get_client(instance).connect().get_vocabularies())


@mcp.tool()
def get_property_types(
    entity_type: str | None = None, instance: str | None = None
) -> list[dict[str, Any]]:
    """List property types. If entity_type is given (a sample/dataset/experiment type code),
    list its assigned properties instead."""
    ob = _get_client(instance).connect()
    if entity_type:
        for getter_name in (
            "get_sample_type",
            "get_object_type",
            "get_dataset_type",
            "get_experiment_type",
        ):
            getter = getattr(ob, getter_name, None)
            if not getter:
                continue
            try:
                t = getter(entity_type)
                return _records(t.get_property_assignments())
            except Exception:  # noqa: BLE001
                continue
        raise ValueError(f"Could not resolve entity type '{entity_type}'.")
    return _records(ob.get_property_types())


# ---------------- files ----------------


@mcp.tool()
def list_dataset_files(
    dataset_permid: str, instance: str | None = None
) -> list[dict[str, Any]]:
    """List files inside a dataset (path, size, checksum, isDirectory). Does not download contents."""
    ds = _get_client(instance).connect().get_dataset(dataset_permid)
    return [
        {
            "path": f.get("pathInDataSet"),
            "size": f.get("fileSize"),
            "checksum_crc32": f.get("checksumCRC32"),
            "is_directory": f.get("isDirectory"),
        }
        for f in ds.file_list
    ]


@mcp.tool()
def download_dataset_file(
    dataset_permid: str, path_in_dataset: str, dest_dir: str, instance: str | None = None
) -> dict[str, Any]:
    """Download one file from a dataset to a local directory.

    dataset_permid: dataset permId
    path_in_dataset: relative file path inside the dataset (see list_dataset_files)
    dest_dir: existing local directory to write the file into
    """
    dest = Path(dest_dir).expanduser()
    if not dest.is_dir():
        raise ValueError(f"dest_dir '{dest}' is not an existing directory.")
    ds = _get_client(instance).connect().get_dataset(dataset_permid)
    written = ds.download(
        files=[path_in_dataset], destination=str(dest), wait_until_finished=True
    )
    return {
        "dataset": dataset_permid,
        "downloaded_to": str(dest),
        "result": str(written),
    }


# ---------------- write (gated by OPENBIS_MCP_ALLOW_WRITE=1) ----------------


@mcp.tool()
def create_project(
    space: str, code: str, description: str | None = None, instance: str | None = None
) -> dict[str, Any]:
    """Create a new project under a space. Requires OPENBIS_MCP_ALLOW_WRITE=1."""
    _require_write()
    ob = _get_client(instance).connect()
    p = ob.new_project(space=space, code=code, description=description)
    p.save()
    return _entity_to_dict(p, include_relations=False)


@mcp.tool()
def create_experiment(
    project: str,
    type: str,
    code: str,
    properties: dict[str, Any] | None = None,
    instance: str | None = None,
) -> dict[str, Any]:
    """Create a new experiment (collection). Requires OPENBIS_MCP_ALLOW_WRITE=1.

    project: project identifier ("/SPACE/PROJ")
    type: experiment type code
    code: new experiment code
    properties: optional dict of property values
    """
    _require_write()
    ob = _get_client(instance).connect()
    e = ob.new_experiment(type=type, project=project, code=code, props=properties or {})
    e.save()
    return _entity_to_dict(e, include_relations=False)


@mcp.tool()
def create_sample(
    type: str,
    space: str | None = None,
    project: str | None = None,
    experiment: str | None = None,
    code: str | None = None,
    properties: dict[str, Any] | None = None,
    parents: list[str] | None = None,
    instance: str | None = None,
) -> dict[str, Any]:
    """Create a new sample (object). Requires OPENBIS_MCP_ALLOW_WRITE=1.

    type: sample type code (required)
    space/project/experiment: at least one location must be given
    code: sample code (auto-generated if omitted, depending on type config)
    properties: dict of property values
    parents: list of parent sample identifiers
    """
    _require_write()
    ob = _get_client(instance).connect()
    kwargs: dict[str, Any] = {"type": type, "props": properties or {}}
    if space:
        kwargs["space"] = space
    if project:
        kwargs["project"] = project
    if experiment:
        kwargs["experiment"] = experiment
    if code:
        kwargs["code"] = code
    if parents:
        kwargs["parents"] = parents
    s = ob.new_sample(**kwargs)
    s.save()
    return _entity_to_dict(s, include_relations=False)


@mcp.tool()
def create_dataset(
    type: str,
    files: list[str],
    sample: str | None = None,
    experiment: str | None = None,
    properties: dict[str, Any] | None = None,
    instance: str | None = None,
) -> dict[str, Any]:
    """Upload a new dataset from local files. Requires OPENBIS_MCP_ALLOW_WRITE=1.

    type: dataset type code
    files: list of local file paths to upload
    sample or experiment: where to attach the dataset (one of them required)
    properties: optional dict of dataset property values
    """
    _require_write()
    if not (sample or experiment):
        raise ValueError("Either 'sample' or 'experiment' must be provided.")
    for f in files:
        if not Path(f).expanduser().exists():
            raise ValueError(f"File not found: {f}")
    ob = _get_client(instance).connect()
    kwargs: dict[str, Any] = {"type": type, "files": files, "props": properties or {}}
    if sample:
        kwargs["sample"] = sample
    if experiment:
        kwargs["experiment"] = experiment
    ds = ob.new_dataset(**kwargs)
    ds.save()
    return _entity_to_dict(ds, include_relations=False)


@mcp.tool()
def update_sample(
    identifier: str,
    properties: dict[str, Any] | None = None,
    add_parents: list[str] | None = None,
    remove_parents: list[str] | None = None,
    add_children: list[str] | None = None,
    remove_children: list[str] | None = None,
    instance: str | None = None,
) -> dict[str, Any]:
    """Update a sample's properties or parent/child links. Requires OPENBIS_MCP_ALLOW_WRITE=1.

    Parent/child changes are explicit add/remove (no full replacement) to avoid accidental data loss.
    """
    _require_write()
    s = _get_client(instance).connect().get_sample(identifier)
    if properties:
        for k, v in properties.items():
            s.props[k] = v
    if add_parents:
        s.add_parents(add_parents)
    if remove_parents:
        s.del_parents(remove_parents)
    if add_children:
        s.add_children(add_children)
    if remove_children:
        s.del_children(remove_children)
    s.save()
    return _entity_to_dict(s)


@mcp.tool()
def update_dataset(
    permid: str, properties: dict[str, Any], instance: str | None = None
) -> dict[str, Any]:
    """Update a dataset's properties. Requires OPENBIS_MCP_ALLOW_WRITE=1."""
    _require_write()
    ds = _get_client(instance).connect().get_dataset(permid)
    for k, v in properties.items():
        ds.props[k] = v
    ds.save()
    return _entity_to_dict(ds, include_relations=False)


@mcp.tool()
def delete_entity(
    kind: str, identifier: str, reason: str, instance: str | None = None
) -> dict[str, Any]:
    """Delete an entity. Requires OPENBIS_MCP_ALLOW_WRITE=1.

    Irreversible — a non-empty 'reason' is required and stored as the deletion log entry.
    """
    _require_write()
    if not reason or not reason.strip():
        raise ValueError("A non-empty 'reason' is required for deletion.")
    ob = _get_client(instance).connect()
    fetch = {
        "space": ob.get_space,
        "project": ob.get_project,
        "experiment": ob.get_experiment,
        "collection": ob.get_experiment,
        "sample": ob.get_sample,
        "object": ob.get_sample,
        "dataset": ob.get_dataset,
    }.get(kind.lower())
    if not fetch:
        raise ValueError(f"Unknown entity kind '{kind}'.")
    e = fetch(identifier)
    e.delete(reason)
    return {"deleted": identifier, "kind": kind, "reason": reason}


# ---------------- S3 storage (gated by S3_* env vars + OPENBIS_MCP_ALLOW_WRITE=1) ----------------


def _get_s3_config_or_raise():
    """Return the active S3Config or raise a descriptive RuntimeError."""
    try:
        cfg = get_s3_config()
    except S3ConfigError as exc:
        raise RuntimeError(f"S3 configuration error: {exc}") from exc
    if cfg is None:
        raise RuntimeError(
            "S3 storage is not configured. Set S3_ACCESS_KEY, S3_ACCESS_SECRET, "
            "S3_BUCKET, and S3_DMS_CODE (plus optionally S3_ENDPOINT_URL, "
            "S3_REGION, S3_ENDPOINT_PORT), or point S3_CONFIG_FILE at a config file."
        )
    return cfg


@mcp.tool()
def get_s3_status() -> dict[str, Any]:
    """Return the current S3 storage configuration status.

    Reports whether S3 is configured and (if so) which bucket and DMS code are
    in use.  Does NOT test the S3 connection or require openBIS credentials.
    """
    try:
        cfg = get_s3_config()
    except S3ConfigError as exc:
        return {"configured": False, "error": str(exc)}
    if cfg is None:
        return {
            "configured": False,
            "hint": (
                "Set S3_ACCESS_KEY, S3_ACCESS_SECRET, S3_BUCKET, and S3_DMS_CODE "
                "environment variables (or S3_CONFIG_FILE) to enable S3 storage."
            ),
        }
    return {
        "configured": True,
        "bucket": cfg.bucket,
        "region": cfg.region,
        "endpoint_url": cfg.endpoint_url,
        "dms_code": cfg.dms_code,
    }


@mcp.tool()
def create_s3_linked_dataset(
    type: str,
    file: str,
    sample: str | None = None,
    experiment: str | None = None,
    properties: dict[str, Any] | None = None,
    instance: str | None = None,
) -> dict[str, Any]:
    """Upload a local file to S3 and register it as a LINK-kind dataset in openBIS.

    The file's actual bytes are stored in the S3 bucket configured via the
    ``S3_*`` environment variables (or ``S3_CONFIG_FILE``).  openBIS records
    only the metadata and a presigned download URL (stored in the dataset
    property ``s3_download_link``).

    Requires OPENBIS_MCP_ALLOW_WRITE=1 **and** S3 to be configured.

    type: dataset type code (must exist in openBIS)
    file: absolute local path to the file to upload
    sample or experiment: identifier of the entity to attach the dataset to
    properties: optional dict of dataset property values
    """
    _require_write()
    cfg = _get_s3_config_or_raise()

    if not (sample or experiment):
        raise ValueError("Either 'sample' or 'experiment' must be provided.")
    from pathlib import Path

    if not Path(file).expanduser().is_file():
        raise ValueError(f"File not found: {file}")

    ob = _get_client(instance).connect()
    return upload_and_register_s3_linked_dataset(
        ob=ob,
        filename=str(Path(file).expanduser()),
        s3_config=cfg,
        dataset_type=type,
        sample=sample,
        experiment=experiment,
        properties=properties,
    )


@mcp.tool()
def generate_s3_download_url(
    s3_key: str,
    validity: int = 604800,
) -> dict[str, Any]:
    """Generate a fresh presigned S3 GET URL for a file in the configured bucket.

    Useful when the ``s3_download_link`` stored on an existing dataset has expired.
    The URL is valid for *validity* seconds (default 7 days).

    s3_key: the object key inside the bucket (as returned by ``create_s3_linked_dataset``)
    validity: URL lifetime in seconds (max depends on your S3 provider)
    """
    cfg = _get_s3_config_or_raise()
    try:
        from .s3_support import build_s3_client
    except ImportError as exc:
        raise RuntimeError(str(exc)) from exc

    s3_client = build_s3_client(cfg)
    url = generate_presigned_url(s3_client, cfg.bucket, s3_key, validity)
    return {
        "bucket": cfg.bucket,
        "s3_key": s3_key,
        "validity_seconds": validity,
        "download_url": url,
    }
