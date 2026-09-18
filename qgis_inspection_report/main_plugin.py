"""Inspection Report プラグイン本体。"""

from datetime import datetime

from qgis.core import (
    QgsBalloonCallout,
    QgsCategorizedSymbolRenderer,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsFillSymbol,
    QgsGeometry,
    QgsMargins,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsProject,
    QgsRectangle,
    QgsRendererCategory,
    QgsTextFormat,
    QgsUnitTypes,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)
from qgis.gui import QgsMapToolEmitPoint
from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QAction, QFileDialog

from .dialogs import DELETE, InspectionInputDialog
from .report import export_report
from .statuses import STATUS_COLORS, UNKNOWN_COLOR, UNKNOWN_LABEL

LAYER_NAME = "点検ポイント"
# プラグインのリロードやプロジェクト再読み込み後も点検レイヤーを見つけるための目印
LAYER_MARKER = "inspection_report/is_inspection_layer"

# クリック位置を「既存ポイントの上」とみなす半径（ピクセル）
HIT_TOLERANCE_PX = 12

# 地物にマウスを重ねたときに出すポップアップ（マップチップ）。
# 写真は属性に埋め込んだデータURIなので、そのまま img の src に置ける。
MAP_TIP = (
    '<div style="font-family:sans-serif; font-size:11pt;">'
    '<b>[% "name" %]</b><br/>'
    'ステータス: [% "status" %]<br/>'
    'コメント: [% coalesce("comment", \'（なし）\') %]<br/>'
    '点検日時: [% "inspected_at" %]'
    '[% if(coalesce("photo",\'\')!=\'\', \'<br/><img src="\' || "photo" || \'" width="200"/>\', \'\') %]'
    '</div>'
)

# 吹き出しに出す内容。詳細（コメント・写真）はマップチップ側で見る
LABEL_EXPRESSION = "\"name\" || '\\n' || \"status\""

# 点検ポイントのマーカーの大きさ（ミリメートル）
MARKER_SIZE_MM = 5.0

FIELDS = [
    ("name", QVariant.String, "設備名"),
    ("status", QVariant.String, "ステータス"),
    ("comment", QVariant.String, "コメント"),
    ("photo", QVariant.String, "写真"),
    ("inspected_at", QVariant.String, "点検日時"),
]


class InspectionReportPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.toolbar = None
        self.actions = []
        self.record_action = None
        self.map_tool = None

    # --- ライフサイクル -------------------------------------------------

    def initGui(self):
        # 他プラグインと混ざらないよう専用ツールバーを用意する
        self.toolbar = self.iface.addToolBar("Inspection Report")
        self.toolbar.setObjectName("InspectionReportToolbar")
        self.toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        # 既存ツールバーと同じ行に並ばないよう、手前で改行させる
        self.iface.mainWindow().insertToolBarBreak(self.toolbar)

        self._add_action("点検レイヤー作成", self.create_layer)
        self.record_action = self._add_action(
            "点検ポイント記録", self.toggle_record, checkable=True
        )
        self.record_action.setToolTip(
            "地図をクリックして点検ポイントを記録します。"
            "既存ポイントの上をクリックすると、その内容を編集します。"
        )

        self._add_action("レポート出力", self.export_report)

        self.map_tool = InspectionPointTool(self.iface.mapCanvas(), self)
        self.map_tool.setAction(self.record_action)

    def _add_action(self, text, callback, checkable=False):
        action = QAction(text, self.iface.mainWindow())
        action.setCheckable(checkable)
        action.triggered.connect(callback)
        self.toolbar.addAction(action)
        self.actions.append(action)
        return action

    def unload(self):
        canvas = self.iface.mapCanvas()
        if self.map_tool is not None and canvas.mapTool() is self.map_tool:
            canvas.unsetMapTool(self.map_tool)
        self.map_tool = None

        for action in self.actions:
            self.toolbar.removeAction(action)
        self.actions.clear()
        self.record_action = None
        if self.toolbar is not None:
            self.iface.mainWindow().removeToolBarBreak(self.toolbar)
            self.toolbar.deleteLater()
            self.toolbar = None

    # --- 機能 -----------------------------------------------------------

    def create_layer(self):
        existing = self.inspection_layer()
        if existing is not None:
            # 二重作成すると記録・出力先が曖昧になるので既存レイヤーを使う
            self.iface.setActiveLayer(existing)
            self.iface.messageBar().pushInfo(
                "Inspection Report", "点検レイヤーは既に存在します。"
            )
            return existing

        layer = QgsVectorLayer("Point?crs=EPSG:4326", LAYER_NAME, "memory")
        provider = layer.dataProvider()
        provider.addAttributes([QgsField(n, t, comment=a) for n, t, a in FIELDS])
        layer.updateFields()
        for index, (_, _, alias) in enumerate(FIELDS):
            layer.setFieldAlias(index, alias)
        layer.setCustomProperty(LAYER_MARKER, True)
        # ステータスに応じた色分け
        self._apply_symbology(layer)
        # 地図上でマウスを重ねたときに詳細を出す
        layer.setMapTipTemplate(MAP_TIP)
        layer.setDisplayExpression('"name"')
        # 地図上に常時出す吹き出し
        self._apply_labeling(layer)

        QgsProject.instance().addMapLayer(layer)
        self.iface.setActiveLayer(layer)
        self.iface.messageBar().pushInfo(
            "Inspection Report", "点検レイヤーを作成しました。"
        )
        return layer

    def _apply_symbology(self, layer):
        """status の値で色分けする分類シンボルを適用する。"""
        categories = []
        for status, color in STATUS_COLORS:
            categories.append(
                QgsRendererCategory(status, self._marker_symbol(color), status)
            )
        # 想定外の値が入っていても点が消えないよう、その他用の分類を足す
        categories.append(
            QgsRendererCategory("", self._marker_symbol(UNKNOWN_COLOR), UNKNOWN_LABEL)
        )
        layer.setRenderer(QgsCategorizedSymbolRenderer("status", categories))

    @staticmethod
    def _marker_symbol(color):
        symbol = QgsMarkerSymbol.createSimple(
            {
                "name": "circle",
                "color": color,
                "outline_color": "white",
                "outline_width": "0.6",
            }
        )
        symbol.setSize(MARKER_SIZE_MM)
        symbol.setSizeUnit(QgsUnitTypes.RenderMillimeters)
        return symbol

    def _apply_labeling(self, layer):
        """設備名とステータスを吹き出しで常時表示する。"""
        text_format = QgsTextFormat()
        text_format.setSize(9)
        text_format.setSizeUnit(QgsUnitTypes.RenderPoints)
        text_format.setColor(QColor("#222222"))

        settings = QgsPalLayerSettings()
        settings.setFormat(text_format)
        settings.fieldName = LABEL_EXPRESSION
        settings.isExpression = True
        settings.placement = QgsPalLayerSettings.AroundPoint
        # 吹き出しの引き出し線が見えるよう、ポイントから離して配置する
        settings.dist = 8
        settings.distUnits = QgsUnitTypes.RenderMillimeters

        callout = QgsBalloonCallout()
        callout.setEnabled(True)
        callout.setFillSymbol(
            QgsFillSymbol.createSimple(
                {
                    "color": "255,255,255,230",
                    "outline_color": "90,90,90,255",
                    "outline_width": "0.3",
                }
            )
        )
        callout.setCornerRadius(1.5)
        callout.setCornerRadiusUnit(QgsUnitTypes.RenderMillimeters)
        callout.setMargins(QgsMargins(2.0, 1.5, 2.0, 1.5))
        callout.setMarginsUnit(QgsUnitTypes.RenderMillimeters)
        callout.setWedgeWidth(2.0)
        callout.setWedgeWidthUnit(QgsUnitTypes.RenderMillimeters)
        settings.setCallout(callout)

        layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
        layer.setLabelsEnabled(True)

    def inspection_layer(self):
        """プロジェクト内の点検レイヤーを返す（なければ None）。"""
        for layer in QgsProject.instance().mapLayers().values():
            if layer.customProperty(LAYER_MARKER):
                return layer
        return None

    def export_report(self):
        """点検結果をA4横のPDFレポートに書き出す。"""
        layer = self.inspection_layer()
        if layer is None:
            self.iface.messageBar().pushWarning(
                "Inspection Report",
                "先に「点検レイヤー作成」で点検レイヤーを作成してください。",
            )
            return

        path, _ = QFileDialog.getSaveFileName(
            self.iface.mainWindow(),
            "レポートの保存先",
            "inspection_report.pdf",
            "PDF (*.pdf)",
        )
        if not path:
            return

        ok, message = export_report(layer, path, canvas=self.iface.mapCanvas())
        if ok:
            self.iface.messageBar().pushInfo(
                "Inspection Report", "レポートを出力しました: %s" % message
            )
        else:
            self.iface.messageBar().pushWarning("Inspection Report", message)

    def toggle_record(self, checked):
        canvas = self.iface.mapCanvas()
        if not checked:
            canvas.unsetMapTool(self.map_tool)
            return

        layer = self.inspection_layer()
        if layer is None:
            self.iface.messageBar().pushWarning(
                "Inspection Report",
                "先に「点検レイヤー作成」で点検レイヤーを作成してください。",
            )
            self.record_action.setChecked(False)
            return

        self.iface.setActiveLayer(layer)
        canvas.setMapTool(self.map_tool)

    def record_point(self, canvas_point):
        """既存ポイントの上なら編集、そうでなければ追加する。"""
        layer = self.inspection_layer()
        if layer is None:
            return

        point = self._to_layer_crs(layer, canvas_point)
        feature = self._feature_at(layer, point, canvas_point)
        if feature is None:
            self._add_point(layer, point)
        else:
            self._edit_point(layer, feature)

    # --- 内部処理 -------------------------------------------------------

    def _to_layer_crs(self, layer, canvas_point):
        transform = QgsCoordinateTransform(
            self.iface.mapCanvas().mapSettings().destinationCrs(),
            layer.crs(),
            QgsProject.instance(),
        )
        return transform.transform(canvas_point)

    def _feature_at(self, layer, point, canvas_point):
        """クリック位置の許容範囲内にある最も近いポイントを返す。"""
        tolerance = self._tolerance_in_layer_units(layer, point, canvas_point)

        rect = QgsRectangle(
            point.x() - tolerance,
            point.y() - tolerance,
            point.x() + tolerance,
            point.y() + tolerance,
        )
        nearest = None
        nearest_distance = None
        for feature in layer.getFeatures(rect):
            distance = feature.geometry().asPoint().distance(point)
            # 矩形の角は半径より遠いので、実距離でも絞り込む
            if distance > tolerance:
                continue
            if nearest_distance is None or distance < nearest_distance:
                nearest = feature
                nearest_distance = distance
        return nearest

    def _tolerance_in_layer_units(self, layer, point, canvas_point):
        """許容半径（ピクセル）をクリック位置周辺のレイヤーCRS距離に換算する。"""
        # キャンバスCRSの縮尺は位置で変わりうるので、原点ではなくクリック位置で測る
        to_map = self.iface.mapCanvas().getCoordinateTransform()
        pixel = to_map.transform(canvas_point)
        tolerance = 0.0
        for dx, dy in ((HIT_TOLERANCE_PX, 0), (0, HIT_TOLERANCE_PX)):
            edge = self._to_layer_crs(
                layer, to_map.toMapCoordinates(pixel.x() + dx, pixel.y() + dy)
            )
            tolerance = max(tolerance, edge.distance(point))
        return tolerance

    def _add_point(self, layer, point):
        dialog = InspectionInputDialog(
            self.iface.mainWindow(),
            default_name="点検-%03d" % (layer.featureCount() + 1),
        )
        if not dialog.exec_():
            return

        values = dialog.values()
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(point))
        for key in ("name", "status", "comment", "photo"):
            feature[key] = values[key]
        feature["inspected_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")

        layer.dataProvider().addFeatures([feature])
        layer.updateExtents()
        layer.triggerRepaint()

    def _edit_point(self, layer, feature):
        current = {name: feature[name] for name, _, _ in FIELDS}
        dialog = InspectionInputDialog(
            self.iface.mainWindow(),
            values=current,
            title="点検ポイントの編集",
            deletable=True,
        )
        result = dialog.exec_()
        if result == DELETE:
            layer.dataProvider().deleteFeatures([feature.id()])
            layer.updateExtents()
            layer.triggerRepaint()
            self.iface.messageBar().pushInfo(
                "Inspection Report", "点検ポイントを削除しました。"
            )
            return
        if not result:
            return

        values = dialog.values()
        fields = layer.fields()
        changes = {
            fields.indexOf(key): values[key]
            for key in ("name", "status", "comment", "photo")
        }
        changes[fields.indexOf("inspected_at")] = datetime.now().strftime(
            "%Y-%m-%d %H:%M"
        )
        layer.dataProvider().changeAttributeValues({feature.id(): changes})
        layer.triggerRepaint()


class InspectionPointTool(QgsMapToolEmitPoint):
    """クリック位置で点検ポイントを記録（追加または編集）するマップツール。"""

    def __init__(self, canvas, plugin):
        super().__init__(canvas)
        self.plugin = plugin
        self.setCursor(Qt.CrossCursor)

    def canvasReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        self.plugin.record_point(self.toMapCoordinates(event.pos()))
