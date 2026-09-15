# Query実装とは何か

**Query実装は、ユースケース側が所有する読み取りポートを、DB行から同じ側が所有する読み取りモデルを組み立てることで実装する。** 一覧、件数、検索、ページング、ソート、フィルタ、JOIN、関係集計をSQLで行う。集約・エンティティを復元または操作せず、書き込まず、トランザクションを開始しない。

## 1. 責務

| する | しない |
|---|---|
| SELECTで必要な行・関係集計を得る | INSERT、UPDATE、DELETE、行ロック |
| DB行を確定済みの読み取りモデルへ写す | 実装側に公開契約型を再定義する |
| ctxに既存txがあれば乗り、無ければpoolで読む | Begin、Commit、Rollback |
| SQLで適切に表せるJOIN、件数、並び順、絞り込み | Goで再ソート、再集計、結果集合の突き合わせ |
| SQLに適さない業務計算で値オブジェクトまたは純関数を再利用する | 集約・エンティティの復元、操作、状態遷移 |

値オブジェクトや純関数の再利用と、集約の利用を混同しない。たとえば金額丸めや営業時間の計算が業務の同じ定義を必要としSQLに適さない場合、Query実装はドメインの値オブジェクトまたは純関数をimportしてよい。関係集合の件数、合計、最大、最小、JOIN、フィルタはSQLで行う。計算済み列を保存するのは別の要求と整合性根拠がある場合だけであり、値オブジェクトを避ける目的で非正規化しない。

## 2. 契約の所有と依存方向

```text
外部境界 ──> usecase/query（ポート、読み取りモデル、Page、sentinel）
                         ^
                         |
Query実装 ───────────────┘
   ├──> DB生成型
   ├──> DB接続・tx参照
   └──> 値オブジェクト／純関数（必要な計算だけ）
```

`usecase/query`は`RoomAvailability`、`ActiveSlot`、`ReservationSummary`、`ReservationHistory`、`HistoryEvent`、`Page`、ページ上限、読み取りsentinel、各読み取りポートを所有する。Query実装はこれらを定義しない。`querycontract "example.com/roomflow/reservation/usecase/query"`をimportし、引数・返り値・sentinelを`querycontract`経由で使う。

## 3. 接続

```go
package query

func queries(ctx context.Context, pool *pgxpool.Pool) *sqlcgen.Queries {
	if current, ok := tx.From(ctx); ok {
		return sqlcgen.New(current)
	}
	return sqlcgen.New(pool)
}
```

Query実装はtxを開始しない。commandの同一tx内で材料を読む場合だけctx上のtxへ乗り、通常のQueryユースケースからはpoolで読む。

## 4. SQL

SQLはSELECTだけとし、列を明示する。`WHERE`、JOIN、`ORDER BY`、`LIMIT`、`OFFSET`、`count(*)`など関係集合で完結する処理をSQLに置く。1件は`:one`、複数件は`:many`とする。親子一覧では親へページングしてから子をJOINする。

半開区間の重なりは関係条件なのでSQLに置く。

```sql
WHERE room_code = $1
  AND starts_at < $3
  AND ends_at > $2
ORDER BY starts_at, reservation_id
```

SQLに不向きな業務計算は、DB行をprimitiveへ写した後、既存の値オブジェクトまたは純関数を呼ぶ。集約やエンティティを復元しない。

## 5. 実装の形

```go
package query

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	querycontract "example.com/roomflow/reservation/usecase/query"
	"example.com/roomflow/rdb/sqlcgen"
)

type RoomAvailabilityQuery struct{ pool *pgxpool.Pool }

func (q *RoomAvailabilityQuery) ListForDay(ctx context.Context, room string, day time.Time) (querycontract.RoomAvailability, error) {
	dayStart, err := utcDate(day)
	if err != nil {
		return querycontract.RoomAvailability{}, fmt.Errorf("会議室 %s の空き状況: %w", room, err)
	}
	rows, err := queries(ctx, q.pool).ListRoomSlotsForDay(ctx, sqlcgen.ListRoomSlotsForDayParams{RoomCode: room, DayStart: dayStart, DayEnd: dayStart.AddDate(0, 0, 1)})
	if err != nil {
		return querycontract.RoomAvailability{}, fmt.Errorf("会議室 %s の空き状況: %w", room, err)
	}
	return listRoomSlotsForDayRowsToRoomAvailability(room, rows), nil
}

func utcDate(day time.Time) (time.Time, error) {
	u := day.UTC()
	d := time.Date(u.Year(), u.Month(), u.Day(), 0, 0, 0, 0, time.UTC)
	if !u.Equal(d) {
		return time.Time{}, querycontract.ErrDayHasClock
	}
	return d, nil
}
```

