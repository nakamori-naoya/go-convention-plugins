// Package lending は、テストの形の例のためだけの小さな被験体である。図書館の貸出の「本を借りる」だけを持つ。
// 例を小さく保つため、エラーの分類の package を使わず、標準の errors で具体エラーを定義している。
package lending

import (
	"errors"
	"time"
)

// 業務知識の拒む理由に一つずつ対応する。
var (
	ErrUserHasOverdue   = errors.New("延滞の貸出がある利用者が本を借りる")
	ErrLoanLimitReached = errors.New("貸出上限に達している利用者が本を借りる")
)

// 値の構造として必ず拒む値。
var ErrCountNegative = errors.New("冊数が負である")

// loanLimit は、一人が同時に借りられる冊数の上限である。
const loanLimit = 5

// loanPeriodDays は、返却期限を決める貸出の期間である。
const loanPeriodDays = 14

// Count は、利用者の貸出の冊数である。
type Count struct{ n int }

func NewCount(n int) (Count, error) {
	if n < 0 {
		return Count{}, ErrCountNegative
	}
	return Count{n: n}, nil
}

// Standing は、本を借りる瞬間の利用者の貸出状況である。借りている冊数と、延滞の貸出の冊数を持つ。
type Standing struct {
	lent    Count
	overdue Count
}

func NewStanding(lent, overdue Count) Standing {
	return Standing{lent: lent, overdue: overdue}
}

// LentAt は、本が貸し出された時点である。
type LentAt struct{ at time.Time }

func NewLentAt(at time.Time) LentAt {
	return LentAt{at: at.UTC()}
}

// Due は、返却期限の日である。例: 2026年10月1日に借りたら 2026年10月15日。
type Due struct{ day time.Time }

func (d Due) Day() time.Time { return d.day }

// OnLoan は、貸出中の貸出である。
type OnLoan struct {
	lentAt LentAt
	due    Due
}

func (l OnLoan) Due() Due { return l.due }

// PendingLoan は、まだ保存されていない貸出である。借りる瞬間の貸出状況を持つ。
type PendingLoan struct {
	standing Standing
}

func NewPendingLoan(standing Standing) PendingLoan {
	return PendingLoan{standing: standing}
}

// Borrow は「本を借りる」。延滞と上限の両方に当たるときは、延滞を先に見る。
func (p PendingLoan) Borrow(lentAt LentAt) (OnLoan, error) {
	if p.standing.overdue.n > 0 {
		return OnLoan{}, ErrUserHasOverdue
	}
	if p.standing.lent.n >= loanLimit {
		return OnLoan{}, ErrLoanLimitReached
	}
	y, m, d := lentAt.at.Date()
	due := Due{day: time.Date(y, m, d, 0, 0, 0, 0, time.UTC).AddDate(0, 0, loanPeriodDays)}
	return OnLoan{lentAt: lentAt, due: due}, nil
}
