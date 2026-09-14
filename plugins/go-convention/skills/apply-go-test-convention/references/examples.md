# 完全な例

規約を満たしたテストファイルを3つ置く。**書き始める前に一度読み、この形を写す。**

コードはリポジトリの `tests/examples/` にある Go モジュール（Go 1.27）と同一で、3つとも `go vet` と `go test -shuffle=on` が通る。
3つの被験体に資料（BDD）は無いので、`id` はすべて生成した id である。資料があるケースの `id` / `name` / `description` の写し方は [case-identity.md](case-identity.md)。
被験体（`numseq` / `stack` / `filestore`）は例のためだけの小さなパッケージで、テストが使う公開 API だけを各節の先頭に示す。

| 例 | Given の形 | 逃げ道 |
|---|---|---|
| §1 `numseq.FindPairSummingTo` | データ | 無し |
| §2 `stack.Stack.Pop` | 操作列（`given []op` + `steps []step`） | 無し |
| §3 `filestore.Store.Save` | `setup func(t *testing.T) fixture` + データ（`seed`） | `setup` と、1ケースだけ `verify` |

## 1. 純粋な関数 — `numseq.FindPairSummingTo`

被験体の公開 API:

```go
func NewNumberSequence(values []int) NumberSequence
func FindPairSummingTo(seq NumberSequence, target int) (IndexPair, error)   // 無ければ ErrNoPairFound
func (p IndexPair) Lo() int
func (p IndexPair) Hi() int
```

Given は `values`（データ）、When は引数名そのままの `target`、Then は `wantLo` / `wantHi` / `wantErr`。
`numseq_test.go`:

```go
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
```

## 2. 入力が操作列である型 — `stack.Stack.Pop`

被験体の公開 API:

```go
func New() Stack
func (s Stack) Push(v int) Stack
func (s Stack) Pop() (PopResult, error)   // 空なら ErrEmpty
func (r PopResult) Value() int
func (r PopResult) Rest() Stack
func (s Stack) Len() int
```

Given は `given []op`、When と Then は `steps []step`（操作と直後の期待）、最終状態の Then は `wantLen`。
`stack_test.go`:

```go
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
```

## 3. 資源が要る型 — `filestore.Store.Save`

被験体の公開 API:

```go
func Open(dir string) (*Store, error)
func (s *Store) Save(key string, body []byte) (Saved, error)   // 空のキーは ErrEmptyKey、保存済みは ErrExists
func (r Saved) Path() string
func (r Saved) Size() int
```

Given は `setup`（保存先を取得するだけ。`1fa5c9` だけ読み取り専用にする）と `seed`（保存済みのキー。投入はループ本体）、When は `key` / `body`、Then は `wantSize` / `wantErr` / `wantFiles`。
`verify` は `6b0d4e` だけが持ち、保存先の絶対パスという、表を書く時点で値が決まらない性質を見る。
`filestore_test.go`:

```go
package filestore_test

import (
	"io/fs"
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"example.com/go-test-convention/examples/filestore"
)

func TestStore_Save(t *testing.T) {
	t.Parallel()

	// fixture は SUT と、Then で覗く共同作業者（保存先ディレクトリ）を持つ。
	type fixture struct {
		sut *filestore.Store
		dir string
	}

	tests := []struct {
		id          string
		name        string
		description string
		setup       func(t *testing.T) fixture              // Given: 資源の取得だけ
		seed        []string                                // Given: 保存済みのキー。投入はループ本体
		key         string                                  // When:  対象メソッドの引数名そのまま
		body        []byte                                  // When
		wantSize    int                                     // Then
		wantErr     error                                   // Then: nil なら成功を期待
		wantFiles   []string                                // Then: 保存先に在るファイル名。無ければ書かない
		verify      func(t *testing.T, got filestore.Saved) // Then: got の性質で、等値で書けないもの
	}{
		{
			id:   "6b0d4e",
			name: "本文をキー名のファイルとして保存する",
			description: `Given: 空の保存先がある
When: キー a に 5 バイトの本文を保存する
Then: 5 バイト保存され、保存先はキー a を名前にした絶対パスである
  And: 保存先にはファイル a だけが在る`,
			setup: func(t *testing.T) fixture {
				dir := t.TempDir()
				sut, err := filestore.Open(dir)
				require.NoError(t, err)
				return fixture{sut: sut, dir: dir}
			},
			key:       "a",
			body:      []byte("hello"),
			wantSize:  5,
			wantFiles: []string{"a"},
			verify: func(t *testing.T, got filestore.Saved) {
				assert.True(t, filepath.IsAbs(got.Path()))
				assert.Equal(t, "a", filepath.Base(got.Path()))
			},
		},
		{
			id:   "f18c72",
			name: "別のキーなら保存済みの隣に足される",
			description: `Given: キー a が保存済みである
