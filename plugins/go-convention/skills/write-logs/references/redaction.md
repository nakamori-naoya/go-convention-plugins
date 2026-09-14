# 秘匿

**秘匿は 4 点で守る。属性に渡すのは primitive だけ、値オブジェクトに `String()` を書かない、JSON handler を使う、`ReplaceAttr` でキーを伏せる。** 前の 3 つが本線で、4 つ目は安全網である。安全網があるから渡してよい、にはならない。

| # | 規則 | 守るもの |
|---|---|---|
| 1 | 属性に渡すのは primitive だけ。値オブジェクトは取り出してから | 何を出すかを書いた場所で決める |
| 2 | 値オブジェクトに `String()` を書かない | `%v` / `fmt.Errorf` / Text handler 経由で中身が漏れる経路を塞ぐ |
| 3 | JSON handler を使う | 非公開フィールドを出さない |
| 4 | `HandlerOptions.ReplaceAttr` でキー一致の値を `[REDACTED]` にする | 1〜3 を破ったときの安全網 |

## 1. 属性に渡すのは primitive だけ

`slog.Any("reservation", r)` のように構造体や値オブジェクトを丸ごと渡さない。出したい値を getter で取り出し、`slog.String` / `slog.Int` で渡す。

```go
// しない: 集約ごと渡す。何が出るかは handler の実装次第になる
logger.InfoContext(ctx, "予約を確定した", slog.Any("reservation", res.Next))

// する: 出す値を選んで primitive で渡す
logger.InfoContext(ctx, "予約を確定した",
	slog.String("reservation_id", res.Next.ID().Value()),
	slog.Int("version", res.Next.Version().Value()),
)
```

getter の名前はドメインの規約に従う（`Value()` 等）。**getter が無い値は出さない値**である。ログのために getter を足したくなったら、それは運用に要る値かを問い、要るならドメインの規約へ返す。

出してよい値は業務 ID（`reservation_id` / `customer_id` / `room_code`）、件数、時刻、`connect.Code`。出さない値はメール・電話・氏名・トークン・認証ヘッダ・接続文字列。迷ったら「問い合わせ対応で他人に見せて困るか」で決め、困るなら業務 ID で追跡する。

## 2. 値オブジェクトに `String()` を書かない

`String()` があると、`fmt.Sprintf("%v", v)`、`fmt.Errorf("... %v", v)`、Text handler の `%+v`、`slog.Any` のすべてで中身が文字列になって出る。書いた人が意図しない場所で漏れる。値オブジェクトは中身を getter でだけ出し、`fmt.Stringer` にしない。

同じ理由で、ドメインに `slog.LogValuer` を実装しない。

| 実装したくなる理由 | しない理由 |
|---|---|
| `slog.Any("customer", c)` と書きたい | ドメイン package が `log/slog` を import することになる（[boundaries.md](boundaries.md) §2）。ログの都合でドメインが変わる |
| `LogValue` で中身を返せば楽 | 規則 1 を型ごとに黙って迂回する。「何を出すか」が書いた行から見えなくなる |
| `LogValue` で伏せた値を返せば安全 | 追跡に要る業務 ID まで伏せる。出す・出さないの判断は境界の 1 行が持つべきで、型に固定しない |

## 3. JSON handler を使う

`slog.NewJSONHandler` を使う。`slog.NewTextHandler` は `slog.Any` に渡した値を `%+v` で整形するので、非公開フィールドの中身が出る。JSON handler は `encoding/json` で整形するので、非公開フィールドは出ない。

```go
type CustomerID struct{ v string }

logger.InfoContext(ctx, "x", slog.Any("customer", CustomerID{v: "c-42"}))
// Text handler: customer="{v:c-42}"   ← 中身が出る
// JSON handler: "customer":{}          ← 出ない
```

規則 1 を守っていれば handler の違いは効かない。それでも JSON を使うのは、破ったときの被害を「出ない」側に倒すためである。テストで `slog.NewTextHandler(t.Output(), nil)` を使うのは、テストの出力が本番ログではないからである。

## 4. `ReplaceAttr` の安全網

`applog.New`（[middleware.md](middleware.md) §1）は `HandlerOptions.ReplaceAttr` に `redact` を渡す。キーが秘匿集合に一致したら値を `[REDACTED]` にする。`ReplaceAttr` はグループの中の属性にも 1 つずつ呼ばれるので、グループを特別扱いしない。

```go
package applog

import (
	"log/slog"
	"strings"
)

// secretKeys は値ごと伏せるキー。新しい秘匿キーはここに足す。
var secretKeys = map[string]struct{}{
	"email":         {},
	"phone":         {},
	"token":         {},
	"authorization": {},
	"password":      {},
	"secret":        {},
}

func redact(_ []string, a slog.Attr) slog.Attr {
	if _, ok := secretKeys[strings.ToLower(a.Key)]; ok {
		return slog.String(a.Key, "[REDACTED]")
	}
	return a
}
```

| 規則 | 理由 |
|---|---|
| キー一致で値ごと伏せる。値の中身を走査しない | 中身の走査（メールらしき文字列の検出）は誤検知と見逃しの両方を生む。出す値を選ぶ規則 1 が本線 |
| `msg` は伏せない | `msg` に値を入れない規則（[severity-and-attributes.md](severity-and-attributes.md) §3）があるので、`msg` に秘匿値は来ない |
| `err` は伏せない | エラー文言は「何が拒まれたか」であり、値を含めない。エラーの規約が守る |
| 秘匿キーの追加は表とテストを同時に | `secretKeys` に足したら、そのキーが `[REDACTED]` になるテストを 1 ケース足す |

安全網が働いた行（`[REDACTED]` が出た行）は、規則 1〜3 のどれかが破られた印である。見つけたら書いた側を直す。
