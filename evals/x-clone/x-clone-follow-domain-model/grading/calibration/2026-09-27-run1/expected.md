# 期待する判定

この較正の資料は、2026-09-27 の1回目の実行（claude plugin eval、`--runs 1 --ablation none`、development-convention は PR #27 の branch）で作られた repository と報告である。下の判定は、eval を組んだ担当がコードと報告と資料を読んで出した。報告は `out/trace.jsonl` の result の行に置いた（grade-eval.sh は作業場所の `out/trace.jsonl` から報告を写すため）。採点役には、このファイルを読ませない。

## 判定

- naming-business-language: FAIL
- no-guess-beyond-docs: PASS
- command-holds-decision: PASS
- decision-material-at-construction: PASS
- initial-state-type: PASS
- states-and-sum: PASS
- no-primitive-concepts: PASS
- domain-knows-no-mechanism: PASS
- public-only-used: PASS（境目）
- comments-own-responsibility: FAIL
- lazy-reuse-before-writing: PASS
- tests-carry-bdd: PASS
- tests-cover-decisions: PASS
- tests-real-values: PASS
- files-and-errors: PASS
- follow-limit-in-command: PASS
- outside-rules-not-invented: PASS
- identifier-proposal-handled: PASS
- reuse-shared-user-id: PASS

## 理由

comments-own-responsibility は、`errors.go` の `ErrAlreadyFollowing` の行末のコメント「フォローを記録する側が守る」が、担わないものを誰が担うかを書いているので FAIL とした。状態ごとの型に共通の値をまとめた非公開の埋め込み `followCore` と初期状態の型 `PendingFollow` は、どちらも形から付けた名前なので、naming-business-language は FAIL とした。public-only-used は、`Version.Next` と `FirstVersion` が同じ package の中と、これから書く永続化から読まれる値で、今は package の外に呼び手が無いので、境目とした。フォロー中の人数は、ドメインモデルがコマンドの引数に置いていたが、初期状態の型 `PendingFollow` に持たせており、decision-material-at-construction は PASS である。外すと終わる状態遷移なので、`UnfollowUser` の結果が次の状態を持たないのは資料に従った形で、states-and-sum は PASS とした。
