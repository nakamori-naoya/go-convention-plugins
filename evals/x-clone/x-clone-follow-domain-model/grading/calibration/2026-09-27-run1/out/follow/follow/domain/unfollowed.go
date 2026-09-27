package domain

// Unfollowed は「フォローを外した」。フォロー中のフォローが終わったことである。業務の時刻を持たない。
type Unfollowed struct{ follow followCore }

func (e Unfollowed) FollowID() FollowID { return e.follow.id }
func (e Unfollowed) Version() Version   { return e.follow.version }
