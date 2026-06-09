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
"""S3 storage support for openbis-mcp-server.

Enables linking files stored in an S3-compatible object store to openBIS
datasets (LINK kind), following the approach of the pybis_aixtended extension
from pyiron/pyiron_rdm (https://github.com/pyiron/pyiron_rdm).

Configuration is read from environment variables or an INI-style config file:

  Environment variables (all prefixed ``S3_``):
    S3_REGION            — AWS region (default: eu-central-1)
    S3_ENDPOINT_URL      — custom endpoint for S3-compatible stores
    S3_ENDPOINT_PORT     — optional port suffix for the endpoint
    S3_ACCESS_KEY        — access key / key ID
    S3_ACCESS_SECRET     — secret access key
    S3_BUCKET            — bucket name
    S3_DMS_CODE          — openBIS External Data Management System code

  Config file (path given via ``S3_CONFIG_FILE`` env var), INI format::

    [s3]
    s3_region = eu-central-1
    s3_endpoint_url = https://s3.example.com
    s3_endpoint_port = 443
    s3_access_key = AKID...
    s3_access_secret = secret
    s3_bucket = my-bucket

    [openbis]
    dms_code = MY_DMS

  The config file takes precedence over individual env vars when both exist.
"""

from __future__ import annotations

import logging
import os
import re
import zlib
from configparser import ConfigParser
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


