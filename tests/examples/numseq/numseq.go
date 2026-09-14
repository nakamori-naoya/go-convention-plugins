// Package numseq は、規約の例のためだけの小さな被験体である。
// 純粋な関数（引数を受け取り、結果と error を返す）の例として使う。
package numseq

import "errors"

// ErrNoPairFound は、目標に合う組が無いという正当な結果を表す。
var ErrNoPairFound = errors.New("no pair sums to target")

// NumberSequence は整数の列。生成後は変わらない。
type NumberSequence struct {
	values []int
}

// NewNumberSequence は values を複製して保持する。呼び出し側が後から書き換えても影響しない。
func NewNumberSequence(values []int) NumberSequence {
	cloned := make([]int, len(values))
	copy(cloned, values)
	return NumberSequence{values: cloned}
}

// Len は要素数を返す。
func (s NumberSequence) Len() int { return len(s.values) }

// IndexPair は異なる2つの添字の組。常に Lo < Hi に正規化されている。
type IndexPair struct {
	lo, hi int
}

// Lo は小さい方の添字を返す。
func (p IndexPair) Lo() int { return p.lo }

// Hi は大きい方の添字を返す。
func (p IndexPair) Hi() int { return p.hi }

// FindPairSummingTo は、和が target になる2要素の添字の組を返す。時間 O(n)、空間 O(n)。
// 組が無ければ ErrNoPairFound を返す。
func FindPairSummingTo(seq NumberSequence, target int) (IndexPair, error) {
	seen := make(map[int]int, len(seq.values))
	for i, v := range seq.values {
		if j, ok := seen[target-v]; ok {
			return IndexPair{lo: j, hi: i}, nil
		}
		// 同じ値が複数あっても最初の位置だけ覚えれば足りる。
		if _, ok := seen[v]; !ok {
			seen[v] = i
		}
	}
	return IndexPair{}, ErrNoPairFound
}
