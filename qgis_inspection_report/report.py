"""点検結果を印刷レイアウトでPDFに書き出す。

QGIS ネイティブの印刷レイアウト（Print Layout）を使うので、外部ライブラリは要らない。
A4横の紙面に、タイトル・地図・凡例・点検結果一覧を配置する。

一覧は `QgsLayoutItemAttributeTable` ではなく `QgsLayoutItemHtml` で組む。
属性テーブルは画像を置けないが、HTMLなら各行の左端に写真のサムネイルを並べられるので、
「どの地点の写真か」を目で追わずに済む。写真は属性に埋め込んだデータURIなので、
img の src にそのまま書ける（一時ファイルへの展開が要らない）。
"""

from datetime import datetime
from html import escape

from qgis.core import (
    QgsLayoutExporter,
    QgsLayoutFrame,
    QgsLayoutItemHtml,
    QgsLayoutItemLabel,
    QgsLayoutItemLegend,
    QgsLayoutItemMap,
    QgsLayoutItemPage,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsPrintLayout,
    QgsProject,
    QgsUnitTypes,
)
from qgis.PyQt.QtCore import QRectF
from qgis.PyQt.QtGui import QFont

from .photos import is_embedded_photo
from .statuses import STATUSES, color_for

# A4横（ミリメートル）
PAGE_WIDTH = 297
PAGE_HEIGHT = 210
MARGIN = 10

# 紙面の左右の分割位置。左に地図と一覧、右に凡例を置く。
LEFT_WIDTH = 180
RIGHT_X = MARGIN + LEFT_WIDTH + 7
RIGHT_WIDTH = PAGE_WIDTH - RIGHT_X - MARGIN

# 地図の高さ（ミリメートル）。残りが一覧表の高さになる。
MAP_HEIGHT = 92

# 凡例の高さ（ミリメートル）。
# 凡例の実寸は描画時にしか確定しないため、固定で確保する。
LEGEND_HEIGHT = 50

# 一覧表に出す列（属性名, 見出し, 幅の割合%）
TABLE_COLUMNS = [
    ("name", "設備名", 20),
    ("status", "ステータス", 13),
    ("comment", "コメント", 33),
    ("inspected_at", "点検日時", 18),
]

# 写真列の幅の割合%
PHOTO_COLUMN_WIDTH = 16

# 一覧表に載せる最大行数
MAX_ROWS = 20

# 一覧表のサムネイルの最大幅（ピクセル）
THUMBNAIL_WIDTH = 110


