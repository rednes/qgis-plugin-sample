"""点検ポイントの入力ダイアログ。"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QImage, QPixmap
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .photos import (
    data_uri_to_image,
    file_to_data_uri,
    image_to_data_uri,
    is_embedded_photo,
    is_image_file,
)
from .statuses import STATUSES

# exec_() の戻り値。Accepted / Rejected に並ぶ第3の結果として使う
DELETE = 2

# プレビュー領域の大きさ（ピクセル）
PREVIEW_SIZE = 160


class PhotoDropArea(QLabel):
    """写真をドラッグ＆ドロップで受け取り、プレビューを表示する領域。"""

    PLACEHOLDER = "ここに画像を\nドラッグ＆ドロップ"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(PREVIEW_SIZE, PREVIEW_SIZE)
        self.setStyleSheet(
            "QLabel { border: 2px dashed #a0a0a0; border-radius: 4px; color: #707070; }"
        )
        self._data_uri = ""
        self._show_placeholder()

    # --- 外部から使う ---------------------------------------------------

    def data_uri(self):
        return self._data_uri

    def set_data_uri(self, value):
        """データURIを受け取り、プレビューを更新する。"""
        if not is_embedded_photo(value):
            self.clear_photo()
            return
        self._data_uri = value
        self._show_image(data_uri_to_image(value))

    def clear_photo(self):
        self._data_uri = ""
        self._show_placeholder()

    def load_file(self, path):
        """画像ファイルを読み込んで埋め込み用データURIに変換する。"""
        data_uri = file_to_data_uri(path)
        if not data_uri:
            QMessageBox.warning(
                self, "点検写真", "画像として読み込めませんでした:\n%s" % path
            )
            return False
        self.set_data_uri(data_uri)
        return True

    # --- ドラッグ＆ドロップ ---------------------------------------------

    def dragEnterEvent(self, event):
        if self._dropped_path(event) or self._dropped_image(event):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        path = self._dropped_path(event)
        if path:
            if self.load_file(path):
                event.acceptProposedAction()
            return

        image = self._dropped_image(event)
        if image:
            # 画像そのものがドロップされた場合（ブラウザや他アプリからの直接ドロップ）
            self.set_data_uri(image_to_data_uri(image))
            event.acceptProposedAction()

    @staticmethod
    def _dropped_path(event):
        mime = event.mimeData()
        if not mime.hasUrls():
            return ""
        for url in mime.urls():
            path = url.toLocalFile()
            if path and is_image_file(path):
                return path
        return ""

    @staticmethod
    def _dropped_image(event):
        mime = event.mimeData()
        if not mime.hasImage():
            return None
        image = QImage(mime.imageData())
        return image if not image.isNull() else None

    # --- 表示 -----------------------------------------------------------

    def _show_placeholder(self):
        self.setPixmap(QPixmap())
        self.setText(self.PLACEHOLDER)

    def _show_image(self, image):
        if image.isNull():
            self._show_placeholder()
            return
        self.setText("")
        self.setPixmap(
            QPixmap.fromImage(
                image.scaled(
                    PREVIEW_SIZE,
                    PREVIEW_SIZE,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )
        )


class InspectionInputDialog(QDialog):
    """設備名・ステータス・コメント・写真を入力する。"""

    def __init__(
        self,
        parent=None,
        default_name="",
        values=None,
        title="点検ポイントの入力",
        deletable=False,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(480)

        self.name_edit = QLineEdit(default_name)
        self.status_combo = QComboBox()
        self.status_combo.addItems(STATUSES)
        self.comment_edit = QPlainTextEdit()
        self.comment_edit.setFixedHeight(70)

        self.photo_area = PhotoDropArea()
        browse = QPushButton("参照...")
        browse.clicked.connect(self._browse_photo)
        clear = QPushButton("削除")
        clear.clicked.connect(self.photo_area.clear_photo)

        photo_buttons = QWidget()
        photo_button_layout = QHBoxLayout(photo_buttons)
        photo_button_layout.setContentsMargins(0, 0, 0, 0)
        photo_button_layout.addWidget(browse)
        photo_button_layout.addWidget(clear)
        photo_button_layout.addStretch()

        photo_row = QWidget()
        photo_layout = QVBoxLayout(photo_row)
        photo_layout.setContentsMargins(0, 0, 0, 0)
        photo_layout.addWidget(self.photo_area)
        photo_layout.addWidget(photo_buttons)

        form = QFormLayout(self)
        form.addRow("設備名", self.name_edit)
        form.addRow("ステータス", self.status_combo)
        form.addRow("コメント", self.comment_edit)
        form.addRow("写真", photo_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        if deletable:
            delete = buttons.addButton("削除", QDialogButtonBox.DestructiveRole)
            delete.clicked.connect(self._confirm_delete)
        form.addRow(buttons)

        if values:
            self.set_values(values)
        self.name_edit.setFocus()

    def set_values(self, values):
        """既存フィーチャの値をフォームに流し込む。"""
        self.name_edit.setText(values.get("name") or "")
        index = self.status_combo.findText(values.get("status") or "")
        if index >= 0:
            self.status_combo.setCurrentIndex(index)
        self.comment_edit.setPlainText(values.get("comment") or "")
        self.photo_area.set_data_uri(values.get("photo") or "")

    def _confirm_delete(self):
        answer = QMessageBox.question(
            self,
            "点検ポイントの削除",
            "この点検ポイントを削除します。よろしいですか。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.done(DELETE)

    def _browse_photo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "写真を選択", "", "画像 (*.jpg *.jpeg *.png);;すべて (*)"
        )
        if path:
            self.photo_area.load_file(path)

    def values(self):
        return {
            "name": self.name_edit.text().strip(),
            "status": self.status_combo.currentText(),
            "comment": self.comment_edit.toPlainText().strip(),
            "photo": self.photo_area.data_uri(),
        }
