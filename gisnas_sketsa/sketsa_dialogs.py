"""
sketsa_dialogs.py — All UI dialogs for GISNAS Sketsa plugin.

Contains:
- SketsaPanel: main connection/sync panel
- ImportDialog: import from external files with field mapping
- DiffPreviewDialog: preview changes before push
- TopologyDialog: server-side topology operations
"""

import os
from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QDialog, QDockWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QTextEdit,
    QComboBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QCheckBox, QFileDialog, QMessageBox, QGroupBox,
    QProgressBar, QSplitter, QWidget, QAbstractItemView, QApplication
)
from qgis.core import QgsVectorLayer, QgsProject


# ---------------------------------------------------------------------------
# Worker thread for async operations
# ---------------------------------------------------------------------------

try:
    USER_ROLE = Qt.ItemDataRole.UserRole
    ITEM_IS_EDITABLE = Qt.ItemFlag.ItemIsEditable
    MSG_YES = QMessageBox.StandardButton.Yes
    MSG_NO = QMessageBox.StandardButton.No
    DLG_ACCEPTED = QDialog.DialogCode.Accepted
except AttributeError:
    USER_ROLE = Qt.UserRole
    ITEM_IS_EDITABLE = Qt.ItemIsEditable
    MSG_YES = QMessageBox.Yes
    MSG_NO = QMessageBox.No
    DLG_ACCEPTED = QDialog.Accepted

class _Worker(QThread):
    log_signal = pyqtSignal(str)
    done_signal = pyqtSignal(object)
    error_signal = pyqtSignal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            self.kwargs["log_fn"] = lambda msg: self.log_signal.emit(msg)
            result = self.fn(*self.args, **self.kwargs)
            self.done_signal.emit(result)
        except Exception as e:
            self.error_signal.emit(str(e))


# ═══════════════════════════════════════════════════════════════════════════
# MAIN PANEL
# ═══════════════════════════════════════════════════════════════════════════

