# Query の実装

# 読み取り専用の接続だけから読む

Query の実装は、読み取り専用の接続（各接続の既定を読み取り専用にした pool）だけから読む。ctx のトランザクションを見ない。「ctx にトランザクションがあれば乗り、無ければ pool で読む」という切り替えを書かない。command は読み取りの口を呼ばないので、Query の実装がトランザクションの中で呼ばれる経路は無い。切り替えを書くと、トランザクションの張り忘れが黙って通る。

sqlc の `Queries` は、書き込みを型で拒む executor で組み立てる。`Exec` を呼ぶと「分類不能」を土台にしたエラーを返し、書き込みの形をした読み取りは PostgreSQL が読み取り専用の接続で拒む。

```go
// ReadExecutor は、読み取り専用の接続を sqlc の DBTX の形にし、Exec だけを拒む。
type ReadExecutor struct{ reader Reader }

func (r ReadExecutor) Exec(context.Context, string, ...any) (pgconn.CommandTag, error) {
	return pgconn.CommandTag{}, ErrWriteInReadOnly
}
```

Query の実装は、トランザクションを張らない。集約を復元せず、操作せず、書き込まない。

# 契約は usecase の側が持つ

読み取りのポートと読み取りモデルは、`usecase/query` が所有する（apply-go-package-layout が決める）。Query の実装はそれを満たし、読み取りモデルを返す。集約やエンティティを返さない。読み取りモデルも、業務の概念を値オブジェクトで持つ（write-go-code）。

# SQL と業務の計算

関係の射影、結合、並べ替え、件数、集計は SQL で行う。SQL は、物理設計の読み取りの台帳（Read-002 のような）に載っているものに限る。台帳に無い読み取りが要ると分かったら、足さずに物理設計の資料へ返す。背景処理の走査、監視の集計、書き込みの中の判定条件も、台帳に載る。

SQL で書けない業務の計算（延滞の日数を返却期限と時点から数える）は、ドメインの値オブジェクトか純関数を借りて、読み取りモデルを組み立てる時点で呼ぶ。集約は借りない。

# 壊れた一件を閉じ込める

互いに独立した複数件を返す読み取りでは、保存値を値オブジェクトへ戻せない一件だけを除き、残りを返す。一覧全体を失敗させない。除いた一件は、除いた場所で ERROR で記録する。そのエラーは境界へ返らないからである（write-logs の「飲み込むなら記録する」）。Query の実装は、そのために logger を注入される。

```go
for _, row := range rows {
	item, err := loanRowToSummary(row)
	if err != nil {
		// row は DB の生成型の行である。保存値が壊れているので、保存された値のまま記録する。
		q.logger.LogAttrs(ctx, slog.LevelError, "保存値の壊れた貸出を一覧から除いた",
			slog.String("loan_id", row.LoanID.String()), slog.Any("err", err))
		continue
	}
	items = append(items, item)
}
```

壊れた値を正常な値へ丸めて返さない。クエリそのものの失敗と、一覧の前提を復元できない失敗は、一件に閉じないので、全体を失敗させる。

ページを進める目印（カーソル）は、返せた件数ではなく、走査した候補の境界で決める。除いた一件を、次のページで読み直さないためである。

保存値を値オブジェクトへ戻せないことを、除かずに返すときは、データの破損として「回復不能」へ付け替える（handle-errors の付け替え）。

作業待ちの行（Outbox の要求）を読む口は、Query の実装ではなく、手順のリポジトリ相当の口である。作業待ちの行は黙って除かない（implement-repository）。
