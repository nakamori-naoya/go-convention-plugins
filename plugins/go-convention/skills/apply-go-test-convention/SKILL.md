---
name: apply-go-test-convention
description: Go のテストを、層を問わない共通の形（対象一つにテスト関数一つ、テーブル駆動、id / name / description と資料の BDD の写し方、差し替えてよい境界、決定的な Builder と持ち主の書き込み経路、dockertest の実物の DB）で書く・直す。「テストを書いて」「何を mock にしてよいか」「テストデータの作り方を決めて」「BDD の網羅を確かめて」と言われたとき、また層の skill が土台にするときに使う。
---

# apply-go-test-convention

守るものは三つある。**テストが本番の組み立てを通ること**、**失敗したテストを同じ値で再現できること**、**資料の一つの BDD を一つのテストだけが名乗ること**。完全な例は [例](references/examples.md) にあり、形に迷ったら読む。前提は testify、`go.uber.org/mock`、`github.com/ory/dockertest/v4` である。

## 形：対象一つにテスト関数一つ、表一つ

対象（一つのメソッドか関数）一つにつき、テスト関数は一つにする。名前は `Test{型}_{メソッド}` か `Test{関数}` で、`_Error` のような接尾辞で二つ目を作らない。状態ごとに分けた型は別の型なので、それぞれにテスト関数を持つ。package は `{pkg}_test` にし、公開 API だけを叩く。テストのために実装を曲げない規律は development-convention の `write-readable-code` に従い、Go では `export_test.go` で内部を晒さない。ファイルスコープには `Test*`、`Benchmark*`、`const` だけを置き、helper 関数を作らない。

表は無名 struct のスライスで、フィールドを識別（`id`、`name`、`description`）、Given、When、Then の順に並べ、実行と検証はループ本体に一回だけ書く。`t.Run(tt.id+" "+tt.name, ...)` にすると `go test -run 'TestX/BDD-001_'` で一つのケースを走らせられる。Given のフィールドは `description` の `Given:` の行と一対一にし、既定ではデータで書く。`setup func(t *testing.T) fixture` は、Given に `t` か直列化できない資源が要り、それがケースごとに違うときだけ置き、置いたら全ケースが持つ。When のフィールドは対象の引数名そのままにし、`in` や `args` の袋に包まない。Then は `want`、`want<何>`、`wantErr error` で、`wantErr` には対象が返す具体エラーを入れ、`require.ErrorIs` の後に `assert.Zero(t, got)` で結果がゼロ値であることも見る。`bool` や文言の一致で失敗を表さない。入力がそれまでの操作である型は、前提の操作 `given` と、操作と直後の期待の組 `steps` に分けて表にする。

`require` は後の検証が無意味になるとき（`NoError`、`ErrorIs`）に、互いに独立した期待は `assert` に使う。ケースの間に依存を作らず、どの順でも一つだけでも通るようにする。`t.Parallel()` はテスト関数とサブテストの両方に書くか、どちらにも書かず、書かないならループの直前のコメントで共有する資源を名指しする。

## ケースの識別：資料の BDD は、主に担うテストだけが名乗る

資料の BDD を写すケースは、資料の ID、見出し、gherkin を、字下げと `NOTE:` を含めて改変せずに `id`、`name`、`description` に写す。資料に無いケースは生成した id（`7c2e19`）を使い、資料風の番号を付けない。`id` と `name` は同じ package で一意にし、消した id を使い直さない。`description` は raw string で、`Given:`、`When:`、`Then:` を行頭にこの順で一回ずつ置き、`And:` は `Given:` か `Then:` の後にだけ置く。

資料の一つの BDD を `id` に写すのは、repository 全体で、その BDD の `Then:` を最も内側で観測できるテストのちょうど一つだけである。どの層が主に担うかは各層の develop-* が書いている。同じ場面を別の層のテストが通るなら、そのケースは生成した id を使う。資料の ID を写すファイルには、`// BDD の資料: <repository 相対の path>` を一つだけ書く。どの層のテストも担わない BDD だけを、最も担いそうな層のテストファイルの末尾に `// どのテストも担わない BDD:` に続けて、ID と理由を一行ずつ並べる。

