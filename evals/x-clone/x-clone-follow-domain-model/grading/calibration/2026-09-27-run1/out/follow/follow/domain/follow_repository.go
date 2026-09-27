package domain

import "context"

// FollowRepository は、フォローと、その出来事を記録する。
//
// FindPendingFollow は、フォロワーのその時点のフォロー中の人数を数えて、フォローする前のフォローに持たせる。
// FindFollowing は、フォロワーからフォロー相手へのフォロー中のフォローを返し、無ければ ErrNotFollowing を返す。
// ApplyFollowed は、同じ二人の間にフォロー中のフォローがあれば ErrAlreadyFollowing を、
// 同じフォロワーのフォロー中の人数がフォロー上限を超えることになれば ErrFollowLimitReached を返す。
type FollowRepository interface {
	FindPendingFollow(ctx context.Context, follower Follower, followee Followee) (PendingFollow, error)
	FindFollowing(ctx context.Context, follower Follower, followee Followee) (Following, error)
	ApplyFollowed(ctx context.Context, evt Followed) error
	ApplyUnfollowed(ctx context.Context, evt Unfollowed) error
}
