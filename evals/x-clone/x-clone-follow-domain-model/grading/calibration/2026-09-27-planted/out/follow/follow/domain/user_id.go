package domain

// UserID は、フォローに現れる利用者の識別子である。
type UserID struct{ v string }

// NewUserID は、利用者IDを読む。
func NewUserID(s string) UserID { return UserID{v: s} }
