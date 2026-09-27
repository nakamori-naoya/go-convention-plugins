// Package id は、複数の業務が同じ利用者やものを指すための識別子を持つ。
package id

import (
	"uuid"

	"example.com/service/internal/crosscutting/errors"
)

// ErrInvalidUserID は、利用者IDとして読めない値である。
var ErrInvalidUserID = errors.Define(errors.ErrInvalidInput, "利用者IDの形が正しくない")

// UserID は、登録した利用者を一人に決める識別子である。例: "0193a3c1-7a4e-7c2e-9f10-5b8d2e6a4f01"。
type UserID struct{ v uuid.UUID }

// NewUserID は、文字列の利用者IDを読む。空や UUID でない値は拒む。
func NewUserID(s string) (UserID, error) {
	u, err := uuid.Parse(s)
	if err != nil {
		return UserID{}, ErrInvalidUserID
	}
	return UserID{v: u}, nil
}

// UserIDFrom は、発行した IDを利用者IDにする。
func UserIDFrom(u uuid.UUID) UserID {
	return UserID{v: u}
}

// Value は、保存と応答のために値を取り出す。
func (i UserID) Value() uuid.UUID {
	return i.v
}
