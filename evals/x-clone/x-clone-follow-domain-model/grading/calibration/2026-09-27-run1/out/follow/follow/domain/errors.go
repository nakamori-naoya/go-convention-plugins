// Package domain は、一人のフォロワーから一人のフォロー相手への一件のフォローを持つ。
package domain

import "example.com/service/internal/crosscutting/errors"

// 業務知識の拒む理由に一つずつ対応する。
var (
	ErrFollowSelf         = errors.Define(errors.ErrPrecondition, "自分自身をフォローする")
	ErrFollowLimitReached = errors.Define(errors.ErrPrecondition, "フォロー上限に達している利用者がフォローする")
	ErrAlreadyFollowing   = errors.Define(errors.ErrAlreadyExists, "すでにフォロー中の相手をフォローする") // フォローを記録する側が守る
	ErrNotFollowing       = errors.Define(errors.ErrNotFound, "フォローしていない相手のフォローを外す")     // 外すフォローが見つからない
)

// ErrFollowingCountNegative は、フォロー中の人数として負の数を受けたことである。人数は負にならない。
var ErrFollowingCountNegative = errors.Define(errors.ErrInvalidInput, "フォロー中の人数が負である")
