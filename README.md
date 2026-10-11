# uim Toolbar for Cinnamon — 0.1.0

Cinnamon 6.7.4を対象に作成した、uim-toolbar-qt6-lxqtwidgetの動作移植版です。
参照したuimコミット: ed67e8a9651cfba564e3bf0125aba15d2c752179。
実機Cinnamon/uimでの動作は未検証です。まずmockモードで確認してください。

## 構成・依存

- applet.js: Cinnamonのパネル表示とメニュー。Qtウィジェットの埋め込みではありません。
- uim_bridge.py: ctypesでlibuimを利用する別プロセス。JSON Linesでアプレットと通信。
- Python 3.8以降、インストール済みuimの共有ライブラリが必要。
- Pythonの追加パッケージ・Qt開発ヘッダ・LXQt・ビルドツールは不要。
- IMモジュール/uim-xim等は既存環境を使用します。本パッケージは入力エンジンではありません。
- 補助ツールを使う場合は対応する実行ファイルを別途インストールしてください。
- Waylandでのuimの入力経路そのものを追加するものではありません。

## インストール

展開後のディレクトリで、一般ユーザーとして実行します。sudoは使用しません。

```sh
python3 test_bridge.py
python3 install.py install
```

Cinnamonの「アプレット」で「uim Toolbar」をパネルに追加してください。
更新は `python3 install.py install --replace`。旧版はバックアップされ、options.jsonは保持されます。
更新後はパネルから一度削除して再追加してください。

## まずUIだけをテストする

インストール先の `options.json` の `"mock": false` を `true` に変更し、
アプレットをパネルから削除・再追加してください。
mockでは2つのプロパティボタンと設定ボタンが表示されます。
入力モードメニューから「ひらがな」「直接入力」を選ぶと表示が変わります。
mockは実際のuimに接続せず、入力方式を変更しません。
補助ツール起動ボタンはmockでも実際にツールを起動するため注意してください。
テスト後はmockをfalseに戻して削除・再追加します。

## 実装した仕様

1. prop_list_updateのbranchごとに独立したパネルボタンとメニューを作成。
2. leafのラベル、説明、コマンド、選択マーク「*」を反映。
3. prop_activate + 改行 + コマンド + 改行をlibuim経由で送信。
4. charsetを指定した受信メッセージをUnicodeに変換。UTF-8/EUC-JPの単体テストを含みます。
5. uimのpixmapsを使用。暗背景設定なら_dark_background.png、なければ通常画像。
6. アイコンがなければbranchのテキストを表示。既定アイコン16px、ボタン26px。
7. toolbar-show-*-button?に従って補助ツールボタンを表示。
8. 右クリックには表示設定によらず全6ツールと再取得・再起動を配置。
9. custom_reload_notifyでuim設定を再読込。
10. uim helperへの接続と起動時/再接続時のプロパティ取得。
11. パネルから削除した際にバックエンドを終了、非同期読み書きをキャンセル。
12. 水平/垂直パネルに応じた配置。

元実装との意図的な違い:

- 元実装はメニュー表示中のprop_list_updateを捨てます。本版は最新の状態を保持し、
  メニューを閉じた後に描画します。操作中のメニュー内容は変更しません。
- 元実装のQString::SkipEmptyPartsと異なり、タブ区切りの空フィールドを保持します。
- 元実装の切断後の再接続処理を補い、helper接続を2秒間隔で再試行。
  バックエンド終了時はCinnamon側が3秒後に再起動します。
- toolbar-display-timeがalwaysなら通常表示、modeなら直接入力時に縮退。
  他の値も縮退扱いです。時間指定のタイマー表示は実装していません。
  縮退時も小さなuimアイコンを残し、右クリック操作・再取得を可能にします。
  元Qt版のようにアプレット全体を非表示にする実装ではありません。
- 補助ツール用のKDE Oxygen固定パス画像は使用せず、Cinnamonのテーマアイコンを使用。
- custom_reload_notify時には補助ツールの表示設定も再反映します。
- ラベルはuim gettextカタログを使用しますが、管理用の追加メニューは日本語固定です。
- 複数インスタンスは無効です。instance固有の設定UIはまだありません。

