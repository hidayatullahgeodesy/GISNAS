"""
sketsa_utils.py — Utility functions for GISNAS Sketsa plugin.

Handles URL parsing, HTTP helpers, GPKG initialization, and type mapping.
"""

import os
import json
import sqlite3
import urllib.request
import urllib.error
from pathlib import Path


# ---------------------------------------------------------------------------
# URL Parsing
# ---------------------------------------------------------------------------

def parse_ogc_url(url):
    """Extract base_url and token from a GISNAS OGC API URL.

    Supported formats:
        http://host/token/TOKEN/api/ogc/features
        http://host/api/ogc/features?token=TOKEN
    Returns (base_url, token) tuple.
    """
    url = url.strip().rstrip("/")
    parts = url.split("/")
    token = ""
    for i, p in enumerate(parts):
        if p == "token" and i + 1 < len(parts):
            token = parts[i + 1]
            break
    if not token and "?token=" in url:
        token = url.split("?token=")[1].split("&")[0]

    protocol = parts[0]  # "http:" or "https:"
    host = parts[2]
    base_url = f"{protocol}//{host}"
    return base_url, token


# ---------------------------------------------------------------------------
# Directory / Path helpers
# ---------------------------------------------------------------------------

def get_sketsa_dir():
    """Return the root GISNAS Sketsa storage directory (~/.gisnas_sketsa/)."""
    sketsa_dir = Path.home() / ".gisnas_sketsa"
    sketsa_dir.mkdir(parents=True, exist_ok=True)
    return str(sketsa_dir)


def gpkg_path_for(base_url, token, table_name):
    """Return the GPKG file path for a specific collection."""
    host = base_url.split("//")[1].replace(":", "_").replace("/", "_")
    token_prefix = token[:16] if len(token) > 16 else token
    dir_path = os.path.join(get_sketsa_dir(), host, token_prefix)
    os.makedirs(dir_path, exist_ok=True)
    return os.path.join(dir_path, f"{table_name}.gpkg")


def meta_path_for(base_url, token):
    """Return the meta.json path for a connection."""
    host = base_url.split("//")[1].replace(":", "_").replace("/", "_")
    token_prefix = token[:16] if len(token) > 16 else token
    dir_path = os.path.join(get_sketsa_dir(), host, token_prefix)
    os.makedirs(dir_path, exist_ok=True)
    return os.path.join(dir_path, "meta.json")


# ---------------------------------------------------------------------------
# GPKG Initialization
# ---------------------------------------------------------------------------