class SketsaPanel(QDockWidget):
    """Panel dock GISNAS Sketsa — bisa dipindah, di-dock, atau diminimize di tepi QGIS."""

    def __init__(self, iface):
        super().__init__("GISNAS Sketsa — Local GPKG + Delta Sync", iface.mainWindow())
        self.iface = iface
        self.setObjectName("GisnasSketsaDockWidget")
        self.setMinimumWidth(480)
        try:
            dock_features = (
                QDockWidget.DockWidgetClosable
                | QDockWidget.DockWidgetMovable
                | QDockWidget.DockWidgetFloatable
            )
        except AttributeError:
            dock_features = (
                QDockWidget.DockWidgetClosable
                | QDockWidget.DockWidgetMovable
                | QDockWidget.DockWidgetFloatable
            )
        self.setFeatures(dock_features)

        self._worker = None
        self._busy = False
        self._connected = False

        # State
        self.base_url = ""
        self.token = ""
        self.collections = []  # list of {"id": table_name, "title": name, ...}

        self._content = QWidget()
        self.setWidget(self._content)
        self._init_ui()
        self._apply_ui_state()

    def closeEvent(self, event):
        """Tutup = sembunyikan panel (bisa dibuka lagi dari toolbar)."""
        event.ignore()
        self.hide()

    def _init_ui(self):
        layout = QVBoxLayout(self._content)

        # --- Connection ---
        grp_conn = QGroupBox("🔗 OGC API Connection")
        conn_layout = QVBoxLayout()
        conn_layout.addWidget(QLabel("OGC API URL (with token):"))
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(
            "http://host/token/GISNAS-xxxx/api/ogc/features"
        )
        conn_layout.addWidget(self.url_input)

        self.lbl_conn_status = QLabel("● Belum terhubung")
        self.lbl_conn_status.setStyleSheet("color: #64748b; font-size: 0.85rem;")
        conn_layout.addWidget(self.lbl_conn_status)

        conn_btn_row = QHBoxLayout()
        self.btn_connect = QPushButton("🔌 Connect")
        self.btn_connect.setStyleSheet(
            "background-color: #3b82f6; color: white; font-weight: bold; padding: 6px;"
        )
        self.btn_connect.clicked.connect(self._on_connect)
        conn_btn_row.addWidget(self.btn_connect)

        self.btn_disconnect = QPushButton("⏏ Disconnect")
        self.btn_disconnect.setStyleSheet(
            "background-color: #64748b; color: white; font-weight: bold; padding: 6px;"
        )
        self.btn_disconnect.clicked.connect(self._on_disconnect)
        conn_btn_row.addWidget(self.btn_disconnect)
        conn_layout.addLayout(conn_btn_row)

        hint = QLabel(
            "Panel bisa di-dock kiri/kanan QGIS, dilepas (float), atau diminimize ke tab tepi jendela."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #94a3b8; font-size: 0.75rem;")
        conn_layout.addWidget(hint)

        grp_conn.setLayout(conn_layout)
        layout.addWidget(grp_conn)

        # --- Collections ---
        grp_layers = QGroupBox("📂 Layers / Collections")
        layers_layout = QVBoxLayout()
        self.list_collections = QListWidget()
        try:
            self.list_collections.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        except AttributeError:
            self.list_collections.setSelectionMode(QAbstractItemView.SingleSelection)
        layers_layout.addWidget(self.list_collections)

        btn_row = QHBoxLayout()
        self.btn_download = QPushButton("⬇️ Download")
        self.btn_download.setStyleSheet(
            "background-color: #22c55e; color: white; font-weight: bold; padding: 5px;"
        )
        self.btn_download.clicked.connect(self._on_download)
        btn_row.addWidget(self.btn_download)

        self.btn_push = QPushButton("⬆️ Push Changes")
        self.btn_push.setStyleSheet(
            "background-color: #f59e0b; color: white; font-weight: bold; padding: 5px;"
        )
        self.btn_push.clicked.connect(self._on_push)
        btn_row.addWidget(self.btn_push)

        self.btn_refresh = QPushButton("🔄 Refresh")
        self.btn_refresh.clicked.connect(self._on_refresh)
        btn_row.addWidget(self.btn_refresh)

        self.btn_open_folder = QPushButton("📂 Open Folder")
        self.btn_open_folder.setToolTip(
            "Buka folder penyimpanan GPKG lokal (~/.gisnas_sketsa/...).\n"
            "Hapus file .gpkg di sini lalu Download ulang jika perlu reset data.\n"
            "Tutup/hapus layer dari peta QGIS dulu agar file tidak terkunci."
        )
        self.btn_open_folder.clicked.connect(self._on_open_folder)
        btn_row.addWidget(self.btn_open_folder)

        self.btn_rename_layer = QPushButton("✏️ Rename")
        self.btn_rename_layer.clicked.connect(self._on_rename_layer)
        btn_row.addWidget(self.btn_rename_layer)

        self.btn_delete_layer = QPushButton("🗑️ Hapus Layer")
        self.btn_delete_layer.setStyleSheet(
            "background-color: #ef4444; color: white; font-weight: bold; padding: 5px;"
        )
        self.btn_delete_layer.clicked.connect(self._on_delete_layer)
        btn_row.addWidget(self.btn_delete_layer)

        layers_layout.addLayout(btn_row)

        btn_row2 = QHBoxLayout()
        self.btn_import = QPushButton("📥 Import from File (SHP/KML/GPKG)")
        self.btn_import.clicked.connect(self._on_import)
        btn_row2.addWidget(self.btn_import)

        self.btn_topo = QPushButton("🔺 Topology")
        self.btn_topo.clicked.connect(self._on_topology)
        btn_row2.addWidget(self.btn_topo)

        layers_layout.addLayout(btn_row2)
        
        btn_row3 = QHBoxLayout()
        self.btn_direct_upload = QPushButton("🚀 Direct Upload QGIS Layer to Server")
        self.btn_direct_upload.setStyleSheet(
            "background-color: #8b5cf6; color: white; font-weight: bold; padding: 8px;"
        )
        self.btn_direct_upload.clicked.connect(self._on_direct_upload)
        btn_row3.addWidget(self.btn_direct_upload)
        layers_layout.addLayout(btn_row3)
        
        grp_layers.setLayout(layers_layout)
        layout.addWidget(grp_layers)

        # --- Log ---
        grp_log = QGroupBox("📋 Log")
        log_layout = QVBoxLayout()
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setMaximumHeight(180)
        log_layout.addWidget(self.log_area)
        grp_log.setLayout(log_layout)
        layout.addWidget(grp_log)

    def _log(self, msg):
        self.log_area.append(msg)
        self.log_area.verticalScrollBar().setValue(
            self.log_area.verticalScrollBar().maximum()
        )

    def _get_selected_collection(self):
        item = self.list_collections.currentItem()
        if not item:
            QMessageBox.warning(self, "Warning", "Please select a layer first.")
            return None
        return item.data(USER_ROLE)

    def _get_selected_collection_full(self):
        item = self.list_collections.currentItem()
        if not item:
            QMessageBox.warning(self, "Warning", "Please select a layer first.")
            return None, None
        table_name = item.data(USER_ROLE)
        title = item.data(USER_ROLE + 1)
        return table_name, title

    # --- Connection ---
    def _on_connect(self):
        from .sketsa_utils import parse_ogc_url, api_get, build_url

        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Error", "URL cannot be empty.")
            return

        try:
            self.base_url, self.token = parse_ogc_url(url)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to parse URL: {e}")
            return

        if not self.token:
            QMessageBox.warning(self, "Error", "Token tidak ditemukan di URL.")
            return

        self._log(f"🔌 Connecting to {self.base_url}...")
        try:
            coll_url = build_url(self.base_url, self.token, "collections")
            data = api_get(coll_url)
            self.collections = data.get("collections", [])
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Connection failed: {e}")
            self._log(f"❌ Failed: {e}")
            return

        self._set_connected_state(True)
        self._log(f"✅ Connected! {len(self.collections)} layers found.")

    def _on_disconnect(self):
        if self._worker and self._worker.isRunning():
            QMessageBox.warning(
                self,
                "Sedang berjalan",
                "Tunggu operasi sync selesai sebelum disconnect.",
            )
            return

        if self._connected:
            reply = QMessageBox.question(
                self,
                "Disconnect",
                "Putuskan koneksi ke server GISNAS?\n\n"
                "Daftar layer di panel akan dikosongkan. File GPKG lokal tidak dihapus.",
                MSG_YES | MSG_NO,
            )
            if reply != MSG_YES:
                return

        self.base_url = ""
        self.token = ""
        self.collections = []
        self.list_collections.clear()
        self._set_connected_state(False)
        self._log("⏏ Disconnected — siap koneksi baru.")

    def _set_connected_state(self, connected):
        self._connected = bool(connected)
        self._apply_ui_state()

    def _set_busy(self, busy):
        self._busy = bool(busy)
        self._apply_ui_state()

    def _apply_ui_state(self):
        busy = self._busy
        connected = self._connected

        self.btn_connect.setEnabled(not busy and not connected)
        self.btn_disconnect.setEnabled(not busy and connected)
        self.url_input.setEnabled(not busy and not connected)

        sync_enabled = not busy and connected
        self.btn_download.setEnabled(sync_enabled)
        self.btn_push.setEnabled(sync_enabled)
        self.btn_refresh.setEnabled(sync_enabled)
        self.btn_open_folder.setEnabled(not busy)
        self.btn_rename_layer.setEnabled(sync_enabled)
        self.btn_delete_layer.setEnabled(sync_enabled)
        self.btn_import.setEnabled(sync_enabled)
        self.btn_topo.setEnabled(sync_enabled)
        self.btn_direct_upload.setEnabled(sync_enabled)

        if connected:
            host = self.base_url.replace("http://", "").replace("https://", "")
            self.lbl_conn_status.setText(
                f"● Terhubung ke {host} — {len(self.collections)} layer"
            )
            self.lbl_conn_status.setStyleSheet(
                "color: #16a34a; font-weight: bold; font-size: 0.85rem;"
            )
        else:
            self.lbl_conn_status.setText("● Belum terhubung")
            self.lbl_conn_status.setStyleSheet("color: #64748b; font-size: 0.85rem;")

    def _refresh_collection_list(self):
        from .sketsa_utils import gpkg_path_for
        from .sketsa_engine import get_sync_status

        self.list_collections.clear()
        for col in self.collections:
            table_name = col.get("id", "")
            title = col.get("title", table_name)

            gpkg_path = gpkg_path_for(self.base_url, self.token, table_name)
            if os.path.exists(gpkg_path):
                status = get_sync_status(gpkg_path)
                if status == "modified":
                    icon = "🟡"
                    status_text = "Ada perubahan lokal"
                else:
                    icon = "🟢"
                    status_text = "Synced"
            else:
                icon = "🔵"
                status_text = "Not downloaded"

            display = f"{icon} {title} ({table_name}) — {status_text}"
            item = QListWidgetItem(display)
            item.setData(USER_ROLE, table_name)
            item.setData(USER_ROLE + 1, title)
            self.list_collections.addItem(item)

    def _resolve_conflict(self, gpkg_path):
        from .sketsa_engine import resolve_sync_conflict
        return resolve_sync_conflict(self, gpkg_path)

    def _start_worker(self, fn, done_slot, *args, **kwargs):
        self._worker = _Worker(fn, *args, **kwargs)
        self._worker.log_signal.connect(self._log)
        self._worker.done_signal.connect(done_slot)
        self._worker.error_signal.connect(self._on_worker_error)
        self._worker.start()

    # --- Download ---
    def _on_download(self):
        from .sketsa_engine import pull_collection, prepare_gpkg_for_file_replace
        from .sketsa_utils import gpkg_path_for

        table_name, title = self._get_selected_collection_full()
        if not table_name:
            return

        gpkg_path = gpkg_path_for(self.base_url, self.token, table_name)
        resolution = self._resolve_conflict(gpkg_path)
        if resolution == "cancel":
            return

        self._log(f"\n{'='*50}")
        self._log(f"⬇️ DOWNLOAD: {table_name}")
        self._set_busy(True)

        if resolution == "push_first" and os.path.exists(gpkg_path):
            from .sketsa_engine import push_changes

            def download_after_push(log_fn=None):
                push_changes(
                    gpkg_path, self.base_url, self.token, table_name, log_fn=log_fn
                )
                return pull_collection(
                    self.base_url, self.token, table_name, log_fn=log_fn
                )

            self._start_worker(
                download_after_push,
                lambda path: self._on_download_done(path, table_name, title),
            )
            return

        prepare_gpkg_for_file_replace(gpkg_path)
        self._start_worker(
            pull_collection,
            lambda path: self._on_download_done(path, table_name, title),
            self.base_url,
            self.token,
            table_name,
        )

    def _on_download_done(self, gpkg_path, table_name, title):
        from .sketsa_engine import release_gpkg_layers

        self._set_busy(False)
        self._refresh_collection_list()

        release_gpkg_layers(gpkg_path)
        # Add GPKG layer to QGIS canvas
        uri = f"{gpkg_path}|layername=layer_data"
        layer = QgsVectorLayer(uri, title, "ogr")
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)
            self._log(f"🗺️ Layer '{title}' ditambahkan ke peta QGIS.")
        else:
            self._log(f"⚠️ Failed menambahkan layer ke QGIS.")

    # --- Push ---
    def _on_push(self):
        from .sketsa_engine import compute_diff, push_changes
        from .sketsa_utils import gpkg_path_for

        table_name = self._get_selected_collection()
        if not table_name:
            return

        gpkg_path = gpkg_path_for(self.base_url, self.token, table_name)
        if not os.path.exists(gpkg_path):
            QMessageBox.warning(
                self, "Error", "Layer belum di-download. Download dulu."
            )
            return

        # Compute diff first for preview
        diff = compute_diff(gpkg_path)
        if not diff.has_changes:
            QMessageBox.information(
                self, "Info", "No ada perubahan lokal untuk dikirim."
            )
            return

        # Show preview dialog
        dlg = DiffPreviewDialog(diff, self)
        try:
            res = dlg.exec()
        except AttributeError:
            res = dlg.exec_()
        if res != DLG_ACCEPTED:
            return

        self._log(f"\n{'='*50}")
        self._log(f"⬆️ PUSH: {table_name}")
        self._set_busy(True)

        self._worker = _Worker(
            push_changes, gpkg_path, self.base_url, self.token, table_name
        )
        self._worker.log_signal.connect(self._log)
        self._worker.done_signal.connect(self._on_push_done)
        self._worker.error_signal.connect(self._on_worker_error)
        self._worker.start()

    def _on_push_done(self, results):
        self._set_busy(False)
        self._refresh_collection_list()

        # Reload QGIS layer to reflect new IDs
        self._reload_active_layer()

    def _on_open_folder(self):
        from .sketsa_utils import (
            open_local_folder,
            gpkg_dir_for,
            gpkg_path_for,
            get_sketsa_dir,
        )
        if not self.base_url or not self.token:
            root = get_sketsa_dir()
            self._log(f"📂 Membuka folder utama Sketsa:\n   {root}")
            open_local_folder(root)
            return

        table_name = self._get_selected_collection()
        folder = gpkg_dir_for(self.base_url, self.token)

        if table_name:
            gpkg_path = gpkg_path_for(self.base_url, self.token, table_name)
            if os.path.exists(gpkg_path):
                self._log(f"📂 Folder layer '{table_name}':")
                self._log(f"   {folder}")
                self._log(f"   File: {os.path.basename(gpkg_path)}")
            else:
                self._log(f"📂 Folder layer (belum diunduh) '{table_name}':")
                self._log(f"   {folder}")
        else:
            self._log("📂 Folder koneksi (pilih layer untuk lihat file .gpkg spesifik):")
            self._log(f"   {folder}")

        open_local_folder(folder)

        if table_name:
            gpkg_path = gpkg_path_for(self.base_url, self.token, table_name)
            if os.path.exists(gpkg_path):
                QMessageBox.information(
                    self,
                    "Folder data lokal",
                    f"Folder:\n{folder}\n\n"
                    f"File layer ini:\n{os.path.basename(gpkg_path)}\n\n"
                    "Untuk unduh ulang dari server:\n"
                    "1. Hapus layer dari peta QGIS (Remove Layer)\n"
                    "2. Hapus file .gpkg di folder ini (opsional)\n"
                    "3. Klik Download di panel Sketsa",
                )

    # --- Refresh ---
    def _on_refresh(self):
        from .sketsa_engine import refresh_from_server, prepare_gpkg_for_file_replace
        from .sketsa_utils import gpkg_path_for

        table_name = self._get_selected_collection()
        if not table_name:
            return

        gpkg_path = gpkg_path_for(self.base_url, self.token, table_name)
        if not os.path.exists(gpkg_path):
            QMessageBox.warning(self, "Error", "Layer has not been downloaded.")
            return

        resolution = self._resolve_conflict(gpkg_path)
        if resolution == "cancel":
            return

        self._log(f"\n{'='*50}")
        self._log(f"🔄 REFRESH: {table_name}")
        self._set_busy(True)

        if resolution == "push_first":
            from .sketsa_engine import push_changes

            def refresh_after_push(log_fn=None):
                push_changes(
                    gpkg_path, self.base_url, self.token, table_name, log_fn=log_fn
                )
                refresh_from_server(
                    gpkg_path,
                    self.base_url,
                    self.token,
                    table_name,
                    log_fn=log_fn,
                    use_gpkg=True,
                )

            self._start_worker(refresh_after_push, lambda _: self._on_refresh_done())
            return

        prepare_gpkg_for_file_replace(gpkg_path)

        def do_refresh(log_fn=None):
            # GPKG utuh = lepas lock file, hindari WinError 32 setelah layer dibuka
            refresh_from_server(
                gpkg_path,
                self.base_url,
                self.token,
                table_name,
                log_fn=log_fn,
                use_gpkg=True,
            )

        self._start_worker(do_refresh, lambda _: self._on_refresh_done())

    def _on_refresh_done(self):
        self._set_busy(False)
        self._refresh_collection_list()
        table_name = self._get_selected_collection()
        if table_name:
            from .sketsa_utils import gpkg_path_for
            from .sketsa_engine import release_gpkg_layers

            gpkg_path = gpkg_path_for(self.base_url, self.token, table_name)
            release_gpkg_layers(gpkg_path)
            _, title = self._get_selected_collection_full()
            uri = f"{gpkg_path}|layername=layer_data"
            layer = QgsVectorLayer(uri, title or table_name, "ogr")
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                self._log("🗺️ Layer dimuat ulang setelah refresh.")
            else:
                self._reload_active_layer()
        else:
            self._reload_active_layer()

    # --- Delete layer ---
    def _on_rename_layer(self):
        from .sketsa_engine import rename_collection

        table_name, title = self._get_selected_collection_full()
        if not table_name:
            return

        from qgis.PyQt.QtWidgets import QInputDialog
        new_title, ok = QInputDialog.getText(
            self, "Rename Layer", "Nama layer baru:", text=title or table_name
        )
        if not ok or not new_title.strip():
            return

        try:
            rename_collection(
                self.base_url, self.token, table_name, new_title.strip()
            )
            self._log(f"✅ Layer diganti nama menjadi: {new_title.strip()}")
            self._on_connect()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _on_delete_layer(self):
        from .sketsa_engine import delete_collection, release_gpkg_layers
        from .sketsa_utils import gpkg_path_for

        table_name, title = self._get_selected_collection_full()
        if not table_name:
            return

        gpkg_path = gpkg_path_for(self.base_url, self.token, table_name)
        msg = (
            f"Hapus layer '{title}' ({table_name}) dari server?\n\n"
            "Semua data di PostGIS untuk layer ini akan dihapus permanen."
        )
        if os.path.exists(gpkg_path):
            msg += "\n\nFile GPKG lokal juga akan dihapus."

        confirm = QMessageBox.question(
            self, "Hapus Layer", msg, MSG_YES | MSG_NO,
        )
        if confirm != MSG_YES:
            return

        self._log(f"\n{'='*50}")
        self._log(f"🗑️ DELETE LAYER: {table_name}")
        self._set_busy(True)

        release_gpkg_layers(gpkg_path)
        self._worker = _Worker(
            delete_collection,
            self.base_url,
            self.token,
            table_name,
            gpkg_path if os.path.exists(gpkg_path) else None,
        )
        self._worker.log_signal.connect(self._log)
        self._worker.done_signal.connect(self._on_delete_layer_done)
        self._worker.error_signal.connect(self._on_worker_error)
        self._worker.start()

    def _on_delete_layer_done(self, _result):
        self._set_busy(False)
        self._on_connect()

    # --- Import ---
    def _on_import(self):
        from .sketsa_utils import gpkg_path_for

        table_name = self._get_selected_collection()
        if not table_name:
            return

        gpkg_path = gpkg_path_for(self.base_url, self.token, table_name)
        if not os.path.exists(gpkg_path):
            QMessageBox.warning(self, "Error", "Download layer dulu sebelum import.")
            return

        dlg = ImportDialog(gpkg_path, table_name, self.iface, self)
        try:
            res = dlg.exec()
        except AttributeError:
            res = dlg.exec_()
        if res == DLG_ACCEPTED:
            self._log(f"📥 Import ke {table_name} selesai.")
            self._refresh_collection_list()
            self._reload_active_layer()

    # --- Topology ---
    def _on_topology(self):
        table_name = self._get_selected_collection()
        if not table_name:
            return

        dlg = TopologyDialog(
            self.base_url, self.token, table_name, self.iface, self
        )
        try:
            dlg.exec()
        except AttributeError:
            dlg.exec_()

    # --- Direct Upload ---
    def _on_direct_upload(self):
        if not self.base_url or not self.token:
            QMessageBox.warning(self, "Warning", "Silakan koneksikan ke OGC API terlebih dahulu!")
            return

        dlg = DirectUploadDialog(self.base_url, self.token, self.iface, self)
        try:
            res = dlg.exec()
        except AttributeError:
            res = dlg.exec_()
        if res == DLG_ACCEPTED:
            self._log(f"🚀 Upload langsung selesai!")
            self._on_connect()

    def _on_worker_error(self, error_msg):
        self._set_busy(False)
        self._log(f"❌ Error: {error_msg}")
        QMessageBox.critical(self, "Error", error_msg)

    def _reload_active_layer(self):
        """Reload GPKG layers in QGIS to reflect changes."""
        for layer_id, layer in QgsProject.instance().mapLayers().items():
            if layer.source() and ".gisnas_sketsa" in layer.source():
                layer.reload()
                layer.triggerRepaint()


