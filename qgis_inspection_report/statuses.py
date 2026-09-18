"""点検ステータスとその配色。

入力ダイアログ・地図の色分け・レポートの3か所から参照するので、
定義を1か所にまとめておく。
"""

# ステータスごとの配色。異常箇所が地図上で赤く浮かび上がるようにする。
# 並び順がそのまま入力ダイアログの選択肢と凡例の並び順になる。
STATUS_COLORS = [
    ("正常", "#4caf50"),
    ("要確認", "#ffc107"),
    ("異常", "#e53935"),
]

# 想定外の値が入っていたときの色と表示名
UNKNOWN_COLOR = "#9e9e9e"
UNKNOWN_LABEL = "未分類"

STATUSES = [status for status, _ in STATUS_COLORS]

STATUS_COLOR_MAP = dict(STATUS_COLORS)


def color_for(status):
    """ステータスに対応する色を返す（未知の値はグレー）。"""
    return STATUS_COLOR_MAP.get(status, UNKNOWN_COLOR)
