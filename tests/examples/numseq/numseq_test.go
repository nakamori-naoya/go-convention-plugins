package numseq_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"example.com/go-test-convention/examples/numseq"
)

func TestFindPairSummingTo(t *testing.T) {
	t.Parallel()

	tests := []struct {
		id          string
		name        string
		description string
		values      []int // Given: 数列の中身
		target      int   // When:  対象関数の引数名そのまま
		wantLo      int   // Then
		wantHi      int   // Then
		wantErr     error // Then: nil なら成功を期待
	}{
		{
			id:   "7c2e19",
			name: "和が目標になる2つの位置を返す",
			description: `Given: 数列 2, 7, 11, 15 がある
When: 和が 9 になる組を探す
Then: 位置 0 と 1 の組が返る`,
			values: []int{2, 7, 11, 15},
			target: 9,
			wantLo: 0,
			wantHi: 1,
		},
		{
			id:   "b4a0f3",
			name: "同じ値が2つあれば別の位置として組にする",
			description: `Given: 数列 3, 3 がある
When: 和が 6 になる組を探す
Then: 位置 0 と 1 の組が返る`,
			values: []int{3, 3},
			target: 6,
			wantLo: 0,
			wantHi: 1,
		},
		{
			id:   "91d6c8",
			name: "負の値を含んでいても組を見つける",
			description: `Given: 数列 -3, 4, 3, 90 がある
When: 和が 0 になる組を探す
Then: 位置 0 と 2 の組が返る`,
			values: []int{-3, 4, 3, 90},
			target: 0,
			wantLo: 0,
			wantHi: 2,
		},
		{
			id:   "e5f2a7",
			name: "要素が1つでは組を作れない",
			description: `Given: 数列 5 がある
When: 和が 10 になる組を探す
Then: 組が無いと返る`,
			values:  []int{5},
			target:  10,
			wantErr: numseq.ErrNoPairFound,
		},
		{
			id:   "3a8b0d",
			name: "どの2つを足しても目標にならなければ組は無い",
			description: `Given: 数列 1, 2, 3 がある
When: 和が 7 になる組を探す
Then: 組が無いと返る`,
			values:  []int{1, 2, 3},
			target:  7,
			wantErr: numseq.ErrNoPairFound,
		},
	}

	for _, tt := range tests {
		t.Run(tt.id+" "+tt.name, func(t *testing.T) {
			t.Parallel()

			seq := numseq.NewNumberSequence(tt.values)

			got, err := numseq.FindPairSummingTo(seq, tt.target)
			if tt.wantErr != nil {
				require.ErrorIs(t, err, tt.wantErr)
				assert.Zero(t, got)
				return
			}
			require.NoError(t, err)
			assert.Equal(t, tt.wantLo, got.Lo())
			assert.Equal(t, tt.wantHi, got.Hi())
		})
	}
}
