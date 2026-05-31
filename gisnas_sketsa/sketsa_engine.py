"""
sketsa_engine.py — Core sync engine for GISNAS Sketsa.

Handles pull (server→local), push (local→server delta), diff computation,
and topology operations via the GISNAS OGC API.
"""

import json
import os
import sqlite3
from .sketsa_utils import (
    api_get, api_post, api_put, api_delete, build_url,
    init_sketsa_gpkg, save_schema_snapshot, add_column_to_gpkg,
    gpkg_path_for,
)


class DiffResult:
    """Holds the computed delta between local GPKG and snapshot."""
    def __init__(self):
        self.inserts = []        # list of dict (feature data, no server id)
        self.updates = []        # list of dict (feature data, with server id)
        self.deletes = []        # list of int (server ids to delete)
        self.new_columns = []    # list of dict {"name": ..., "type": ...}
        self.dropped_columns = []  # list of str (column names)

    @property
    def has_changes(self):
        return bool(self.inserts or self.updates or self.deletes
                     or self.new_columns or self.dropped_columns)

    def summary(self):
        parts = []
        if self.inserts:
            parts.append(f"{len(self.inserts)} feature baru")
        if self.updates:
            parts.append(f"{len(self.updates)} feature diubah")
        if self.deletes:
            parts.append(f"{len(self.deletes)} feature dihapus")
        if self.new_columns:
            parts.append(f"{len(self.new_columns)} kolom baru")
        if self.dropped_columns:
            parts.append(f"{len(self.dropped_columns)} kolom dihapus")
        return ", ".join(parts) if parts else "No ada perubahan"


# ---------------------------------------------------------------------------
# PULL — Server → Local (Full Download)
# ---------------------------------------------------------------------------

def pull_collection(base_url, token, table_name, log_fn=None):
    """Download a full collection from server as GPKG and create a local GPKG."""
    def log(msg):
        if log_fn:
            log_fn(msg)

    import sqlite3
    import datetime
    from .sketsa_utils import gpkg_path_for, api_download_file, build_url

    gpkg_path = gpkg_path_for(base_url, token, table_name)
    tmp_path = gpkg_path + ".part"

    # 1. Download GPKG directly from server
    url_download = build_url(base_url, token, "download_gpkg") + f"&table_name={table_name}"
    log(f"📥 Mengunduh GPKG utuh dari server (Cepat): {table_name}...")

    try:
        release_gpkg_layers(gpkg_path)
        api_download_file(url_download, tmp_path)
        if os.path.exists(gpkg_path):
            os.remove(gpkg_path)
        os.replace(tmp_path, gpkg_path)
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise Exception(f"Gagal mengunduh file GPKG: {e}")

    log("📦 Menyiapkan schema GPKG lokal...")
    conn = sqlite3.connect(gpkg_path)

    # Rename the exported table to layer_data
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT table_name FROM gpkg_contents WHERE data_type='features'"
        ).fetchall()}
        if table_name in tables and table_name != "layer_data":
            conn.execute(f"ALTER TABLE '{table_name}' RENAME TO layer_data")
            conn.execute(
                "UPDATE gpkg_contents SET table_name = 'layer_data' WHERE table_name = ?",
                (table_name,),
            )
            conn.execute(
                "UPDATE gpkg_geometry_columns SET table_name = 'layer_data' WHERE table_name = ?",
                (table_name,),
            )
            conn.execute(
                "UPDATE gpkg_extensions SET table_name = 'layer_data' WHERE table_name = ?",
                (table_name,),
            )
            conn.commit()
    except Exception as e:
        print("Rename table warning:", e)

    _normalize_layer_schema(conn)
    _ensure_tracking_tables(conn)
    _drop_spatialite_triggers(conn)  # Hapus trigger ST_IsEmpty agar edit di QGIS tidak error

    # Snapshot tanpa CREATE AS SELECT (hindari trigger SpatiaLite ST_IsEmpty)
    log("📸 Membuat snapshot baseline...")
    conn.close()
    _create_snapshot(gpkg_path)

    conn = sqlite3.connect(gpkg_path)
    cols = []
    for row in conn.execute("PRAGMA table_info(layer_data)").fetchall():
        if row[1] not in ("fid", "id", "geom"):
            cols.append({"name": row[1], "type": row[2]})

    conn.execute("DELETE FROM _sketsa_schema_snap")
    for col in cols:
        conn.execute(
            "INSERT INTO _sketsa_schema_snap VALUES (?, ?)", (col["name"], col["type"])
        )

    conn.execute(
        "INSERT OR REPLACE INTO _sketsa_meta (key, value) VALUES ('last_sync', ?)",
        (datetime.datetime.now().isoformat(),),
    )
    conn.execute(
        "INSERT OR REPLACE INTO _sketsa_meta (key, value) VALUES ('base_url', ?)",
        (base_url,),
    )
    conn.execute(
        "INSERT OR REPLACE INTO _sketsa_meta (key, value) VALUES ('token', ?)",
        (token,),
    )
    conn.commit()
    conn.close()

    log(f"✅ Download selesai! File GPKG berhasil diperbarui secara lokal.")
    return gpkg_path


