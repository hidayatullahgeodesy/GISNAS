# GISNAS Project Summary (Gemini Context)

This file serves as a knowledge base and summary of the GISNAS (Geographic Information System Network Attached Storage) project, its architecture, and the recent fixes that have been applied.

## Architecture Overview

1. **Backend (Go + PostgreSQL/PostGIS)**
   - **Role:** Central server handling spatial data, REST APIs, and vector tiles.
   - **Key Endpoints:** OGC API Features (`/api/ogc/features/...`), Vector Tiles (`/api/tiles/`), SHP Upload (`/api/upload`), Authentication (`/api/login`).
   - **Dependencies:** `ogr2ogr` (GDAL) for shapefile importing into PostGIS.
   - **Database:** PostgreSQL with PostGIS extension. Uses `geometry` columns and relies on `ST_AsMVT`, `ST_AsGeoJSON`, and `ST_Transform`.

2. **Frontend (React + Vite + MapLibre GL JS)**
   - **Role:** Web dashboard for managing workspaces, datasets, styling maps, and data tabular editing.
   - **Styling:** Vanilla CSS (`index.css` and `App.css`).
   - **Map:** Uses MapLibre GL to render Vector Tiles (MVT) directly from the Go backend.

3. **QGIS Plugin (Python + PyQt)**
   - **Role:** Allows QGIS users to connect to the GISNAS server, download datasets locally as GPKG, make local edits, and sync (push) changes back to the server using Delta Sync.
   - **Compatibility:** QGIS 3 and QGIS 4 (PyQt5 and PyQt6 compatibility).

## Recent Fixes & Improvements

1. **PyQt6 Compatibility (QGIS 4)**
   - Fixed `QMessageBox.Yes` to fallback correctly to `QMessageBox.StandardButton.Yes`.
   - Fixed `QDialog.Accepted` to fallback correctly to `QDialog.DialogCode.Accepted`.
   - Ensures the plugin loads and runs perfectly on the latest QGIS 4.0.

2. **GDAL PostgreSQL Driver Error**
   - **Issue:** Web upload failed with `ERROR 1: Unable to find driver PostgreSQL`.
   - **Fix:** Switched the `backend/Dockerfile` base image from `golang:1.21-alpine` to `golang:1.21-bullseye` (Debian) which includes full PostgreSQL support in `gdal-bin`.

3. **Attributes Becoming NULL after QGIS Upload**
   - **Issue:** Pushing features from QGIS resulted in geometries being saved but all attributes becoming NULL in the database.
   - **Fix:** Added case-insensitive sanitization (`sanitizeIdentifier`) when matching QGIS property keys against PostGIS columns in the `POST /items`, `PUT /items`, and `PATCH /items` endpoints.

4. **HTTP 500 Error on Download & Map Render (Reserved Keywords)**
   - **Issue:** Downloading datasets via QGIS Plugin or viewing them on the Web Map failed with HTTP 500.
   - **Fix:** Safely wrapped all dynamic column names with double quotes (`"colName"`) in `main.go` SQL queries (`SELECT`, `INSERT`, `UPDATE`). This prevents PostgreSQL syntax crashes when shapefiles have columns named after reserved keywords (e.g., `DESC`, `ORDER`, `TYPE`, `USER`).

5. **UI Translation (Indonesian to English)**
   - Translated the vast majority of hardcoded UI strings in both the React Frontend (`App.jsx`) and the QGIS Plugin (`sketsa_dialogs.py`).

## Notes for Future Agent (Gemini)
- If the database throws syntax errors, check how column names are queried from `information_schema.columns`. Always quote them!
- OGC API Features responses must closely follow GeoJSON structure.
- When working with QGIS plugin Python code, always use the `try-except AttributeError` blocks for PyQt5 vs PyQt6 flags compatibility.
- Ensure Docker containers (`gisnas_backend`, `gisnas_db`, `gisnas_frontend`) are rebuilt after significant changes.
