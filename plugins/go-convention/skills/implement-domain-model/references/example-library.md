# 例：図書館の貸出

図書館の貸出のドメインモデル（集約「貸出」、状態は貸出中・延滞・返却済み）を写した、ドメインの package の全体である。書き始める前に一度読み、この形を写す。

名前と引数は、W1 の生成例（ドメインモデルと業務知識）に合わせている。業務の時刻の引数は、時点で受ける（「本を借りる」は貸出日時、「延滞にする」は判定日時）。延滞と返却済みの貸出が「延滞にする」を受けたときの拒む理由は、資料で提案の段階にあるので、その二つのメソッドは書いていない。貸出番号も資料では提案の段階にあるが、保存した貸出を見分ける識別子なので、[資料の読み方](reading-the-model.md) の例外に従って仮置きの語で書いている。

`errors` は、エラーの分類を持つプロジェクトの package（handle-errors が定める）である。`vo` は、文脈共有の値オブジェクトの置き場（apply-go-package-layout が決める）である。例は省かずに書いている。写すときも、省かれた型を自分で補わずに済むようにするためである。

# errors.go

```go
package domain

import "example.com/library/internal/crosscutting/errors"

// 業務知識の「拒むときの理由」に一つずつ対応する。
var (
	ErrUserHasOverdue   = errors.Define(errors.ErrPrecondition, "延滞の貸出がある利用者が本を借りる")
	ErrLoanLimitReached = errors.Define(errors.ErrPrecondition, "貸出上限に達している利用者が本を借りる")
	ErrBookOnLoan       = errors.Define(errors.ErrPrecondition, "貸出中の本を借りる")
	ErrAlreadyReturned  = errors.Define(errors.ErrPrecondition, "返却済みの本を返す")
	ErrNotPastDue       = errors.Define(errors.ErrPrecondition, "返却期限を過ぎていない貸出を延滞にする")
)

// 値の構造として必ず拒む値。
var (
	ErrLentCountNegative    = errors.Define(errors.ErrInvalidInput, "借りている冊数が負である")
	ErrLoanIDMalformed      = errors.Define(errors.ErrInvalidInput, "貸出番号の形式が正しくない")
	ErrVersionOutOfRange    = errors.Define(errors.ErrInvalidInput, "版が1より小さい")
	ErrTimeZoneUnknown      = errors.Define(errors.ErrInvalidInput, "図書館のタイムゾーンが分からない")
)
```

`ErrBookOnLoan` は、ドメインが事前に確かめる場面を持たない。同じ本の貸出中の貸出は一つだけという規則を DB の一意制約が守り、リポジトリがその違反をこのエラーへ翻訳する。

# 識別子と版

`uuid` は、Go 1.27 で標準ライブラリに入った package である（https://pkg.go.dev/uuid ）。`uuid.Parse` と `UUID.String` はそこに載っている。版が違うなら、書く前に pkg.go.dev で確かめる。

```go
package domain

import "uuid"

// LoanID は、貸出を見分ける貸出番号である。
type LoanID struct{ id uuid.UUID }

// NewLoanIDFromUUID は、採番器が返した UUID を貸出番号にする。採番はしない。
func NewLoanIDFromUUID(id uuid.UUID) LoanID { return LoanID{id: id} }

// NewLoanID は、外から受けた文字列（例: "0193a3c1-7a4e-7c2e-9f10-5b8d2e6a4f01"）が貸出番号の形式かを確かめる。
func NewLoanID(s string) (LoanID, error) {
	id, err := uuid.Parse(s)
	if err != nil {
		return LoanID{}, ErrLoanIDMalformed
	}
	return LoanID{id: id}, nil
}

// Value は、境界の外の形（DB の列、ログの属性）へ写すときに使う。
func (l LoanID) Value() string { return l.id.String() }

// Version は、貸出の版である。保存された状態だけが持ち、コマンドを受けるたびに一つ進む。
type Version struct{ n int64 }

// FirstVersion は、生成のコマンドを受けて初めて保存される貸出の版である。
var FirstVersion = Version{n: 1}

// RestoreVersion は、保存された版を戻す。1より小さい版は保存されない。
func RestoreVersion(n int64) (Version, error) {
	if n < 1 {
		return Version{}, ErrVersionOutOfRange
	}
	return Version{n: n}, nil
}

func (v Version) Next() Version { return Version{n: v.n + 1} }

func (v Version) Int64() int64 { return v.n }
```

