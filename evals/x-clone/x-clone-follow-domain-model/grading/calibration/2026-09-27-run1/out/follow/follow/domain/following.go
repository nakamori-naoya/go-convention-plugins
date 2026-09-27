package domain

// Following は、フォロー中のフォローである。フォローの状態はフォロー中だけで、外すと終わり、状態として残らない。
type Following struct{ followCore }

type followCore struct {
	id       FollowID
	follower Follower
	followee Followee
	version  Version
}

// RestoreFollowing は、保存されたフォロー中のフォローを組み立て直す。検証しない。
func RestoreFollowing(id FollowID, follower Follower, followee Followee, v Version) Following {
	return Following{followCore{id: id, follower: follower, followee: followee, version: v}}
}

// UnfollowUser は「フォローを外す」。フォロー中のフォローはいつでも外せ、外したフォローは終わる。
func (f Following) UnfollowUser() UnfollowUserResult {
	ended := f.followCore
	ended.version = ended.version.Next()
	return UnfollowUserResult{Event: Unfollowed{follow: ended}}
}

// UnfollowUserResult は、「フォローを外す」を受けた結果である。外したフォローは終わるので、次の状態を持たない。
type UnfollowUserResult struct {
	Event Unfollowed
}
