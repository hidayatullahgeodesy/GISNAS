"""
sketsa_main.py — Main QGIS plugin class for GISNAS Sketsa.
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from .sketsa_dialogs import SketsaPanel

class GisnasSketsa:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = __path__[0] if '__path__' in globals() else ""
        self.actions = []
        self.menu = "&GISNAS Sketsa"
        self.panel = None

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""
        icon_path = "" # We could add an icon later
        
        self.action = QAction(
            "GISNAS Sketsa (GPKG + Delta Sync)",
            self.iface.mainWindow()
        )
        self.action.triggered.connect(self.run)
        
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu(self.menu, self.action)
        
        from qgis.core import QgsMapLayerType
        self.attr_action = QAction("Open Attributes with Versioning", self.iface.mainWindow())
        self.attr_action.triggered.connect(self.open_custom_attr)
        self.iface.addCustomActionForLayerType(self.attr_action, "", QgsMapLayerType.VectorLayer, False)

    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        self.iface.removePluginMenu(self.menu, self.action)
        self.iface.removeToolBarIcon(self.action)
        self.iface.removeCustomActionForLayerType(self.attr_action)
        if self.panel:
            self.panel.close()

    def run(self):
        """Run method that performs all the real work"""
        if not self.panel:
            self.panel = SketsaPanel(self.iface)
        self.panel.show()
        self.panel.raise_()
        self.panel.activateWindow()

    def open_custom_attr(self):
        layer = self.iface.activeLayer()
        if not layer:
            return
            
        import sqlite3
        import os
        base_url = ""
        token = ""
        try:
            db_path = layer.source().split("|")[0]
            if os.path.exists(db_path):
                conn = sqlite3.connect(db_path)
                row_url = conn.execute("SELECT value FROM _sketsa_meta WHERE key='base_url'").fetchone()
                row_token = conn.execute("SELECT value FROM _sketsa_meta WHERE key='token'").fetchone()
                if row_url: base_url = row_url[0]
                if row_token: token = row_token[0]
                conn.close()
        except Exception:
            pass
            
        if not base_url or not token:
            from qgis.PyQt.QtWidgets import QMessageBox
            QMessageBox.warning(self.iface.mainWindow(), "Warning", "Layer ini tidak terkait dengan GISNAS (tidak ada metadata).")
            return
            
        from .sketsa_dialogs import CustomAttributeTableDialog
        self.attr_dlg = CustomAttributeTableDialog(self.iface.mainWindow(), base_url, token, layer)
        self.attr_dlg.show()
