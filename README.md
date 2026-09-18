# qgis-plugin-sample

現地の点検結果を地図に記録し、地図つきPDFレポートを出力するQGISプラグインのサンプル。
Claude Code と QGIS MCP でプラグインを作る流れを示すために書いたもので、そのまま業務に載せる前提のものではない。

詳しくは [業務で繰り返し使えるQGISプラグインを、Claude CodeとQGIS MCPでサクッと作ってみた](https://dev.classmethod.jp/articles/building-reusable-qgis-plugin-claude-code-qgis-mcp/) を参照。

## できること

- 点検ポイントレイヤーの生成（設備名・ステータス・コメント・写真・点検日時）
- 地図クリックでの記録。何もない場所なら追加、既存ポイントの上なら編集
- ステータス（正常 / 要確認 / 異常）による色分けと、吹き出しラベルの常時表示
- 写真のドラッグ＆ドロップ。プロジェクトに埋め込むので元ファイルが移動しても壊れない
- 一覧表・地図・凡例を並べたA4横のPDFレポート出力

## 動作環境

QGIS 3.28 以降（QGIS 3.44 で確認）。

## インストール

リポジトリをクローンし、プラグインディレクトリへシンボリックリンクを張る。

```sh
git clone https://github.com/rednes/qgis-plugin-sample.git
ln -s "$PWD/qgis-plugin-sample/qgis_inspection_report" \
  ~/Library/Application\ Support/QGIS/QGIS3/profiles/default/python/plugins/
```

Linux は `~/.local/share/QGIS/QGIS3/...`、Windows は `%APPDATA%\QGIS\QGIS3\...` に読み替える。
QGIS を起動し、プラグイン管理から `Inspection Report` を有効化する（実験的プラグインの表示を有効にしておく）。

## 使い方

ツールバーに3つのボタンが並ぶ。

1. **点検レイヤー作成** — 「点検ポイント」レイヤーを作る。色分けとラベル設定もここで入る
2. **点検ポイント記録** — 地図をクリックして記録。既存ポイントをクリックすると編集ダイアログが開き、削除もできる
3. **レポート出力** — 保存先を選ぶとPDFを書き出す

## 構成

| ファイル                        | 役割                                                         |
| ------------------------------- | ------------------------------------------------------------ |
| `qgis_inspection_report/main_plugin.py` | ツールバー、レイヤー生成、シンボル・ラベル設定、マップツール |
| `qgis_inspection_report/dialogs.py`     | 点検内容の入力ダイアログ（写真のドロップ領域を含む）         |
| `qgis_inspection_report/photos.py`      | 写真をデータURIに変換してプロジェクトに埋め込む              |
| `qgis_inspection_report/report.py`      | 印刷レイアウトの組み立てとPDF書き出し                        |
| `qgis_inspection_report/statuses.py`    | ステータスと配色の定義                                       |
| `qgis_project/sample.qgz`               | 動作確認用のQGISプロジェクト。背景地図と記録済みの点検ポイント入り |

`.mcp.json` には開発に使った QGIS MCP サーバーの設定が入っている。プラグインの動作自体には要らない。
