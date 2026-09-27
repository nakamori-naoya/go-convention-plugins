# 例：図書館の貸出の永続化

図書館の貸出のコマンドデータモデル、クエリデータモデル、物理設計の見本の資料を写した、`LoanRepository` と Query の実装の要の部分と、そのテストの形である。写すのは形で、テーブル、制約、読み取りの番号は対象の資料から取る。

## 翻訳の対応と Find

```go
// ErrStoredLoanCorrupted は、保存された貸出を値オブジェクトへ戻せないことを表す。運用者がデータを直すまで解決しない。
var ErrStoredLoanCorrupted = errors.Define(errors.ErrInternal, "保存された貸出を復元できない")

// ErrLoanVersionConflict は、同じ貸出の同じ版が先に記録されたことを表す。
var ErrLoanVersionConflict = errors.Define(errors.ErrConflict, "貸出が先に更新された")

// loanConstraints は、物理設計の制約の名前から、物理設計が決めた業務の結果の具体エラーへの対応である。
var loanConstraints = rdb.Constraints{
	"loans_book_active_key":             domain.ErrBookOnLoan,
	"loan_base_events_loan_version_key": ErrLoanVersionConflict,
}

func (r *LoanRepository) queries(ctx context.Context) (*sqlcgen.Queries, error) {
	executor, err := rdb.ExecutorFromContext(ctx)
	if err != nil {
		return nil, err
	}
	return sqlcgen.New(executor), nil
}

// FindBorrower は、利用者の貸出状況を読み、本を借りようとしている利用者を返す。借りられるかは判断しない。
func (r *LoanRepository) FindBorrower(ctx context.Context, user vo.UserNo, book vo.BookNo) (domain.Borrower, error) {
	q, err := r.queries(ctx)
	if err != nil {
		return domain.Borrower{}, err
	}
	// 物理設計の Read-001。
	row, err := q.GetUserLoanStanding(ctx, user.Value())
	if err != nil {
		return domain.Borrower{}, rdb.Translate(ctx, err, nil)
	}
	lent, err := domain.NewLentCount(int(row.ActiveCount))
	if err != nil {
		return domain.Borrower{}, fmt.Errorf("%w: 利用者 %s の借りている冊数: %s", ErrStoredLoanCorrupted, user.Value(), err.Error())
	}
	overdue := domain.NoOverdue
	if row.HasOverdue {
		overdue = domain.HasOverdue
	}
	return domain.NewBorrower(user, book, domain.NewStanding(lent, overdue)), nil
}
```

同じ本を二人が同時に借りると、後の一方の `InsertLoan` が部分一意 index `loans_book_active_key` の違反になり、翻訳で「貸出中の本を借りる」になる。

## marshaller と Apply

```go
package marshaller

// eventTypeReturned は、基底イベントの種類の列に書く返却の値である。
const eventTypeReturned = "returned"

// Stamps は、一回の保存で共有する出来事の時点と識別子である。
type Stamps struct {
	OccurredAt time.Time
	EventID    pgtype.UUID
}

func ReturnedToInsertLoanBaseEventParams(evt domain.Returned, st Stamps) sqlcgen.InsertLoanBaseEventParams {
	return sqlcgen.InsertLoanBaseEventParams{
		EventID:    st.EventID,
		LoanID:     rdb.UUIDColumn(evt.LoanID().Value()),
		EventType:  eventTypeReturned,
		Version:    evt.Version().Value(),
		OccurredAt: st.OccurredAt,
	}
}

// ReturnedToUpdateLoanStateParams は、読んだ版（イベントの版の一つ前）を条件に、状態と版を進める引数を作る。
func ReturnedToUpdateLoanStateParams(evt domain.Returned) sqlcgen.UpdateLoanStateParams {
	return sqlcgen.UpdateLoanStateParams{
		LoanID:         rdb.UUIDColumn(evt.LoanID().Value()),
		Status:         domain.StatusReturned.Value(),
		CurrentVersion: evt.Version().Value(),
		ReadVersion:    evt.Version().Value() - 1,
	}
}
```

```go
// ApplyReturned は、返却の出来事を記録し、貸出の状態を返却済みにする。
// 返却は時刻で何も判断しないので、出来事の時点を時計から一度だけ取る。
func (r *LoanRepository) ApplyReturned(ctx context.Context, evt domain.Returned) error {
	q, err := r.queries(ctx)
	if err != nil {
		return err
	}
	st := marshaller.Stamps{OccurredAt: r.clock.Now(), EventID: rdb.UUIDColumn(r.ids.NewID())}
	if err := q.InsertLoanBaseEvent(ctx, marshaller.ReturnedToInsertLoanBaseEventParams(evt, st)); err != nil {
		return rdb.Translate(ctx, err, loanConstraints)
	}
	if err := q.InsertLoanReturnedEvent(ctx, st.EventID); err != nil {
		return rdb.Translate(ctx, err, loanConstraints)
	}
	updated, err := q.UpdateLoanState(ctx, marshaller.ReturnedToUpdateLoanStateParams(evt))
	if err != nil {
		return rdb.Translate(ctx, err, loanConstraints)
	}
	if updated == 0 { // 先に別の操作が版を進めた
		return ErrLoanVersionConflict
	}
	return nil
}
```

