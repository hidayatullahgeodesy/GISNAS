"""
sketsa_import.py — Import module for GISNAS Sketsa.

Handles importing data from external files (SHP, KML, GPKG, GeoJSON)
into the local GPKG with field mapping support.
"""

import json
import sqlite3
from qgis.core import (
    QgsVectorLayer,
    QgsFeature,
    QgsGeometry,
    QgsField,
    QgsFields,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant
from .sketsa_utils import add_column_to_gpkg


def get_source_fields(file_path):
    """Read field definitions from an external file.

    Parameters
    ----------
    file_path : str — path to SHP, KML, GPKG, or GeoJSON

    Returns
    -------
    list[dict] — [{"name": "field_name", "type": "String"}, ...]
    """
    layer = QgsVectorLayer(file_path, "source_inspect", "ogr")
    if not layer.isValid():
        raise ValueError(f"No bisa membuka file: {file_path}")

    fields = []
    for field in layer.fields():
        fields.append({
            "name": field.name(),
            "type": QVariant.typeToName(field.type()),
            "type_name": field.typeName(),
        })
    return fields


def get_source_geom_type(file_path):
    """Get geometry type name from source file."""
    layer = QgsVectorLayer(file_path, "source_inspect", "ogr")
    if not layer.isValid():
        return "Unknown"
    return QgsWkbTypes.displayString(layer.wkbType())


def get_target_fields(gpkg_path):
    """Read field definitions from the local GPKG layer_data table.

    Returns
    -------
    list[dict] — [{"name": "col_name", "type": "TEXT"}, ...]
    """
    conn = sqlite3.connect(gpkg_path)
    fields = []
    for row in conn.execute("PRAGMA table_info(layer_data)").fetchall():
        name = row[1]
        if name in ("fid", "geom"):
            continue
        fields.append({"name": name, "type": row[2] or "TEXT"})
    conn.close()
    return fields


def preview_data(file_path, limit=5):
    """Read first N features for preview display.

    Returns
    -------
    tuple(list[str], list[list]) — (column_names, rows)
    """
    layer = QgsVectorLayer(file_path, "preview", "ogr")
    if not layer.isValid():
        return [], []

    col_names = [f.name() for f in layer.fields()]
    rows = []
    for i, feat in enumerate(layer.getFeatures()):
        if i >= limit:
            break
        row = []
        for name in col_names:
            val = feat[name]
            row.append(str(val) if val is not None else "")
        rows.append(row)

    return col_names, rows


def import_with_mapping(source_path, gpkg_path, field_map,
                        create_missing_columns=False, log_fn=None):
    """Import features from source file to local GPKG with field mapping.

    Parameters
    ----------
    source_path : str — path to SHP/KML/GPKG/GeoJSON
    gpkg_path : str — path to local GPKG (target)
    field_map : dict — {"source_field": "target_field", ...}
                       If target_field is "(Abaikan)" or None, skip that field.
                       If target_field starts with "(Buat Baru)", create new column.
    create_missing_columns : bool — auto-create target columns for unmapped fields
    log_fn : callable — optional logging callback

    Returns
    -------
    dict — {"imported": int, "skipped": int, "errors": int}
    """
    def log(msg):
        if log_fn:
            log_fn(msg)

    # Open source layer
    src_layer = QgsVectorLayer(source_path, "import_source", "ogr")
    if not src_layer.isValid():
        raise ValueError(f"No bisa membuka file sumber: {source_path}")

    # Open target GPKG layer
    target_uri = f"{gpkg_path}|layername=layer_data"
    tgt_layer = QgsVectorLayer(target_uri, "import_target", "ogr")
    if not tgt_layer.isValid():
        raise ValueError(f"No bisa membuka GPKG target: {gpkg_path}")

    # Get existing target fields
    tgt_field_names = {f.name() for f in tgt_layer.fields()}

    # Resolve field mapping — create missing columns if needed
    resolved_map = {}  # source_field → target_field
    for src_field, tgt_field in field_map.items():
        if not tgt_field or tgt_field == "(Abaikan)":
            continue

        if tgt_field.startswith("(Buat Baru)"):
            # Create new column with same name as source
            new_col_name = src_field.lower().replace(" ", "_")
            # Determine type from source field
            src_type = _get_source_field_type(src_layer, src_field)
            sqlite_type = _qvariant_to_sqlite(src_type)
            log(f"   ➕ Membuat kolom baru: {new_col_name} ({sqlite_type})")
            add_column_to_gpkg(gpkg_path, new_col_name, sqlite_type)
            resolved_map[src_field] = new_col_name
        elif tgt_field in tgt_field_names or tgt_field == "id":
            resolved_map[src_field] = tgt_field
        else:
            log(f"   ⚠️ Kolom target '{tgt_field}' tidak ditemukan, skip {src_field}")

    if create_missing_columns:
        # Auto-create columns for source fields not in field_map
        for field in src_layer.fields():
            src_name = field.name()
            if src_name not in field_map:
                col_name = src_name.lower().replace(" ", "_")
                if col_name not in tgt_field_names and col_name not in ("fid", "geom", "id"):
                    sqlite_type = _qvariant_to_sqlite(field.type())
                    log(f"   ➕ Auto-create kolom: {col_name} ({sqlite_type})")
                    add_column_to_gpkg(gpkg_path, col_name, sqlite_type)
                    resolved_map[src_name] = col_name

    if not resolved_map:
        log("⚠️ No ada field mapping yang valid. Import dibatalkan.")
        return {"imported": 0, "skipped": 0, "errors": 0}

    # Re-open target layer after schema changes
    tgt_layer = QgsVectorLayer(target_uri, "import_target", "ogr")
    if not tgt_layer.isValid():
        raise ValueError("Gagal membuka GPKG setelah perubahan skema")

    # Start editing
    tgt_layer.startEditing()

    result = {"imported": 0, "skipped": 0, "errors": 0}

    for src_feat in src_layer.getFeatures():
        try:
            new_feat = QgsFeature(tgt_layer.fields())

            # Geometry — transform if needed
            geom = src_feat.geometry()
            if geom and not geom.isNull():
                new_feat.setGeometry(geom)
            else:
                result["skipped"] += 1
                continue

            # Map attributes
            for src_field, tgt_field in resolved_map.items():
                if tgt_field == "id":
                    continue  # Don't copy ID, let it be NULL (new feature)
                val = src_feat[src_field]
                idx = tgt_layer.fields().indexOf(tgt_field)
                if idx >= 0 and val is not None:
                    new_feat.setAttribute(idx, val)

            # id = NULL → marks as new (locally created, will be pushed later)
            id_idx = tgt_layer.fields().indexOf("id")
            if id_idx >= 0:
                new_feat.setAttribute(id_idx, None)

            tgt_layer.addFeature(new_feat)
            result["imported"] += 1

        except Exception as e:
            result["errors"] += 1
            log(f"   ❌ Error pada feature: {e}")

    # Commit
    if not tgt_layer.commitChanges():
        log(f"   ❌ Gagal commit: {tgt_layer.commitErrors()}")
        result["errors"] += result["imported"]
        result["imported"] = 0
    else:
        log(f"✅ Import selesai: {result['imported']} feature diimpor")

    return result


def _get_source_field_type(layer, field_name):
    """Get QVariant type for a field in a layer."""
    idx = layer.fields().indexOf(field_name)
    if idx >= 0:
        return layer.fields().at(idx).type()
    return QVariant.String


def _qvariant_to_sqlite(qvariant_type):
    """Map QVariant type to SQLite column type string."""
    mapping = {
        QVariant.Int: "INTEGER",
        QVariant.LongLong: "INTEGER",
        QVariant.Double: "REAL",
        QVariant.Bool: "INTEGER",
        QVariant.Date: "TEXT",
        QVariant.DateTime: "TEXT",
        QVariant.Time: "TEXT",
    }
    return mapping.get(qvariant_type, "TEXT")