# ═══════════════════════════════════════════════════════════════════════════
# IMPORT DIALOG
# ═══════════════════════════════════════════════════════════════════════════

class ImportDialog(QDialog):
    """Import from external file (SHP/KML/GPKG) with field mapping."""

    def __init__(self, gpkg_path, table_name, iface, parent=None):
        super().__init__(parent)
        self.gpkg_path = gpkg_path
        self.table_name = table_name
        self.iface = iface
        self.setWindowTitle(f"📥 Import ke {table_name}")
        self.setMinimumSize(650, 550)

        self.source_path = ""
        self.source_fields = []
        self.target_fields = []

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # File picker
        file_layout = QHBoxLayout()
        file_layout.addWidget(QLabel("File Sumber:"))
        self.file_input = QLineEdit()
        self.file_input.setPlaceholderText("Pilih file SHP, KML, GPKG, atau GeoJSON...")
        self.file_input.setReadOnly(True)
        file_layout.addWidget(self.file_input)
        self.btn_browse = QPushButton("📂 Browse")
        self.btn_browse.clicked.connect(self._on_browse)
        file_layout.addWidget(self.btn_browse)
        layout.addLayout(file_layout)

        # Field Mapper
        layout.addWidget(QLabel("🔗 Column Mapping (Field Mapper):"))
        self.mapping_table = QTableWidget(0, 2)
        self.mapping_table.setHorizontalHeaderLabels(["Source Column", "Kolom Tujuan"])
        self.mapping_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.mapping_table)

        # Auto-create checkbox
        self.chk_auto_create = QCheckBox(
            "Buat kolom baru otomatis untuk field sumber yang belum ada di tujuan"
        )
        layout.addWidget(self.chk_auto_create)

        # Preview
        layout.addWidget(QLabel("👁️ Preview Data Sumber (5 baris pertama):"))
        self.preview_table = QTableWidget(0, 0)
        self.preview_table.setMaximumHeight(140)
        layout.addWidget(self.preview_table)

        # Buttons
        btn_layout = QHBoxLayout()
        self.btn_import = QPushButton("📥 Import")
        self.btn_import.setStyleSheet(
            "background-color: #22c55e; color: white; font-weight: bold; padding: 8px;"
        )
        self.btn_import.clicked.connect(self._on_import)
        self.btn_import.setEnabled(False)
        btn_layout.addWidget(self.btn_import)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

    def _on_browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Pilih File Sumber",
            "", "Spatial Files (*.shp *.kml *.kmz *.gpkg *.geojson *.json);;All Files (*)"
        )
        if not path:
            return

        self.source_path = path
        self.file_input.setText(path)

        try:
            from .sketsa_import import get_source_fields, get_target_fields, preview_data

            self.source_fields = get_source_fields(path)
            self.target_fields = get_target_fields(self.gpkg_path)

            self._populate_mapping_table()
            self._populate_preview(path)
            self.btn_import.setEnabled(True)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to read file: {e}")

    def _populate_mapping_table(self):
        target_names = [f["name"] for f in self.target_fields]
        options = ["(Abaikan)", "(Buat Baru)"] + target_names

        self.mapping_table.setRowCount(len(self.source_fields))
        for i, src_field in enumerate(self.source_fields):
            # Source column name (read-only)
            src_item = QTableWidgetItem(src_field["name"])
            src_item.setFlags(src_item.flags() & ~ITEM_IS_EDITABLE)
            self.mapping_table.setItem(i, 0, src_item)

            # Target dropdown
            combo = QComboBox()
            combo.addItems(options)

            # Auto-match by name
            src_lower = src_field["name"].lower()
            matched = False
            for j, tgt_name in enumerate(target_names):
                if tgt_name.lower() == src_lower:
                    combo.setCurrentIndex(j + 2)  # +2 for "(Abaikan)" and "(Buat Baru)"
                    matched = True
                    break

            if not matched:
                combo.setCurrentIndex(0)  # "(Abaikan)"

            self.mapping_table.setCellWidget(i, 1, combo)

    def _populate_preview(self, file_path):
        from .sketsa_import import preview_data

        col_names, rows = preview_data(file_path, limit=5)
        self.preview_table.setColumnCount(len(col_names))
        self.preview_table.setHorizontalHeaderLabels(col_names)
        self.preview_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                self.preview_table.setItem(r, c, QTableWidgetItem(str(val)))

    def _on_import(self):
        from .sketsa_import import import_with_mapping

        # Build field map from table
        field_map = {}
        for i in range(self.mapping_table.rowCount()):
            src_name = self.mapping_table.item(i, 0).text()
            combo = self.mapping_table.cellWidget(i, 1)
            tgt_name = combo.currentText()
            field_map[src_name] = tgt_name

        try:
            result = import_with_mapping(
                source_path=self.source_path,
                gpkg_path=self.gpkg_path,
                field_map=field_map,
                create_missing_columns=self.chk_auto_create.isChecked(),
            )

            msg = (
                f"Import selesai!\n\n"
                f"✅ Diimpor: {result['imported']}\n"
                f"⏭️ Dilewati: {result['skipped']}\n"
                f"❌ Error: {result['errors']}"
            )
            QMessageBox.information(self, "Hasil Import", msg)
            self.accept()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Import failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# DIFF PREVIEW DIALOG
