# 実 DB

実 DB を使うテスト（永続化層、usecase、handler、受信境界、ワーカー）は、dockertest で起動した PostgreSQL の実物を使う。偽のリポジトリ、インメモリの代わり、sqlc の `DBTX` の差し替え、トランザクションの管理の wrapper を作らない。Docker が無いときに `t.Skip` しない。起動できなければ、テストは失敗する。実 DB を使うテストを、ビルドタグで普段のテストから分けない。分けると、普段は走らないテストが生まれ、壊れたことに気づくのが遅れるからである。

# 置き場は二つ

実 DB の基盤は、テスト支援の二つの package に分ける。どちらも横断的関心事の置き場（例：`internal/crosscutting`）に置き、本番のコードは import しない。

**コンテナの package**（例：`dockertest`）は、コンテナの起動、起動待ち、migration の適用、全テーブルを空にする処理だけを持つ。`testing.TB` と testify を扱わない。

**テストの基盤の package**（例：`integrationtest`）は、`TestMain` と組み合わせてコンテナの起動と終了をプロセスに一回にし、サブテストごとにデータを空にする。`testing.TB` を扱うのはこちらだけである。

実 DB を使う package は、`main_test.go` の `TestMain` でこの基盤を起動し、DB を使う各サブテストを基盤の `Run` で始める。起動の手順を、package ごとに書かない。

```go
var suite = integrationtest.NewPostgresSuite()

func TestMain(m *testing.M) {
	os.Exit(suite.RunTests(m))
}
```

`main_test.go` に置けるのは、この共有の基盤と `TestMain` だけである。

# 起動待ちには、試行ごとの期限を付ける

コンテナを起動した直後の PostgreSQL は、接続を拒む。接続できるまで繰り返し試すが、**各試行に、全体より短い期限を付ける**。全体の期限しか無いと、一回の試行が起動途中のコンテナで止まったとき、残りの時間をすべてその試行に使ってしまう。起動待ちの失敗が「間に合わなかった」のか「止まった」のかを、分けられなくなる。

```go
const (
	readyTimeout        = 30 * time.Second
	readyAttemptTimeout = 2 * time.Second
)

err = dockerPool.Retry(ctx, readyTimeout, func() error {
	attemptCtx, cancel := context.WithTimeout(ctx, readyAttemptTimeout)
	defer cancel()
	return database.Ping(attemptCtx)
})
```

待ち方の原則（sleep で待たず、観測できる条件で期限を付けて待つ）は、testing-strategy の待機の原則に従う。ここに置くのは、その原則を Go の起動待ちに当てた形だけである。

# スキーマは migration の履歴から作る

テスト用の DB は、本番と同じ migration の履歴を、名前の順に適用して作る。テストの中で DDL を書かない。期待するスキーマと migration の履歴が一致することは、物理設計の資料が決める検査で確かめる。

PostgreSQL の版は、本番とローカルの環境と同じ tag（と digest）に固定する。`latest` にしない。

`timestamptz` は UTC の `time.Time` として読むよう、接続ごとに型の対応を登録する。期待の値を UTC で書き、読み返した行と比べるからである。

# ケースごとに空にする

各サブテストの初めに、アプリケーションの全テーブルを一文の `TRUNCATE ... RESTART IDENTITY CASCADE` で空にする。対象のテーブルは、migration を適用した後の DB のカタログから一度だけ取る。テストがテーブルの一覧を持たない。

ケースどうしが独立していられるのは、この空にする処理があるからである。同じ DB を package の全ケースが共有するので、DB を使うテストは `t.Parallel()` を書かない。ループの直前のコメントで、共有する資源を名指しする。

```go
// 同じ実 DB を全ケースが共有するため直列で走らせる。
for _, tt := range tests {
```

`go test ./...` は package を並列に走らせるので、コンテナは package ごとに専用にする（dockertest の再利用を切る）。コンテナには、強制終了で残ったものを見つけて消すための印（label）を付ける。

# 読み取り専用の接続

Query の実装のテストのために、基盤は読み取り専用の接続（各接続の既定を読み取り専用にした pool）も用意する。Query の実装は本番と同じくこの接続から読み、書き込みの形をした読み取りも PostgreSQL が拒む。

# 後片付け

`TestMain` は、`m.Run()` の後に接続を閉じ、コンテナを削除してから、終了コードを返す。`os.Exit` は `defer` を実行しないので、片付けを `defer` に書かない。接続の返し忘れは、期限付きで待ったうえで失敗として報告する。