既定の補助ツールコマンド（参照したQt6版と同じ）:

| 種別 | コマンド |
| --- | --- |
| 入力方式切替 | uim-im-switcher-qt6 |
| 設定 | uim-pref-qt6 |
| 辞書 | uim-dict-gtk3 |
| 文字パッド | uim-chardict-qt6 |
| 手書き | uim-tomoe-gtk |
| ヘルプ | uim-help |

## options.json

配置先（標準）:
`~/.local/share/cinnamon/applets/uim-toolbar@hanaguro-port/options.json`
XDG_DATA_HOMEを設定している場合はその配下になります。
設定変更は削除・再追加後に反映します。

uimの画像が別の場所にある場合はpixmapDirsにそのディレクトリを追加します。
libuimはPythonのctypes.util.find_libraryで検索します。
ライブラリが標準検索パス外の場合はCinnamonセッション起動前にUIM_LIBRARYを
共有ライブラリの絶対パスに設定してください。端末だけでexportしても既存Cinnamonには伝わりません。

補助ツールの変更例（options.jsonのcommandsに指定）:

```json
"commands": {
  "pref": ["uim-pref-gtk3"],
  "switcher": ["uim-im-switcher-gtk3"]
}
```

コマンドはargv配列です。シェル展開・パイプ・リダイレクトは行いません。
存在しない補助ツールは通知で報告します。自動的な別版への置換はしません。

## バックエンド単独の診断

```sh
python3 -u uim-toolbar@hanaguro-port/uim_bridge.py
```

上記は待機し続けるプログラムです。入力欄へフォーカスするとpropertiesが出るか確認します。
Ctrl+Cで終了。EOFでも終了するため、`</dev/null`は使わないでください。
別端末から実行する場合は同じユーザー・同じデスクトップセッションで実行してください。
アプレットのプロセスと同時に動作させるとhelperクライアントが2つになるため、診断時は
パネルからアプレットを外してください。

出力例の種類:
- config: Scheme側のuimツールバー設定
- status: helper接続状態
- properties: フォーカス先の入力コンテキストが送ったプロパティ

libuimがない環境では以下でプロトコルだけを確認できます。

```sh
printf '%s\n' '{"type":"activate","command":"mode_direct"}' '{"type":"quit"}' |
  python3 -u uim-toolbar@hanaguro-port/uim_bridge.py --mock
```

アプレット/バックエンドの異常はCinnamonのログと継承したstderrに出力します。
環境がjournald管理の場合は `journalctl --user -b` も確認してください。

## 実機で確認する項目

- mockでアプレットが読み込める、各メニューが開ける、選択表示が変わる。
- 通常モードでGTK/Qt/XIMなど既存のuim入力アプリへフォーカスすると状態が更新される。
- モード変更後に対象アプリへ戻ると実際の入力モードが変更されている。
- メニューを開いたままアプリ/モードが変わっても操作中のメニューが壊れない。
- 全6補助ツールの起動と、未インストールの場合のエラー通知。
- uim設定変更・暗背景画像・アイコン未検出時の文字表示。
- helper停止/再起動、バックエンド終了後の再接続。
- 水平/垂直パネル、削除・再追加、Cinnamon再ログイン後の状態。

Cinnamonのパネルメニュー操作によるフォーカス移動とuim helperの通知順序は、
実機での確認が必要です。初期版では特定ウィンドウに対する強制フォーカス復帰を行いません。

## アンインストール

まずパネルからアプレットを削除し、その後:

```sh
python3 install.py uninstall
```

削除対象のUUIDを確認し、yes入力後にこのアプレットのディレクトリだけを削除します。
旧インストールのバックアップは削除しません。

## 検証範囲とライセンス

同梱テストはパーサー、文字コード、mock通信、コマンド検査を対象とします。
実libuimのABI、Cinnamon 6.7.4のAPI、実際のフォーカス挙動は実機未検証です。
ライセンスはLICENSE、参照元はPROVENANCE.mdをご覧ください。