# ═══════════════════════════════════════════════════════════════════════════

class DiffPreviewDialog(QDialog):
    """Preview changes before pushing to server."""

    def __init__(self, diff, parent=None):
        super().__init__(parent)
        self.diff = diff
        self.setWindowTitle("📊 Preview Changes")
        self.setMinimumSize(400, 300)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Changes to be sent to server:"))

        # Summary
        summary_text = ""
        if self.diff.inserts:
            summary_text += f"➕ {len(self.diff.inserts)} feature baru\n"
        if self.diff.updates:
            summary_text += f"✏️ {len(self.diff.updates)} features modified\n"
        if self.diff.deletes:
            summary_text += f"🗑️ {len(self.diff.deletes)} features deleted\n"
        if self.diff.new_columns:
            cols = ", ".join([c["name"] for c in self.diff.new_columns])
            summary_text += f"➕ Kolom baru: {cols}\n"
        if self.diff.dropped_columns:
            cols = ", ".join(self.diff.dropped_columns)
            summary_text += f"➖ Columns deleted: {cols}\n"

        summary_label = QTextEdit()
        summary_label.setPlainText(summary_text)
        summary_label.setReadOnly(True)
        summary_label.setMaximumHeight(150)
        layout.addWidget(summary_label)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_send = QPushButton("🚀 Kirim ke Server")
        btn_send.setStyleSheet(
            "background-color: #22c55e; color: white; font-weight: bold; padding: 8px;"
        )
        btn_send.clicked.connect(self.accept)
        btn_layout.addWidget(btn_send)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)


