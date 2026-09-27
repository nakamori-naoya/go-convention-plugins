package domain_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"example.com/service/follow/follow/domain"
)

func TestNewFollowingCount(t *testing.T) {
	t.Parallel()

	tests := []struct {
		id          string
		name        string
		description string
		n           int   // When
		wantErr     error // Then: nil なら作れる
	}{
		{
			id:   "3a9f51",
			name: "0人のフォロー中の人数は作れる",
			description: `Given: 利用者はだれもフォローしていない
When: フォロー中の人数を0人として作る
Then: フォロー中の人数が作れる`,
			n: 0,
		},
		{
			id:   "b6d02e",
			name: "負のフォロー中の人数は拒む",
			description: `Given: 数えた人数が-1人である
When: フォロー中の人数を-1人として作る
Then: フォロー中の人数が負であるとして拒まれる`,
			n:       -1,
			wantErr: domain.ErrFollowingCountNegative,
		},
	}
	for _, tt := range tests {
		t.Run(tt.id+" "+tt.name, func(t *testing.T) {
			t.Parallel()

			got, err := domain.NewFollowingCount(tt.n)
			if tt.wantErr != nil {
				require.ErrorIs(t, err, tt.wantErr)
				assert.Zero(t, got)
				return
			}
			require.NoError(t, err)
		})
	}
}
