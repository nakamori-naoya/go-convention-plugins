package domain

import "example.com/service/internal/shared/vo/id"

// Followee は、フォロワーがフォローした側の利用者である。フォロー相手の側からはフォローを始めることも終えることもできない。
type Followee struct{ user id.UserID }

// NewFollowee は、利用者をフォロー相手にする。
func NewFollowee(user id.UserID) Followee { return Followee{user: user} }

func (f Followee) is(follower Follower) bool { return f.user == follower.user }