# ═══════════════════════════════════════════════════════════════════════════
# TOPOLOGY DIALOG
# ═══════════════════════════════════════════════════════════════════════════

class TopologyDialog(QDialog):
    """Server-side PostGIS topology operations."""

    def __init__(self, base_url, token, table_name, iface, parent=None):
        super().__init__(parent)
        self.base_url = base_url
        self.token = token
        self.table_name = table_name
        self.iface = iface
        self.setWindowTitle(f"🔺 Topology — {table_name}")
        self.setMinimumSize(450, 400)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(
            "Topology diproses di server (PostGIS Topology Engine).\n"
            "Data dikirim ke PostGIS untuk validasi dan pembangunan topology."
        ))

        # Stats
        grp_stats = QGroupBox("📊 Status Topology")
        stats_layout = QVBoxLayout()
        self.stats_label = QLabel("Belum dimuat. Klik 'Cek Status' untuk melihat.")
        stats_layout.addWidget(self.stats_label)
        self.btn_stats = QPushButton("📊 Cek Status")
        self.btn_stats.clicked.connect(self._on_stats)
        stats_layout.addWidget(self.btn_stats)
        grp_stats.setLayout(stats_layout)
        layout.addWidget(grp_stats)

        # Actions
        grp_actions = QGroupBox("⚙️ Action")
        actions_layout = QVBoxLayout()

        self.btn_build = QPushButton("🔨 Build Topology")
        self.btn_build.setStyleSheet(
            "background-color: #3b82f6; color: white; font-weight: bold; padding: 6px;"
        )
        self.btn_build.clicked.connect(self._on_build)
        actions_layout.addWidget(self.btn_build)

        self.btn_validate = QPushButton("✅ Validate Topology")
        self.btn_validate.setStyleSheet(
            "background-color: #22c55e; color: white; font-weight: bold; padding: 6px;"
        )
        self.btn_validate.clicked.connect(self._on_validate)
        actions_layout.addWidget(self.btn_validate)

        grp_actions.setLayout(actions_layout)
        layout.addWidget(grp_actions)

        # Log
        layout.addWidget(QLabel("📋 Hasil:"))
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        layout.addWidget(self.log_area)

        # Close
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)

    def _log(self, msg):
        self.log_area.append(msg)

    def _on_stats(self):
        from .sketsa_engine import topology_stats
        try:
            self._log("📊 Mengambil status topology...")
            result = topology_stats(self.base_url, self.token, self.table_name)
            has_topo = result.get("has_topology", False)
            if has_topo:
                self.stats_label.setText(
                    f"✅ Topology aktif\n"
                    f"   Nodes: {result.get('nodes', 0)}\n"
                    f"   Edges: {result.get('edges', 0)}\n"
                    f"   Faces: {result.get('faces', 0)}"
                )
                self._log(f"✅ Topology aktif — {result.get('nodes', 0)} nodes, "
                          f"{result.get('edges', 0)} edges, {result.get('faces', 0)} faces")
            else:
                self.stats_label.setText("❌ Topology belum dibangun")
                self._log("❌ Topology belum ada. Klik 'Build Topology' untuk membangun.")
        except Exception as e:
            self._log(f"❌ Error: {e}")

    def _on_build(self):
        from .sketsa_engine import topology_build

        confirm = QMessageBox.question(
            self, "Confirmation",
            "Build topology akan memproses semua geometri di server.\n"
            "Topology lama (jika ada) akan di-rebuild.\n\nLanjutkan?",
            MSG_YES | MSG_NO,
        )
        if confirm != MSG_YES:
            return

        try:
            self._log("🔨 Membangun topology di server...")
            result = topology_build(self.base_url, self.token, self.table_name)
            self._log(f"✅ Build selesai!")
            self._log(f"   Nodes: {result.get('nodes', '?')}")
            self._log(f"   Edges: {result.get('edges', '?')}")
            self._log(f"   Faces: {result.get('faces', '?')}")
            self._on_stats()  # Refresh stats
        except Exception as e:
            self._log(f"❌ Build Failed: {e}")

    def _on_validate(self):
        from .sketsa_engine import topology_validate
        try:
            self._log("✅ Memvalidasi topology di server...")
            result = topology_validate(self.base_url, self.token, self.table_name)
            is_valid = result.get("valid", False)
            errors = result.get("errors", [])
            if is_valid:
                self._log("✅ Topology VALID — tidak ada error!")
            else:
                self._log(f"⚠️ Topology memiliki {len(errors)} error:")
                for err in errors[:20]:  # Show max 20 errors
                    self._log(f"   • {err}")
                if len(errors) > 20:
                    self._log(f"   ... dan {len(errors) - 20} error lainnya")
        except Exception as e:
            self._log(f"❌ Validasi Failed: {e}")

