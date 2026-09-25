# 例：図書館の貸出

図書館の貸出（集約「貸出」、状態は貸出中、延滞、返却済み）を写したドメインの package と、そのテストである。写すのは形である。値オブジェクトと状態ごとの型の分け方、和型のコマンドと `<コマンド名>Result`、具体エラーの置き方、テストの表の形がこれに当たる。名前、状態の数、コマンド、拒む理由は写さない。

見本の資料は、延滞と返却済みの貸出が「延滞にする」を受けたときの拒む理由を業務知識への提案に回しているので、`MarkOverdue` は和型に置かず、貸出中の型だけが持つ。貸出番号も提案に回っているが、保存した貸出を見分ける識別子なので仮置きして書いている。`errors` はエラーの分類の package、`vo` は文脈共有の値オブジェクトの package である。

## エラー、値オブジェクト、暦

```go
package domain

// 業務知識の「拒むときの理由」に一つずつ対応する。
var (
	ErrUserHasOverdue   = errors.Define(errors.ErrPrecondition, "延滞の貸出がある利用者が本を借りる")
	ErrLoanLimitReached = errors.Define(errors.ErrPrecondition, "貸出上限に達している利用者が本を借りる")
	ErrBookOnLoan       = errors.Define(errors.ErrPrecondition, "貸出中の本を借りる") // DB の制約が守り、リポジトリが翻訳する
	ErrAlreadyReturned  = errors.Define(errors.ErrPrecondition, "返却済みの本を返す")
	ErrNotPastDue       = errors.Define(errors.ErrPrecondition, "返却期限を過ぎていない貸出を延滞にする")
)

// 値の構造として必ず拒む値。
var ErrLentCountNegative = errors.Define(errors.ErrInvalidInput, "借りている冊数が負である")

const (
	loanPeriodDays = 14 // 業務知識の「返却期限は貸出日の14日後」
	loanLimit      = 5
)

// LoanID は、貸出を見分ける貸出番号である。
type LoanID struct{ id uuid.UUID }

// NewLoanIDFromUUID は、採番器が返した UUID を貸出番号にする。採番はしない。
func NewLoanIDFromUUID(id uuid.UUID) LoanID { return LoanID{id: id} }

// Version は、保存された貸出の版である。コマンドを受けるたびに一つ進む。
type Version struct{ n int64 }

var FirstVersion = Version{n: 1}

func (v Version) Next() Version { return Version{n: v.n + 1} }

// LibraryCalendar は、図書館のタイムゾーンで時点を暦の日へ変える。組み立ての場所が設定（例: "Asia/Tokyo"）から
// NewLibraryCalendar で一度だけ作り、知らない名前は ErrTimeZoneUnknown で拒む。
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
// PendingLoan は、まだ保存されていない貸出である。版を持たない。
type PendingLoan struct {
	user     vo.UserNo
	book     vo.BookNo
	standing Standing
}

func NewPendingLoan(user vo.UserNo, book vo.BookNo, standing Standing) PendingLoan {
	return PendingLoan{user: user, book: book, standing: standing}
}

// Borrow は「本を借りる」。延滞を先に見る（資料の未決の仮置き）。
func (p PendingLoan) Borrow(id LoanID, lentAt LentAt, cal LibraryCalendar) (BorrowResult, error) {
	if p.standing.overdue == HasOverdue {
		return BorrowResult{}, ErrUserHasOverdue
	}
	if p.standing.lent.n >= loanLimit {
		return BorrowResult{}, ErrLoanLimitReached
	}
	next := OnLoan{loanCore{id: id, user: p.user, book: p.book, lentAt: lentAt, due: DueFrom(lentAt, cal), version: FirstVersion}}
	return BorrowResult{Next: next, Event: Lent{loan: next.loanCore}}, nil
}

// Loan は、保存された貸出である。どの状態も同じコマンドを持ち、受けるか拒むかを状態ごとに決める。
//
//sumtype:decl
type Loan interface {
	Return() (ReturnResult, error)
	loan()
}

type loanCore struct {
	id      LoanID
	user    vo.UserNo
	book    vo.BookNo
	lentAt  LentAt
	due     Due
	version Version
}

type OnLoan struct{ loanCore }
type OverdueLoan struct{ loanCore }
type ReturnedLoan struct{ loanCore } // 終端。どのコマンドも受けない

func RestoreOnLoan(id LoanID, user vo.UserNo, book vo.BookNo, lentAt LentAt, due Due, v Version) OnLoan {
	return OnLoan{loanCore{id: id, user: user, book: book, lentAt: lentAt, due: due, version: v}}
}

// RestoreOverdueLoan、RestoreReturnedLoan も同じ形である。

func (l OnLoan) Return() (ReturnResult, error)      { return l.returnLoan(), nil }
func (l OverdueLoan) Return() (ReturnResult, error) { return l.returnLoan(), nil }
func (ReturnedLoan) Return() (ReturnResult, error)  { return ReturnResult{}, ErrAlreadyReturned }

// MarkOverdue は「延滞にする」。延滞と返却済みが受けたときの拒む理由を資料が持たないので、和型に置かない。
func (l OnLoan) MarkOverdue(checked CheckedAt, cal LibraryCalendar) (MarkOverdueResult, error) {
	if !l.due.PassedAt(checked, cal) {
		return MarkOverdueResult{}, ErrNotPastDue
	}
	next := OverdueLoan{l.loanCore.next()}
	return MarkOverdueResult{Next: next, Event: Overdue{loan: next.loanCore, checkedAt: checked}}, nil
}

func (OnLoan) loan()       {}
func (OverdueLoan) loan()  {}
func (ReturnedLoan) loan() {}

func (c loanCore) returnLoan() ReturnResult {
	next := ReturnedLoan{c.next()}
	return ReturnResult{Next: next, Event: Returned{loan: next.loanCore}}
}

func (c loanCore) next() loanCore {
	c.version = c.version.Next()
	return c
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

// Lent は「本が貸し出された」。貸出日時を持ち、それが出来事の時点になる。
type Lent struct{ loan loanCore }

func (e Lent) LoanID() LoanID   { return e.loan.id }
func (e Lent) Version() Version { return e.loan.version }
func (e Lent) LentAt() LentAt   { return e.loan.lentAt }
func (e Lent) Due() Due         { return e.loan.due } // 取り出しの関数は、読む呼び手がいるものだけ

// Returned は「本が返却された」。業務の時刻を持たない。出来事の時点はリポジトリが記録のときに決める。
type Returned struct{ loan loanCore }

// MarkOverdueResult と、判定日時を持つイベント Overdue も同じ形である。

// LoanRepository は、貸出の永続化ポートである。
type LoanRepository interface {
	FindLoan(ctx context.Context, id LoanID) (Loan, error)
	FindPendingLoan(ctx context.Context, user vo.UserNo, book vo.BookNo) (PendingLoan, error)
	ApplyLent(ctx context.Context, evt Lent) error
	ApplyReturned(ctx context.Context, evt Returned) error
	ApplyOverdue(ctx context.Context, evt Overdue) error
}
```

## テスト

```go
package domain_test

// BDD の資料: docs/lending/業務知識.md

func TestPendingLoan_Borrow(t *testing.T) {
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
			wantNext:  domain.RestoreOnLoan(loanID, user, book, lentAt, domain.DueFrom(lentAt, cal), domain.FirstVersion),
			wantEvent: lent{loanID: loanID, version: domain.FirstVersion, lentAt: lentAt},
		},
	}
	for _, tt := range tests {
		t.Run(tt.id+" "+tt.name, func(t *testing.T) {
			t.Parallel()

			got, err := domain.NewPendingLoan(user, book, tt.standing).Borrow(loanID, lentAt, cal)
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
