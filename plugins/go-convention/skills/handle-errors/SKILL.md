---
name: handle-errors
description: >-
  Go のエラーを、資料の「拒む理由」と 1:1 の sentinel（`errors.New`・日本語文言）、層境界で 1 回だけの `fmt.Errorf("...: %w")`、`errors.Is` での判定、境界 1 か所の `connect.Code` 対応表、という一つの形で書く・直す。「エラーを定義して」「このエラーの包み方を直して」「エラーを connect.Code に翻訳して」「エラー文言を揃えて」と言われたとき、また層別の実装規約が「エラーの規約」としてここを指したときに使う。エラーをどこで記録するか（ログの規約）と、テストでエラーをどう検証するか（テストの形の共通規則）は対象外として、それぞれの規約へ返す。
---

# handle-errors

[工程順序の正本](playbook.yml)を最初に読み、同じagentが\`steps\`を宣言順に実行する。YAMLは工程順序を決め、各工程の判断内容と根拠はこの本文と参照資料を実読して評価する。失敗時は成功扱いせず停止して、完了工程、根拠、未決を残し、再開時は最初の未完了工程から続ける。

これは、**「拒まれたこと・できなかったこと」を、起きた場所から最外境界まで、判定できる形（sentinel）と読める文言（日本語）で運ぶ規約**である。どの層でも同じ道具（`errors` と `fmt` だけ）で書き、翻訳は境界 1 か所に集める。

これは、**ログではない**。エラーは「返す」もので、記録するのは最外境界の仕事である。内側の層は返す直前にログを書かない（ログの規約が決める）。**transport の分類でもない**。sentinel は業務の拒否理由であって、`connect.Code` も HTTP status も知らない。Code は境界の対応表が決める。**独自のエラー基盤でもない**。`Kind` / `Layer` / `Reason` のような分類型、`errs.Wrap` のような包む API、`RejectionError{Reason}` のような汎用型は作らない。分類は「どの sentinel か」で足り、基盤は「今回はどの分類を選ぶか」という判断を毎回生む。

前提: Go 1.27（`errors.AsType` は 1.26 以降）・`github.com/jackc/pgx/v5`・`connectrpc.com/connect` v1.21.0（v2 alpha は採らない）・`github.com/stretchr/testify`（テストでの判定に `require.ErrorIs`）。

題材は貸会議室予約 RoomFlow（module `example.com/roomflow`）。ディレクトリ構成そのものは上位の開発規約が決めるので、例は import path を短くするため `reservation` / `rdb` / `usecase` / `handler` と平らにしている。

## 規約

| # | 柱 | 一言で | 正本 |
|---|---|---|---|
| 1 | sentinel | 資料の「拒む理由」1 行に `errors.New` 1 つ。`Err{何が拒まれたか}`、行末コメントに資料の語。資料に無い Go の都合（値オブジェクトの生成の条件・和型の nil）は別の var ブロック | [sentinels.md](references/sentinels.md) |
| 2 | 文言 | 日本語。句点なし・改行なし。「何が拒まれたか／何ができなかったか」。「失敗しました」だけの文言は書かない | [sentinels.md](references/sentinels.md) |
| 3 | 返す形 | `(T, error)` か `(T, bool)` の 2 つだけ。拒まないが何も変えない操作は `bool`。panic は書かない | [wrapping.md](references/wrapping.md) |
| 4 | 包み方と判定 | 層境界で `fmt.Errorf("<操作> <業務 ID>: %w", err)` を 1 回。同じ package 内は `return err`。判定は `errors.Is` | [wrapping.md](references/wrapping.md) |
| 5 | 翻訳 | 永続化層が DB 制約違反・0 行を sentinel へ、最外の interceptor `Logging` が `handler/error_table.go` の `codeTable` で `connect.Code` へ。表は 1 か所、応答の文言は sentinel だけ | [translation.md](references/translation.md) |
| 6 | 丸めない | エラーを既定値に丸めない。フォールバックを書かない。エラー分岐はガード節の早期リターン | [wrapping.md](references/wrapping.md) |

## 手順

1. **資料の「拒む理由」を集めて sentinel にする。** domain-model 資料の各操作の「拒む理由」、「生成の条件」、「状態と型の分割」の「できない操作」を読み、業務上の根拠 1 つに `errors.New` 1 つを `errors.go` に並べる。同じ根拠が複数の操作に現れるなら sentinel は 1 つ。値オブジェクトの生成の条件と和型の nil は資料に無い Go の都合なので、別の var ブロックにそう書いて置く。完了条件: 資料と 1:1 のブロックの全 sentinel が行末コメントで資料の語を指せ、資料に無い sentinel がそのブロックに無い
2. **文言を書く。** 日本語・句点なし・改行なし・「何が拒まれたか」。包んだときに `予約 R-0101 の確定: 仮押さえ期限以降は確定できない` と連なるか声に出して確かめる。完了条件: 「失敗しました」「エラー」だけの文言が無く、個人情報を文言に入れていない
3. **返す形を決める。** 拒む操作は `(T, error)`、拒まないが何も変えない操作は `(T, bool)`、値が複数要るなら結果 struct。完了条件: `(T, bool, error)` が無く、error を返す経路で `T` はゼロ値
4. **包む場所を決める。** package を出る `return` ごとに `%w` を 1 回。同じ package 内、および自分が起こしていない error を通すだけの関数（handler 本体、interceptor の `next`）は包まない。`tx.Manager.Run` は `fn` の error を包まず、rollback の失敗を `errors.Join` して返す。エラー分岐は `if err != nil { return ... }` のガード節で書き、`else` に正常系を入れない。完了条件: 1 つの error が通る境界の数と `%w` の数が一致し、`%v` で包んだ箇所が無く、`err != nil` の分岐がすべて `return` で終わる
5. **翻訳する。** リポジトリで `errors.AsType[*pgconn.PgError]` により名前付き制約の違反をドメイン sentinel か `ErrConflict` へ、current 行の 0 行を `ErrNotFound` へ、楽観ロックの 0 行を `ErrConflict` へ写す。`codeTable` に新しい sentinel を載せるか、載せず `Internal` に落とすかを決める。完了条件: 対応表が `handler/error_table.go` の 1 か所にあり、追加した sentinel ごとに「載せた Code」か「載せない理由」が言える
6. **機械検査を通す。** `go vet ./...`（`%w` の誤用と `fmt.Errorf` の引数不足を検出する）。完了条件: vet が通る
7. **報告する。** 下の「報告」の項目

## 停止条件

- 資料に「拒む理由」が無い操作で拒みたくなった → sentinel を作らない。資料（domain-model）へ「拒む理由の追加」として返して止まる
- 集約の外で守る不変条件（重なる利用枠など）を、生成を呼ぶ側の確認だけで守るか DB 制約でも守るかが決まっていない → データモデル資料へ返して止まる。翻訳表に載せる制約名が決まらない
- 呼ぶ側が「拒否の種類」で分岐したがり、sentinel の `errors.Is` では足りず値が要る → その操作専用の型付きエラーを 1 つ作る（[sentinels.md](references/sentinels.md) §6）。2 つ以上の操作で使い回す型になりそうなら止まり、汎用型を作らずに済む設計を提案する
- 外部ライブラリのエラーを usecase やドメインで型判定したくなった → 境界（リポジトリ・interceptor）へ翻訳を戻す。usecase に `pgconn` / `connect` の import が現れたら止まる
- エラーを既定値に丸めたくなった（取得できなければ空で続ける・不正値なら初期値にする）、または別経路で再試行して黙って続けるフォールバックを書きたくなった → 書かずに止まる。何を丸めたいか・なぜ error で返せないかを示して、利用者の許可を得てからだけ書く（[wrapping.md](references/wrapping.md) §9）

## チェックリスト

- [ ] sentinel は `errors.New` で、変数名が `Err{何が拒まれたか}`、行末コメントが資料の語を指している
- [ ] 文言は日本語・句点なし・改行なし・「何が拒まれたか」。「失敗しました」だけ、英語だけ、技術語だけの文言が無い
- [ ] `%w` は 1 つの `fmt.Errorf` に 1 つ。`%v` / `err.Error()` / `errors.New(err.Error())` で連鎖を切っていない
- [ ] 文脈は「<操作> <業務 ID>」。氏名・メール・トークンが文脈にも文言にも無い
- [ ] 判定は `errors.Is`。文言の比較（`err.Error() == ...` / `strings.Contains`）と、自前のエラーの型 switch が無い
- [ ] `errors.AsType` はリポジトリ（`*pgconn.PgError`）と interceptor（`*connect.Error`）、および型付きエラーを作った操作の呼び手だけにある
- [ ] `errors.Join` はドメイン外の独立した複数失敗（入力 DTO の複数フィールド、`defer` の Close 合成、`tx.Manager.Run` の rollback 合成）だけにある
- [ ] `panic` が無い。`Must*` はテストと package 変数の定数だけ、`recover` は最外境界だけ
- [ ] 返り値は `(T, error)` か `(T, bool)`。error のとき `T` はゼロ値
- [ ] ドメイン package が sentinel を包んでいない（そのまま返している）
- [ ] `connect.Code` への対応表が `handler/error_table.go` の `codeTable` 1 か所にあり、handler 本体と変換関数に `connect.NewError` が無い
- [ ] 応答の文言が sentinel の文言だけで、包んだ文脈を出していない。`Internal` に落とすとき、内部の文言（包んだ文脈・外部ライブラリの文言）を応答に出していない
- [ ] `_ = err` でエラーを捨てていない（例外は読み取り専用の `Close`）
- [ ] `if err != nil` の中身が `return` で終わっている。エラーをゼロ値・既定値・空スライスに置き換えて続行する箇所、別経路へ黙って切り替える箇所が無い
- [ ] 正常系が `else` の中に入っていない（ガード節の後に平らに続いている）

## 報告

- 追加・変更した sentinel と、それが指す資料の行（操作名と「拒む理由」の語）
- 資料に無いのに欲しくなった拒否と、資料へ返した論点
- 対応表の変更: 載せた sentinel と Code、載せずに `Internal` にした sentinel とその理由
- 包み方を変えた境界（どの package の `return` に `%w` を足した／外した）
- 型付きエラーを作ったなら、その操作名と呼び手が読む値
- 利用者の許可を得て書いたフォールバックがあるなら、その箇所と許可の内容