# ═══════════════════════════════════════════════════════════════════════════
# DIRECT UPLOAD DIALOG
# ═══════════════════════════════════════════════════════════════════════════

class DirectUploadDialog(QDialog):
    """Directly upload a QGIS layer to the server as a new OGC Collection."""

    def __init__(self, base_url, token, iface, parent=None):
        super().__init__(parent)
        self.base_url = base_url
        self.token = token
        self.iface = iface
        self.setWindowTitle("🚀 Upload QGIS Layer ke Server")
        self.setMinimumSize(450, 300)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("Select active QGIS layer to upload to server:"))

        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Nama layer di server:"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Contoh: titik_penjualan_minyak")
        name_layout.addWidget(self.name_input)
        layout.addLayout(name_layout)

        layer_layout = QHBoxLayout()
        self.layer_combo = QComboBox()
        self.layer_combo.currentIndexChanged.connect(self._on_layer_combo_changed)
        self._populate_layers()
        layer_layout.addWidget(self.layer_combo)
        
        self.btn_browse = QPushButton("📂 Browse File...")
        self.btn_browse.clicked.connect(self._on_browse)
        layer_layout.addWidget(self.btn_browse)
        layout.addLayout(layer_layout)
        
        if self.layer_combo.count() == 0:
            self.layer_combo.addItem("-- Buka layer di QGIS atau klik Browse --", None)
        
        btn_layout = QHBoxLayout()
        self.btn_upload = QPushButton("🚀 Buat Koleksi & Upload Data")
        self.btn_upload.setStyleSheet(
            "background-color: #8b5cf6; color: white; font-weight: bold; padding: 8px;"
        )
        self.btn_upload.clicked.connect(self._on_upload)
        btn_layout.addWidget(self.btn_upload)
        
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        
        layout.addLayout(btn_layout)
        
    def _populate_layers(self):
        self.layer_combo.blockSignals(True)
        self.layer_combo.clear()
        for layer_id, layer in QgsProject.instance().mapLayers().items():
            if layer.type() == QgsVectorLayer.VectorLayer:
                self.layer_combo.addItem(layer.name(), layer_id)
        self.layer_combo.blockSignals(False)
        self._on_layer_combo_changed()

    def _on_layer_combo_changed(self):
        layer_id = self.layer_combo.currentData()
        if not layer_id:
            return
        layer = QgsProject.instance().mapLayer(layer_id)
        if layer:
            self.name_input.setText(layer.name())
                
    def _on_browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Pilih File Vektor",
            "", "Vector Files (*.shp *.kml *.kmz *.geojson *.gpkg);;All Files (*)"
        )
        if not path:
            return
            
        import os
        layer_name = os.path.splitext(os.path.basename(path))[0]
        layer = QgsVectorLayer(path, layer_name, "ogr")
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)
            self._populate_layers()
            # Select the newly added layer
            idx = self.layer_combo.findData(layer.id())
            if idx >= 0:
                self.layer_combo.setCurrentIndex(idx)
        else:
            QMessageBox.critical(self, "Error", "File tidak valid atau tidak dapat dibaca oleh QGIS.")
                
    def _on_upload(self):
        from .sketsa_engine import upload_layer_to_server
        
        layer_id = self.layer_combo.currentData()
        if not layer_id:
            QMessageBox.warning(self, "Warning", "No ada layer yang dipilih.")
            return
            
        layer = QgsProject.instance().mapLayer(layer_id)
        if not layer:
            return
            
        confirm = QMessageBox.question(
            self, "Confirmation",
            f"Upload layer '{layer.name()}' to GISNAS server?\nThis will create a new collection and upload all features.",
            MSG_YES | MSG_NO
        )
        
        if confirm != MSG_YES:
            return
            
        self.btn_upload.setEnabled(False)
        self.btn_upload.setText("Mengupload... Mohon tunggu")
        QApplication.processEvents()
        
        display_name = self.name_input.text().strip() or layer.name()
        try:
            result = upload_layer_to_server(
                layer, self.base_url, self.token, display_name=display_name
            )
            QMessageBox.information(
                self,
                "Sukses",
                f"Layer '{result.get('name', display_name)}' berhasil diupload!\n\n"
                f"Tabel: {result['table_name']}\n"
                f"Total fitur: {result['feature_count']}",
            )
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to upload layer:\n{e}")
            self.btn_upload.setEnabled(True)
            self.btn_upload.setText("🚀 Buat Koleksi & Upload Data")