class S3ConfigError(RuntimeError):
    """Raised when S3 configuration is missing or invalid."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class S3Config:
    """Holds all settings needed to connect to an S3-compatible store."""

    region: str
    access_key: str
    access_secret: str
    bucket: str
    dms_code: str
    endpoint_url: str | None = None


def load_s3_config_from_env() -> S3Config | None:
    """Read S3 settings from environment variables.

    Returns ``None`` if the mandatory vars (S3_ACCESS_KEY, S3_ACCESS_SECRET,
    S3_BUCKET, S3_DMS_CODE) are not all set — i.e. S3 is not configured.
    """
    get = os.environ.get
    access_key = get("S3_ACCESS_KEY")
    access_secret = get("S3_ACCESS_SECRET")
    bucket = get("S3_BUCKET")
    dms_code = get("S3_DMS_CODE")

    if not all([access_key, access_secret, bucket, dms_code]):
        return None

    region = get("S3_REGION", "eu-central-1")
    endpoint_url = get("S3_ENDPOINT_URL")
    port = get("S3_ENDPOINT_PORT")
    if endpoint_url and port:
        endpoint_url = f"{endpoint_url}:{port}"

    return S3Config(
        region=region,
        access_key=access_key,  # type: ignore[arg-type]
        access_secret=access_secret,  # type: ignore[arg-type]
        bucket=bucket,  # type: ignore[arg-type]
        dms_code=dms_code,  # type: ignore[arg-type]
        endpoint_url=endpoint_url,
    )


def load_s3_config_from_file(config_path: str) -> S3Config:
    """Read S3 settings from an INI-style config file.

    Raises :class:`S3ConfigError` if the file is missing or malformed.
    """
    if not os.path.isfile(config_path):
        raise S3ConfigError(f"S3 config file not found: {config_path}")

    parser = ConfigParser(allow_no_value=True)
    with open(config_path) as fh:
        parser.read_string(fh.read())

    try:
        dms_code = parser.get("openbis", "dms_code", fallback=None) or parser.get(
            "openBIS", "dms_code", fallback=None
        )
        if not dms_code:
            raise S3ConfigError("dms_code missing in [openbis] section of config file")

        region = parser.get("s3", "s3_region", fallback="eu-central-1")
        endpoint_url = parser.get("s3", "s3_endpoint_url", fallback=None)
        port = parser.get("s3", "s3_endpoint_port", fallback=None)
        access_key = parser.get("s3", "s3_access_key")
        access_secret = parser.get("s3", "s3_access_secret")
        bucket = parser.get("s3", "s3_bucket")
    except S3ConfigError:
        raise
    except Exception as exc:
        raise S3ConfigError(f"S3 config file is not formatted correctly: {exc}") from exc

    if endpoint_url and port:
        endpoint_url = f"{endpoint_url}:{port}"

    return S3Config(
        region=region,
        access_key=access_key,
        access_secret=access_secret,
        bucket=bucket,
        dms_code=dms_code,
        endpoint_url=endpoint_url,
    )


def get_s3_config() -> S3Config | None:
    """Return an :class:`S3Config` from the config file (if ``S3_CONFIG_FILE``
    is set) or from individual environment variables.

    Returns ``None`` when S3 is not configured at all.
    Raises :class:`S3ConfigError` when a config file is declared but invalid.
    """
    config_file = os.environ.get("S3_CONFIG_FILE")
    if config_file:
        return load_s3_config_from_file(config_file)
    return load_s3_config_from_env()


# ---------------------------------------------------------------------------
# boto3 client
# ---------------------------------------------------------------------------


def build_s3_client(config: S3Config) -> Any:  # type: ignore[return]
    """Create and return a boto3 S3 client from *config*.

    Raises :class:`S3ConfigError` if boto3 is not installed.
    """
    try:
        import boto3  # type: ignore[import-not-found]
        import boto3.session  # type: ignore[import-not-found]
    except ImportError as exc:
        raise S3ConfigError(
            "boto3 is not installed. Install it with: pip install 'openbis-mcp-server[s3]'"
        ) from exc

    if config.endpoint_url and "datastorage.nrw" in config.endpoint_url.lower():
        s3_config = boto3.session.Config(
            signature_version="s3v4",
            connect_timeout=5,
            read_timeout=10,
            s3={"addressing_style": "virtual"},
        )
    else:
        s3_config = boto3.session.Config(
            signature_version="s3v4",
            connect_timeout=5,
            read_timeout=10,
        )

    return boto3.client(
        service_name="s3",
        endpoint_url=config.endpoint_url,
        region_name=config.region,
        aws_access_key_id=config.access_key,
        aws_secret_access_key=config.access_secret,
        config=s3_config,
    )


# ---------------------------------------------------------------------------
# S3 key generation
# ---------------------------------------------------------------------------

# pybis session tokens are formatted as ``username-<session-uuid>`` where the
# session UUID matches the standard 8-4-4-4-12 hex pattern.
_TOKEN_UUID_RE = re.compile(
    r"-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _get_ob_username(ob: Any) -> str:
    """Extract the username from a logged-in pybis ``Openbis`` instance.

    The pybis session token is formatted as ``username-<uuid>``.  This
    function strips the trailing UUID to recover the username.  Falls back to
    ``"unknown"`` if the token is absent or does not match the expected format.
    """
    token = getattr(ob, "token", None)
    if token:
        m = _TOKEN_UUID_RE.search(token)
        if m:
            return token[: m.start()]
    return "unknown"


def _make_s3_key(filename: str, dataset_type: str, username: str) -> str:
    """Return a collision-resistant S3 object key for *filename*.

    Follows the same naming convention as *pybis_aixtended*::

        {timestamp}_{dataset_type}_{username}_{basename}

    where *timestamp* is the current UTC time formatted as
    ``%Y-%m-%dT%H-%M-%S.%f``.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S.%f")
    basename = os.path.basename(filename)
    return f"{timestamp}_{dataset_type}_{username}_{basename}"


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------


def _crc32_file(path: str) -> str:
    """Return the CRC32 checksum of *path* as an unsigned hex string."""
    prev = 0
    with open(path, "rb") as fh:
        for chunk in fh:
            prev = zlib.crc32(chunk, prev)
    return "%x" % (prev & 0xFFFFFFFF)


def _xxhash64_file(path: str, block_size: int = 2**22) -> str:
    """Return the xxHash-64 hex digest of *path*.

    Raises :class:`S3ConfigError` if xxhash is not installed.
    """
    try:
        import xxhash  # type: ignore[import-not-found]
    except ImportError as exc:
        raise S3ConfigError(
            "xxhash is not installed. Install it with: pip install 'openbis-mcp-server[s3]'"
        ) from exc

    h = xxhash.xxh64()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(block_size), b""):
            h.update(chunk)
    return h.hexdigest()


