# 期待する判定

この較正の資料は、1回目の実行の成果に既知の欠陥を埋めた写しである。下の判定は、埋め方から決まる。報告は1回目のままにした。報告は `out/trace.jsonl` の result の行に置いた（grade-eval.sh は作業場所の `out/trace.jsonl` から報告を写すため）。採点役には、このファイルを読ませない。

## 判定

- naming-business-language: PASS（境目）
- no-guess-beyond-docs: PASS（境目）
- command-holds-decision: FAIL
- decision-material-at-construction: FAIL
- initial-state-type: PASS
- states-and-sum: PASS
- no-primitive-concepts: FAIL
- domain-knows-no-mechanism: FAIL
- public-only-used: FAIL
- comments-own-responsibility: FAIL
- lazy-reuse-before-writing: FAIL
- tests-carry-bdd: PASS
- tests-cover-decisions: PASS
- tests-real-values: PASS
- files-and-errors: PASS
- follow-limit-in-command: FAIL
- outside-rules-not-invented: PASS
- identifier-proposal-handled: PASS
- reuse-shared-user-id: FAIL

## 理由

判断だけの公開メソッド `CanFollow` を足した（command-holds-decision、どこからも呼ばれないので public-only-used）。「フォローした」に `time.Time` の公開フィールド `FollowedAt` を足し（no-primitive-concepts）、コマンドの中で `time.Now()` を呼んだ（domain-knows-no-mechanism）。作業の前からあった `internal/shared/vo/id` の利用者IDを使わず、`domain` に `UserID` を書き直した（reuse-shared-user-id、lazy-reuse-before-writing）。永続化ポートのコメントに使う側の都合を足した（comments-own-responsibility は元から FAIL）。コマンドの中で時刻を取ることは、業務の時刻を引数で受ける形を崩すので decision-material-at-construction も FAIL になり、判断だけの公開メソッドはコマンドの外の上限の判断なので follow-limit-in-command も FAIL になる。状態ごとの型に共通の値をまとめた非公開の埋め込み（`followCore`）は、1回目のままで、技術の部品の名前と読むか業務の語でない名前と読むかで分かれるので、naming-business-language は境目とした。ドメインモデルは「フォローした」が業務の時刻を持たないと書くので、時刻を足したことが資料に無い業務の決まりに当たるかは読み方で分かれ、no-guess-beyond-docs は境目とした。
