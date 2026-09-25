# 例：図書館の貸出の永続化

図書館の貸出のコマンドデータモデル、クエリデータモデル、物理設計の見本の資料を写した、`LoanRepository` と Query の実装の要の部分と、そのテストの形である。写すのは形で、テーブル、制約、読み取りの番号は対象の資料から取る。

## 翻訳の対応と Find

```go
// ErrStoredLoanCorrupted は、保存された貸出を値オブジェクトへ戻せないことを表す。運用者がデータを直すまで解決しない。
var ErrStoredLoanCorrupted = errors.Define(errors.ErrInternal, "保存された貸出を復元できない")

// ErrLoanVersionConflict は、同じ貸出の同じ版が先に記録されたことを表す。
var ErrLoanVersionConflict = errors.Define(errors.ErrConflict, "貸出が先に更新された")

// loanConstraints は、物理設計の一意制約の名前から具体エラーへの対応である。
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

// FindPendingLoan は、利用者の貸出状況を読み、これから借りる貸出を返す。借りられるかは判断しない。
func (r *LoanRepository) FindPendingLoan(ctx context.Context, user vo.UserNo, book vo.BookNo) (domain.PendingLoan, error) {
	q, err := r.queries(ctx)
	if err != nil {
		return domain.PendingLoan{}, err
	}
	// 物理設計の Read-001。
	row, err := q.GetUserLoanStanding(ctx, user.Value())
	if err != nil {
		return domain.PendingLoan{}, rdb.Translate(ctx, err, nil)
	}
	lent, err := domain.NewLentCount(int(row.ActiveCount))
	if err != nil {
		return domain.PendingLoan{}, fmt.Errorf("%w: 利用者 %s の借りている冊数: %v", ErrStoredLoanCorrupted, user.Value(), err)
	}
	overdue := domain.NoOverdue
	if row.HasOverdue {
		overdue = domain.HasOverdue
	}
	return domain.NewPendingLoan(user, book, domain.NewStanding(lent, overdue)), nil
}
```

同じ本を二人が同時に借りると、後の一方の `InsertLoan` が部分一意 index `loans_book_active_key` の違反になり、翻訳で「貸出中の本を借りる」になる。

## Apply

```go
// ApplyReturned は、返却の出来事を記録し、貸出の状態を返却済みにする。
// 返却は業務の時刻を持たないので、出来事の時点を時計から一度だけ取る。
func (r *LoanRepository) ApplyReturned(ctx context.Context, evt domain.Returned) error {
	q, err := r.queries(ctx)
	if err != nil {
		return err
	}
	occurredAt := r.clock.Now()
	eventID := rdb.UUIDColumn(r.ids.NewID())
	if err := q.InsertLoanBaseEvent(ctx, returnedToBaseEventParams(eventID, evt, occurredAt)); err != nil {
		return rdb.Translate(ctx, err, loanConstraints)
	}
	if err := q.InsertLoanReturnedEvent(ctx, eventID); err != nil {
		return rdb.Translate(ctx, err, loanConstraints)
	}
	// 読んだ版（イベントの版の一つ前）を条件に、状態と版を進める。0件なら先に別の操作が進めた。
	updated, err := q.UpdateLoanState(ctx, returnedToUpdateLoanStateParams(evt))
	if err != nil {
		return rdb.Translate(ctx, err, loanConstraints)
	}
	if updated == 0 {
		return ErrLoanVersionConflict
	}
	return nil
}
```

`ApplyLent` は、貸出の時点（イベントが持つ業務の時刻）を `occurred_at` に書き、時計を読まない。`ApplyOverdue` は、延滞の出来事と同じトランザクションで延滞の通知の要求を一行追加し、要求の時点を延滞の出来事の時点と同じ値にする。

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

## テストのループ本体

```go
for _, tt := range tests { // 同じ実 DB を全ケースが共有するため直列で走らせる。
	t.Run(tt.id+" "+tt.name, func(t *testing.T) {
		suite.Run(t) // 全テーブルを空にする
		ctx := t.Context()
		tt.before(ctx, t) // 持ち主の書き込み経路で Before を作る Builder
		unchanged := dbassert.CountRowsExcept(t, suite.Reader, "loans", "loan_base_events", "loan_returned_events")

		err := txm.Run(ctx, tx.Options{Isolation: tx.ReadCommitted}, func(ctx context.Context) error { // 本番と同じトランザクションの管理
			loan, err := repo.FindLoan(ctx, loanL001)
			require.NoError(t, err)
			res, err := loan.Return()
			require.NoError(t, err)
			return repo.ApplyReturned(ctx, res.Event)
		})

		require.ErrorIs(t, err, tt.wantErr)
		assert.Equal(t, tt.wantLoans, testq.AllLoans(ctx, t, suite.Reader))
		assert.Equal(t, tt.wantBaseEvents, testq.AllLoanBaseEvents(ctx, t, suite.Reader))
		dbassert.RequireRowCountsUnchanged(t, suite.Reader, unchanged)
	})
}
```

`testq` は、全行を主キー順に読むテスト専用の SQL から生成した package で、本番の生成の package とは別である。同じ本を二人が同時に借りる BDD は、二つのトランザクションでそれぞれ `FindPendingLoan` まで進め、一つ目の `ApplyLent` を確定させた後に二つ目の `ApplyLent` を呼び、`domain.ErrBookOnLoan` と、貸出の行が一行だけであることを確かめる。