def get_file_metadata(filename: str, dms_path: str, compute_crc32: bool = False) -> list[dict]:
    """Build the file-metadata list required by the openBIS linked-dataset API.

    Args:
        filename: Local path to the file.
        dms_path: Fully-qualified path on the external store (DMS URL + filename).
        compute_crc32: Whether to compute the CRC32 checksum (can be slow for large files).

    Returns:
        A one-element list containing the metadata dict expected by openBIS.
    """
    if not os.path.isfile(filename):
        raise FileNotFoundError(f"File not found: {filename}")

    file_size = os.path.getsize(filename)
    file_crc32 = _crc32_file(filename) if compute_crc32 else "0"
    file_xxhash = _xxhash64_file(filename)

    logging.debug("file size: %s, crc32: %s, xxhash: %s", file_size, file_crc32, file_xxhash)

    return [
        {
            "fileLength": file_size,
            "crc32": file_crc32,
            "crc32Checksum": file_crc32,
            "checksum": file_xxhash,
            "checksumType": "xxHash",
            "directory": False,
            "path": dms_path,
        }
    ]


# ---------------------------------------------------------------------------
# openBIS DMS / DSS helpers
# ---------------------------------------------------------------------------


def get_dms_info(ob: Any, filename: str, dms_code: str, key: str | None = None) -> tuple[str, dict]:
    """Return the full DMS path and DMS ID dict for *filename*.

    Args:
        ob: A logged-in ``pybis.Openbis`` instance.
        filename: The local file path (used only when *key* is ``None``).
        dms_code: openBIS External Data Management System code.
        key: The S3 object key to embed in the DMS path.  When omitted the
            bare basename of *filename* is used.  Pass the value returned by
            :func:`_make_s3_key` to use the collision-resistant naming
            convention.

    Returns:
        A ``(dms_path, dms_id)`` tuple as required by the linked-dataset API.
    """
    dms = ob.get_external_data_management_system(dms_code)
    logging.debug("DMS URL template: %s", dms.urlTemplate)
    dms_id = ob.external_data_managment_system_to_dms_id(dms_code)
    object_name = key if key is not None else os.path.basename(filename)
    dms_path = dms.urlTemplate + "/" + object_name
    return dms_path, dms_id


def _get_datastore_url(ob: Any, dss_code: str) -> str:
    """Return the full JSON-RPC URL for the openBIS Data Store Server."""
    data_stores = ob.get_datastores()
    row = data_stores[data_stores["code"] == dss_code]
    download_url = row["downloadUrl"].iloc[0]
    return f"{download_url}/datastore_server/rmi-data-store-server-v3.json"


# ---------------------------------------------------------------------------
# S3 upload and openBIS registration
# ---------------------------------------------------------------------------


def upload_file_to_s3(s3_client: Any, filename: str, bucket: str, key: str | None = None) -> str:
    """Upload *filename* to *bucket* using *s3_client*.

    Args:
        s3_client: A boto3 S3 client.
        filename: Local path to the file.
        bucket: Destination bucket name.
        key: S3 object key.  When omitted the bare basename of *filename* is
            used.  Pass the value returned by :func:`_make_s3_key` to store
            the file under a collision-resistant name.

    Returns:
        The object key that was used for the upload.
    """
    if key is None:
        key = os.path.basename(filename)
    try:
        s3_client.upload_file(Filename=filename, Bucket=bucket, Key=key)
        logging.info("Uploaded %s to s3://%s/%s", filename, bucket, key)
    except Exception as exc:
        logging.error("S3 upload failed: %s", exc)
        raise
    return key


def generate_presigned_url(s3_client: Any, bucket: str, key: str, validity: int = 604800) -> str:
    """Generate a presigned GET URL for *key* in *bucket*.

    Args:
        s3_client: A boto3 S3 client.
        bucket: Bucket name.
        key: Object key.
        validity: URL validity in seconds (default 7 days).

    Returns:
        The presigned URL string.
    """
    return s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=validity,
        HttpMethod="GET",
    )