class HistoryDialog(QDialog):
    def __init__(self, parent, base_url, token, table_name, layer):
        super().__init__(parent)
        self.setWindowTitle(f"History: {table_name}")
        self.setMinimumSize(700, 400)
        self.base_url = base_url
        self.token = token
        self.table_name = table_name
        self.layer = layer
        self.preview_layer = None
        
        layout = QVBoxLayout(self)
        
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Waktu", "Aksi", "Feature ID", "User", "ID Histori"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table)
        
        btn_layout = QHBoxLayout()
        self.btn_revert = QPushButton("Revert (Undo)")
        self.btn_revert.setEnabled(False)
        self.btn_revert.clicked.connect(self._on_revert)
        self.btn_close = QPushButton("Tutup")
        self.btn_close.clicked.connect(self.close)
        
        btn_layout.addWidget(self.btn_revert)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_close)
        layout.addLayout(btn_layout)
        
        self.history_data = []
        self._load_history()
        
    def _load_history(self):
        url = f"{self.base_url}/collections/{self.table_name}/history"
        if self.token:
            url += f"?token={self.token}"
            
        import urllib.request, json
        req = urllib.request.Request(url, headers={"User-Agent": "GISNAS-Sketsa"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                self.history_data = data
                self.table.setRowCount(len(data))
                for i, row in enumerate(data):
                    self.table.setItem(i, 0, QTableWidgetItem(str(row.get('created_at', ''))))
                    self.table.setItem(i, 1, QTableWidgetItem(str(row.get('action', ''))))
                    self.table.setItem(i, 2, QTableWidgetItem(str(row.get('feature_id', ''))))
                    self.table.setItem(i, 3, QTableWidgetItem(str(row.get('changed_by', ''))))
                    self.table.setItem(i, 4, QTableWidgetItem(str(row.get('id', ''))))
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Gagal memuat riwayat: {e}")
            
    def _on_selection_changed(self):
        sel = self.table.selectedItems()
        self.btn_revert.setEnabled(len(sel) > 0)
        
        # Hapus preview layer lama jika ada
        from qgis.core import QgsProject
        if self.preview_layer:
            QgsProject.instance().removeMapLayer(self.preview_layer.id())
            self.preview_layer = None
            
        if not sel:
            return
            
        row_idx = sel[0].row()
        data = self.history_data[row_idx]
        
        old_geom = data.get('old_geom')
        if not old_geom or old_geom == 'null':
            return
            
        # Tampilkan highlight merah
        from qgis.core import QgsVectorLayer, QgsFeature, QgsGeometry, QgsSymbol, QgsSingleSymbolRenderer, QgsProject
        import json
        
        geom_type = self.layer.geometryType()
        type_str = "Polygon"
        if geom_type == 0: type_str = "Point"
        elif geom_type == 1: type_str = "LineString"
        
        crs = self.layer.crs().authid()
        self.preview_layer = QgsVectorLayer(f"{type_str}?crs={crs}", "Preview Histori (Merah)", "memory")
        
        feat = QgsFeature()
        geom = QgsGeometry.fromGeoJson(json.dumps(old_geom))
        feat.setGeometry(geom)
        
        pr = self.preview_layer.dataProvider()
        pr.addFeature(feat)
        self.preview_layer.updateExtents()
        
        # Style merah
        symbol = QgsSymbol.defaultSymbol(self.preview_layer.geometryType())
        symbol.setColor(QtGui.QColor(255, 0, 0, 150))
        if type_str == "Polygon":
            symbol.symbolLayer(0).setStrokeColor(QtGui.QColor(255, 0, 0))
            symbol.symbolLayer(0).setStrokeWidth(1.0)
        
        self.preview_layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        QgsProject.instance().addMapLayer(self.preview_layer, False)
        
        # Dapatkan canvas dan tambahkan layernya ke paling atas
        iface = getattr(sys.modules.get('qgis.utils'), 'iface', None)
        if iface:
            canvas = iface.mapCanvas()
            layers = canvas.layers()
            canvas.setLayers([self.preview_layer] + layers)
            
    def _on_revert(self):
        sel = self.table.selectedItems()
        if not sel: return
        
        row_idx = sel[0].row()
        data = self.history_data[row_idx]
        
        action = data.get('action')
        server_id = data.get('feature_id')
        old_geom = data.get('old_geom')
        old_props = data.get('old_properties', {})
        
        # Cari fitur di layer lokal berdasarkan kolom 'id'
        target_fid = None
        for f in self.layer.getFeatures():
            if f.attribute('id') == server_id:
                target_fid = f.id()
                break
                
        self.layer.startEditing()
        
        import json
        from qgis.core import QgsGeometry, QgsFeature
        
        if action == 'INSERT':
            # Jika dulu insert, revert artinya hapus
            if target_fid is not None:
                self.layer.deleteFeature(target_fid)
        elif action in ('UPDATE', 'DELETE'):
            # Kembalikan geometri dan atribut lama
            geom = QgsGeometry.fromGeoJson(json.dumps(old_geom))
            
            if action == 'DELETE' and target_fid is None:
                # Jika sudah dihapus, tambahkan baru
                new_f = QgsFeature(self.layer.fields())
                new_f.setGeometry(geom)
                new_f.setAttribute('id', server_id)
                for k, v in old_props.items():
                    idx = self.layer.fields().indexOf(k)
                    if idx != -1:
                        new_f.setAttribute(idx, v)
                self.layer.addFeature(new_f)
            else:
                if target_fid is not None:
                    self.layer.changeGeometry(target_fid, geom)
                    for k, v in old_props.items():
                        idx = self.layer.fields().indexOf(k)
                        if idx != -1:
                            self.layer.changeAttributeValue(target_fid, idx, v)
                            
        self.layer.triggerRepaint()
        QMessageBox.information(self, "Berhasil", "Revert diterapkan ke peta lokal! Silakan klik 'Push Changes' untuk menyimpan ke server.")
        self.close()
        
    def closeEvent(self, event):
        from qgis.core import QgsProject
        if self.preview_layer:
            QgsProject.instance().removeMapLayer(self.preview_layer.id())
        super().closeEvent(event)


class FeatureHistorySideBySideDialog(QDialog):
    def __init__(self, parent, layer, server_id, history_data):
        super().__init__(parent)
        self.setWindowTitle(f"Detail Riwayat (Feature ID: {server_id})")
        self.setMinimumSize(1000, 600)
        self.layer = layer
        self.history_data = history_data
        self.server_id = server_id
        
        main_layout = QVBoxLayout(self)
        
        info_label = QLabel(f"<b>Diedit oleh:</b> {history_data.get('changed_by', 'Unknown')} | <b>Waktu:</b> {history_data.get('created_at', '')} | <b>Aksi:</b> {history_data.get('action', '')}")
        info_label.setStyleSheet("font-size: 14px; padding: 10px; background-color: #e0f7fa; border-radius: 5px;")
        main_layout.addWidget(info_label)
        
        split_layout = QHBoxLayout()
        
        # LEFT: Current
        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel("<b>Data Saat Ini (Lokal)</b>"))
        
        self.left_canvas = QgsMapCanvas(self)
        self.left_canvas.setMinimumSize(400, 300)
        self.left_canvas.enableAntiAliasing(True)
        left_layout.addWidget(self.left_canvas)
        
        self.left_table = QTableWidget()
        self.left_table.setColumnCount(2)
        self.left_table.setHorizontalHeaderLabels(["Atribut", "Nilai"])
        self.left_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        left_layout.addWidget(self.left_table)
        
        split_layout.addLayout(left_layout)
        
        # RIGHT: Old Version
        right_layout = QVBoxLayout()
        right_layout.addWidget(QLabel("<b>Data Riwayat (Versi Lawas)</b>"))
        
        self.right_canvas = QgsMapCanvas(self)
        self.right_canvas.setMinimumSize(400, 300)
        self.right_canvas.enableAntiAliasing(True)
        right_layout.addWidget(self.right_canvas)
        
        self.right_table = QTableWidget()
        self.right_table.setColumnCount(2)
        self.right_table.setHorizontalHeaderLabels(["Atribut", "Nilai"])
        self.right_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        right_layout.addWidget(self.right_table)
        
        split_layout.addLayout(right_layout)
        
        main_layout.addLayout(split_layout)
        
        btn_layout = QHBoxLayout()
        self.btn_revert = QPushButton("Revert ke Versi Lawas (Undo)")
        self.btn_revert.setStyleSheet("background-color: #d32f2f; color: white; font-weight: bold; padding: 8px;")
        self.btn_revert.clicked.connect(self._on_revert)
        self.btn_close = QPushButton("Tutup")
        self.btn_close.clicked.connect(self.close)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_revert)
        btn_layout.addWidget(self.btn_close)
        main_layout.addLayout(btn_layout)
        
        self._populate_data()
        
    def _populate_data(self):
        import json
        from qgis.core import QgsFeature, QgsGeometry, QgsVectorLayer, QgsSymbol, QgsSingleSymbolRenderer
        
        # Ambil data lokal saat ini
        current_feat = None
        for f in self.layer.getFeatures():
            if f.attribute('id') == self.server_id:
                current_feat = QgsFeature(f)
                break
                
        geom_type = self.layer.geometryType()
        type_str = "Polygon"
        if geom_type == 0: type_str = "Point"
        elif geom_type == 1: type_str = "LineString"
        crs = self.layer.crs().authid()
        
        # --- LEFT PANEL (Current) ---
        if current_feat:
            self.left_layer = QgsVectorLayer(f"{type_str}?crs={crs}", "Lokal", "memory")
            pr = self.left_layer.dataProvider()
            for field in self.layer.fields():
                pr.addAttributes([field])
            self.left_layer.updateFields()
            pr.addFeature(current_feat)
            self.left_layer.updateExtents()
            
            symbol = QgsSymbol.defaultSymbol(self.left_layer.geometryType())
            symbol.setColor(QtGui.QColor(33, 150, 243, 150)) # Blue
            self.left_layer.setRenderer(QgsSingleSymbolRenderer(symbol))
            
            self.left_canvas.setLayers([self.left_layer])
            self.left_canvas.setExtent(self.left_layer.extent())
            self.left_canvas.refresh()
            
            # Populate table
            fields = self.layer.fields()
            self.left_table.setRowCount(fields.count())
            for i, field in enumerate(fields):
                self.left_table.setItem(i, 0, QTableWidgetItem(field.name()))
                self.left_table.setItem(i, 1, QTableWidgetItem(str(current_feat.attribute(field.name()))))
        
        # --- RIGHT PANEL (History) ---
        old_geom = self.history_data.get('old_geom')
        old_props = self.history_data.get('old_properties', {})
        
        self.right_layer = QgsVectorLayer(f"{type_str}?crs={crs}", "Riwayat", "memory")
        pr2 = self.right_layer.dataProvider()
        for field in self.layer.fields():
            pr2.addAttributes([field])
        self.right_layer.updateFields()
        
        feat_hist = QgsFeature(self.layer.fields())
        if old_geom and old_geom != 'null':
            geom = QgsGeometry.fromGeoJson(json.dumps(old_geom))
            feat_hist.setGeometry(geom)
            
        for k, v in old_props.items():
            idx = self.layer.fields().indexOf(k)
            if idx != -1:
                feat_hist.setAttribute(idx, v)
                
        pr2.addFeature(feat_hist)
        self.right_layer.updateExtents()
        
        symbol2 = QgsSymbol.defaultSymbol(self.right_layer.geometryType())
        symbol2.setColor(QtGui.QColor(244, 67, 54, 150)) # Red
        self.right_layer.setRenderer(QgsSingleSymbolRenderer(symbol2))
        
        self.right_canvas.setLayers([self.right_layer])
        self.right_canvas.setExtent(self.right_layer.extent())
        self.right_canvas.refresh()
        
        fields = self.layer.fields()
        self.right_table.setRowCount(fields.count())
        for i, field in enumerate(fields):
            self.right_table.setItem(i, 0, QTableWidgetItem(field.name()))
            val = old_props.get(field.name(), '')
            self.right_table.setItem(i, 1, QTableWidgetItem(str(val)))
            
    def _on_revert(self):
        # Langsung update target feature di active layer
        action = self.history_data.get('action')
        old_geom = self.history_data.get('old_geom')
        old_props = self.history_data.get('old_properties', {})
        
        target_fid = None
        for f in self.layer.getFeatures():
            if f.attribute('id') == self.server_id:
                target_fid = f.id()
                break
                
        self.layer.startEditing()
        
        import json
        from qgis.core import QgsGeometry, QgsFeature
        
        if action == 'INSERT':
            if target_fid is not None:
                self.layer.deleteFeature(target_fid)
        elif action in ('UPDATE', 'DELETE'):
            if old_geom and old_geom != 'null':
                geom = QgsGeometry.fromGeoJson(json.dumps(old_geom))
                if action == 'DELETE' and target_fid is None:
                    new_f = QgsFeature(self.layer.fields())
                    new_f.setGeometry(geom)
                    new_f.setAttribute('id', self.server_id)
                    for k, v in old_props.items():
                        idx = self.layer.fields().indexOf(k)
                        if idx != -1:
                            new_f.setAttribute(idx, v)
                    self.layer.addFeature(new_f)
                else:
                    if target_fid is not None:
                        self.layer.changeGeometry(target_fid, geom)
                        for k, v in old_props.items():
                            idx = self.layer.fields().indexOf(k)
                            if idx != -1:
                                self.layer.changeAttributeValue(target_fid, idx, v)
                                
        self.layer.triggerRepaint()
        QMessageBox.information(self, "Berhasil", "Revert berhasil diterapkan secara lokal! Harap tekan 'Push Changes' di panel utama.")
        self.close()