When: キー b に 5 バイトの本文を保存する
Then: 5 バイト保存される
  And: 保存先にはファイル a と b が在る`,
			setup: func(t *testing.T) fixture {
				dir := t.TempDir()
				sut, err := filestore.Open(dir)
				require.NoError(t, err)
				return fixture{sut: sut, dir: dir}
			},
			seed:      []string{"a"},
			key:       "b",
			body:      []byte("world"),
			wantSize:  5,
			wantFiles: []string{"a", "b"},
		},
		{
			id:   "4d9a35",
			name: "空の本文でもファイルは作られる",
			description: `Given: 空の保存先がある
When: キー a に空の本文を保存する
Then: 0 バイト保存される
  And: 保存先にはファイル a だけが在る`,
			setup: func(t *testing.T) fixture {
				dir := t.TempDir()
				sut, err := filestore.Open(dir)
				require.NoError(t, err)
				return fixture{sut: sut, dir: dir}
			},
			key:       "a",
			body:      []byte{},
			wantSize:  0,
			wantFiles: []string{"a"},
		},
		{
			id:   "c72e60",
			name: "空のキーには保存できない",
			description: `Given: 空の保存先がある
When: 空のキーに本文を保存する
Then: キーが空のため拒まれる
  And: 保存先にファイルは無い`,
			setup: func(t *testing.T) fixture {
				dir := t.TempDir()
				sut, err := filestore.Open(dir)
				require.NoError(t, err)
				return fixture{sut: sut, dir: dir}
			},
			key:     "",
			body:    []byte("hello"),
			wantErr: filestore.ErrEmptyKey,
		},
		{
			id:   "09e7b4",
			name: "保存済みのキーには上書きしない",
			description: `Given: キー a が保存済みである
When: キー a に本文を保存する
Then: 保存済みのため拒まれる
  And: 保存先にはファイル a だけが在る
  NOTE: Rule: 同じキーには一度しか保存できない
    Reason: キー a が保存済みで、二件目の保存になるため`,
			setup: func(t *testing.T) fixture {
				dir := t.TempDir()
				sut, err := filestore.Open(dir)
				require.NoError(t, err)
				return fixture{sut: sut, dir: dir}
			},
			seed:      []string{"a"},
			key:       "a",
			body:      []byte("again"),
			wantErr:   filestore.ErrExists,
			wantFiles: []string{"a"},
		},
		{
			id:   "1fa5c9",
			name: "保存先が読み取り専用なら保存できない",
			description: `Given: 読み取り専用の保存先がある
When: キー a に本文を保存する
Then: 書き込めないため拒まれる
  And: 保存先にファイルは無い`,
			setup: func(t *testing.T) fixture {
				dir := t.TempDir()
				sut, err := filestore.Open(dir)
				require.NoError(t, err)
				require.NoError(t, os.Chmod(dir, 0o500))
				t.Cleanup(func() { _ = os.Chmod(dir, 0o700) }) // 権限を戻してから t.TempDir の削除が走る（LIFO）
				return fixture{sut: sut, dir: dir}
			},
			key:     "a",
			body:    []byte("hello"),
			wantErr: fs.ErrPermission,
		},
	}

	for _, tt := range tests {
		t.Run(tt.id+" "+tt.name, func(t *testing.T) {
			t.Parallel()

			f := tt.setup(t) // サブテストの t を渡す。t.Cleanup がこのケースの終わりに走る
			for _, key := range tt.seed {
				_, err := f.sut.Save(key, []byte("seeded"))
				require.NoError(t, err)
			}

			got, err := f.sut.Save(tt.key, tt.body)
			if tt.wantErr != nil {
				require.ErrorIs(t, err, tt.wantErr)
				assert.Zero(t, got)
			} else {
				require.NoError(t, err)
				assert.Equal(t, tt.wantSize, got.Size())
				if tt.verify != nil {
					tt.verify(t, got)
				}
			}

			// 副作用は共同作業者（保存先）を公開の手段で観測し、want{何} と突き合わせる。
			entries, err := os.ReadDir(f.dir)
			require.NoError(t, err)
			var gotFiles []string // ファイル無しはゼロ値。wantFiles を書かないケースと一致する
			for _, e := range entries {
				gotFiles = append(gotFiles, e.Name())
			}
			assert.Equal(t, tt.wantFiles, gotFiles)
		})
	}
}
```
