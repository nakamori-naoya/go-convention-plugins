package domain

// Followed は「フォローした」。フォロー中のフォローが一つ生まれたことである。業務の時刻を持たない。
type Followed struct{ follow followCore }

func (e Followed) FollowID() FollowID { return e.follow.id }
func (e Followed) Version() Version   { return e.follow.version }
func (e Followed) Follower() Follower { return e.follow.follower }
func (e Followed) Followee() Followee { return e.follow.followee }
