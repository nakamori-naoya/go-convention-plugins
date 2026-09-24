# 例：図書館の貸出のリポジトリ

W1 の生成例（論理データモデルと物理設計）の図書館の貸出を写した、`LoanRepository` の要の部分である。ドメインの形は implement-domain-model の例に合わせている。

# 翻訳の対応

```go
// ErrStoredLoanCorrupted は、保存された貸出を値オブジェクトへ戻せないことを表す。運用者がデータを直すまで解決しない。
var ErrStoredLoanCorrupted = errors.Define(errors.ErrInternal, "保存された貸出を復元できない")

// ErrLoanVersionConflict は、同じ貸出の同じ版が先に記録されたことを表す。
var ErrLoanVersionConflict = errors.Define(errors.ErrConflict, "貸出が先に更新された")

// loanConstraints は、物理設計の一意制約の名前から具体エラーへの対応である。
var loanConstraints = rdb.Constraints{
	"loans_book_active_key":             domain.ErrBookOnLoan,
	"loan_base_events_loan_version_key":   ErrLoanVersionConflict,
}
```

`domain.ErrBookOnLoan` は、業務知識の拒む理由「貸出中の本を借りる」の具体エラーである。事前に確かめる場面が無く、DB の部分一意 index だけが守るので、翻訳で返す。

# FindPendingLoan

```go
// FindPendingLoan は、利用者の貸出状況を読み、これから借りる貸出を返す。読むだけで、借りられるかは判断しない。
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
	return domain.NewPendingLoan(user, book, domain.NewStanding(lent, row.HasOverdue)), nil
}
```

usecase は、物理設計の指定（`SERIALIZABLE`、直列化の失敗だけを最大3回やり直す）でトランザクションを張ってから、これを呼ぶ。読み取りと書き込みが同じトランザクションに入るので、同じ利用者が同時に借りても上限を超えない。

# ApplyLent

```go
// ApplyLent は、貸出と、その最初の出来事を記録する。
// 出来事の時点は、貸出の時点（コマンドの引数）をそのまま使い、Clock を読まない。
func (r *LoanRepository) ApplyLent(ctx context.Context, evt domain.Lent) error {
	q, err := r.queries(ctx)
	if err != nil {
		return err
	}
	loanID := rdb.IDColumn(evt.LoanID())
	eventID := rdb.UUIDColumn(r.ids.NewID())
	// 貸出の行は、状態 lent と版1を持って生まれる。
	if err := q.InsertLoan(ctx, lentToInsertLoanParams(loanID, evt)); err != nil {
		return rdb.Translate(ctx, err, loanConstraints)
	}
	if err := q.InsertLoanBaseEvent(ctx, sqlcgen.InsertLoanBaseEventParams{
		EventID:    eventID,
		LoanID:     loanID,
		EventType:  string(eventTypeLent),
		Version:    evt.Version().Int64(),
		OccurredAt: evt.LentAt().Value(),
	}); err != nil {
		return rdb.Translate(ctx, err, loanConstraints)
	}
	if err := q.InsertLoanLentEvent(ctx, sqlcgen.InsertLoanLentEventParams{EventID: eventID, DueOn: dateColumn(evt.Due())}); err != nil {
		return rdb.Translate(ctx, err, loanConstraints)
	}
	return nil
}
```

同じ本を二人が同時に借りると、後の一方の `InsertLoan` が部分一意 index（`loans_book_active_key`）の違反になり、翻訳表で「貸出中の本を借りる」になる。

# ApplyReturned

```go
// ApplyReturned は、返却の出来事を記録し、貸出の状態を返却済みにする。
// 返却は業務の時刻を持たないので、出来事の時点を Clock から一度だけ取る。
func (r *LoanRepository) ApplyReturned(ctx context.Context, evt domain.Returned) error {
	q, err := r.queries(ctx)
	if err != nil {
		return err
	}
	occurredAt := r.clock.Now()
	// 基底イベントの版の一意制約の違反は、同時更新で競合した、になる。
	eventID, err := r.insertBaseEvent(ctx, q, evt.LoanID(), eventTypeReturned, evt.Version(), occurredAt)
	if err != nil {
		return err
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

`ApplyOverdue` は、延滞の出来事を書くのと同じトランザクションで、延滞の通知の要求（`overdue_notice_requested_events`）を一行追加する。要求の時点は、延滞の出来事の時点と同じ値にする。