# ---------------------------------------------------------------------------
# PUSH — Local → Server (Delta Only)
# ---------------------------------------------------------------------------

def push_changes(gpkg_path, base_url, token, table_name, log_fn=None):
    """Compute diff and send only changed data to server.

    Returns
    -------
    dict — {"success": int, "errors": int, "details": [...]}
    """
    def log(msg):
        if log_fn:
            log_fn(msg)

    log("🔍 Menghitung perubahan lokal (diff)...")
    diff = compute_diff(gpkg_path)

    if not diff.has_changes:
        log("✅ No ada perubahan untuk dikirim.")
        return {"success": 0, "errors": 0, "details": []}

    log(f"📊 Ditemukan: {diff.summary()}")

    results = {"success": 0, "errors": 0, "details": []}

    # 1. Schema changes first (new columns)
    for col in diff.new_columns:
        log(f"   ➕ Menambah kolom: {col['name']} ({col['type']})")
        try:
            url = build_url(base_url, token, "collections", table_name, "columns")
            api_post(url, {"column_name": col["name"], "column_type": col["type"]})
            results["success"] += 1
        except Exception as e:
            results["errors"] += 1
            results["details"].append(f"❌ Gagal tambah kolom {col['name']}: {e}")
            log(f"   ❌ Gagal: {e}")

    for col_name in diff.dropped_columns:
        log(f"   ➖ Menghapus kolom: {col_name}")
        try:
            url = build_url(base_url, token, "collections", table_name, "columns")
            url += f"&name={col_name}"
            api_delete(url)
            results["success"] += 1
        except Exception as e:
            results["errors"] += 1
            results["details"].append(f"❌ Gagal hapus kolom {col_name}: {e}")
            log(f"   ❌ Gagal: {e}")

    # 2. Delete features
    for server_id in diff.deletes:
        log(f"   🗑️ Menghapus feature #{server_id}")
        try:
            url = build_url(base_url, token, "collections", table_name, "items", server_id)
            api_delete(url)
            results["success"] += 1
        except Exception as e:
            results["errors"] += 1
            results["details"].append(f"❌ Gagal hapus feature #{server_id}: {e}")

    # 3. Insert new features
    id_map = {}  # local_fid → server_id (for updating local after push)
    for feat in diff.inserts:
        log(f"   ➕ Menambah feature baru...")
        try:
            url = build_url(base_url, token, "collections", table_name, "items")
            geojson = _feature_dict_to_geojson(feat, gpkg_path=gpkg_path)
            if not geojson.get("geometry"):
                raise ValueError("Geometri kosong — tidak bisa dikirim ke server")
            resp = api_post(url, geojson)
            new_id = resp.get("id")
            if new_id and feat.get("_local_fid"):
                id_map[feat["_local_fid"]] = new_id
            results["success"] += 1
        except Exception as e:
            results["errors"] += 1
            results["details"].append(f"❌ Gagal insert feature: {e}")

    # 4. Update modified features
    for feat in diff.updates:
        server_id = feat.get("id")
        log(f"   ✏️ Mengupdate feature #{server_id}")
        try:
            url = build_url(base_url, token, "collections", table_name, "items", server_id)
            geojson = _feature_dict_to_geojson(feat, gpkg_path=gpkg_path)
            if not geojson.get("geometry"):
                raise ValueError("Geometri kosong — tidak bisa dikirim ke server")
            api_put(url, geojson)
            results["success"] += 1
        except Exception as e:
            results["errors"] += 1
            msg = f"❌ Gagal update feature #{server_id}: {e}"
            results["details"].append(msg)
            log(f"   {msg}")

    # 5. Update local GPKG: assign server IDs to new features
    if id_map:
        conn = sqlite3.connect(gpkg_path)
        for local_fid, server_id in id_map.items():
            conn.execute(
                "UPDATE layer_data SET id = ? WHERE fid = ?",
                (server_id, local_fid),
            )
        conn.commit()
        conn.close()

    # 6. Refresh snapshot
    log("📸 Memperbarui snapshot...")
    _create_snapshot(gpkg_path)

    # Update schema snapshot
    current_cols = _get_current_columns(gpkg_path)
    save_schema_snapshot(gpkg_path, current_cols)

    # Update last sync time
    conn = sqlite3.connect(gpkg_path)
    import datetime
    conn.execute(
        "INSERT OR REPLACE INTO _sketsa_meta (key, value) VALUES ('last_sync', ?)",
        (datetime.datetime.now().isoformat(),),
    )
    conn.commit()
    conn.close()

    total = results["success"] + results["errors"]
    log(f"✅ Push selesai: {results['success']}/{total} berhasil")
    return results


