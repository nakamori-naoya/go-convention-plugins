# query service のテスト

**query service のテストは、Before を投入し、読み取りメソッドを呼び、返った DTO を `assert.Equal` で突き合わせる。** 書き込みが無いので、全テーブルの突き合わせは要らない。実 DB は同じ dockertest で、package `query` に `main_test.go` を置く（[dockertest-and-testmain.md](dockertest-and-testmain.md)）。

これは、**リポジトリのテストではない**（集約を復元しない。`FindByID` の代わりに query service を使わない）。**usecase のテストでもない**（ページングの既定値や入力の解決は usecase の関心。query service には解決済みの値を渡す）。

## 1. する／しない

| する | しない |
|---|---|
| フィルタ: 条件に合う行だけが返り、合わない行（別の会議室・別の日）が混ざらない | 全テーブルの突き合わせ（書き込みが無い） |
| ページング: `limit` / `cursor`（または `offset`）で件数と続きが正しい。最後のページと、次が無いことの表現 | ドメインの規則（有効な予約とは何か、を query service が判断していないか、はコードレビューで見る） |
| NULL: NULL になりうる列（NULL 許可列と、LEFT JOIN で NULL になる列）が DTO の値と有無の対（`{X} T` + `Has{X} bool`）に写るか。NULL の行と値がある行を同じケースに並べる | SQL の文言、JOIN の形 |
| 空: 該当する行が無いとき、DTO の一覧が nil（または空）で、error にならない | 集約の復元、`Restore*` の呼び出し |
| 並び順: DTO の一覧が宣言された順（利用開始順）で返る | 書き込みメソッドの追加（query service に書き込みは無い） |

フィルタ・ページング・NULL・空のうち対象メソッドに実在する分岐を列挙し、入力と返る DTO の違いを観測できるケースへ割り振る。1 ケースで複数観点を区別できるなら兼ねる。観点が対象に無ければ書かない（`ListForDay` にページングは無い）。題材の表に NULL 許可列は無いが、`ListForDay` は `tentative_hold_deadlines` を LEFT JOIN するので `expires_at` が NULL になる。NULL 観点はここで持つ。

## 2. 形

| 区分 | フィールド | 内容 |
|---|---|---|
| 識別 | `id` / `name` / `description` | 資料に読み取りの BDD があればその ID。無ければ生成した id |
| Given | `seed{Table}` | 読み取り元のテーブルと、FK で要る親のテーブルだけ。全テーブルは要らない |
| When | 対象メソッドの引数名そのまま（`room` / `day`） | `context.Context` はフィールドにしない |
| Then | `want {DTO}` / `wantErr error` | DTO をそのまま。`Slots` が空なら書かない（nil） |

ループ本体は `Reset` → `Seed` → `q.ListForDay(ctx, tt.room, tt.day)` → `require.NoError` → `assert.Equal(t, tt.want, got)`。error を期待するケースは `require.ErrorIs` の後に `assert.Zero(t, got)` で結果がゼロ値であることも見る。

DTO の中の `time.Time` は query service が UTC で返す（読み取りモデルの規約）。表の `want` も UTC で書く。

## 3. 例 `query/room_availability_query_test.go`

DTO は `query.RoomAvailability{RoomCode string; Slots []query.AvailableSlot}`、`AvailableSlot` は「その日その会議室で占有されている枠」で、`ReservationID` / `StartsAt` / `EndsAt` / `Status`（`query.StatusTentative` か `query.StatusConfirmed`）と、仮押さえのときだけある期限の対 `HoldExpiresAt time.Time` + `HasHoldExpiresAt bool` を持つ。`NewRoomAvailabilityQuery(pool)` は `*pgxpool.Pool` を直接受け、tx を張らない。`main_test.go` は `rdb` と同じ内容。

