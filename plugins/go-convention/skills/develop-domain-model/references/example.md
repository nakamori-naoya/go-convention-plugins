# 例：図書館の貸出

図書館の貸出（集約「貸出」、状態は貸出中、延滞、返却済み）を写したドメインの package と、そのテストである。写すのは形である。値オブジェクトと状態ごとの型の分け方、和型のコマンドと `<コマンド名>Result`、具体エラーの置き方、テストの表の形がこれに当たる。名前、状態の数、コマンド、拒む理由は写さない。

見本の資料は、延滞と返却済みの貸出が「延滞にする」を受けたときの拒む理由を業務知識への提案に回しているので、`MarkOverdue` は和型に置かず、貸出中の型だけが持つ。貸出番号も提案に回っているが、保存した貸出を見分ける識別子なので仮置きして書いている。`errors` はエラーの分類の package、`vo` は文脈共有の値オブジェクトの package である。

## エラー、値オブジェクト、暦

```go
package domain

// 業務知識の拒む理由に一つずつ対応する。利用者に返す文言は、貸出の公開契約が決めたものである。
var (
	ErrUserHasOverdue   = errors.Define(errors.ErrPrecondition, "延滞している本を返すまで、新しい本は借りられません")
	ErrLoanLimitReached = errors.Define(errors.ErrPrecondition, "借りられるのは5冊までです")
	ErrBookOnLoan       = errors.Define(errors.ErrPrecondition, "この本は貸出中です")
	ErrAlreadyReturned  = errors.Define(errors.ErrPrecondition, "この本は返却済みです")
)

// 延滞にするのは図書館の巡回で、利用者には返らないので、業務知識の拒む理由の語をそのまま文言にする。
var ErrNotPastDue = errors.Define(errors.ErrPrecondition, "返却期限を過ぎていない貸出を延滞にする")

// 値の構造として必ず拒む値。
var ErrLentCountNegative = errors.Define(errors.ErrInvalidInput, "借りている冊数が負である")

const (
	loanPeriodDays = 14 // 業務知識の「返却期限は貸出日の14日後」
	loanLimit      = 5
)

// LoanID は、貸出を見分ける貸出番号である。
type LoanID struct{ id uuid.UUID }

// NewLoanIDFromUUID は、ID ジェネレーターが発行した UUID を貸出番号にする。ID の発行はしない。
func NewLoanIDFromUUID(id uuid.UUID) LoanID { return LoanID{id: id} }

// Version は、保存された貸出の版である。コマンドを受けるたびに一つ進む。
type Version struct{ n int64 }

var FirstVersion = Version{n: 1}

func (v Version) Next() Version { return Version{n: v.n + 1} }

// LibraryCalendar は、図書館のタイムゾーン（例: "Asia/Tokyo"）で時点を暦の日へ変える。知らない名前のタイムゾーンでは作れない（ErrTimeZoneUnknown）。
type LibraryCalendar struct{ loc *time.Location }

// LentAt は、貸出日時である。返却期限の起点になる。
type LentAt struct{ at time.Time }

func NewLentAt(at time.Time) LentAt { return LentAt{at: at.UTC()} }

// Due は、返却期限の日である。この日の翌日以降に判定すると延滞になる。
type Due struct{ day time.Time }

func DueFrom(lentAt LentAt, cal LibraryCalendar) Due {
	y, m, d := lentAt.at.In(cal.loc).Date()
	return Due{day: time.Date(y, m, d+loanPeriodDays, 0, 0, 0, 0, time.UTC)}
}

// Standing は、本を借りる瞬間の利用者の貸出状況である。本を借りるコマンドの判断にだけ使い、貸出はこれを持ち続けない。
type Standing struct {
	lent    LentCount
	overdue OverdueStatus
}

func NewStanding(lent LentCount, overdue OverdueStatus) Standing {
	return Standing{lent: lent, overdue: overdue}
}
```

