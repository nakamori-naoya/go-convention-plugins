package domain

// Follower は、フォローを行った側の利用者である。フォローを始め、終えられるのはフォロワーだけである。
type Follower struct{ user UserID }

// NewFollower は、利用者をフォロワーにする。
func NewFollower(user UserID) Follower { return Follower{user: user} }