`:one`の対象なしは実装側のerrorへ置き換えず、契約のsentinelへ翻訳する。

```go
if errors.Is(err, pgx.ErrNoRows) {
	return querycontract.ReservationSummary{}, fmt.Errorf("予約 %s の概要: %w", id, querycontract.ErrNotFound)
}
```

## 6. ページングと履歴

`Page`、上限、範囲外sentinel、履歴の読み取りモデルも`usecase/query`が所有する。Query実装は検査関数をprivateに持ち、契約の値とerrorを使う。

```go
func validatePage(page querycontract.Page) error {
	if page.Limit < 1 || page.Limit > querycontract.MaxPageLimit {
		return querycontract.ErrPageLimitOutOfRange
	}
	if page.Offset < 0 {
		return querycontract.ErrPageOffsetNegative
	}
	return nil
}

func (q *ReservationHistoryQuery) ListByCustomer(ctx context.Context, customer string, page querycontract.Page) ([]querycontract.ReservationHistory, error) {
	if err := validatePage(page); err != nil {
		return nil, fmt.Errorf("顧客 %s の予約履歴: %w", customer, err)
	}
	rows, err := queries(ctx, q.pool).ListCustomerHistory(ctx, sqlcgen.ListCustomerHistoryParams{CustomerCode: customer, Limit: int32(page.Limit), Offset: int32(page.Offset)})
	if err != nil {
		return nil, fmt.Errorf("顧客 %s の予約履歴: %w", customer, err)
	}
	return listCustomerHistoryRowsToReservationHistories(rows), nil
}
```

行変換も契約型を返す。

```go
func listActiveOverlappingClaimsRowsToActiveSlots(rows []sqlcgen.ListActiveOverlappingClaimsRow) []querycontract.ActiveSlot {
	var slots []querycontract.ActiveSlot
	for _, row := range rows {
		slots = append(slots, querycontract.ActiveSlot{ReservationID: row.ReservationID, StartsAt: row.StartsAt.UTC(), EndsAt: row.EndsAt.UTC()})
	}
	return slots
}

func listCustomerHistoryRowToHistoryEvent(row sqlcgen.ListCustomerHistoryRow) querycontract.HistoryEvent {
	return querycontract.HistoryEvent{Version: int(row.Version), EventType: row.EventType, ActorCode: row.ActorCode, OccurredAt: row.OccurredAt.UTC()}
}
```

## 7. エラー

読み取りに固有の公開sentinelは`usecase/query`の契約である。Query実装は新しい公開errorを定義しない。接続断やSQL失敗は分類せず文脈を一度足す。DB制約違反は読み取りでは起こらない。

## 8. commandやworkerの材料

commandが集約へ渡す材料やworkerが処理対象を選ぶ材料も同じポート契約を使う。重複枠は`[]querycontract.ActiveSlot`、無断不利用時刻は`[]time.Time`、期限到来IDは`[]string`を返す。Query実装は材料を選択して写すだけで、資格、期限到来後の状態遷移、重なりの最終判断を行わない。

## 停止

- 読み取りポート、読み取りモデル、Page、必要なsentinelが`usecase/query`に確定していない
- 必要な値を保存列、SQLの関係計算、確認済みのドメイン値オブジェクトまたは純関数のどれからも導けず、新しい業務規則を発明しなければならない
- 集約・エンティティの復元や操作が必要とされる
- 業務計算を再利用できる値オブジェクトまたは純関数がなく、新しい業務規則を発明する必要がある
