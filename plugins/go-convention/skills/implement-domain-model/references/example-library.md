# 例：図書館の貸出

図書館の貸出のドメインモデル（集約「貸出」、状態は貸出中・延滞・返却済み）を写した、ドメインの package の全体である。書き始める前に一度読み、この形を写す。

名前と引数は、W1 の生成例（ドメインモデルと業務知識）に合わせている。業務の時刻の引数は、時点で受ける（「本を借りる」は貸出の時点、「延滞にする」は確かめた時点）。延滞と返却済みの貸出が「延滞にする」を受けたときの拒む理由は、資料で提案の段階にあるので、その二つのメソッドは書いていない。貸出番号も提案の段階にあり、ここでは仮置きとして書いている。

`errors` は、エラーの分類を持つプロジェクトの package（handle-errors が定める）である。`vo` は、文脈共有の値オブジェクトの置き場（apply-go-package-layout が決める）である。

# errors.go

```go
package domain

import "example.com/library/internal/crosscutting/errors"

// 業務知識の「拒むときの理由」に一つずつ対応する。
var (
	ErrUserHasOverdue   = errors.Define(errors.ErrPrecondition, "延滞の貸出がある利用者が本を借りる")
	ErrLoanLimitReached = errors.Define(errors.ErrPrecondition, "貸出上限に達している利用者が本を借りる")
	ErrAlreadyReturned  = errors.Define(errors.ErrPrecondition, "返却済みの本を返す")
	ErrNotPastDue       = errors.Define(errors.ErrPrecondition, "返却期限を過ぎていない貸出を延滞にする")
)

// 値の構造として必ず拒む値。
var (
	ErrLentCountNegative = errors.Define(errors.ErrInvalidInput, "借りている冊数が負である")
	ErrLoanIDMalformed   = errors.Define(errors.ErrInvalidInput, "貸出番号の形式が正しくない")
)
```

# 値オブジェクト

```go
package domain

// loanPeriodDays は、返却期限を決める貸出の期間である。業務知識の「返却期限は貸出日の14日後」。
const loanPeriodDays = 14

// loanLimit は、一人が同時に借りられる冊数の上限である。
const loanLimit = 5

// LentAt は、本が貸し出された時点である。返却期限の起点になる。
type LentAt struct{ at time.Time }

func NewLentAt(at time.Time) LentAt {
	return LentAt{at: at.UTC()}
}

func (l LentAt) Value() time.Time { return l.at }

// CheckedAt は、延滞かどうかを確かめた時点である。
type CheckedAt struct{ at time.Time }

func NewCheckedAt(at time.Time) CheckedAt {
	return CheckedAt{at: at.UTC()}
}

// Due は、返却期限の日である。この日の翌日以降に確かめると延滞になる。
type Due struct{ day LibraryDay }

func DueFrom(lentAt LentAt) Due {
	return Due{day: LibraryDayOf(lentAt.at).AddDays(loanPeriodDays)}
}

func RestoreDue(day LibraryDay) Due { return Due{day: day} }

func (d Due) Day() LibraryDay { return d.day }

// PassedAt は、確かめた時点が返却期限の翌日以降かを返す。返却期限の当日は、まだ過ぎていない。
func (d Due) PassedAt(checked CheckedAt) bool {
	return LibraryDayOf(checked.at).After(d.day)
}

// Standing は、本を借りる瞬間の利用者の貸出状況である。借りている冊数と、延滞の貸出の有無を持つ。
// 本を借りるコマンドの判断にだけ使い、貸出はこれを持ち続けない。
type Standing struct {
	lent       LentCount
	hasOverdue bool
}

func NewStanding(lent LentCount, hasOverdue bool) Standing {
	return Standing{lent: lent, hasOverdue: hasOverdue}
}

// LentCount は、利用者が借りている（貸出中と延滞の）冊数である。
type LentCount struct{ n int }

func NewLentCount(n int) (LentCount, error) {
	if n < 0 {
		return LentCount{}, ErrLentCountNegative
	}
	return LentCount{n: n}, nil
}
```

`LibraryDay`（図書館の暦の日）は、時点を図書館のタイムゾーンの日へ変える値オブジェクトで、ここでは省く。

# 集約