# ---------------------------------------------------------------------------
# DIFF — Compute delta between local and snapshot
# ---------------------------------------------------------------------------

def compute_diff(gpkg_path):
    """Compare layer_data vs _sketsa_snapshot → DiffResult.

    Detection logic:
    - INSERT: features where `id` IS NULL (never synced to server)
    - DELETE: server IDs in snapshot but not in layer_data
    - UPDATE: same server `id` but any column value differs
    - New columns: in layer_data schema but not in _sketsa_schema_snap
    - Dropped columns: in _sketsa_schema_snap but not in layer_data schema
    """
    diff = DiffResult()
    conn = sqlite3.connect(gpkg_path)
    _normalize_layer_schema(conn)

    # --- Schema diff ---
    current_cols = set()
    for row in conn.execute("PRAGMA table_info(layer_data)").fetchall():
        col_name = row[1]
        if col_name not in ("fid", "id", "geom"):
            current_cols.add(col_name)

    snap_cols = {}
    try:
        for row in conn.execute("SELECT column_name, column_type FROM _sketsa_schema_snap").fetchall():
            snap_cols[row[0]] = row[1]
    except Exception:
        pass

    snap_col_names = set(snap_cols.keys())

    for col_name in current_cols - snap_col_names:
        # Guess type from PRAGMA
        col_type = "TEXT"
        for row in conn.execute("PRAGMA table_info(layer_data)").fetchall():
            if row[1] == col_name:
                col_type = row[2] or "TEXT"
                break
        diff.new_columns.append({"name": col_name, "type": col_type})

    for col_name in snap_col_names - current_cols:
        diff.dropped_columns.append(col_name)

    # --- Data diff ---
    # Get comparable column names (present in both layer_data and snapshot)
    data_cols = []
    for row in conn.execute("PRAGMA table_info(layer_data)").fetchall():
        col_name = row[1]
        if col_name != "fid":
            data_cols.append(col_name)

    # Check if snapshot has data
    try:
        snap_count = conn.execute("SELECT COUNT(*) FROM _sketsa_snapshot").fetchone()[0]
    except Exception:
        snap_count = 0

    # --- INSERTs: features with id IS NULL (locally created, never pushed) ---
    insert_rows = conn.execute(
        "SELECT fid, * FROM layer_data WHERE id IS NULL"
    ).fetchall()

    layer_col_names = ["fid"] + data_cols
    for row in insert_rows:
        feat = dict(zip(layer_col_names, row))
        feat["_local_fid"] = feat["fid"]
        # Read geometry as WKT for sending
        geom_wkb = feat.get("geom")
        feat["_geom_blob"] = geom_wkb
        diff.inserts.append(feat)

    if snap_count > 0:
        # --- DELETEs: server IDs in snapshot but not in layer_data ---
        delete_rows = conn.execute("""
            SELECT id FROM _sketsa_snapshot
            WHERE id IS NOT NULL
              AND id NOT IN (SELECT id FROM layer_data WHERE id IS NOT NULL)
        """).fetchall()
        diff.deletes = [row[0] for row in delete_rows]

        # --- UPDATEs: same id, different data ---
        # Build comparison clauses for all columns except fid
        compare_cols = [
            c for c in data_cols
            if c not in ("fid", "create_gn", "update_gn")
        ]
        if compare_cols:
            conditions = []
            for c in compare_cols:
                if c == "geom":
                    conditions.append(f'hex(l."{c}") != hex(s."{c}")')
                else:
                    conditions.append(
                        f'(l."{c}" IS NOT s."{c}" AND NOT (l."{c}" IS NULL AND s."{c}" IS NULL))'
                    )
            where = " OR ".join(conditions)

            select_cols = ", ".join([f'l."{c}"' for c in data_cols])
            update_rows = conn.execute(f"""
                SELECT l.fid, {select_cols}
                FROM layer_data l
                JOIN _sketsa_snapshot s ON l.id = s.id
                WHERE l.id IS NOT NULL AND ({where})
            """).fetchall()

            for row in update_rows:
                feat = dict(zip(["fid"] + data_cols, row))
                feat["_geom_blob"] = feat.get("geom")
                diff.updates.append(feat)

    conn.close()
    return diff


