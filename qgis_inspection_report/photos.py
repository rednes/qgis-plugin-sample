"""点検写真をプロジェクトに埋め込むためのユーティリティ。

写真はローカルファイルのパスで持たず、縮小したサムネイルを PNG の
base64 データURIに変換して属性値として保持する。こうするとプロジェクト
ファイルだけで写真が完結し、元ファイルを移動・削除しても表示が壊れない。
"""

from qgis.PyQt.QtCore import QBuffer, QByteArray, QIODevice, Qt
from qgis.PyQt.QtGui import QImage

# 埋め込むサムネイルの最大辺（ピクセル）。
# 大きくすると画質は上がるが、属性値（＝プロジェクトファイル）も膨らむ。
THUMBNAIL_MAX_SIZE = 320

DATA_URI_PREFIX = "data:image/png;base64,"

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp")


def is_embedded_photo(value):
    """属性値が埋め込み写真（データURI）かどうかを返す。"""
    return bool(value) and value.startswith(DATA_URI_PREFIX)


def image_to_data_uri(image, max_size=THUMBNAIL_MAX_SIZE):
    """QImage を縮小し、PNG の base64 データURIに変換する。"""
    if image.isNull():
        return ""

    thumbnail = image.scaled(
        max_size, max_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
    )
    buffer_data = QByteArray()
    buffer = QBuffer(buffer_data)
    buffer.open(QIODevice.WriteOnly)
    thumbnail.save(buffer, "PNG")
    buffer.close()
    return DATA_URI_PREFIX + bytes(buffer_data.toBase64()).decode("ascii")


def file_to_data_uri(path, max_size=THUMBNAIL_MAX_SIZE):
    """画像ファイルを読み込み、データURIに変換する（読めなければ空文字）。"""
    return image_to_data_uri(QImage(path), max_size)


def data_uri_to_image(value):
    """データURIから QImage を復元する（データURIでなければ空の QImage）。"""
    if not is_embedded_photo(value):
        return QImage()

    encoded = value[len(DATA_URI_PREFIX):]
    raw = QByteArray.fromBase64(QByteArray(encoded.encode("ascii")))
    image = QImage()
    image.loadFromData(raw, "PNG")
    return image


def is_image_file(path):
    """拡張子から画像ファイルらしさを判定する。"""
    return path.lower().endswith(IMAGE_SUFFIXES)