## 差し替えの仕組み

どの境界を差し替えてよいかは、testing-strategy の `design-test-strategy` の test-strategy-judgment.md に従う。Go では、差し替えはポートの interface から `mockgen` で生成した gomock で行い、手書きの偽物（固定の時計、インメモリのリポジトリ）と、外部の API を `httptest` で立てる stub は作らない。stub が要ると感じたら、ポートの切り方を疑う。それ以外の部品は本番の組み立ての関数で実物を使い、実物で起こせる失敗（制約の違反、行が無い、古い版での更新）は実物を壊れた状態にして起こす。

## テストデータ：決定的な Builder と、持ち主の書き込み経路

前提の値は `New<型>Builder().With<項目>(...).Build(t)` の Builder で作り、保存済みの前提の Builder は `Build(ctx, t)` にする。`t` は `Build` でだけ受け、Builder は対象の実装の直下の `builders/` に置く。既定値は資料の BDD の代表値の固定の値にし、乱数、現在時刻、採番を使わない。テストの対象そのものは Builder で作らない。Builder の誤りと対象の誤りが打ち消し合うからである。

保存済みの前提は、そのデータを本番で書き込むコマンドとリポジトリ（持ち主の書き込み経路）を順に通して作り、自分でトランザクションを張って確定させてから返す。延滞の貸出が前提なら、借りる、適用する、延滞にする、適用する、を実物で通す。`Restore*` で組んだり行を直接入れたりすると、集約の不変条件を破った前提を黙って作れてしまう。行を直接入れてよいのは、保存値の破損を検出するテストと、別の配備単位が所有していてコンパイル上 import できない行だけで、後者は資料の After の行を写し、理由を Builder の型のコメントに書く。

## 実 DB：dockertest の実物を、試行ごとの期限付きで待つ

DB を使うテストは、dockertest で起動した PostgreSQL の実物を使い、Docker が無くても `t.Skip` せず、build tag で分けない。コンテナの起動、起動待ち、migration、全テーブルを空にする処理は横断的関心事の `dockertest` に、`testing.TB` を扱う基盤は `integrationtest` に置き、DB を使う package は `main_test.go` の `TestMain` で一度だけ起動する。

起動待ちは、各試行に全体より短い期限を付ける。全体の期限しか無いと、止まった一回の試行が残りの時間を全部使い、間に合わなかったのか止まったのかを分けられなくなる。スキーマは本番と同じ migration の履歴から作り、PostgreSQL の版は本番と同じ tag に固定する。各サブテストの初めに、カタログから取った全テーブルを `TRUNCATE ... RESTART IDENTITY CASCADE` で空にし、DB を使うテストは直列で走らせる。基盤は読み取り専用の接続も用意する。

```go
err = dockerPool.Retry(ctx, 30*time.Second, func() error {
	attemptCtx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	return database.Ping(attemptCtx)
})
```

## 機械検査

```bash
go vet ./...
go test -shuffle=on -count=1 ./...
python3 scripts/check-cases.py <テストのあるディレクトリ>
python3 scripts/check-bdd-coverage.py <repository root> <資料.md>...
```

二つの tool はこの `SKILL.md` の隣の `scripts/` にあり、違反があれば終了コード 1、入力が無ければ 2 を返す。`check-cases.py` はテストの形を、`check-bdd-coverage.py` は資料の各 BDD が repository 全体でちょうど一回名乗られていることを判定する。どのテストが主に担うべきか、差し替えが testing-strategy の原則に沿うかは、読んで確かめる。

## 止まるとき

対象が公開 API から観測できないとき、内部の部品を差し替えないと書けないとき（ポートの切り方か組み立ての関数の不足）、前提を持ち主の書き込み経路で作れず例外にも当たらないとき、`go.mod` に testify か `go.uber.org/mock` が無いときは、書かずに不足を返す。ケースの名前や並びの揺れでは止まらず、資料の順と語に最も近い形を採る。