# ---------------------------------------------------------------------------
# REFRESH — Re-download from server
# ---------------------------------------------------------------------------

def refresh_from_server(gpkg_path, base_url, token, table_name, log_fn=None):
    """Re-download all data from server, replacing local data + snapshot."""
    def log(msg):
        if log_fn:
            log_fn(msg)

    log(f"🔄 Refreshing {table_name} dari server...")

    columns = _fetch_columns(base_url, token, table_name)
    features = _fetch_all_items(base_url, token, table_name)
    log(f"   ➜ {len(features)} feature dari server")

    conn = sqlite3.connect(gpkg_path)
    _ensure_tracking_tables(conn)
    saved = _disable_table_triggers(conn, "layer_data")
    try:
        conn.execute("DELETE FROM layer_data")
        try:
            conn.execute("DELETE FROM _sketsa_snapshot")
        except Exception:
            pass
        conn.commit()
    finally:
        _restore_triggers(conn, saved)
    conn.close()

    # Re-insert
    if features:
        _insert_features_to_gpkg(gpkg_path, features, columns)
    _normalize_layer_schema_on_path(gpkg_path)
    _drop_spatialite_triggers_on_path(gpkg_path)  # Hapus trigger ST_IsEmpty agar edit di QGIS tidak error
    _create_snapshot(gpkg_path)
    save_schema_snapshot(gpkg_path, columns)

    import datetime
    conn = sqlite3.connect(gpkg_path)
    conn.execute(
        "INSERT OR REPLACE INTO _sketsa_meta (key, value) VALUES ('last_sync', ?)",
        (datetime.datetime.now().isoformat(),),
    )
    conn.commit()
    conn.close()

    log(f"✅ Refresh selesai! {len(features)} feature diperbarui.")


# ---------------------------------------------------------------------------
# TOPOLOGY — Server-side PostGIS topology operations
# ---------------------------------------------------------------------------

def topology_build(base_url, token, table_name):
    """Trigger topology build on server."""
    url = build_url(base_url, token, "collections", table_name, "topology", "build")
    return api_post(url, {})


