package domain

import "example.com/service/internal/shared/vo/id"

// Follower は、フォローを行った側の利用者である。フォローを始め、終えられるのはフォロワーだけである。
type Follower struct{ user id.UserID }

// NewFollower は、利用者をフォロワーにする。
func NewFollower(user id.UserID) Follower { return Follower{user: user} }