`LentCount`（負を拒む `NewLentCount`）、封じた型 `OverdueStatus`（`HasOverdue`、`NoOverdue`）、判定日時の `CheckedAt`、返却期限の当日はまだ過ぎていないとする `Due.PassedAt` は同じ形なので省く。

## 集約

```go
// Borrower は、本を借りようとしている利用者（借り手）である。まだ貸出は無いので版を持たない。
type Borrower struct {
	user     vo.UserNo
	book     vo.BookNo
	standing Standing
}

func NewBorrower(user vo.UserNo, book vo.BookNo, standing Standing) Borrower {
	return Borrower{user: user, book: book, standing: standing}
}

// Borrow は「本を借りる」。延滞を先に見る（資料の未決の仮置き）。
func (b Borrower) Borrow(id LoanID, lentAt LentAt, cal LibraryCalendar) (BorrowResult, error) {
	if b.standing.overdue == HasOverdue {
		return BorrowResult{}, ErrUserHasOverdue
	}
	if b.standing.lent.n >= loanLimit {
		return BorrowResult{}, ErrLoanLimitReached
	}
	next := OnLoan{loanSlip{id: id, user: b.user, book: b.book, due: DueFrom(lentAt, cal), version: FirstVersion}}
	return BorrowResult{Next: next, Event: Lent{loan: next.loanSlip, lentAt: lentAt}}, nil
}

// Loan は、保存された貸出である。どの状態も同じコマンドを持ち、受けるか拒むかを状態ごとに決める。
//
//sumtype:decl
type Loan interface {
	Return() (ReturnResult, error)
	loan()
}

// loanSlip は、貸出票（どの利用者がどの本をいつまでに返すか）である。どの状態でも変わらない。貸出日時は持たない。後のコマンドが判断に使うのは返却期限だけだからである。
type loanSlip struct {
	id      LoanID
	user    vo.UserNo
	book    vo.BookNo
	due     Due
	version Version
}

type OnLoan struct{ loanSlip }
type OverdueLoan struct{ loanSlip }
type ReturnedLoan struct{ loanSlip } // 終端。どのコマンドも受けない

func RestoreOnLoan(id LoanID, user vo.UserNo, book vo.BookNo, due Due, v Version) OnLoan {
	return OnLoan{loanSlip{id: id, user: user, book: book, due: due, version: v}}
}

// RestoreOverdueLoan、RestoreReturnedLoan も同じ形である。

func (l OnLoan) Return() (ReturnResult, error)      { return l.returnLoan(), nil }
func (l OverdueLoan) Return() (ReturnResult, error) { return l.returnLoan(), nil }
func (ReturnedLoan) Return() (ReturnResult, error)  { return ReturnResult{}, ErrAlreadyReturned }

// MarkOverdue は「延滞にする」。返却期限を過ぎていない貸出は延滞にしない。
func (l OnLoan) MarkOverdue(checked CheckedAt, cal LibraryCalendar) (MarkOverdueResult, error) {
	if !l.due.PassedAt(checked, cal) {
		return MarkOverdueResult{}, ErrNotPastDue
	}
	next := OverdueLoan{l.loanSlip.next()}
	return MarkOverdueResult{Next: next, Event: Overdue{loan: next.loanSlip, checkedAt: checked}}, nil
}

func (OnLoan) loan()       {}
func (OverdueLoan) loan()  {}
func (ReturnedLoan) loan() {}

func (s loanSlip) returnLoan() ReturnResult {
	next := ReturnedLoan{s.next()}
	return ReturnResult{Next: next, Event: Returned{loan: next.loanSlip}}
}

func (s loanSlip) next() loanSlip {
	s.version = s.version.Next()
	return s
}
```

## 結果、イベント、永続化ポート

