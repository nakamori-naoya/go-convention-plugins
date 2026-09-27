package domain

import "uuid"

// FollowID は、一件のフォローを見分ける。同じ二人の間でも、外した後にもう一度フォローすれば別の値になる。
type FollowID struct{ id uuid.UUID }

// NewFollowIDFromUUID は、採番器が返した UUID をフォローIDにする。採番はしない。
func NewFollowIDFromUUID(id uuid.UUID) FollowID { return FollowID{id: id} }
