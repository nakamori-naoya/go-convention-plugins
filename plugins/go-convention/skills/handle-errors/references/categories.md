# エラーの分類

# 15の分類

分類は、正当に起こりうる失敗の意味による14個と、「分類不能」1個である。業務が増えても、分類は増やさない。

| 分類 | 変数 | 意味 |
|---|---|---|
| 入力が不正 | `ErrInvalidInput` | 入力そのものを受け入れられない |
| 認証されていない | `ErrUnauthenticated` | 操作の主体を確認できない |
| 許可されていない | `ErrForbidden` | 確認済みの主体に、その操作が許されていない |
| 存在しない | `ErrNotFound` | 対象が存在しない |
| すでに存在する | `ErrAlreadyExists` | 同じものがすでに存在する |
| 業務ルールに反する | `ErrPrecondition` | 業務知識の規則により、その操作を行えない |
| 利用上限に達した | `ErrRateLimited` | 頻度の上限に当たった |
| 未対応の操作 | `ErrUnimplemented` | 定義はあるが、提供していない操作を呼ばれた |
| 中断された | `ErrCanceled` | 呼び出し側の都合で、操作が中断された |
| 同時更新で競合した | `ErrConflict` | 同時更新の競合で、完了できなかった |
| 容量の上限を超えた | `ErrExhausted` | 接続数や依存先の全体の上限など、容量を超えた |
| 時間切れ | `ErrTimeout` | 期限内に完了できなかった |
| 依存先が利用できない | `ErrUnavailable` | 依存先が一時的に利用できない |
| 回復不能 | `ErrInternal` | 運用者がデータか環境を直すまで解決しない |
| 分類不能 | `ErrUnclassified` | 実装の間違いか、翻訳の漏れ |

# 境目

業務知識が定める数量の上限（一人が借りられる冊数）は「業務ルールに反する」で、資料の拒む理由として現れる。「利用上限に達した」は、サービスを守るために入口が課す時間当たりの回数の上限だけに使う。

「回復不能」は、もう一度処理しても直らず、運用者がデータか環境を直すまで解決しないもの（設定や環境の不備、保存されたデータの破損、外部の依存先が契約を破った応答）だけに使う。一時的な不在、時間切れ、競合には使わない。分類が分からないことを理由に選ばず、分からなければ分類に当てずに返して境界に分類不能と判定させる。

`Define` の第一引数に「分類不能」を自分で選んでよいのは、正しい呼び方では起こりえない呼び方の間違い（トランザクションの無い ctx でリポジトリを呼んだ、入れ子のトランザクションを張ろうとした）だけである。実装の間違いを表す分類を別に作らない。分類不能として境界に届くこと自体が、実装を直す合図になる。

# 分類の package

分類は `internal/crosscutting/errors` が持つ。標準の `errors` を import してよいのはこの package だけで、ほかは同じ名前で提供する `Is` と `AsType` を使う。分類を経ずにエラーを作る道を無くすためで、import の禁止は `depguard` で守る。

```go
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
	base Base
	text string
}

func Define(base Base, text string) *Error {
	return &Error{base: base, text: text}
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
	if c == ErrInternal || c == ErrUnclassified {
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
func (e *Error) Unwrap() error    { return e.base }
func (e *Error) base()            {}
```

一つの連鎖は分類を一つだけ持つので、`Category` は最初に見つかった分類を、`Message` は最初の具体エラーの文言を返せばよい。分類の一覧を公開する関数は作らない。
