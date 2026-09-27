package domain

import "time"

// PendingFollow は、まだ保存されていないフォローである。版を持たない。
type PendingFollow struct {
	follower       Follower
	followee       Followee
	followingCount FollowingCount
}

// NewPendingFollow は、フォロワー、フォロー相手、フォローする瞬間のフォロワーのフォロー中の人数から、フォローする前のフォローを作る。
func NewPendingFollow(follower Follower, followee Followee, followingCount FollowingCount) PendingFollow {
	return PendingFollow{follower: follower, followee: followee, followingCount: followingCount}
}

// FollowUser は「フォローする」。自分自身を先に、フォロー上限を後に見る。
// すでにフォロー中の相手かどうかは、生まれる前のフォローからは見えないので判断しない。
func (p PendingFollow) FollowUser(id FollowID) (FollowUserResult, error) {
	if p.followee.is(p.follower) {
		return FollowUserResult{}, ErrFollowSelf
	}
	if p.followingCount.reachedLimit() {
		return FollowUserResult{}, ErrFollowLimitReached
	}
	followedAt := time.Now()
	next := Following{followCore{id: id, follower: p.follower, followee: p.followee, version: FirstVersion}}
	return FollowUserResult{Next: next, Event: Followed{follow: next.followCore, FollowedAt: followedAt}}, nil
}

// CanFollow は、フォロー上限に達していないかを返す。
func (p PendingFollow) CanFollow() bool { return !p.followingCount.reachedLimit() }

// FollowUserResult は、「フォローする」を受けた結果である。
type FollowUserResult struct {
	Next  Following
	Event Followed
}