```go
package query_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	queryimpl "example.com/roomflow/reservation/query"
	query "example.com/roomflow/reservation/usecase/query"
	"example.com/roomflow/rdb/rdbtest"
	"example.com/roomflow/rdb/sqlcgen"
)

func TestRoomAvailabilityQuery_ListForDay(t *testing.T) {
	day := time.Date(2026, 9, 18, 0, 0, 0, 0, time.UTC)
	heldAt := time.Date(2026, 9, 1, 9, 0, 0, 0, time.UTC)
	expiresAt := heldAt.Add(15 * time.Minute)
	confirmedAt := time.Date(2026, 9, 1, 9, 5, 0, 0, time.UTC)
	// 資料の時刻。表の中で何度も書くので、表の直前で値にする（関数は置かない）。
	at1000 := day.Add(10 * time.Hour)
	at1100 := day.Add(11 * time.Hour)
	at1130 := day.Add(11*time.Hour + 30*time.Minute)
	at1300 := day.Add(13 * time.Hour)
	at1400 := day.Add(14 * time.Hour)
	nextDay1000 := at1000.AddDate(0, 0, 1)
	nextDay1100 := at1100.AddDate(0, 0, 1)

	tests := []struct {
		id                         string
		name                       string
		description                string
		seedReservations           []sqlcgen.Reservation           // Given: 占有の親行（FK）。読み取り元ではない
		seedRoomBookingClaims      []sqlcgen.RoomBookingClaim      // Given: 読み取り元
		seedTentativeHoldDeadlines []sqlcgen.TentativeHoldDeadline // Given: LEFT JOIN 先。仮押さえの枠だけが持つ
		room                       string                          // When:  対象メソッドの引数名そのまま
		day                        time.Time                       // When
		want                       query.RoomAvailability          // Then:  DTO をそのまま
		wantErr                    error                           // Then:  nil なら成功を期待
	}{
		{
			id:   "a71e02",
			name: "その日の会議室の占有を利用開始順に返す",
			description: `Given: 会議室M-301の2026年9月18日に 13:00から14:00 と 10:00から11:30 の確定予約の占有がある
  And: 会議室M-302の同じ日と、会議室M-301の翌日にも占有がある
When: 会議室M-301の2026年9月18日の空き状況を一覧する
Then: M-301の当日の2件だけが利用開始順に返る`,
			seedReservations: []sqlcgen.Reservation{
				{ReservationID: "R-20260901-0101", RoomCode: "M-301", CustomerCode: "C-4102", StartsAt: at1000, EndsAt: at1130, Status: "confirmed", CurrentVersion: 2, CreatedAt: heldAt, UpdatedAt: confirmedAt},
				{ReservationID: "R-20260901-0102", RoomCode: "M-301", CustomerCode: "C-5821", StartsAt: at1300, EndsAt: at1400, Status: "confirmed", CurrentVersion: 2, CreatedAt: heldAt, UpdatedAt: confirmedAt},
				{ReservationID: "R-20260901-0103", RoomCode: "M-302", CustomerCode: "C-4102", StartsAt: at1000, EndsAt: at1100, Status: "confirmed", CurrentVersion: 2, CreatedAt: heldAt, UpdatedAt: confirmedAt},
				{ReservationID: "R-20260901-0104", RoomCode: "M-301", CustomerCode: "C-4102", StartsAt: nextDay1000, EndsAt: nextDay1100, Status: "confirmed", CurrentVersion: 2, CreatedAt: heldAt, UpdatedAt: confirmedAt},
			},
			seedRoomBookingClaims: []sqlcgen.RoomBookingClaim{
				{ReservationID: "R-20260901-0101", RoomCode: "M-301", StartsAt: at1000, EndsAt: at1130, CreatedAt: heldAt},
				{ReservationID: "R-20260901-0102", RoomCode: "M-301", StartsAt: at1300, EndsAt: at1400, CreatedAt: heldAt},
				{ReservationID: "R-20260901-0103", RoomCode: "M-302", StartsAt: at1000, EndsAt: at1100, CreatedAt: heldAt},
				{ReservationID: "R-20260901-0104", RoomCode: "M-301", StartsAt: nextDay1000, EndsAt: nextDay1100, CreatedAt: heldAt},
			},
			room: "M-301",
			day:  day,
			want: query.RoomAvailability{
				RoomCode: "M-301",
				Slots: []query.AvailableSlot{
					{ReservationID: "R-20260901-0101", StartsAt: at1000, EndsAt: at1130, Status: query.StatusConfirmed},
					{ReservationID: "R-20260901-0102", StartsAt: at1300, EndsAt: at1400, Status: query.StatusConfirmed},
				},
			},
		},
		{
			id:   "e5c1b7",
			name: "仮押さえの占有だけが仮押さえ期限を持つ",
			description: `Given: 会議室M-301の2026年9月18日に 10:00から11:30 の確定予約の占有がある
  And: 同じ日に 13:00から14:00 の仮押さえ予約の占有があり、仮押さえ期限は2026年9月1日 09:15である
