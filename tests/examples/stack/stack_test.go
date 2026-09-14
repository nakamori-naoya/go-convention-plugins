package stack_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"example.com/go-test-convention/examples/stack"
)

func TestStack_Pop(t *testing.T) {
	t.Parallel()

	type opKind int

	const (
		opPush opKind = iota
		opPop
	)

	// op は被験体への1回の操作。given（準備）と steps（検証対象）の両方がこれを使う。
	type op struct {
		kind opKind
		v    int // opPush のときだけ意味を持つ
	}

	// step は操作と、その直後の観測値への期待を1組で持つ。
	type step struct {
		op      op
		want    int   // Then: opPush は積んだ後の個数、opPop は取り出した値
		wantErr error // Then: nil なら成功を期待
	}

	tests := []struct {
		id          string
		name        string
		description string
		given       []op   // Given: 準備の操作。期待を持たない
		steps       []step // When + Then: 操作と、その直後の期待
		wantLen     int    // Then: 最終状態を公開クエリで観測した値
	}{
		{
			id:   "5e1c4a",
			name: "最後に積んだ値から順に取り出す",
			description: `Given: 1, 2 の順に積んである
When: 2回取り出す
Then: 2, 1 の順に取り出せる
  And: スタックは空になる`,
			given: []op{{kind: opPush, v: 1}, {kind: opPush, v: 2}},
			steps: []step{
				{op: op{kind: opPop}, want: 2},
				{op: op{kind: opPop}, want: 1},
			},
			wantLen: 0,
		},
		{
			id:   "d07b92",
			name: "1つ取り出しても残りはそのまま残る",
			description: `Given: 1, 2, 3 の順に積んである
When: 1回取り出す
Then: 3 が取り出せる
  And: スタックには 2 つ残る`,
			given:   []op{{kind: opPush, v: 1}, {kind: opPush, v: 2}, {kind: opPush, v: 3}},
			steps:   []step{{op: op{kind: opPop}, want: 3}},
			wantLen: 2,
		},
		{
			id:   "2f6ea1",
			name: "取り出した後に積んだ値は次に取り出せる",
			description: `Given: 1 を積んである
When: 取り出してから 5 を積み、もう一度取り出す
Then: 1 が取り出せ、積むと 1 つになり、次に 5 が取り出せる
  And: スタックは空になる`,
			given: []op{{kind: opPush, v: 1}},
			steps: []step{
				{op: op{kind: opPop}, want: 1},
				{op: op{kind: opPush, v: 5}, want: 1},
				{op: op{kind: opPop}, want: 5},
			},
			wantLen: 0,
		},
		{
			id:   "8c93d5",
			name: "空で拒まれた後も積めば取り出せる",
			description: `Given: スタックが空である
When: 取り出しに失敗してから 9 を積み、取り出す
Then: 最初は空のため拒まれ、積むと 1 つになり、次に 9 が取り出せる
  And: スタックは空になる`,
			steps: []step{
				{op: op{kind: opPop}, wantErr: stack.ErrEmpty},
				{op: op{kind: opPush, v: 9}, want: 1},
				{op: op{kind: opPop}, want: 9},
			},
			wantLen: 0,
		},
		{
			id:   "a3f9c1",
			name: "空のスタックからは取り出せない",
			description: `Given: スタックが空である
When: 取り出す
Then: 空のため取り出せないと拒まれる
  And: スタックは空のままである
  NOTE: Rule: 空のスタックからは取り出せない
    Reason: 取り出す値が無く、取り出しの結果を作れないため`,
			steps:   []step{{op: op{kind: opPop}, wantErr: stack.ErrEmpty}},
			wantLen: 0,
		},
	}

	for _, tt := range tests {
		t.Run(tt.id+" "+tt.name, func(t *testing.T) {
			t.Parallel()

			s := stack.New()
			// 操作の実行はこの switch 1か所。given と steps の両方がここを通る。
			// 戻り値は操作直後の観測値。エラー時は被験体が返した値をそのまま返し、ゼロ値かは呼び出し側が見る。
			run := func(o op) (int, error) {
				switch o.kind {
				case opPush:
					s = s.Push(o.v)
					return s.Len(), nil
				case opPop:
					r, err := s.Pop()
					if err != nil {
						return r.Value(), err
					}
					s = r.Rest()
					return r.Value(), nil
				default:
					t.Fatalf("op の種別が不正: %d", o.kind)
					return 0, nil
				}
			}

			for _, g := range tt.given {
				_, err := run(g)
				require.NoError(t, err)
			}
			for _, st := range tt.steps {
				got, err := run(st.op)
				if st.wantErr != nil {
					require.ErrorIs(t, err, st.wantErr)
					assert.Zero(t, got)
					continue
				}
				require.NoError(t, err)
				assert.Equal(t, st.want, got)
			}
			assert.Equal(t, tt.wantLen, s.Len())
		})
	}
}