# 時刻と暦

```go
package domain

import "time"

// LibraryCalendar は、図書館のタイムゾーンで時点を暦の日へ変える。
// タイムゾーンは設定値で、組み立て（main）が一度だけ作って usecase へ渡す。ドメインは既定のタイムゾーンを読まない。
type LibraryCalendar struct{ loc *time.Location }

// NewLibraryCalendar は、IANA のタイムゾーン名（例: "Asia/Tokyo"）から暦を作る。
// 名前は設定値から来るので、拒まれたら組み立て（main）がこのエラーを「回復不能」へ付け替えて起動を止める。
func NewLibraryCalendar(zone string) (LibraryCalendar, error) {
	loc, err := time.LoadLocation(zone)
	if err != nil || zone == "" {
		return LibraryCalendar{}, ErrTimeZoneUnknown
	}
	return LibraryCalendar{loc: loc}, nil
}

// DayOf は、時点を図書館の暦の日にする。
func (c LibraryCalendar) DayOf(at time.Time) LibraryDay {
	y, m, d := at.In(c.loc).Date()
	return LibraryDay{date: time.Date(y, m, d, 0, 0, 0, 0, time.UTC)}
}

// LibraryDay は、図書館の暦の日である。時刻とタイムゾーンを持たない。
type LibraryDay struct{ date time.Time }

// RestoreLibraryDay は、保存された日付を戻す。時刻の部分は捨てる。
func RestoreLibraryDay(date time.Time) LibraryDay {
	y, m, d := date.Date()
	return LibraryDay{date: time.Date(y, m, d, 0, 0, 0, 0, time.UTC)}
}

func (d LibraryDay) AddDays(n int) LibraryDay { return LibraryDay{date: d.date.AddDate(0, 0, n)} }

func (d LibraryDay) After(other LibraryDay) bool { return d.date.After(other.date) }

// Date は、その日の0時（UTC）を返す。日付の列へ写すときに使う。
func (d LibraryDay) Date() time.Time { return d.date }

// LentAt は、貸出日時である。返却期限の起点になる。
type LentAt struct{ at time.Time }

func NewLentAt(at time.Time) LentAt { return LentAt{at: at.UTC()} }

func (l LentAt) Value() time.Time { return l.at }

// CheckedAt は、延滞かどうかを判定した日時である。
type CheckedAt struct{ at time.Time }

func NewCheckedAt(at time.Time) CheckedAt { return CheckedAt{at: at.UTC()} }

func (c CheckedAt) Value() time.Time { return c.at }
```

# 返却期限と貸出状況

```go
package domain

// loanPeriodDays は、返却期限を決める貸出の期間である。業務知識の「返却期限は貸出日の14日後」。
const loanPeriodDays = 14

// loanLimit は、一人が同時に借りられる冊数の上限である。
const loanLimit = 5

// Due は、返却期限の日である。この日の翌日以降に判定すると延滞になる。
type Due struct{ day LibraryDay }

func DueFrom(lentAt LentAt, cal LibraryCalendar) Due {
	return Due{day: cal.DayOf(lentAt.at).AddDays(loanPeriodDays)}
}

func RestoreDue(day LibraryDay) Due { return Due{day: day} }

func (d Due) Day() LibraryDay { return d.day }

// PassedAt は、判定した日時が返却期限の翌日以降かを返す。返却期限の当日は、まだ過ぎていない。
func (d Due) PassedAt(checked CheckedAt, cal LibraryCalendar) bool {
	return cal.DayOf(checked.at).After(d.day)
}

// LentCount は、利用者が借りている（貸出中と延滞の）冊数である。
type LentCount struct{ n int }

func NewLentCount(n int) (LentCount, error) {
	if n < 0 {
		return LentCount{}, ErrLentCountNegative
	}
	return LentCount{n: n}, nil
}

// OverdueStatus は、利用者が延滞の貸出を持っているかである。取りうる値は二つで、封じた型にする。
type OverdueStatus struct{ has bool }

var (
	HasOverdue = OverdueStatus{has: true}
	NoOverdue  = OverdueStatus{has: false}
)

// Standing は、本を借りる瞬間の利用者の貸出状況である。借りている冊数と、延滞の貸出の有無を持つ。
// 本を借りるコマンドの判断にだけ使い、貸出はこれを持ち続けない。
type Standing struct {
	lent    LentCount
	overdue OverdueStatus
}

func NewStanding(lent LentCount, overdue OverdueStatus) Standing {
	return Standing{lent: lent, overdue: overdue}
}

func (s Standing) hasOverdue() bool { return s.overdue == HasOverdue }
func (s Standing) reachedLimit() bool { return s.lent.n >= loanLimit }
```

