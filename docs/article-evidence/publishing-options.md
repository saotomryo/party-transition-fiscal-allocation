# 公開方式の検討（2026-10-13）

現段階では公開作業は未実施。

- Streamlit：既存のPython画面・条件選択・個別自治体閲覧を活かす最短の方式。Community CloudはGitHubリポジトリと連携する。現状はdata/をGit対象外にしているので、コードだけの公開では動かない。生成済みの必要データを配布・読み込む設計と依存環境の動作確認が必要。
- GitHub Pages：HTML/CSS/JavaScriptの静的ホスティング。現在のPythonアプリをそのまま実行できない。今回の事前集計CSVから、年・項目・窓幅を切り替える静的グラフと出典ページを作る方式が適する。Pythonでの集計は公開前に行う。自治体閲覧まで同等にするには追加実装が必要。

記事から読者に全体傾向を簡単に確認してもらう用途なら、GitHub Pagesに集計済みグラフ・方法・CSVを置く構成を推奨。既存の全機能を早く公開することを優先する場合はStreamlitを選ぶ。どちらも公開対象データを確定してから配布する。

公式資料（2ページ取得成功、失敗0）：
- https://docs.streamlit.io/deploy/streamlit-community-cloud
- https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages
