# 要求・応答と usecase の入出力の変換

**変換は handler package の純粋関数 `{元}To{先}` で、proto の型と usecase の型だけを扱う。** proto の型を usecase やドメインへ持ち込まず、ドメインの型を proto へ直に写さない。欠けた要素は既定値に丸めず、`InvalidArgument` になる sentinel で止める。

## 1. 置き場と命名

| 規則 | 内容 | 理由 |
|---|---|---|
| 置き場 | handler package の `reservation_mapping.go`。`dto/` や `shared/` の package を切らない | 変換は proto と usecase の両方を知る唯一の場所で、それが handler。別 package にすると proto の型が handler の外へ出る |
| 命名 | `{元}To{先}`。要求 → 入力は `confirmRequestToInput`、出力 → 応答は `holdOutputToResponse`、DTO → proto は `roomAvailabilityToProto` | 名前で向きが分かる。`to*` / `from*` の混在を作らない |
| 純粋 | 引数から返り値を作るだけ。ctx・時計・ID 生成・リポジトリを持たない。操作の時刻は server が `Clock` から読んで引数で渡す | テストが値の突き合わせだけで書ける。ID は usecase が用意し、時刻は server が 1 回決めて渡す |
| 返り値 | 欠けを検出する関数は `(T, error)`。検出しない関数は `T` だけ | 欠けが無い変換に error を付けると、呼ぶ側に空の `if err != nil` が並ぶ |
| 非公開 | 変換関数は非公開。公開するのは `ReservationServer` と interceptor だけ | 変換は handler の内側の都合で、外から呼ぶ理由が無い |

## 2. 要求 → usecase の入力

`handler/reservation_mapping.go`:

```go
package handler

import (
	"time"

	"google.golang.org/protobuf/types/known/timestamppb"

	"example.com/roomflow/gen/roomflowv1"
	"example.com/roomflow/usecase"
)

// confirmRequestToInput は ConfirmReservation の要求を usecase の入力へ写す。
// 予約番号は文字列のまま渡す（値オブジェクト化は usecase）。呼び手は ctx の主体、時刻はサーバーの Clock で、どちらも要求の本文から取らない。
// 欠けを検出する要素が無いので error を返さない。
func confirmRequestToInput(msg *roomflowv1.ConfirmReservationRequest, caller string, at time.Time) usecase.ConfirmReservationInput {
	return usecase.ConfirmReservationInput{
		ReservationID: msg.GetReservationId(),
		CustomerID:    caller,
		At:            at,
	}
}

// holdRequestToInput は HoldReservation の要求を usecase の入力へ写す。
// 利用開始が利用終了より前かは確かめない。それは利用枠の生成の条件で、usecase が呼ぶ NewTimeSlot が拒む。
func holdRequestToInput(msg *roomflowv1.HoldReservationRequest, caller string, at time.Time) (usecase.HoldReservationInput, error) {
	startsAt, err := requiredTime(msg.GetStartsAt(), ErrStartsAtRequired)
	if err != nil {
		return usecase.HoldReservationInput{}, err
	}
	endsAt, err := requiredTime(msg.GetEndsAt(), ErrEndsAtRequired)
	if err != nil {
		return usecase.HoldReservationInput{}, err
	}
	return usecase.HoldReservationInput{
		CustomerID: caller,
		RoomCode:   msg.GetRoomCode(),
		StartsAt:   startsAt,
		EndsAt:     endsAt,
		At:         at,
	}, nil
}

// requiredTime は必須の Timestamp を time.Time（UTC）へ写す。
// nil の AsTime() は 1970-01-01 を返すので、nil を既定へ倒さずここで止める。IsValid は nil と範囲外の両方を偽にする。
func requiredTime(ts *timestamppb.Timestamp, missing error) (time.Time, error) {
	if !ts.IsValid() {
		return time.Time{}, missing
	}
	return ts.AsTime(), nil
}
```

`handler/errors.go`:

```go
package handler

import "errors"

// handler の sentinel。要求に欠けがあるとき返す。翻訳表で InvalidArgument になる（error_table.go）。
// 公開にする。入口のテストが errors.Is で突き合わせ、エラーの規約の対応表が名前で参照するため。
// 文言は利用者に見せる（連鎖の文脈は見せない）ので、何が欠けたかを日本語で書く。
var (
	ErrStartsAtRequired = errors.New("利用開始の無い仮押さえ要求は受け付けない")
	ErrEndsAtRequired   = errors.New("利用終了の無い仮押さえ要求は受け付けない")
)

// 組み立ての誤り。翻訳表に載せず Internal にする。
var errNoCaller = errors.New("呼び手の主体が ctx に無い")

// errInternal は翻訳表に無い error に返す唯一の公開文言。
var errInternal = errors.New("内部エラーが発生した")
```

usecase の入力型は usecase の規約が定める。題材では次の形を前提にする（`ConfirmReservationInput` / `HoldReservationInput` / `HoldReservationOutput` はいずれも usecase の規約が定める実名）:

```go
package usecase

import "time"

type ConfirmReservationInput struct {
	ReservationID string
	CustomerID    string
	At            time.Time
}

type HoldReservationInput struct {
	CustomerID string
	RoomCode   string
	StartsAt   time.Time
	EndsAt     time.Time
	At         time.Time
}

type HoldReservationOutput struct {
	ReservationID string
	ExpiresAt     time.Time
}
```

