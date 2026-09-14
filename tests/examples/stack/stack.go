// Package stack は、規約の例のためだけの小さな被験体である。
// 入力が引数ではなく、それまでの操作である型の例として使う。
package stack

import "errors"

// ErrEmpty は、空のスタックから取り出そうとしたという正当な結果を表す。
var ErrEmpty = errors.New("stack is empty")

type node struct {
	value int
	next  *node
	size  int
}

// Stack は不変な整数スタック。操作は自分を書き換えず、新しい値を返す。
// ゼロ値は空のスタックとして正しく振る舞う。
type Stack struct {
	top *node
}

// New は空のスタックを返す。
func New() Stack { return Stack{} }

// Push は v を積んだ新しいスタックを返す。O(1)。
func (s Stack) Push(v int) Stack {
	return Stack{top: &node{value: v, next: s.top, size: s.Len() + 1}}
}

// PopResult は取り出した値と、それを取り除いた残りのスタックの組。
type PopResult struct {
	value int
	rest  Stack
}

// Value は取り出した値を返す。
func (r PopResult) Value() int { return r.value }

// Rest は取り出した後のスタックを返す。
func (r PopResult) Rest() Stack { return r.rest }

// Pop は最後に積んだ値と残りのスタックを返す。O(1)。空なら ErrEmpty を返す。
func (s Stack) Pop() (PopResult, error) {
	if s.top == nil {
		return PopResult{}, ErrEmpty
	}
	return PopResult{value: s.top.value, rest: Stack{top: s.top.next}}, nil
}

// Len は要素数を返す。O(1)。
func (s Stack) Len() int {
	if s.top == nil {
		return 0
	}
	return s.top.size
}