When: 会議室M-301の2026年9月18日の空き状況を一覧する
Then: 確定予約の占有は仮押さえ期限を持たない
  And: 仮押さえ予約の占有は仮押さえ期限 2026年9月1日 09:15 を持つ`,
			seedReservations: []sqlcgen.Reservation{
				{ReservationID: "R-20260901-0101", RoomCode: "M-301", CustomerCode: "C-4102", StartsAt: at1000, EndsAt: at1130, Status: "confirmed", CurrentVersion: 2, CreatedAt: heldAt, UpdatedAt: confirmedAt},
				{ReservationID: "R-20260901-0102", RoomCode: "M-301", CustomerCode: "C-5821", StartsAt: at1300, EndsAt: at1400, Status: "tentative", CurrentVersion: 1, CreatedAt: heldAt, UpdatedAt: heldAt},
			},
			seedRoomBookingClaims: []sqlcgen.RoomBookingClaim{
				{ReservationID: "R-20260901-0101", RoomCode: "M-301", StartsAt: at1000, EndsAt: at1130, CreatedAt: heldAt},
				{ReservationID: "R-20260901-0102", RoomCode: "M-301", StartsAt: at1300, EndsAt: at1400, CreatedAt: heldAt},
			},
			seedTentativeHoldDeadlines: []sqlcgen.TentativeHoldDeadline{
				{ReservationID: "R-20260901-0102", ExpiresAt: expiresAt, CreatedAt: heldAt},
			},
			room: "M-301",
			day:  day,
			want: query.RoomAvailability{
				RoomCode: "M-301",
				Slots: []query.AvailableSlot{
					{ReservationID: "R-20260901-0101", StartsAt: at1000, EndsAt: at1130, Status: query.StatusConfirmed},
					{ReservationID: "R-20260901-0102", StartsAt: at1300, EndsAt: at1400, Status: query.StatusTentative, HoldExpiresAt: expiresAt, HasHoldExpiresAt: true},
				},
			},
		},
		{
			id:   "3d58b9",
			name: "占有が無い日は空の一覧を返す",
			description: `Given: 会議室M-301に占有が一つも無い
When: 会議室M-301の2026年9月18日の空き状況を一覧する
Then: 会議室だけを持ち、占有が空の一覧が返る`,
			room: "M-301",
			day:  day,
			want: query.RoomAvailability{RoomCode: "M-301"},
		},
	}

	// 同じ実 DB（TestMain の pool）を全ケースが共有するため直列で走らせる（t.Parallel() を書かない）。
	for _, tt := range tests {
		t.Run(tt.id+" "+tt.name, func(t *testing.T) {
			ctx := t.Context()
			rdbtest.Reset(ctx, t, pool)
			rdbtest.SeedReservations(ctx, t, pool, tt.seedReservations)
			rdbtest.SeedRoomBookingClaims(ctx, t, pool, tt.seedRoomBookingClaims)
			rdbtest.SeedTentativeHoldDeadlines(ctx, t, pool, tt.seedTentativeHoldDeadlines)
			q := queryimpl.NewRoomAvailabilityQuery(pool)

			got, err := q.ListForDay(ctx, tt.room, tt.day)
			if tt.wantErr != nil {
				require.ErrorIs(t, err, tt.wantErr)
				assert.Zero(t, got)
				return
			}
			require.NoError(t, err)
			assert.Equal(t, tt.want, got)
		})
	}
}
```

| ケース | 観点 |
|---|---|
| `a71e02` | フィルタ（別の会議室・別の日が混ざらない）と並び順（利用開始順） |
| `e5c1b7` | NULL（LEFT JOIN で `expires_at` が NULL の行は `HasHoldExpiresAt` が偽で `HoldExpiresAt` がゼロ値、値がある行は真と値） |
| `3d58b9` | 空（`Slots` が nil で error にならない） |
