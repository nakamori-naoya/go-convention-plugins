// Package errors は、失敗の意味を表す分類と、それを土台にした具体エラーを定義する。
// 例を小さく保つため、見本が使う二つの分類だけを持つ。
package errors

type category struct{ text string }

var (
	ErrInvalidInput = &category{text: "入力が不正"}
	ErrPrecondition = &category{text: "業務ルールに反する"}
)

// Error は、分類を土台にした具体エラーである。文言は、応答で利用者に見せてよい内容だけを持つ。
type Error struct {
	of   *category
	text string
}

func Define(base *category, text string) *Error {
	return &Error{of: base, text: text}
}

func (c *category) Error() string { return c.text }
func (e *Error) Error() string    { return e.text }
func (e *Error) Unwrap() error    { return e.of }