class ReportBuilder:
    """点検レイヤーから印刷レイアウトを組み立てる。"""

    def __init__(self, layer, canvas=None, title="設備点検レポート"):
        self.layer = layer
        self.canvas = canvas
        self.title = title
        self.project = QgsProject.instance()
        self.layout = None
        self.map_item = None

    def build(self):
        self.layout = QgsPrintLayout(self.project)
        self.layout.initializeDefaults()
        self._setup_page()

        self._add_title()
        self._add_map()
        self._add_legend()
        self._add_table()
        return self.layout

    # --- 紙面 -----------------------------------------------------------

    def _setup_page(self):
        page = self.layout.pageCollection().page(0)
        page.setPageSize("A4", QgsLayoutItemPage.Landscape)

    def _place(self, item, x, y, width, height=None):
        """レイアウト上の位置と大きさをミリメートルで指定する。"""
        self.layout.addLayoutItem(item)
        item.attemptMove(QgsLayoutPoint(x, y, QgsUnitTypes.LayoutMillimeters))
        if height is not None:
            item.attemptResize(
                QgsLayoutSize(width, height, QgsUnitTypes.LayoutMillimeters)
            )
        return item

    # --- 各要素 ---------------------------------------------------------

    def _add_title(self):
        title = QgsLayoutItemLabel(self.layout)
        title.setText(self.title)
        font = QFont()
        font.setPointSize(18)
        font.setBold(True)
        title.setFont(font)
        title.adjustSizeToText()
        self._place(title, MARGIN, MARGIN - 4, LEFT_WIDTH, 10)

        subtitle = QgsLayoutItemLabel(self.layout)
        subtitle.setText(
            "出力日時: %s / 点検地点数: %d"
            % (datetime.now().strftime("%Y-%m-%d %H:%M"), self.layer.featureCount())
        )
        small = QFont()
        small.setPointSize(9)
        subtitle.setFont(small)
        subtitle.adjustSizeToText()
        self._place(subtitle, MARGIN, MARGIN + 6, LEFT_WIDTH, 6)

    def _add_map(self):
        self.map_item = QgsLayoutItemMap(self.layout)
        self.map_item.setRect(0, 0, LEFT_WIDTH, MAP_HEIGHT)
        self._place(self.map_item, MARGIN, MARGIN + 14, LEFT_WIDTH, MAP_HEIGHT)

        if self.canvas is not None:
            # キャンバスと同じ向きで描く
            self.map_item.setMapRotation(self.canvas.rotation())
        self.map_item.zoomToExtent(self._map_extent())
        self.map_item.setFrameEnabled(True)

    def _map_extent(self):
        """全点検ポイントが余白付きで入る範囲を返す。"""
        extent = self.layer.extent()
        if self.canvas is not None:
            # レイヤーのCRSとキャンバスのCRSが違う場合に備える
            extent = self.canvas.mapSettings().layerExtentToOutputExtent(
                self.layer, extent
            )
        if extent.isEmpty():
            return self.canvas.extent() if self.canvas else extent
        # 点が1つだけだと範囲が潰れるので、幅を持たせる
        margin = max(extent.width(), extent.height()) * 0.5 or 200
        extent.grow(margin)
        return extent

    def _add_legend(self):
        legend = QgsLayoutItemLegend(self.layout)
        legend.setTitle("凡例")
        legend.setLinkedMap(self.map_item)
        # 点検レイヤーだけを凡例に出す
        legend.setAutoUpdateModel(False)
        root = legend.model().rootGroup()
        for child in list(root.children()):
            if child.name() != self.layer.name():
                root.removeChildNode(child)
        legend.setResizeToContents(False)
        self._place(legend, RIGHT_X, MARGIN + 14, RIGHT_WIDTH, LEGEND_HEIGHT)

    def _add_table(self):
        table = QgsLayoutItemHtml.create(self.layout)
        self.layout.addMultiFrame(table)
        table.setContentMode(QgsLayoutItemHtml.ManualHtml)
        table.setHtml(self._build_html())
        table.loadHtml()

        table_y = MARGIN + 14 + MAP_HEIGHT + 6
        frame = QgsLayoutFrame(self.layout, table)
        frame.attemptSetSceneRect(
            QRectF(MARGIN, table_y, LEFT_WIDTH, PAGE_HEIGHT - table_y - MARGIN)
        )
        table.addFrame(frame)

    # --- 一覧表のHTML ---------------------------------------------------

    def _build_html(self):
        headings = "".join(
            '<th style="width:%d%%">%s</th>' % (width, escape(heading))
            for _, heading, width in TABLE_COLUMNS
        )
        rows = "\n".join(self._build_row(f) for f in self._sorted_features())
        style = """
body { font-family: sans-serif; margin: 0; }
table { border-collapse: collapse; width: 100%%; font-size: 9pt; }
th, td { border: 1px solid #808080; padding: 3px 5px; text-align: left;
         vertical-align: middle; }
th { background: #eeeeee; }
td.photo, th.photo { width: %(photo_width)d%%; padding: 2px; text-align: center; }
td.photo img { max-width: %(thumb)dpx; }
td.empty { color: #999999; font-size: 8pt; }
span.chip { display: inline-block; width: 8px; height: 8px;
            border-radius: 4px; margin-right: 4px; }
""" % {
            "photo_width": PHOTO_COLUMN_WIDTH,
            "thumb": THUMBNAIL_WIDTH,
        }
        return (
            '<html><head><meta charset="utf-8"><style>%s</style></head><body>'
            '<table><tr><th class="photo">写真</th>%s</tr>%s</table>'
            "</body></html>" % (style, headings, rows)
        )

    def _sorted_features(self):
        """異常・要確認を先に、正常を後に並べる。"""
        # STATUSES は「正常, 要確認, 異常」の順なので、逆順が深刻度の高い順になる
        priority = {status: index for index, status in enumerate(reversed(STATUSES))}
        features = sorted(
            self.layer.getFeatures(),
            key=lambda f: priority.get(f["status"], len(STATUSES)),
        )
        return features[:MAX_ROWS]

    def _build_row(self, feature):
        photo = feature["photo"]
        if is_embedded_photo(photo):
            photo_cell = '<td class="photo"><img src="%s"/></td>' % photo
        else:
            photo_cell = '<td class="photo empty">写真なし</td>'

        cells = [photo_cell]
        for attribute, _, _ in TABLE_COLUMNS:
            value = feature[attribute]
            text = escape(str(value)) if value not in (None, "") else ""
            if attribute == "status":
                text = '<span class="chip" style="background:%s"></span>%s' % (
                    color_for(value),
                    text,
                )
            cells.append("<td>%s</td>" % text)
        return "<tr>%s</tr>" % "".join(cells)


def export_report(layer, path, canvas=None, title="設備点検レポート"):
    """レイアウトを組み立ててPDFに書き出す。(成功したか, メッセージ) を返す。"""
    if layer is None or layer.featureCount() == 0:
        return False, "点検ポイントがありません。"

    layout = ReportBuilder(layer, canvas=canvas, title=title).build()
    exporter = QgsLayoutExporter(layout)
    settings = QgsLayoutExporter.PdfExportSettings()
    settings.dpi = 300
    result = exporter.exportToPdf(path, settings)
    if result == QgsLayoutExporter.Success:
        return True, path
    return False, "PDFの書き出しに失敗しました（コード %s）" % result
