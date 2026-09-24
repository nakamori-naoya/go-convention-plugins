# エラーの分類

# 15の分類

分類は、正当に起こりうる失敗の意味による14個と、「分類不能」1個である。業務が増えても、分類は増やさない。実装の間違い（不変条件の破れ、到達しないはずの分岐、翻訳の漏れ）を表す分類も、別には作らない。実装の間違いは「分類不能」として境界に届き、それ自体が実装を直す合図になる。

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

## 「業務ルールに反する」と「利用上限に達した」

業務知識が定める数量の上限は、「業務ルールに反する」である。図書館の貸出上限（一人5冊）がこれに当たる。上限は業務の規則で、資料の拒む理由として現れる。

「利用上限に達した」は、サービスを守るために RPC の interceptor が課す、時間当たりの回数のような頻度の上限だけに使う。業務の資料には現れず、頻度を制限する interceptor が返す。

## 「回復不能」と、一時的な失敗

「回復不能」は、もう一度処理しても直らず、運用者がデータか環境を直すまで解決しないものだけに使う。設定や環境の不備、保存されたデータの破損、外部の依存先が契約を破った応答がこれに当たる。依存先の一時的な不在（「依存先が利用できない」）、時間切れ、競合には使わない。「分類が分からない」を理由に選ばない。分からなければ、分類に当てずに返し、境界に「分類不能」と判定させる。

## 「分類不能」を土台にしてよい場面

`errors.Define` の第一引数に「分類不能」を自分で選んでよいのは、値オブジェクトを経た正しい呼び方では起こりえない、呼び方の間違いだけである。トランザクションの無い ctx でリポジトリを呼んだ、入れ子のトランザクションを張ろうとした、がこれに当たる。業務の拒否を「分類不能」にしない。

# 分類の package

分類は、横断的関心事の一つの package（例：`internal/crosscutting/errors`）が持つ。標準の `errors` を import してよいのはこの package だけで、ほかの package は、この package が同じ名前で提供する `Is` と `AsType` を使う。こうすると、分類を経ずにエラーを作る道が無くなる。import の禁止は `depguard` で機械的に守る（write-go-code のツールの設定）。

```go
// errors は、失敗の意味を表す15の分類と、それを土台にした具体エラーを定義する。
// 内側の層は具体エラーを返すだけで、応答や記録の仕方を知らない。境界が Category で分類を取り出し、表で扱いを決める。
package errors

import (
	"context"
	stderrors "errors"
)

// Base は、具体エラーの土台にできるものである。分類と具体エラーだけが満たすので、分類を経ない土台はコンパイルが通らない。
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

// aliases は、標準ライブラリのエラーを同じ意味の分類として扱う対応である。
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

一つのエラーの連鎖は、分類を一つだけ持つ（[運び方、翻訳、付け替え](propagation.md)）。そのため `Category` は、連鎖の中で最初に見つかった分類を返せばよく、照合の順に意味を持たせない。`Message` も、連鎖の中の最初の具体エラーの文言を返せばよい。

この package が公開するのは、実装のコードが呼ぶものだけである。分類の一覧を公開する関数は作らない。表の網羅を確かめるテストは、テストの側に15の分類の期待の表を持つ（[境界の表](tables.md)）。