```go
type BorrowResult struct {
	Next  OnLoan
	Event Lent
}

type ReturnResult struct {
	Next  ReturnedLoan
	Event Returned
}

// Lent は「本を借りた」。返却期限を決めるのに使った貸出日時を持ち、それが出来事の時点になる。
type Lent struct {
	loan   loanSlip
	lentAt LentAt
}

func (e Lent) LoanID() LoanID   { return e.loan.id }
func (e Lent) Version() Version { return e.loan.version }
func (e Lent) LentAt() LentAt   { return e.lentAt }
func (e Lent) Due() Due         { return e.loan.due }

// Returned は「本を返した」。返すときは時刻で何も判断しないので、時刻を持たない。
type Returned struct{ loan loanSlip }

// MarkOverdueResult と、判定日時を持つイベント Overdue も同じ形である。

// LoanRepository は、貸出の永続化ポートである。
type LoanRepository interface {
	FindLoan(ctx context.Context, id LoanID) (Loan, error)
	FindBorrower(ctx context.Context, user vo.UserNo, book vo.BookNo) (Borrower, error)
	ApplyLent(ctx context.Context, evt Lent) error
	ApplyReturned(ctx context.Context, evt Returned) error
	ApplyOverdue(ctx context.Context, evt Overdue) error
}
```

## テスト

```go
package domain_test

// BDD の資料: docs/lending/業務知識.md

func TestBorrower_Borrow(t *testing.T) {
	t.Parallel()

	user := vobuilders.NewUserNoBuilder().Build(t)
	book := vobuilders.NewBookNoBuilder().Build(t)
	loanID := domainbuilders.NewLoanIDBuilder().Build(t)
	lentAt := domain.NewLentAt(time.Date(2026, 10, 1, 1, 0, 0, 0, time.UTC)) // 図書館の暦では10月1日 10:00
	cal, err := domain.NewLibraryCalendar("Asia/Tokyo")
	require.NoError(t, err)
	noneLent := domainbuilders.NewLentCountBuilder().WithValue(0).Build(t)

	type lent struct {
		loanID  domain.LoanID
		version domain.Version
		lentAt  domain.LentAt
	}

	tests := []struct {
		id          string
		name        string
		description string
		standing    domain.Standing // Given: 借りる瞬間の貸出状況
		wantNext    domain.OnLoan   // Then
		wantEvent   lent            // Then
		wantErr     error           // Then: nil なら受ける
	}{
		{
			id:   "BDD-001",
			name: "延滞の無い利用者が本を借りると貸出中の貸出が生まれる",
			description: `Given: 利用者 U-0001 は本を1冊も借りておらず、延滞の貸出も無い
When: 利用者 U-0001 が2026年10月1日 10:00に本 B-1001 を借りる
Then: 利用者 U-0001 と本 B-1001 の貸出が貸出中で生まれる
  And: 返却期限は2026年10月15日である`,
			standing:  domain.NewStanding(noneLent, domain.NoOverdue),
			wantNext:  domain.RestoreOnLoan(loanID, user, book, domain.DueFrom(lentAt, cal), domain.FirstVersion),
			wantEvent: lent{loanID: loanID, version: domain.FirstVersion, lentAt: lentAt},
		},
	}
	for _, tt := range tests {
		t.Run(tt.id+" "+tt.name, func(t *testing.T) {
			t.Parallel()

			got, err := domain.NewBorrower(user, book, tt.standing).Borrow(loanID, lentAt, cal)
			if tt.wantErr != nil {
				require.ErrorIs(t, err, tt.wantErr)
				assert.Zero(t, got)
				return
			}
			require.NoError(t, err)
			assert.Equal(t, tt.wantNext, got.Next)
			assert.Equal(t, tt.wantEvent, lent{loanID: got.Event.LoanID(), version: got.Event.Version(), lentAt: got.Event.LentAt()})
		})
	}
}
```

拒むケースは `standing` と `wantErr` だけを持つ行で、ループ本体の `require.ErrorIs` と `assert.Zero` を通る。受けない状態のテスト（`TestReturnedLoan_Return`）は、`RestoreReturnedLoan` で Given を組み、`wantErr` と結果のゼロ値だけを見る短い表になる。
