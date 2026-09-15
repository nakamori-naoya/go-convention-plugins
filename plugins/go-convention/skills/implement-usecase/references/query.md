# Query の形

**Query のユースケースは、自分が所有する読み取りポートと読み取りモデルを通じて問いを実行する。Query 実装がその契約へ依存する。集約を復元せず、集約リポジトリを呼ばず、書かず、トランザクションを開始しない。**

## 読み取りポートと読み取りモデル

読み取りポートは使う側の package に置く。返り値も同じ側が所有する、primitive だけの平坦な読み取りモデルにする。Query 実装側の型を返り値にすると依存方向が外向きになるため禁止する。

```go
package query

import (
	"context"
	"errors"
	"time"
)

const MaxPageLimit = 100

const (
	StatusTentative = "tentative"
	StatusConfirmed = "confirmed"
)

var (
	ErrNotFound            = errors.New("読み取り対象が見つからない")
	ErrDayHasClock         = errors.New("時刻を含む日付では読み取れない")
	ErrPageLimitOutOfRange = errors.New("取得件数が範囲にない")
	ErrPageOffsetNegative  = errors.New("取得開始位置が負")
)

type Page struct { Limit, Offset int }

type AvailableSlot struct {
	ReservationID string
	StartsAt, EndsAt time.Time
	Status string
	HoldExpiresAt time.Time
	HasHoldExpiresAt bool
}
type RoomAvailability struct {
	RoomCode string
	Slots    []AvailableSlot
}
type ActiveSlot struct { ReservationID string; StartsAt, EndsAt time.Time }
type WaitingEntry struct { WaitlistID string }
type ReservationSummary struct { ReservationID, RoomCode, Status string; StartsAt, EndsAt time.Time }
type HistoryEvent struct { Version int; EventType, ActorCode string; OccurredAt time.Time }
type ReservationHistory struct {
	ReservationID, RoomCode, Status string
	StartsAt, EndsAt time.Time
	Events []HistoryEvent
}
type RoomAvailabilityReader interface {
	ListForDay(ctx context.Context, room string, day time.Time) (RoomAvailability, error)
}
type ActiveReservationReader interface {
	ListActiveOverlapping(context.Context, string, time.Time, time.Time) ([]ActiveSlot, error)
}
type ReservationHistoryReader interface {
	ListByCustomer(context.Context, string, Page) ([]ReservationHistory, error)
	CountByCustomer(context.Context, string) (int, error)
}
```

| 項目 | 規則 |
|---|---|
| 所有者 | 読み取りポートと読み取りモデルはユースケース側 |
| 依存 | Query 実装がユースケース側の契約 package を import する |
| 引数 | `string`、`time.Time` など解決済みの値。VO を渡さない |
| 返り値 | primitive だけの読み取りモデル。集約・VO・DB行・protoを返さない |
| tx | Query ユースケースは開始しない。実装は ctx に既存 tx があれば乗る |

入力の解決と読むソースの選択はユースケースが行う。SQL、並び順、集計、ページングは読み取りポートの実装が行う。エラーを見て別ソースへ倒すフォールバック、既定値への丸め、Go側での再ソートは行わない。

command が集約へ渡す材料を読む場合も契約の所有者と依存方向は同じである。違いは command のトランザクション内で呼ばれ、Query 実装が ctx 上の同じ tx に乗る点だけである。

## 停止

- 読み取りポートまたは読み取りモデルが確定していない
- Query 実装側の型をユースケースが import する構成を求められた
- 集約の復元、書き込み、業務判断を Query に求められた