`ApplyLent` は、返却期限を決めるのに使った貸出の時点（イベントが持つ）を `Stamps` の `OccurredAt` にし、時計を読まない。`ApplyOverdue` は、延滞の出来事と同じ `Stamps` から延滞の通知の要求の引数も作り、要求の時点を延滞の出来事の時点と同じ値にする。

## Query の実装の壊れた一件

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

## テスト専用の読み取りと突き合わせ

```sql
-- db/query/lending_loan_test_support.sql。本番と別の生成の package（testsqlcgen）へ生成する。
-- name: ListLoansForTest :many
SELECT * FROM loans ORDER BY loan_id;

-- name: ListLoanBaseEventsForTest :many
SELECT * FROM loan_base_events ORDER BY event_id;

-- name: ListLoanReturnedEventsForTest :many
SELECT * FROM loan_returned_events ORDER BY event_id;
```

資料の After の表は、生成された行の型でケースに写す。資料の識別子は、表の前で一度だけ変換しておく。

```go
// 資料の L-001。固定の UUID の文字列を、表の前で値オブジェクトと行の型へ一度ずつ変換する。
loanID := domain.NewLoanIDFromUUID(uuid.MustParse(loanL001))
rowL001 := rdb.UUIDColumn(loanID.Value())
```

```go
wantLoans: []testsqlcgen.Loan{
	{LoanID: rowL001, UserNo: "U-001", BookNo: "B-001", Status: "returned", DueOn: dueOn, CurrentVersion: 2},
},
wantBaseEvents: []testsqlcgen.LoanBaseEvent{
	{EventID: rowLentEvent, LoanID: rowL001, EventType: "lent", Version: 1, OccurredAt: lentAt},
	{EventID: rowReturnedEvent, LoanID: rowL001, EventType: "returned", Version: 2, OccurredAt: returnedAt},
},
wantReturnedEvents: []pgtype.UUID{rowReturnedEvent}, // 列が一つのテーブルは、その列の型の一覧になる
```

```go
for _, tt := range tests { // 同じ実 DB を全ケースが共有するため直列で走らせる。
	t.Run(tt.id+" "+tt.name, func(t *testing.T) {
		suite.Run(t) // 全テーブルを空にする
		ctx := t.Context()
		tt.before(ctx, t) // 持ち主の書き込み経路で Before を作る Builder
		unchanged := dbassert.CountRowsExcept(t, suite.Reader, "loans", "loan_base_events", "loan_returned_events")

		err := txm.Run(ctx, tx.Options{Isolation: tx.ReadCommitted}, func(ctx context.Context) error { // 本番と同じトランザクションの管理
			loan, err := repo.FindLoan(ctx, loanID)
			require.NoError(t, err)
			res, err := loan.Return()
			require.NoError(t, err)
			return repo.ApplyReturned(ctx, res.Event)
		})

		require.ErrorIs(t, err, tt.wantErr)
		rows := testsqlcgen.New(suite.Reader)
		loans, err := rows.ListLoansForTest(ctx)
		require.NoError(t, err)
		baseEvents, err := rows.ListLoanBaseEventsForTest(ctx)
		require.NoError(t, err)
		returnedEvents, err := rows.ListLoanReturnedEventsForTest(ctx)
		require.NoError(t, err)
		assert.Equal(t, tt.wantLoans, loans)
		assert.Equal(t, tt.wantBaseEvents, baseEvents)
		assert.Equal(t, tt.wantReturnedEvents, returnedEvents)
		dbassert.RequireRowCountsUnchanged(t, suite.Reader, unchanged)
	})
}
```

`loanL001` はファイルスコープの `const`（`"0193a3c1-7a4e-7c2e-9f10-5b8d2e6a4f01"`）で、変換はテスト関数の中で一度だけ行うので、helper 関数も、同じ変換を繰り返す無名関数も要らない。`suite.Reader` は時刻の列を UTC で読むように組んであるので、期待の時刻も UTC で書けば行の型のまま比べられる。同じ本を二人が同時に借りる BDD は、二つのトランザクションでそれぞれ `FindBorrower` まで進め、一つ目の `ApplyLent` を確定させた後に二つ目の `ApplyLent` を呼び、`domain.ErrBookOnLoan` と、貸出の行が一行だけであることを確かめる。
