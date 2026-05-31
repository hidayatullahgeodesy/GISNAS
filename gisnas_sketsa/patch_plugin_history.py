import re

path = r'c:\docker\gisnas\gisnas_sketsa\sketsa_dialogs.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

history_dialog_code = '''
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
'''

content += "\n" + history_dialog_code

# Add button to SketsaPanel
panel_btn_target = '''        self.btn_pull.clicked.connect(self._on_pull)'''
panel_btn_repl = '''        self.btn_pull.clicked.connect(self._on_pull)
        self.btn_history = QPushButton("Lihat Riwayat (History)")
        self.btn_history.clicked.connect(self._on_history)
        btn_layout2.addWidget(self.btn_history)'''
content = content.replace(panel_btn_target, panel_btn_repl)

# Add method to SketsaPanel
panel_method_target = '''    def _on_pull(self):'''
panel_method_repl = '''    def _on_history(self):
        sel = self.table_collections.selectedItems()
        if not sel:
            QMessageBox.warning(self, "Warning", "Pilih layer terlebih dahulu.")
            return
        
        table_name = self.table_collections.item(sel[0].row(), 0).text()
        
        # Pastikan layer aktif di QGIS sesuai dengan tabel
        from qgis.core import QgsProject
        active_layer = None
        for layer in QgsProject.instance().mapLayers().values():
            if layer.name() == table_name:
                active_layer = layer
                break
                
        if not active_layer:
            QMessageBox.warning(self, "Warning", f"Layer {table_name} belum dimuat di peta.")
            return
            
        dlg = HistoryDialog(self, self.base_url, self.token, table_name, active_layer)
        dlg.exec_()

    def _on_pull(self):'''
content = content.replace(panel_method_target, panel_method_repl)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("sketsa_dialogs.py updated with HistoryDialog")