| 要素 | 写し方 | 理由 |
|---|---|---|
| 文字列の ID（`reservation_id` / `room_code`） | `GetReservationId()` をそのまま `string` のフィールドへ | 値オブジェクトの生成の条件（空を拒む）は usecase が `NewID` で確かめ、sentinel が翻訳表で `InvalidArgument` になる。handler で作ると生成の条件が 2 か所で走る |
| 呼び手（`CustomerID`） | `callerFrom(ctx)` の値を引数で受けて載せる | 要求の本文の `customer_id` を信じると、他人の ID で操作できる。主体は認証だけが決める |
| 必須の時刻（`Timestamp`。利用開始・利用終了） | `IsValid()` で確かめ、`AsTime()`（UTC を返す） | nil の `AsTime()` は `time.Unix(0, 0)`。丸めると「1970 年から始まる利用枠」が通る |
| 操作の時刻（`At`） | server が `Clock.Now()` で 1 回決め、変換関数の引数で受けて載せる。要求に `confirmed_at` のような時刻を持たせない | 期限が到来したかの判定に使う時刻をクライアントの申告で決めさせない。`Clock` を server が持てば、テストは固定時計で期限の前後を表に書ける |
| 任意の時刻 | 題材に無い。要るなら `(time.Time, bool)` を返す関数を別に書く | 「nil ならゼロ値」を必須の関数に混ぜると、必須の欠けが通る |
| 列挙（`enum`） | 題材に無い。要るなら `_UNSPECIFIED` と未知の値を欠けの sentinel で止める | proto3 の列挙は未指定が 0 で、既定の意味を持つ値と区別がつかない。丸めると未指定が「最初の選択肢」になる |
| 整数の版・件数 | `int32` → `int` は `int(v)` で写す。`int` → `int32` は範囲を確かめる | 応答側で `int32(v)` に切り詰めると、大きい値が黙って別の値になる |

要求の中身の妥当性（利用開始が利用終了より前か、期限が到来していないか）は確かめない。それは値オブジェクトと集約が拒み、翻訳表が Code にする。handler が確かめると、同じ規則が 2 か所に書かれ、片方だけ直る。

## 3. usecase の出力 → 応答

```go
package handler

import (
	"google.golang.org/protobuf/types/known/timestamppb"

	"example.com/roomflow/gen/roomflowv1"
	"example.com/roomflow/usecase"
)

// holdOutputToResponse は HoldReservation の出力を応答へ写す。出力は primitive の struct なので、欠けは無く error を返さない。
func holdOutputToResponse(out usecase.HoldReservationOutput) *roomflowv1.HoldReservationResponse {
	return &roomflowv1.HoldReservationResponse{
		ReservationId: out.ReservationID,
		ExpiresAt:     timestamppb.New(out.ExpiresAt),
	}
}
```

読み取り RPC の応答はユースケース側が所有する読み取りモデルから写す。読み取りモデルは primitive だけを持つので、同じ形になる（`RoomAvailability{RoomCode string; Slots []AvailableSlot}` を `roomAvailabilityToProto(a query.RoomAvailability) *roomflowv1.RoomAvailability` で。スライスは `make([]*T, 0, len(...))` で長さを決めて `append`）。

| 規則 | 理由 |
|---|---|
| 応答に写すのは usecase の出力型またはusecaseが所有する読み取りモデル。集約・値オブジェクトを引数に取る変換関数を書かない | proto の型と ドメインの型を同じ関数に置くと、handler がドメインの getter を知り、ドメインの変更が handler に波及する |
| 時刻は `timestamppb.New(t)`。`t` は UTC のまま渡す | `timestamppb` は時刻の絶対値を持つ。地域の時刻に直すのは表示側 |
| 空のスライスは `nil` でなく長さ 0 で作る | proto の `repeated` は nil と空を区別しないが、Go 側の等値比較（テスト）で差が出る |
| 応答が空の RPC（`ConfirmReservation`）は `&roomflowv1.ConfirmReservationResponse{}` を直接書く | 空を返す変換関数を置く理由が無い |

## 4. 禁止

| 書かない | 代わりに |
|---|---|
| `usecase.ConfirmReservationInput{ReservationID: id}` の `id` を `reservation.NewID(...)` で作ってから渡す | 文字列のまま渡す。値オブジェクト化は usecase |
| `msg.GetStartsAt().AsTime()` を `IsValid` 無しで呼ぶ | `requiredTime` を通す |
| 要求に `confirmed_at` を持たせ、`if msg.GetConfirmedAt() == nil { at = time.Now() }` で補う | 操作の時刻は要求に持たせない。server の `Clock` が決め、変換関数は引数で受ける |
| 変換関数の中で `time.Now()` を呼ぶ | 時刻は引数。関数を純粋に保つ |
| usecase の入力に `*roomflowv1.ConfirmReservationRequest` を持たせる | primitive の struct に写す。usecase が proto を import しない |
| `reservationToProto(r reservation.Reservation)` | usecase が出力型へ写し、handler は出力型から proto へ写す |
