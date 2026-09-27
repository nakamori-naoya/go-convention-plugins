package domain

// Followee は、フォロワーがフォローした側の利用者である。フォロー相手の側からはフォローを始めることも終えることもできない。
type Followee struct{ user UserID }

// NewFollowee は、利用者をフォロー相手にする。
func NewFollowee(user UserID) Followee { return Followee{user: user} }

func (f Followee) is(follower Follower) bool { return f.user == follower.user }
