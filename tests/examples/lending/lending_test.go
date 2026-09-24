package lending_test

// BDD の資料: tests/examples/docs/lending/業務知識.md

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"example.com/go-test-convention/examples/lending"
)

func TestPendingLoan_Borrow(t *testing.T) {
	t.Parallel()

	// 表で使う冊数。生成の条件は Count のテストが確かめるので、ここで失敗するなら表以前の問題である。
	none, err := lending.NewCount(0)
	require.NoError(t, err)
	one, err := lending.NewCount(1)
	require.NoError(t, err)
	four, err := lending.NewCount(4)
	require.NoError(t, err)
	five, err := lending.NewCount(5)
	require.NoError(t, err)

	tests := []struct {
		id          string
		name        string
		description string
		lent        lending.Count  // Given: 借りている冊数
		overdue     lending.Count  // Given: 延滞の貸出の冊数
		lentAt      lending.LentAt // When:  貸出の時点
		wantDueDay  time.Time      // Then:  返却期限の日（取り出した値）
		wantErr     error          // Then:  nil なら借りられる
	}{
		{
			id:   "BDD-001",
			name: "延滞の無い利用者が本を借りると貸出中の貸出が生まれる",
			description: `Given: 利用者 U-0001 は本を1冊も借りておらず、延滞の貸出も無い
When: 利用者 U-0001 が2026年10月1日 10:00に本を借りる
Then: 貸出中の貸出が生まれる
  And: 返却期限は2026年10月15日である`,
			lent:       none,
			overdue:    none,
			lentAt:     lending.NewLentAt(time.Date(2026, 10, 1, 10, 0, 0, 0, time.UTC)),
			wantDueDay: time.Date(2026, 10, 15, 0, 0, 0, 0, time.UTC),
		},
		{
			id:   "BDD-003",
			name: "5冊借りている利用者は6冊目を借りられない",
			description: `Given: 利用者 U-0001 は貸出中の本を5冊借りており、延滞の貸出は無い
When: 利用者 U-0001 が2026年10月1日 10:00に本を借りる
Then: 貸出は生まれない
  NOTE: Rule: 貸出上限に達している利用者が本を借りる
    Reason: 一人の貸出中と延滞の貸出は5冊を超えない`,
			lent:    five,
			overdue: none,
			lentAt:  lending.NewLentAt(time.Date(2026, 10, 1, 10, 0, 0, 0, time.UTC)),
			wantErr: lending.ErrLoanLimitReached,
		},
		{
			id:   "BDD-004",
			name: "延滞の貸出がある利用者は本を借りられない",
			description: `Given: 利用者 U-0002 は延滞の貸出を1冊持ち、借りている冊数は1冊である
When: 利用者 U-0002 が2026年10月20日 10:00に本を借りる
Then: 貸出は生まれない
  NOTE: Rule: 延滞の貸出がある利用者が本を借りる
    Reason: 返していない延滞がある利用者には新しい本を貸さない`,
			lent:    one,
			overdue: one,
			lentAt:  lending.NewLentAt(time.Date(2026, 10, 20, 10, 0, 0, 0, time.UTC)),
			wantErr: lending.ErrUserHasOverdue,
		},
		{
			id:   "7c2e19",
			name: "4冊借りている利用者は5冊目を借りられる",
			description: `Given: 利用者は貸出中の本を4冊借りており、延滞の貸出は無い
When: 利用者が2026年10月1日 10:00に本を借りる
Then: 貸出中の貸出が生まれ、返却期限は2026年10月15日である`,
			lent:       four,
			overdue:    none,
			lentAt:     lending.NewLentAt(time.Date(2026, 10, 1, 10, 0, 0, 0, time.UTC)),
			wantDueDay: time.Date(2026, 10, 15, 0, 0, 0, 0, time.UTC),
		},
		{
			id:   "91d6c8",
			name: "延滞があり上限にも達している利用者は延滞の理由で拒まれる",
			description: `Given: 利用者は延滞の貸出を1冊持ち、借りている冊数は5冊である
When: 利用者が2026年10月20日 10:00に本を借りる
Then: 延滞の貸出がある利用者が本を借りるとして拒まれる`,
			lent:    five,
			overdue: one,
			lentAt:  lending.NewLentAt(time.Date(2026, 10, 20, 10, 0, 0, 0, time.UTC)),
			wantErr: lending.ErrUserHasOverdue,
		},
	}

	for _, tt := range tests {
		t.Run(tt.id+" "+tt.name, func(t *testing.T) {
			t.Parallel()

			pending := lending.NewPendingLoan(lending.NewStanding(tt.lent, tt.overdue))

			got, err := pending.Borrow(tt.lentAt)
			if tt.wantErr != nil {
				require.ErrorIs(t, err, tt.wantErr)
				assert.Zero(t, got)
				return
			}
			require.NoError(t, err)
			assert.Equal(t, tt.wantDueDay, got.Due().Day())
		})
	}
}