class CustomAttributeTableDialog(QDialog):
    def __init__(self, parent, base_url, token, layer):
        super().__init__(parent)
        self.setWindowTitle(f"Attribute Table with Versioning: {layer.name()}")
        self.setMinimumSize(900, 500)
        
        self.base_url = base_url
        self.token = token
        self.layer = layer
        
        import os
        # The table_name is either the layer name or what we exported.
        # But for GISNAS, we can rely on layer.name().
        self.table_name = layer.name()
        
        layout = QVBoxLayout(self)
        
        self.table = QTableWidget()
        layout.addWidget(self.table)
        
        self.history_map = {} # feature_id -> latest history record
        self._fetch_history()
        self._populate_table()
        
    def _fetch_history(self):
        url = f"{self.base_url}/collections/{self.table_name}/history"
        if self.token:
            url += f"?token={self.token}"
            
        import urllib.request, json
        req = urllib.request.Request(url, headers={"User-Agent": "GISNAS-Sketsa"})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                # Simpan riwayat terbaru untuk setiap feature_id
                for row in reversed(data): 
                    # reversed so that the latest (index 0) overwrites and becomes the one stored.
                    # Wait, data is ordered by DESC. So the first one is the newest.
                    pass
                for row in data:
                    fid = row.get('feature_id')
                    if fid not in self.history_map:
                        self.history_map[fid] = row
        except Exception as e:
            print("Gagal fetch history:", e)
            
    def _populate_table(self):
        features = list(self.layer.getFeatures())
        fields = self.layer.fields()
        
        self.table.setRowCount(len(features))
        self.table.setColumnCount(fields.count() + 1) # +1 for V button
        
        headers = ["History"] + [f.name() for f in fields]
        self.table.setHorizontalHeaderLabels(headers)
        
        for r, feat in enumerate(features):
            fid = feat.attribute('id')
            
            # Buat tombol V
            btn_v = QPushButton("v")
            btn_v.setFixedWidth(30)
            
            if fid in self.history_map:
                btn_v.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
                btn_v.clicked.connect(lambda checked, f_id=fid: self._open_history_side(f_id))
            else:
                btn_v.setStyleSheet("background-color: #9E9E9E; color: white; font-weight: bold;")
                btn_v.setToolTip("Tidak ada histori.")
                
            self.table.setCellWidget(r, 0, btn_v)
            
            for c, field in enumerate(fields):
                val = str(feat.attribute(field.name()))
                self.table.setItem(r, c + 1, QTableWidgetItem(val))
                
    def _open_history_side(self, feature_id):
        hist_data = self.history_map.get(feature_id)
        if not hist_data: return
        
        dlg = FeatureHistorySideBySideDialog(self, self.layer, feature_id, hist_data)
        dlg.exec_()
