package domain

// followLimit は、一人の利用者が同時にフォロー中にしていられる相手の数の上限（フォロー上限）である。
const followLimit = 5000

// FollowingCount は、一人のフォロワーがフォローする瞬間にフォロー中にしているフォローの数である。
// フォローの中には持たず、フォローするコマンドの判断にだけ使う。
type FollowingCount struct{ n int }

// NewFollowingCount は、数えたフォロー中の人数を受ける。負の数は拒む。
func NewFollowingCount(n int) (FollowingCount, error) {
	if n < 0 {
		return FollowingCount{}, ErrFollowingCountNegative
	}
	return FollowingCount{n: n}, nil
}

func (c FollowingCount) reachedLimit() bool { return c.n >= followLimit }