```go
package domain

// PendingLoan は、まだ保存されていない貸出である。版を持たない。
// 本を借りるコマンドの受け手で、利用者、本、その瞬間の貸出状況を持つ。
type PendingLoan struct {
	user     vo.UserNo
	book     vo.BookNo
	standing Standing
}

func NewPendingLoan(user vo.UserNo, book vo.BookNo, standing Standing) PendingLoan {
	return PendingLoan{user: user, book: book, standing: standing}
}

// Borrow は「本を借りる」。延滞を先に見る（資料の未決の仮置き）。
func (p PendingLoan) Borrow(id LoanID, lentAt LentAt) (BorrowResult, error) {
	if p.standing.hasOverdue {
		return BorrowResult{}, ErrUserHasOverdue
	}
	if p.standing.lent.n >= loanLimit {
		return BorrowResult{}, ErrLoanLimitReached
	}
	next := OnLoan{loanCore: loanCore{id: id, user: p.user, book: p.book, lentAt: lentAt, due: DueFrom(lentAt), version: FirstVersion}}
	return BorrowResult{Next: next, Event: Lent{loan: next.loanCore}}, nil
}

// Loan は、保存された貸出である。どの状態も同じコマンドを持ち、受けるか拒むかを状態ごとに決める。
//
//sumtype:decl
type Loan interface {
	Return() (ReturnResult, error)
	loan()
}

// loanCore は、どの状態でも変わらない値と、版である。
type loanCore struct {
	id      LoanID
	user    vo.UserNo
	book    vo.BookNo
	lentAt  LentAt
	due     Due
	version Version
}

// OnLoan は、貸出中の貸出である。
type OnLoan struct{ loanCore }

// OverdueLoan は、延滞の貸出である。
type OverdueLoan struct{ loanCore }

// ReturnedLoan は、返却済みの貸出である。終端で、どのコマンドも受け付けない。
type ReturnedLoan struct{ loanCore }

func RestoreOnLoan(id LoanID, user vo.UserNo, book vo.BookNo, lentAt LentAt, due Due, v Version) OnLoan {
	return OnLoan{loanCore{id: id, user: user, book: book, lentAt: lentAt, due: due, version: v}}
}

// RestoreOverdueLoan と RestoreReturnedLoan も同じ形で置く。

func (l OnLoan) Return() (ReturnResult, error) {
	return l.returnLoan(), nil
}

func (l OverdueLoan) Return() (ReturnResult, error) {
	return l.returnLoan(), nil
}

func (ReturnedLoan) Return() (ReturnResult, error) {
	return ReturnResult{}, ErrAlreadyReturned
}

// MarkOverdue は「延滞にする」。延滞と返却済みが受けたときの拒む理由は資料で提案の段階にあり、
// 確定するまで和型の Loan には置かない。
func (l OnLoan) MarkOverdue(checked CheckedAt) (MarkOverdueResult, error) {
	if !l.due.PassedAt(checked) {
		return MarkOverdueResult{}, ErrNotPastDue
	}
	next := OverdueLoan{l.loanCore.next()}
	return MarkOverdueResult{Next: next, Event: Overdue{loan: next.loanCore, checkedAt: checked}}, nil
}

func (l OnLoan) ID() LoanID        { return l.id }
func (l OnLoan) Due() Due          { return l.due }
func (l OnLoan) Version() Version  { return l.version }

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

`Return` を持つ状態は二つ（貸出中と延滞）で、同じ振る舞いを非公開の `returnLoan` に一つだけ書く。返却済みは、資料の拒む理由をそのまま返す。

# 結果とイベント

```go
package domain

type BorrowResult struct {
	Next  OnLoan
	Event Lent
}

type ReturnResult struct {
	Next  ReturnedLoan
	Event Returned
}

type MarkOverdueResult struct {
	Next  OverdueLoan
	Event Overdue
}

// Lent は「本が貸し出された」。貸出の時点を持ち、それが出来事の時点になる。
type Lent struct{ loan loanCore }

// Returned は「本が返却された」。業務の時刻を持たない。出来事の時点はリポジトリが記録のときに決める。
type Returned struct{ loan loanCore }

// Overdue は「貸出が延滞になった」。確かめた時点を持ち、それが出来事の時点になる。
type Overdue struct {
	loan      loanCore
	checkedAt CheckedAt
}

func (e Lent) LoanID() LoanID    { return e.loan.id }
func (e Lent) Version() Version  { return e.loan.version }
func (e Lent) LentAt() LentAt    { return e.loan.lentAt }
// 残りの取り出しの関数は、リポジトリの Apply が実際に読むものだけを置く。
```

イベントが持つ値の列は、データモデルの資料のイベント表の列から決める。

# 永続化ポート

```go
package domain

// LoanRepository は、貸出の永続化ポートである。
type LoanRepository interface {
	FindLoan(ctx context.Context, id LoanID) (Loan, error)
	FindPendingLoan(ctx context.Context, user vo.UserNo, book vo.BookNo) (PendingLoan, error)
	ApplyLent(ctx context.Context, evt Lent) error
	ApplyReturned(ctx context.Context, evt Returned) error
	ApplyOverdue(ctx context.Context, evt Overdue) error
}
```

`FindPendingLoan` は、利用者の貸出状況を読んで `Standing` にし、初期状態の型へ持たせて返すだけで、上限に達しているかを判断しない。判断は `Borrow` が行う。

延滞にする usecase は、延滞と返却済みの拒む理由が資料で確定し、`MarkOverdue` を和型の `Loan` に置けるまで書かない。和型に置けないまま書くと、usecase が状態の型を調べることになるからである。確定したら、`MarkOverdue` を和型に足し、延滞と返却済みにも資料の拒む理由を返すメソッドを置く。