def topology_validate(base_url, token, table_name):
    """Request topology validation from server."""
    url = build_url(base_url, token, "collections", table_name, "topology", "validate")
    return api_post(url, {})


def topology_stats(base_url, token, table_name):
    """Get topology stats from server."""
    url = build_url(base_url, token, "collections", table_name, "topology", "stats")
    return api_get(url)


def rename_collection(base_url, token, table_name, new_title, log_fn=None):
    """Ganti nama tampilan layer (datasets.name di server)."""
    from .sketsa_utils import api_patch, build_url

    def log(msg):
        if log_fn:
            log_fn(msg)

    url = build_url(base_url, token, "collections", table_name)
    log(f"✏️ Mengganti nama layer → {new_title}...")
    api_patch(url, {"title": new_title})
    log("✅ Nama layer diperbarui.")


def delete_collection(base_url, token, table_name, gpkg_path=None, log_fn=None):
    """Hapus layer/collection di server (+ file GPKG lokal jika ada)."""
    def log(msg):
        if log_fn:
            log_fn(msg)

    url = build_url(base_url, token, "collections", table_name)
    log(f"🗑️ Menghapus layer di server: {table_name}...")
    api_delete(url)

    if gpkg_path and os.path.exists(gpkg_path):
        release_gpkg_layers(gpkg_path)
        os.remove(gpkg_path)
        log("   ➜ File GPKG lokal dihapus.")
    log("✅ Layer berhasil dihapus.")


# ---------------------------------------------------------------------------
# Internal Helpers
# ---------------------------------------------------------------------------

def release_gpkg_layers(gpkg_path):
    """Lepas layer QGIS yang mengunci file GPKG (penting di Windows)."""
    try:
        from qgis.core import QgsProject
    except ImportError:
        return

    norm = os.path.normpath(gpkg_path).lower()
    to_remove = []
    for layer in QgsProject.instance().mapLayers().values():
        try:
            if layer.providerType() != "ogr":
                continue
            src = os.path.normpath(layer.source().split("|")[0]).lower()
            if src == norm:
                to_remove.append(layer.id())
        except Exception:
            continue
    for lid in to_remove:
        QgsProject.instance().removeMapLayer(lid)


def _drop_spatialite_triggers(conn):
    """Hapus trigger SpatiaLite yang pakai ST_IsEmpty — tidak tersedia di SQLite murni.

    Trigger ini dibuat otomatis oleh OGR/SpatiaLite saat membuat GPKG, tapi
    karena QGIS plugin ini jalan di SQLite tanpa SpatiaLite extension, trigger
    ini menyebabkan error 'no such function: ST_IsEmpty' saat user menambah/
    mengedit feature.
    """
    triggers = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger'"
    ).fetchall()
    for name, sql in triggers:
        if sql and "ST_IsEmpty" in sql:
            conn.execute(f'DROP TRIGGER IF EXISTS "{name}"')
    conn.commit()


def _drop_spatialite_triggers_on_path(gpkg_path):
    """Versi path dari _drop_spatialite_triggers."""
    conn = sqlite3.connect(gpkg_path)
    _drop_spatialite_triggers(conn)
    conn.close()


def _disable_table_triggers(conn, table):
    saved = []
    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?",
        (table,),
    ).fetchall()
    for name, sql in rows:
        if sql:
            saved.append((name, sql))
        conn.execute(f'DROP TRIGGER IF EXISTS "{name}"')
    return saved


def _restore_triggers(conn, saved):
    for _name, sql in saved:
        try:
            conn.execute(sql)
        except Exception:
            pass


