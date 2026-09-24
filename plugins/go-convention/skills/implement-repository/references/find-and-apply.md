# Find と Apply

# ctx のトランザクションに乗る

リポジトリは、トランザクションを張らない。usecase が物理設計の指定でトランザクションを張り、ctx に載せて呼ぶ。リポジトリは ctx からトランザクションを取り出し、無ければ「分類不能」を土台にしたエラー（呼び方の間違い）を返す。pool で続けない。トランザクションの張り忘れを黙って通さないためである。

sqlc の `Queries` は、ctx のトランザクションから組み立てる。

```go
func (r *LoanRepository) queries(ctx context.Context) (*sqlcgen.Queries, error) {
	executor, err := rdb.ExecutorFromContext(ctx)
	if err != nil {
		return nil, err
	}
	return sqlcgen.New(executor), nil
}
```

# Find は集約を一つ返し、判断しない

`Find<返す型>` は、コマンドを直ちに呼べる完全な集約を一つ返す。値オブジェクト、件数、存在の判定、集約の一部を、usecase が集約を組み立てるための途中の結果として返さない。

**保存された状態を返す Find**（`FindLoan`）は、派生のテーブル（`loan_current_states`）の行から状態を選び、`Restore<状態名>` で組み立てて和型で返す。行が無ければ「存在しない」を土台にしたエラーを返す。状態の値が知らない値なら、丸めずに、保存値の破損として付け替える。

**初期状態の型を返す Find**（`FindPendingLoan`）は、コマンドの判断に要る集約の外の事実（利用者の貸出状況）を読んで値オブジェクトにし、初期状態の型へ持たせて返す。読むだけで、判断しない。上限に達しているかを見て拒んだり、読み方を変えたりしない。拒むのは、初期状態の型のコマンドである。読む SQL は、物理設計の読み取りの台帳（Read-001 のような）に載っているものに限る。

Find の中で複数を読むなら、同じトランザクションで、必要な順に読む。ロックを取る読み取りは、物理設計が指定したときだけ書く。

# Apply はイベントを書き、error だけを返す

`Apply<イベント名>` は、イベントを基底イベントと詳細イベントへ追加し、派生のテーブルを更新する（[テーブルの型の写し方](tables.md)）。生成のイベントなら、リソースの行も追加する。発生元のイベントが後続の要求を伴うなら（延滞になったら通知を頼む）、同じトランザクションで要求の行も追加する。

戻り値は error だけにする。保存したイベントや、イベントから既に得られる値を、リポジトリ独自の構造体へ詰め直して返さない。usecase の出力は、コマンドの結果から作る。

リポジトリは、業務の判断をしない。閾値や経路の選び方（どちらのテーブルへ書くか、を値で決めること）がデータモデルの資料にあっても、リポジトリに書かない。判断に要る値を Find で集約へ渡し、コマンドが決めてイベントに載せる形を、implement-domain-model と資料へ返す。

# 行とドメインの往復

行からドメインへの変換は、値オブジェクトの `New*` を通し、保存された状態の型を `Restore<状態名>` で組み立てる。`New*` が保存値を拒んだら、それは入力の誤りではなく**データの破損**である。「回復不能」を土台にしたリポジトリのエラーへ付け替え、元のエラーは文言だけを残す（handle-errors の付け替え）。

```go
user, err := vo.NewUserNo(row.UserNumber)
if err != nil {
	return nil, fmt.Errorf("%w: 貸出 %s の利用者番号: %v", ErrStoredLoanCorrupted, row.LoanID, err)
}
```

ドメインから行への変換は、イベントの取り出しの関数で値を取り、DB の生成型へ写す。プリミティブへ戻すのは、この変換の内側だけである。取りうる値が有限な列（`event_type`、`status`）は、値を所有する package の名前付きの定数を使い、同じ文字列を実装とテストで繰り返さない。

変換の関数は `<元>To<先>` と名付ける（`loanStateRowToLoan`、`lentToInsertParams`）。

# sqlc

SQL は sqlc の query のファイルにだけ書き、生成した `Queries` を直接呼ぶ。`sql_package` は `pgx/v5`、生成先は `sqlcgen` である。NOT NULL の `timestamptz` は `time.Time` に写す。生成物はコミットし、手で直さない。query の名前は、何をするかを言う（`InsertLoanBaseEvent`、`GetLoanCurrentState`、`CountActiveLoansByUser`）。

本番の SQL は、物理設計の読み取りの台帳と、Apply の書き込みに対応するものだけにする。台帳に無い読み取りが要ると分かったら、足さずに物理設計の資料へ返す。

テストが行を確かめるための SQL は、本番の query のファイルに足さない。置き場は test-repository が決める。
