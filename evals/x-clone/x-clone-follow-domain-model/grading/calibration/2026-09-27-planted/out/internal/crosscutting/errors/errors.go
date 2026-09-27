// errors は、失敗の意味を表す15の分類と、それを土台にした具体エラーを定義する。
package errors

import (
	"context"
	stderrors "errors"
)

// Base は、具体エラーの土台にできるものである。分類と具体エラーだけが満たす。
type Base interface {
	error
	base()
}

type category struct{ text string }

var (
	ErrInvalidInput    = &category{text: "入力が不正"}
	ErrUnauthenticated = &category{text: "認証されていない"}
	ErrForbidden       = &category{text: "許可されていない"}
	ErrNotFound        = &category{text: "存在しない"}
	ErrAlreadyExists   = &category{text: "すでに存在する"}
	ErrPrecondition    = &category{text: "業務ルールに反する"}
	ErrRateLimited     = &category{text: "利用上限に達した"}
	ErrUnimplemented   = &category{text: "未対応の操作"}
	ErrCanceled        = &category{text: "中断された"}
	ErrConflict        = &category{text: "同時更新で競合した"}
	ErrExhausted       = &category{text: "容量の上限を超えた"}
	ErrTimeout         = &category{text: "時間切れ"}
	ErrUnavailable     = &category{text: "依存先が利用できない"}
	ErrInternal        = &category{text: internalMessage}
	ErrUnclassified    = &category{text: "分類不能"}
)

const internalMessage = "内部エラーが発生した"

var categories = []*category{
	ErrInvalidInput, ErrUnauthenticated, ErrForbidden, ErrNotFound, ErrAlreadyExists,
	ErrPrecondition, ErrRateLimited, ErrUnimplemented, ErrCanceled, ErrConflict,
	ErrExhausted, ErrTimeout, ErrUnavailable, ErrInternal, ErrUnclassified,
}

// aliases は、標準ライブラリのエラーを同じ意味の分類として扱う。
var aliases = map[*category]error{
	ErrCanceled: context.Canceled,
	ErrTimeout:  context.DeadlineExceeded,
}

// Error は、分類を土台にした具体エラーである。文言は、応答で利用者に見せてよい内容だけを持つ。
type Error struct {
	of   Base
	text string
}

func Define(base Base, text string) *Error {
	return &Error{of: base, text: text}
}

func Is(err, target error) bool {
	return stderrors.Is(err, target)
}

func AsType[T error](err error) (T, bool) {
	return stderrors.AsType[T](err)
}

// Category は、連鎖が土台にする分類を返す。どれにも当たらなければ ErrUnclassified、nil には nil を返す。
func Category(err error) error {
	if err == nil {
		return nil
	}
	for _, c := range categories {
		if stderrors.Is(err, c) {
			return c
		}
	}
	for _, c := range categories {
		if alias, ok := aliases[c]; ok && stderrors.Is(err, alias) {
			return c
		}
	}
	return ErrUnclassified
}

// Classified は、連鎖が分類を土台にしているかを返す。別名（ctx の中断と期限切れ）だけでは真にならない。
func Classified(err error) bool {
	for _, c := range categories {
		if stderrors.Is(err, c) {
			return true
		}
	}
	return false
}

// Message は、応答に載せてよい文言を返す。回復不能と分類不能は、固定の文言だけを返す。
func Message(err error) string {
	c := Category(err)
	if stderrors.Is(c, ErrInternal) || stderrors.Is(c, ErrUnclassified) {
		return internalMessage
	}
	if specific, ok := stderrors.AsType[*Error](err); ok {
		return specific.text
	}
	return c.Error()
}

func (c *category) Error() string { return c.text }
func (c *category) base()         {}
func (e *Error) Error() string    { return e.text }
func (e *Error) Unwrap() error    { return e.of }
func (e *Error) base()            {}