def _ensure_tracking_tables(conn):
    """Buat tabel internal sketsa jika belum ada (mis. setelah download gagal)."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS _sketsa_meta (key TEXT PRIMARY KEY, value TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS _sketsa_schema_snap "
        "(column_name TEXT PRIMARY KEY, column_type TEXT)"
    )
    cols_info = conn.execute("PRAGMA table_info(layer_data)").fetchall()
    col_defs = ", ".join(
        [f'"{r[1]}" {r[2]}' for r in cols_info if r[1] != "fid"]
    )
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='_sketsa_snapshot'"
    ).fetchone()
    if not exists:
        if col_defs:
            conn.execute(
                f"CREATE TABLE _sketsa_snapshot (fid INTEGER PRIMARY KEY, {col_defs})"
            )
        else:
            conn.execute("CREATE TABLE _sketsa_snapshot (fid INTEGER PRIMARY KEY)")
    conn.commit()


def _normalize_layer_schema_on_path(gpkg_path):
    conn = sqlite3.connect(gpkg_path)
    _normalize_layer_schema(conn)
    conn.close()

def _table_column_names(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _normalize_layer_schema(conn):
    """Pastikan layer_data punya fid (baris lokal) dan id (ID server).

    Variasi skema dari ogr2ogr:
    - FID=id (lama): kolom id ada, fid tidak → tambah fid
    - FID=fid (baru): nilai server di fid, id tidak ada → tambah id dari fid
    """
    saved = _disable_table_triggers(conn, "layer_data")
    try:
        layer_cols = _table_column_names(conn, "layer_data")

        if "id" not in layer_cols and "fid" in layer_cols:
            conn.execute("ALTER TABLE layer_data ADD COLUMN id INTEGER")
            conn.execute("UPDATE layer_data SET id = fid")
        elif "fid" not in layer_cols and "id" in layer_cols:
            conn.execute("ALTER TABLE layer_data ADD COLUMN fid INTEGER")
            conn.execute("UPDATE layer_data SET fid = rowid")
        elif "fid" not in layer_cols and "id" not in layer_cols:
            conn.execute("ALTER TABLE layer_data ADD COLUMN fid INTEGER")
            conn.execute("ALTER TABLE layer_data ADD COLUMN id INTEGER")
            conn.execute("UPDATE layer_data SET fid = rowid")

        try:
            snap_cols = _table_column_names(conn, "_sketsa_snapshot")
        except Exception:
            snap_cols = set()
        if snap_cols and "id" not in snap_cols and "fid" in snap_cols:
            conn.execute("ALTER TABLE _sketsa_snapshot ADD COLUMN id INTEGER")
            conn.execute("UPDATE _sketsa_snapshot SET id = fid")
    finally:
        _restore_triggers(conn, saved)

    conn.commit()


def _fetch_columns(base_url, token, table_name):
    """GET /collections/{table}/columns → list of {name, type}"""
    url = build_url(base_url, token, "collections", table_name, "columns")
    return api_get(url)


def _fetch_collection_info(base_url, token, table_name):
    """GET /collections/{table} → collection metadata including geom_type, srid"""
    url = build_url(base_url, token, "collections", table_name)
    info = api_get(url)
    # Extract geom_type from description "PostGIS Layer: Name (TYPE)"
    desc = info.get("description", "")
    geom_type = "POINT"
    for gt in ("MULTIPOLYGON", "POLYGON", "MULTILINESTRING", "LINESTRING", "MULTIPOINT", "POINT"):
        if gt in desc.upper():
            geom_type = gt
            break
    return {"geom_type": geom_type, "srid": 4326}


def _fetch_all_items(base_url, token, table_name):
    """GET /collections/{table}/items → semua halaman GeoJSON features."""
    features = []
    offset = 0
    page_size = 1000
    while True:
        url = (
            build_url(base_url, token, "collections", table_name, "items")
            + f"&limit={page_size}&offset={offset}"
        )
        data = api_get(url)
        batch = data.get("features") or []
        if not batch:
            break
        features.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return features


def _insert_features_to_gpkg(gpkg_path, features, columns):
    """Insert GeoJSON features into the GPKG layer_data table."""
    from osgeo import ogr, osr

    ds = ogr.Open(gpkg_path, 1)  # 1 = update mode
    lyr = ds.GetLayerByName("layer_data")
    lyr_defn = lyr.GetLayerDefn()

    for feat_json in features:
        feat = ogr.Feature(lyr_defn)

        # Server ID
        server_id = feat_json.get("id")
        if server_id is not None:
            feat.SetField("id", int(server_id))

        # Geometry
        geom_json = feat_json.get("geometry")
        if geom_json:
            geom_str = json.dumps(geom_json)
            geom = ogr.CreateGeometryFromJson(geom_str)
            if geom:
                feat.SetGeometry(geom)

        # Properties
        props = feat_json.get("properties", {})
        for key, val in props.items():
            if key in ("id", "geom", "create_gn", "update_gn"):
                continue
            idx = lyr_defn.GetFieldIndex(key)
            if idx >= 0 and val is not None:
                feat.SetField(idx, val)

        lyr.CreateFeature(feat)
        feat = None

    ds = None  # flush & close


def _create_snapshot(gpkg_path):
    """Copy current layer_data into _sketsa_snapshot (baseline for diff)."""
    conn = sqlite3.connect(gpkg_path)
    _ensure_tracking_tables(conn)

    cols_info = conn.execute("PRAGMA table_info(layer_data)").fetchall()
    col_names = [r[1] for r in cols_info if r[1] != "fid"]

    if not col_names:
        conn.close()
        return

    cols_str = ", ".join([f'"{c}"' for c in col_names])

    saved = _disable_table_triggers(conn, "layer_data")
    try:
        conn.execute("DELETE FROM _sketsa_snapshot")
        snap_cols = {
            r[1] for r in conn.execute("PRAGMA table_info(_sketsa_snapshot)").fetchall()
        }
        for col_name in col_names:
            if col_name not in snap_cols:
                col_type = "TEXT"
                for r in cols_info:
                    if r[1] == col_name:
                        col_type = r[2] or "TEXT"
                        break
                try:
                    conn.execute(
                        f'ALTER TABLE _sketsa_snapshot ADD COLUMN "{col_name}" {col_type}'
                    )
                except Exception:
                    pass

        conn.execute(
            f"INSERT INTO _sketsa_snapshot ({cols_str}) "
            f"SELECT {cols_str} FROM layer_data"
        )
        conn.commit()
    finally:
        _restore_triggers(conn, saved)
    conn.close()


def _json_safe_value(val):
    """Nilai yang aman untuk json.dumps (datetime, bytes, dll.)."""
    if val is None:
        return None
    if isinstance(val, memoryview):
        val = bytes(val)
    if isinstance(val, bytes):
        try:
            return val.decode("utf-8")
        except UnicodeDecodeError:
            return val.hex()
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return val


def _gpkg_blob_to_geojson_geometry(geom_blob):
    """Fallback: decode geom blob (format GeoPackage GP… + WKB)."""
    from osgeo import ogr

    if geom_blob is None:
        return None
    raw = bytes(geom_blob)
    if not raw:
        return None

    def _wkb_to_geojson(wkb_bytes):
        try:
            geom = ogr.CreateGeometryFromWkb(wkb_bytes)
            if geom and not geom.IsEmpty():
                return json.loads(geom.ExportToJson())
        except Exception:
            pass
        return None

    try:
        if raw[0:2] != b"GP":
            return _wkb_to_geojson(raw)

        if len(raw) < 5:
            return None
        flags = raw[3]
        if flags & 0x08:
            return None
        env_code = flags & 0x07
        envelope_sizes = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
        wkb_start = 4 + envelope_sizes.get(env_code, 0)
        if wkb_start >= len(raw):
            return None
        return _wkb_to_geojson(raw[wkb_start:])
    except Exception:
        return None


def _read_geometry_from_gpkg(gpkg_path, fid=None, server_id=None):
    """Baca geometri via OGR — cara paling andal untuk file GPKG di QGIS."""
    from osgeo import ogr

    ds = ogr.Open(gpkg_path)
    if not ds:
        return None
    lyr = ds.GetLayerByName("layer_data")
    if not lyr:
        return None

    feat = None
    if fid is not None:
        try:
            feat = lyr.GetFeature(int(fid))
        except Exception:
            feat = None
    if feat is None and server_id is not None:
        try:
            lyr.SetAttributeFilter(f"id = {int(server_id)}")
            feat = lyr.GetNextFeature()
        finally:
            lyr.SetAttributeFilter(None)

    if not feat:
        return None
    geom = feat.GetGeometryRef()
    if geom and not geom.IsEmpty():
        return json.loads(geom.ExportToJson())
    return None


def _feature_dict_to_geojson(feat_dict, gpkg_path=None):
    """Convert a feature dict (from diff) to GeoJSON for sending to server."""
    geojson = {
        "type": "Feature",
        "geometry": None,
        "properties": {},
    }

    if gpkg_path:
        geojson["geometry"] = _read_geometry_from_gpkg(
            gpkg_path,
            fid=feat_dict.get("fid"),
            server_id=feat_dict.get("id"),
        )

    if not geojson["geometry"]:
        geom_blob = feat_dict.get("_geom_blob") or feat_dict.get("geom")
        geojson["geometry"] = _gpkg_blob_to_geojson_geometry(geom_blob)

    skip = ("fid", "geom", "id", "_local_fid", "_geom_blob", "create_gn", "update_gn")
    for key, val in feat_dict.items():
        if key in skip:
            continue
        geojson["properties"][key] = _json_safe_value(val)

    return geojson


def _get_current_columns(gpkg_path):
    """Get current column schema from GPKG layer_data table."""
    conn = sqlite3.connect(gpkg_path)
    cols = []
    for row in conn.execute("PRAGMA table_info(layer_data)").fetchall():
        name = row[1]
        if name not in ("fid", "id", "geom"):
            cols.append({"name": name, "type": row[2] or "TEXT"})
    conn.close()
    return cols


def get_sync_status(gpkg_path):
    """Check if a GPKG has local changes pending push.

    Returns
    -------
    str — "synced", "modified", or "unknown"
    """
    try:
        diff = compute_diff(gpkg_path)
        return "modified" if diff.has_changes else "synced"
    except Exception:
        return "unknown"


def get_meta(gpkg_path, key, default=""):
    """Read a value from _sketsa_meta."""
    try:
        conn = sqlite3.connect(gpkg_path)
        row = conn.execute(
            "SELECT value FROM _sketsa_meta WHERE key = ?", (key,)
        ).fetchone()
        conn.close()
        return row[0] if row else default
    except Exception:
        return default

# ---------------------------------------------------------------------------
# DIRECT UPLOAD (QGIS -> SERVER)
# ---------------------------------------------------------------------------

def upload_layer_to_server(layer, base_url, token, display_name=None):
    """Directly upload a QGIS QgsVectorLayer to the server via GPKG."""
    from qgis.core import QgsVectorFileWriter, QgsCoordinateTransformContext
    from .sketsa_utils import api_post_file, build_url
    import tempfile
    import re

    layer_title = (display_name or layer.name() or "layer").strip()
    safe_file = re.sub(r"[^\w\-.]+", "_", layer_title)[:80] or "layer"
    if not safe_file.lower().endswith(".gpkg"):
        safe_file = f"{safe_file}.gpkg"

    temp_dir = tempfile.mkdtemp()
    temp_gpkg = os.path.join(temp_dir, safe_file)

    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = layer.name()

    error = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, temp_gpkg, QgsCoordinateTransformContext(), options
    )
    if error[0] != QgsVectorFileWriter.NoError:
        raise Exception(f"Gagal mengekspor layer ke GPKG lokal: {error[0]}")

    url_upload = build_url(base_url, token, "upload_gpkg")
    resp = api_post_file(
        url_upload, temp_gpkg, layer_name=layer_title, upload_filename=safe_file
    )
    
    # Clean up temp file
    try:
        os.remove(temp_gpkg)
        os.rmdir(temp_dir)
    except:
        pass
        
    table_name = resp.get("table_name")
    if not table_name:
        raise Exception("Gagal mendapatkan nama tabel dari server.")
        
    return {
        "name": resp.get("name", layer_title),
        "table_name": table_name,
        "feature_count": resp.get("feature_count", 0),
    }