def register_linked_file(
    ob: Any,
    file_metadata: list[dict],
    dms_path: str,
    dms_id: dict,
    dss_code: str,
    sample_name: str | None,
    experiment_name: str | None,
    properties: dict,
    dataset_type: str,
    parent_ids: list,
    token: str,
) -> str:
    """Register a file on external storage as a LINK-kind dataset in openBIS.

    The file must already be present on the external store.  This function
    only sends the metadata to openBIS so it knows where the file lives.

    Returns:
        The permId of the newly created linked dataset.
    """
    data_set_creation: dict[str, Any] = {
        "linkedData": {
            "@type": "as.dto.dataset.create.LinkedDataCreation",
            "contentCopies": [
                {
                    "@type": "as.dto.dataset.create.ContentCopyCreation",
                    "path": dms_path,
                    "externalDmsId": dms_id,
                }
            ],
        },
        "typeId": {
            "@type": "as.dto.entitytype.id.EntityTypePermId",
            "permId": dataset_type,
        },
        "dataStoreId": {
            "permId": dss_code,
            "@type": "as.dto.datastore.id.DataStorePermId",
        },
        "parentIds": parent_ids,
        "measured": False,
        "properties": properties,
        "@type": "as.dto.dataset.create.DataSetCreation",
        "autoGeneratedCode": True,
    }

    if sample_name is not None:
        data_set_creation["sampleId"] = ob.sample_to_sample_id(sample_name)
    elif experiment_name is not None:
        data_set_creation["experimentId"] = ob.experiment_to_experiment_id(experiment_name)

    full_ds_creation = {
        "fileMetadata": file_metadata,
        "metadataCreation": data_set_creation,
        "@type": "dss.dto.dataset.create.FullDataSetCreation",
    }

    request = {
        "method": "createDataSets",
        "params": [token, [full_ds_creation]],
    }

    dss_url = _get_datastore_url(ob, dss_code)

    logging.debug("POST linked-dataset request to %s", dss_url)
    response = ob._post_request_full_url(dss_url, request)  # type: ignore[attr-defined]
    perm_id: str = ob.get_dataset(response[0]["permId"]).permId
    return perm_id


def upload_and_register_s3_linked_dataset(
    ob: Any,
    filename: str,
    s3_config: S3Config,
    dataset_type: str,
    sample: str | None = None,
    experiment: str | None = None,
    properties: dict | None = None,
    dss_code: str | None = None,
) -> dict[str, Any]:
    """Upload *filename* to S3 and register it as a LINK-kind dataset in openBIS.

    Args:
        ob: A logged-in ``pybis.Openbis`` instance.
        filename: Local path to the file to upload.
        s3_config: S3 connection configuration.
        dataset_type: openBIS dataset type code.
        sample: openBIS sample identifier to attach the dataset to.
        experiment: openBIS experiment identifier (if not attaching to a sample).
        properties: Optional property dict for the dataset.
        dss_code: DSS code override (defaults to the first available store).

    Returns:
        A dict with ``permId``, ``s3_key``, and ``s3_bucket``.
    """
    if not (sample or experiment):
        raise ValueError("Either 'sample' or 'experiment' must be provided.")
    if not os.path.isfile(filename):
        raise ValueError(f"File not found: {filename}")

    props = properties or {}
    s3_client = build_s3_client(s3_config)

    # Build a collision-resistant S3 key using the pybis_aixtended convention:
    # {timestamp}_{dataset_type}_{username}_{original_filename}
    username = _get_ob_username(ob)
    s3_key = _make_s3_key(filename, dataset_type, username)

    # Upload to S3 under the generated key
    upload_file_to_s3(s3_client, filename, s3_config.bucket, key=s3_key)

    # Generate a presigned download URL and store it as a dataset property
    presigned_url = generate_presigned_url(s3_client, s3_config.bucket, s3_key)
    props = dict(props)
    props["s3_download_link"] = presigned_url

    # Get DMS path and ID using the same key so openBIS points at the right object
    dms_path, dms_id = get_dms_info(ob, filename, s3_config.dms_code, key=s3_key)

    # Compute file metadata (checksum etc.)
    file_meta = get_file_metadata(filename, dms_path, compute_crc32=False)

    # Resolve DSS code
    if dss_code is None:
        dss_code = ob.get_datastores()["code"].iloc[0]

    token: str = ob.token

    perm_id = register_linked_file(
        ob=ob,
        file_metadata=file_meta,
        dms_path=dms_path,
        dms_id=dms_id,
        dss_code=dss_code,
        sample_name=sample,
        experiment_name=experiment,
        properties=props,
        dataset_type=dataset_type,
        parent_ids=[],
        token=token,
    )

    return {
        "permId": perm_id,
        "s3_bucket": s3_config.bucket,
        "s3_key": s3_key,
        "s3_download_link": presigned_url,
    }