# 集約

```go
package domain

import "example.com/library/internal/shared/vo"

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
func (p PendingLoan) Borrow(id LoanID, lentAt LentAt, cal LibraryCalendar) (BorrowResult, error) {
	if p.standing.hasOverdue() {
		return BorrowResult{}, ErrUserHasOverdue
	}
	if p.standing.reachedLimit() {
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

func RestoreOverdueLoan(id LoanID, user vo.UserNo, book vo.BookNo, lentAt LentAt, due Due, v Version) OverdueLoan {
	return OverdueLoan{loanCore{id: id, user: user, book: book, lentAt: lentAt, due: due, version: v}}
}

func RestoreReturnedLoan(id LoanID, user vo.UserNo, book vo.BookNo, lentAt LentAt, due Due, v Version) ReturnedLoan {
	return ReturnedLoan{loanCore{id: id, user: user, book: book, lentAt: lentAt, due: due, version: v}}
}

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
func (l OnLoan) MarkOverdue(checked CheckedAt, cal LibraryCalendar) (MarkOverdueResult, error) {
	if !l.due.PassedAt(checked, cal) {
		return MarkOverdueResult{}, ErrNotPastDue
	}
	next := OverdueLoan{l.loanCore.next()}
	return MarkOverdueResult{Next: next, Event: Overdue{loan: next.loanCore, checkedAt: checked}}, nil
}

func (OnLoan) loan() {}
func (OverdueLoan) loan() {}
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

`Return` を持つ状態は二つ（貸出中と延滞）で、同じ振る舞いを非公開の `returnLoan` に一つだけ書く。返却済みは、資料の拒む理由をそのまま返す。状態の型は、値の取り出しの関数を持たない。取り出すのはイベントからで、リポジトリの Apply はイベントだけを読むからである。

# 結果とイベント

```go
package domain

import "example.com/library/internal/shared/vo"

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

// Lent は「本が貸し出された」。貸出日時を持ち、それが出来事の時点になる。
type Lent struct{ loan loanCore }

func (e Lent) LoanID() LoanID { return e.loan.id }
func (e Lent) Version() Version { return e.loan.version }
func (e Lent) User() vo.UserNo { return e.loan.user }
func (e Lent) Book() vo.BookNo { return e.loan.book }
func (e Lent) LentAt() LentAt { return e.loan.lentAt }
func (e Lent) Due() Due { return e.loan.due }

// Returned は「本が返却された」。業務の時刻を持たない。出来事の時点はリポジトリが記録のときに決める。
type Returned struct{ loan loanCore }

func (e Returned) LoanID() LoanID { return e.loan.id }
func (e Returned) Version() Version { return e.loan.version }

// Overdue は「貸出が延滞になった」。判定日時を持ち、それが出来事の時点になる。
type Overdue struct {
	loan      loanCore
	checkedAt CheckedAt
}

func (e Overdue) LoanID() LoanID { return e.loan.id }
func (e Overdue) Version() Version { return e.loan.version }
func (e Overdue) CheckedAt() CheckedAt { return e.checkedAt }
```

イベントが持つ値の列は、データモデルの資料のイベント表の列から決める。取り出しの関数は、リポジトリの Apply が実際に読むものだけを置く。

# 永続化ポート

```go
package domain

import (
	"context"

	"example.com/library/internal/shared/vo"
)

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