def init_sketsa_gpkg(gpkg_path, table_name, columns, geom_type, srid):
    """Create a new GPKG with layer_data + internal tracking tables.

    Parameters
    ----------
    gpkg_path : str — file path for the GPKG
    table_name : str — server table name (stored in metadata)
    columns : list[dict] — [{"name": "col", "type": "character varying"}, ...]
    geom_type : str — "POINT", "LINESTRING", "POLYGON", etc.
    srid : int — e.g. 4326
    """
    from osgeo import ogr, osr

    driver = ogr.GetDriverByName("GPKG")
    if os.path.exists(gpkg_path):
        os.remove(gpkg_path)

    ds = driver.CreateDataSource(gpkg_path)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(srid)

    ogr_geom = _geom_type_to_ogr(geom_type)
    lyr = ds.CreateLayer("layer_data", srs, ogr_geom, ["FID=fid"])

    # 'id' column = server primary key (NULL for locally-created features)
    lyr.CreateField(ogr.FieldDefn("id", ogr.OFTInteger64))

    # User-defined columns
    for col in columns:
        name = col.get("name", "")
        if name in ("id", "geom", "fid", "create_gn", "update_gn"):
            continue
        fd = _pg_type_to_ogr_field(name, col.get("type", "character varying"))
        if fd:
            lyr.CreateField(fd)

    ds = None  # flush & close

    # Create internal tracking tables via raw sqlite3
    conn = sqlite3.connect(gpkg_path)
    conn.execute("PRAGMA journal_mode=WAL;")

    # Read schema of layer_data to replicate in snapshot
    cols_info = conn.execute("PRAGMA table_info(layer_data)").fetchall()
    col_defs = ", ".join(
        [f'"{r[1]}" {r[2]}' for r in cols_info if r[1] != "fid"]
    )

    conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS _sketsa_snapshot (
            fid INTEGER PRIMARY KEY,
            {col_defs}
        );

        CREATE TABLE IF NOT EXISTS _sketsa_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS _sketsa_schema_snap (
            column_name TEXT PRIMARY KEY,
            column_type TEXT
        );
    """)

    # Store metadata
    conn.execute(
        "INSERT OR REPLACE INTO _sketsa_meta (key, value) VALUES ('table_name', ?)",
        (table_name,),
    )
    conn.execute(
        "INSERT OR REPLACE INTO _sketsa_meta (key, value) VALUES ('srid', ?)",
        (str(srid),),
    )
    conn.execute(
        "INSERT OR REPLACE INTO _sketsa_meta (key, value) VALUES ('geom_type', ?)",
        (geom_type,),
    )

    conn.commit()
    conn.close()


def save_schema_snapshot(gpkg_path, columns):
    """Store column schema snapshot for DDL diff detection.

    Parameters
    ----------
    columns : list[dict] — [{"name": "col", "type": "character varying"}, ...]
    """
    conn = sqlite3.connect(gpkg_path)
    conn.execute("DELETE FROM _sketsa_schema_snap")
    for col in columns:
        name = col.get("name", "")
        if name in ("id", "geom", "fid", "create_gn", "update_gn"):
            continue
        conn.execute(
            "INSERT INTO _sketsa_schema_snap (column_name, column_type) VALUES (?, ?)",
            (name, col.get("type", "TEXT")),
        )
    conn.commit()
    conn.close()


def add_column_to_gpkg(gpkg_path, col_name, col_type):
    """Add a column to both layer_data and _sketsa_snapshot tables."""
    sqlite_type = _pg_type_to_sqlite(col_type)
    conn = sqlite3.connect(gpkg_path)
    try:
        conn.execute(f'ALTER TABLE layer_data ADD COLUMN "{col_name}" {sqlite_type}')
    except Exception:
        pass  # column may already exist
    try:
        conn.execute(f'ALTER TABLE _sketsa_snapshot ADD COLUMN "{col_name}" {sqlite_type}')
    except Exception:
        pass
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Type Mapping
# ---------------------------------------------------------------------------

def _geom_type_to_ogr(geom_type_str):
    from osgeo import ogr
    mapping = {
        "POINT": ogr.wkbPoint,
        "LINESTRING": ogr.wkbLineString,
        "POLYGON": ogr.wkbPolygon,
        "MULTIPOINT": ogr.wkbMultiPoint,
        "MULTILINESTRING": ogr.wkbMultiLineString,
        "MULTIPOLYGON": ogr.wkbMultiPolygon,
        "GEOMETRY": ogr.wkbUnknown,
    }
    return mapping.get(geom_type_str.upper(), ogr.wkbUnknown)


def _pg_type_to_ogr_field(name, pg_type):
    from osgeo import ogr
    upper = pg_type.upper().strip()
    if "INT" in upper:
        return ogr.FieldDefn(name, ogr.OFTInteger64)
    if any(t in upper for t in ("REAL", "FLOAT", "DOUBLE", "NUMERIC")):
        return ogr.FieldDefn(name, ogr.OFTReal)
    if "BOOL" in upper:
        return ogr.FieldDefn(name, ogr.OFTInteger)
    if "DATE" in upper and "TIMESTAMP" not in upper:
        return ogr.FieldDefn(name, ogr.OFTDate)
    if "TIMESTAMP" in upper:
        return ogr.FieldDefn(name, ogr.OFTDateTime)
    fd = ogr.FieldDefn(name, ogr.OFTString)
    fd.SetWidth(255)
    return fd


def _pg_type_to_sqlite(pg_type):
    upper = pg_type.upper().strip()
    if "INT" in upper:
        return "INTEGER"
    if any(t in upper for t in ("REAL", "FLOAT", "DOUBLE", "NUMERIC")):
        return "REAL"
    if "BOOL" in upper:
        return "INTEGER"
    return "TEXT"


# ---------------------------------------------------------------------------
# HTTP Helpers
# ---------------------------------------------------------------------------

def api_get(url):
    """HTTP GET → parsed JSON."""
    req = urllib.request.Request(url, headers={"User-Agent": "GISNAS-Sketsa/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _json_default(obj):
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def api_post(url, data):
    """HTTP POST with JSON body → parsed JSON."""
    body = json.dumps(data, default=_json_default).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "GISNAS-Sketsa/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw.strip() else {"status": resp.status}


def api_put(url, data):
    """HTTP PUT with JSON body → status code."""
    body = json.dumps(data, default=_json_default).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "GISNAS-Sketsa/1.0"},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise Exception(f"HTTP {e.code}: {err_body}") from e


def api_delete(url):
    """HTTP DELETE → status code."""
    req = urllib.request.Request(
        url, headers={"User-Agent": "GISNAS-Sketsa/1.0"}, method="DELETE"
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.status


def api_patch(url, data):
    """HTTP PATCH with JSON body → parsed JSON."""
    body = json.dumps(data, default=_json_default).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "GISNAS-Sketsa/1.0"},
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {"status": resp.status}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise Exception(f"HTTP {e.code}: {err_body}") from e


def build_url(base_url, token, *path_parts):
    """Build a full GISNAS API URL with token in both path and query."""
    path = "/".join(str(p) for p in path_parts)
    return f"{base_url}/token/{token}/api/ogc/features/{path}?token={token}"


def api_post_file(url, file_path, layer_name=None, upload_filename=None):
    import urllib.request
    import uuid
    import os

    boundary = uuid.uuid4().hex
    filename = upload_filename or os.path.basename(file_path)
    if layer_name is None:
        layer_name = os.path.splitext(filename)[0]

    with open(file_path, 'rb') as f:
        file_data = f.read()

    safe_layer = layer_name.replace('"', "'")
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="layer_name"\r\n\r\n'
        f"{safe_layer}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode('utf-8') + file_data + f"\r\n--{boundary}--\r\n".encode('utf-8')

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "GISNAS-Sketsa/1.0"
        },
        method="POST",
    )
    
    with urllib.request.urlopen(req, timeout=300) as resp:
        raw = resp.read().decode("utf-8")
        import json
        return json.loads(raw) if raw.strip() else {"status": resp.status}

def api_download_file(url, target_path):
    import urllib.request
    import shutil
    
    req = urllib.request.Request(url, headers={"User-Agent": "GISNAS-Sketsa/1.0"})
    with urllib.request.urlopen(req, timeout=300) as resp, open(target_path, 'wb') as out_file:
        shutil.copyfileobj(resp, out_file)
