import re

path = r'c:\docker\gisnas\gisnas_sketsa\sketsa_engine.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

pull_code = '''def pull_collection(base_url, token, table_name, log_fn=None):
    """Download a full collection from server as GPKG and create a local GPKG."""
    def log(msg):
        if log_fn:
            log_fn(msg)

    import os
    import sqlite3
    import datetime
    from .sketsa_utils import gpkg_path_for, api_download_file, build_url

    gpkg_path = gpkg_path_for(base_url, token, table_name)
    
    # 1. Download GPKG directly from server
    url_download = build_url(base_url, token, "download_gpkg") + f"&table_name={table_name}"
    log(f"📥 Mengunduh GPKG utuh dari server (Cepat): {table_name}...")
    
    try:
        if os.path.exists(gpkg_path):
            os.remove(gpkg_path)
        api_download_file(url_download, gpkg_path)
    except Exception as e:
        raise Exception(f"Gagal mengunduh file GPKG: {e}")
        
    log("📦 Menyiapkan schema GPKG lokal...")
    conn = sqlite3.connect(gpkg_path)
    
    # Rename the exported table to layer_data
    try:
        conn.execute(f"ALTER TABLE '{table_name}' RENAME TO layer_data")
        conn.execute(f"UPDATE gpkg_contents SET table_name = 'layer_data' WHERE table_name = '{table_name}'")
        conn.execute(f"UPDATE gpkg_geometry_columns SET table_name = 'layer_data' WHERE table_name = '{table_name}'")
        conn.execute(f"UPDATE gpkg_extensions SET table_name = 'layer_data' WHERE table_name = '{table_name}'")
        conn.commit()
    except Exception as e:
        print("Rename table warning:", e)

    # Create snapshot (baseline for future diffs)
    log("📸 Membuat snapshot baseline...")
    conn.execute("DROP TABLE IF EXISTS _sketsa_snapshot")
    conn.execute("CREATE TABLE _sketsa_snapshot AS SELECT * FROM layer_data")

    # Save schema snapshot
    cols = []
    for row in conn.execute("PRAGMA table_info(layer_data)").fetchall():
        if row[1] not in ("fid", "id", "geom"):
            cols.append({"name": row[1], "type": row[2]})
    
    conn.execute("CREATE TABLE IF NOT EXISTS _sketsa_schema_snap (column_name TEXT PRIMARY KEY, column_type TEXT)")
    conn.execute("DELETE FROM _sketsa_schema_snap")
    for col in cols:
        conn.execute("INSERT INTO _sketsa_schema_snap VALUES (?, ?)", (col["name"], col["type"]))

    # Store sync metadata
    conn.execute("CREATE TABLE IF NOT EXISTS _sketsa_meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT OR REPLACE INTO _sketsa_meta (key, value) VALUES ('last_sync', ?)", (datetime.datetime.now().isoformat(),))
    conn.execute("INSERT OR REPLACE INTO _sketsa_meta (key, value) VALUES ('base_url', ?)", (base_url,))
    conn.execute("INSERT OR REPLACE INTO _sketsa_meta (key, value) VALUES ('token', ?)", (token,))
    conn.commit()
    conn.close()

    log(f"✅ Download selesai! File GPKG berhasil diperbarui secara lokal.")
    return gpkg_path'''

content = re.sub(r'def pull_collection.*?return gpkg_path', pull_code, content, flags=re.DOTALL)

upload_code = '''def upload_layer_to_server(layer, base_url, token):
    """Directly upload a QGIS QgsVectorLayer to the server via GPKG."""
    from qgis.core import QgsVectorFileWriter, QgsCoordinateTransformContext
    from .sketsa_utils import api_post_file, build_url
    import tempfile
    import os
    
    # 1. Export layer to temp GPKG
    temp_dir = tempfile.mkdtemp()
    temp_gpkg = os.path.join(temp_dir, "upload.gpkg")
    
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = layer.name()
    
    error = QgsVectorFileWriter.writeAsVectorFormatV3(layer, temp_gpkg, QgsCoordinateTransformContext(), options)
    if error[0] != QgsVectorFileWriter.NoError:
        raise Exception(f"Gagal mengekspor layer ke GPKG lokal: {error[0]}")
        
    # 2. Upload GPKG to server
    url_upload = build_url(base_url, token, "upload_gpkg")
    resp = api_post_file(url_upload, temp_gpkg)
    
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
        "table_name": table_name,
        "feature_count": resp.get("feature_count", 0)
    }'''

content = re.sub(r'def upload_layer_to_server.*?feature_count\n    \}', upload_code, content, flags=re.DOTALL)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print('Done modifying sketsa_engine.py')
