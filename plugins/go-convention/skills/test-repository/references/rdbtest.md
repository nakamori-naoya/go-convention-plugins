# rdbtest

**`rdb/rdbtest` は、永続化層のテストが実 DB を起動し、Before を投入し、After を全行読むための支援 package である。** dockertest で PostgreSQL を起動する `Start`、データモデル資料の全テーブルについてテーブルごとに型付きの `Seed{Table}` と `Read{Table}`、全テーブルを空にする `Reset`、usecase の代わりに tx を張る `Run` を持つ。テスト本文は SQL を書かず、この package の関数だけを呼ぶ。

これは、**テストデータの生成器（Builder）ではない**。Before の行は資料の表を写した値で、テストが `sqlcgen` の行型で書く。**本番コードが import する package でもない**。実 DB を使う層（`rdb` / `query` / usecase / handler）の `*_test.go` だけが import する。

## 1. 置き場と依存

| 項目 | 規則 |
|---|---|
| package | `rdb/rdbtest`（Go の慣習 `{pkg}test`）。ファイルは `start.go`（`Start` / `DB`。[dockertest-and-testmain.md](dockertest-and-testmain.md) §1）と `rdbtest.go`（`Reset` / `Run` / `Seed*` / `Read*`）の 2 つ。集約が増えてテーブルが増えたら、集約ごとに `{aggregate}.go` に分ける |
| 行型 | sqlc の生成型（`sqlcgen.Reservation` 等）をそのまま使う。独自の行型を作らない |
| query | `rdb/query/rdbtest.sql` に置き、本番と同じ `sqlc.yaml` で `rdb/sqlcgen` へ生成する。本番の query ファイル（`rdb/query/reservation.sql`）には足さない |
| 投入 | `pgx` の `CopyFrom`。SQL 文を組み立てない |
| tx | `tx.Manager` の実物を `Run` が張る |
| 依存 | `sqlcgen` / `tx` / `rdb/schema` / `pgx` / `pgxpool` / `testify` / `dockertest`（`Start` だけが使う）。`rdb`・`reservation` を import しない（ドメインの値を知らない） |

## 2. 関数

起動が 1 組と、資料の 8 テーブル分の `Seed` / `Read`。`Seed` / `Read` の引数の並びは全部 `(ctx, t, pool, ...)`。

```go
func Start(ctx context.Context) (*DB, error)
func (db *DB) Pool() *pgxpool.Pool
func (db *DB) Close(ctx context.Context) error

func Reset(ctx context.Context, t *testing.T, pool *pgxpool.Pool)
func Run(ctx context.Context, t *testing.T, pool *pgxpool.Pool, fn func(ctx context.Context) error) error

func SeedReservations(ctx context.Context, t *testing.T, pool *pgxpool.Pool, rows []sqlcgen.Reservation)
func ReadReservations(ctx context.Context, t *testing.T, pool *pgxpool.Pool) []sqlcgen.Reservation
func SeedRoomBookingClaims(ctx context.Context, t *testing.T, pool *pgxpool.Pool, rows []sqlcgen.RoomBookingClaim)
func ReadRoomBookingClaims(ctx context.Context, t *testing.T, pool *pgxpool.Pool) []sqlcgen.RoomBookingClaim
func SeedTentativeHoldDeadlines(ctx context.Context, t *testing.T, pool *pgxpool.Pool, rows []sqlcgen.TentativeHoldDeadline)
func ReadTentativeHoldDeadlines(ctx context.Context, t *testing.T, pool *pgxpool.Pool) []sqlcgen.TentativeHoldDeadline
func SeedReservationBaseEvents(ctx context.Context, t *testing.T, pool *pgxpool.Pool, rows []sqlcgen.ReservationBaseEvent)
func ReadReservationBaseEvents(ctx context.Context, t *testing.T, pool *pgxpool.Pool) []sqlcgen.ReservationBaseEvent
func SeedReservationTentativeCreatedEvents(ctx context.Context, t *testing.T, pool *pgxpool.Pool, rows []sqlcgen.ReservationTentativeCreatedEvent)
func ReadReservationTentativeCreatedEvents(ctx context.Context, t *testing.T, pool *pgxpool.Pool) []sqlcgen.ReservationTentativeCreatedEvent
func SeedReservationConfirmedEvents(ctx context.Context, t *testing.T, pool *pgxpool.Pool, rows []sqlcgen.ReservationConfirmedEvent)
func ReadReservationConfirmedEvents(ctx context.Context, t *testing.T, pool *pgxpool.Pool) []sqlcgen.ReservationConfirmedEvent
func SeedReservationCancelledEvents(ctx context.Context, t *testing.T, pool *pgxpool.Pool, rows []sqlcgen.ReservationCancelledEvent)
func ReadReservationCancelledEvents(ctx context.Context, t *testing.T, pool *pgxpool.Pool) []sqlcgen.ReservationCancelledEvent
func SeedReservationExpiredEvents(ctx context.Context, t *testing.T, pool *pgxpool.Pool, rows []sqlcgen.ReservationExpiredEvent)
func ReadReservationExpiredEvents(ctx context.Context, t *testing.T, pool *pgxpool.Pool) []sqlcgen.ReservationExpiredEvent
```

| 関数 | 規則 | 理由 |
|---|---|---|
| `Start` / `Pool` / `Close` | dockertest で PostgreSQL を起動し、スキーマを当てて `*DB` を返す。`TestMain` だけが呼ぶ | 起動の手順を 1 点に置く。実 DB を使う全 package の `TestMain` が同じ起動を使う |
| `Reset` | 資料の全テーブルを 1 文の `TRUNCATE ... RESTART IDENTITY` で空にする。各ケースの先頭で呼ぶ | ケースの独立を `Reset` だけで保証する。identity を戻すので、After のイベント表の `id` が `1, 2, ...` と決まり、表に書ける |
| `Run` | `tx.NewManager(pool).Run(ctx, fn)` を呼ぶだけ。`fn` の error をそのまま返し、`t` を失敗させない | usecase が張る tx の実物を使う。goroutine から呼ぶ（同時実行）ので `require` を中で使えない |
| `Seed{Table}` | 行型のスライスを `CopyFrom` で投入する。`rows` が空なら何もしない。identity 列を持つテーブルは `id` を明示して投入し、投入後に採番を最大の `id` の次へ進める | 資料の Before の識別子（`BE-0101-01`）が `id: 1` に写り、リポジトリが次に採番する `id` が `2` と決まる |
| `Read{Table}` | 全行を主キー順に返す。0 行なら `nil`。`timestamptz` の列は `.UTC()` を通す | `want{Table}` を書かないケースの nil スライスと一致する。pgx が返す `time.Time` は Local を持ち、`assert.Equal` は `reflect.DeepEqual` で Location まで比べるので、UTC に揃えないと同じ時刻が不一致になる |
| すべて | `t.Helper()` を呼ぶ。`Reset` / `Seed*` / `Read*` は `require` で失敗させる（main goroutine から呼ぶ） | 失敗の行がテスト本文を指す。前提の失敗で後続の検証を続けない |

リポジトリの実装が資料に無い 9 表目 `reservation_no_show_recorded_events`（無断不利用の詳細イベント表。列は `id` と `base_event_id`。資料は無断不利用を範囲外にしているので仮定）を置くなら、同じ形の `SeedReservationNoShowRecordedEvents` / `ReadReservationNoShowRecordedEvents` を足し、`TruncateReservationTables` と `Sync*Identity` にも加える。その表もテストでは「資料に登場する全テーブル」に数える。

## 3. query ファイル `rdb/query/rdbtest.sql`

```sql
-- テスト支援 package rdbtest だけが使う query。本番の query ファイルには足さない。
-- Read* は全行を主キー順に、Truncate* は全テーブルを空にして identity を 1 に戻し、
-- Sync*Identity は id を明示して投入した後に identity の採番を最大の id の次へ進める。

-- name: TruncateReservationTables :exec
TRUNCATE reservations, room_booking_claims, tentative_hold_deadlines,
    reservation_base_events, reservation_tentative_created_events,
    reservation_confirmed_events, reservation_cancelled_events, reservation_expired_events
RESTART IDENTITY;

-- name: ReadReservations :many
SELECT * FROM reservations ORDER BY reservation_id;

-- name: ReadRoomBookingClaims :many
SELECT * FROM room_booking_claims ORDER BY reservation_id;

-- name: ReadTentativeHoldDeadlines :many
SELECT * FROM tentative_hold_deadlines ORDER BY reservation_id;

-- name: ReadReservationBaseEvents :many
SELECT * FROM reservation_base_events ORDER BY id;

-- name: ReadReservationTentativeCreatedEvents :many
SELECT * FROM reservation_tentative_created_events ORDER BY id;

-- name: ReadReservationConfirmedEvents :many
SELECT * FROM reservation_confirmed_events ORDER BY id;

-- name: ReadReservationCancelledEvents :many
SELECT * FROM reservation_cancelled_events ORDER BY id;

-- name: ReadReservationExpiredEvents :many
SELECT * FROM reservation_expired_events ORDER BY id;

-- name: SyncReservationBaseEventsIdentity :exec
SELECT setval(pg_get_serial_sequence('reservation_base_events', 'id'), coalesce((SELECT max(id) FROM reservation_base_events), 0) + 1, false);

-- name: SyncReservationTentativeCreatedEventsIdentity :exec
SELECT setval(pg_get_serial_sequence('reservation_tentative_created_events', 'id'), coalesce((SELECT max(id) FROM reservation_tentative_created_events), 0) + 1, false);

-- name: SyncReservationConfirmedEventsIdentity :exec
SELECT setval(pg_get_serial_sequence('reservation_confirmed_events', 'id'), coalesce((SELECT max(id) FROM reservation_confirmed_events), 0) + 1, false);

-- name: SyncReservationCancelledEventsIdentity :exec
SELECT setval(pg_get_serial_sequence('reservation_cancelled_events', 'id'), coalesce((SELECT max(id) FROM reservation_cancelled_events), 0) + 1, false);

-- name: SyncReservationExpiredEventsIdentity :exec
SELECT setval(pg_get_serial_sequence('reservation_expired_events', 'id'), coalesce((SELECT max(id) FROM reservation_expired_events), 0) + 1, false);
```

- `Read*` は `SELECT *` で行型をそのまま受け、主キーで並べる。列を絞らない（全列を突き合わせるため）
- `Sync*Identity` は `id` を明示して投入した後に呼ぶ。`setval(..., max + 1, false)` なので、投入が 0 行でも次の採番は `1` になる
- `TRUNCATE` は 1 文で全テーブル。FK の順序を気にしない
- テストが使う query はこのファイルだけ。本番の query ファイルに `Read*` / `Truncate*` を足さない

`sqlc.yaml` は本番と同じ（`schema: rdb/schema`、`queries: rdb/query`、`sql_package: pgx/v5`、NOT NULL の `timestamptz` は `time.Time` に override）。生成物は `rdb/sqlcgen` にコミットする。

## 4. コード `rdb/rdbtest/rdbtest.go`

```go
// Package rdbtest は、永続化層のテストが実 DB の Before を投入し After を全行読むための支援 package。
// 資料「RDB論理設計 — 貸会議室の予約」の 8 テーブルを、テーブルごとの Seed / Read で扱う。起動は start.go の Start。
// テスト本文は SQL を書かず、この package の関数だけを呼ぶ。
package rdbtest

import (
	"context"
	"testing"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/stretchr/testify/require"

	"example.com/roomflow/rdb/sqlcgen"
	"example.com/roomflow/tx"
)

// Reset は資料の全テーブルを空にし、identity 列の採番を 1 に戻す。各ケースの先頭で呼ぶ。
func Reset(ctx context.Context, t *testing.T, pool *pgxpool.Pool) {
	t.Helper()
	require.NoError(t, sqlcgen.New(pool).TruncateReservationTables(ctx))
}

// Run は tx を張って fn を呼び、fn が nil を返せば commit、error を返せば rollback してその error を返す。
// usecase が張る tx の代わりで、実物の tx.Manager を使う。goroutine から呼べるよう t を失敗させない。
func Run(ctx context.Context, t *testing.T, pool *pgxpool.Pool, fn func(ctx context.Context) error) error {
	t.Helper()
	return tx.NewManager(pool).Run(ctx, fn)
}

// SeedReservations は reservations に rows を投入する。列は行型のフィールドと 1:1。
func SeedReservations(ctx context.Context, t *testing.T, pool *pgxpool.Pool, rows []sqlcgen.Reservation) {
	t.Helper()
	copyFrom(ctx, t, pool, "reservations",
		[]string{"reservation_id", "room_code", "customer_code", "starts_at", "ends_at", "status", "current_version", "created_at", "updated_at"},
		rows, func(r sqlcgen.Reservation) []any {
			return []any{r.ReservationID, r.RoomCode, r.CustomerCode, r.StartsAt, r.EndsAt, r.Status, r.CurrentVersion, r.CreatedAt, r.UpdatedAt}
		})
}

// ReadReservations は reservations の全行を主キー順に返す。0 行なら nil。時刻は UTC に揃える。
func ReadReservations(ctx context.Context, t *testing.T, pool *pgxpool.Pool) []sqlcgen.Reservation {
	t.Helper()
	rows, err := sqlcgen.New(pool).ReadReservations(ctx)
	require.NoError(t, err)
	for i := range rows {
		rows[i].StartsAt = rows[i].StartsAt.UTC()
		rows[i].EndsAt = rows[i].EndsAt.UTC()
		rows[i].CreatedAt = rows[i].CreatedAt.UTC()
		rows[i].UpdatedAt = rows[i].UpdatedAt.UTC()
	}
	return rows
}

// SeedRoomBookingClaims は room_booking_claims に rows を投入する。
func SeedRoomBookingClaims(ctx context.Context, t *testing.T, pool *pgxpool.Pool, rows []sqlcgen.RoomBookingClaim) {
	t.Helper()
	copyFrom(ctx, t, pool, "room_booking_claims",
		[]string{"reservation_id", "room_code", "starts_at", "ends_at", "created_at"},
		rows, func(r sqlcgen.RoomBookingClaim) []any {
			return []any{r.ReservationID, r.RoomCode, r.StartsAt, r.EndsAt, r.CreatedAt}
		})
}

// ReadRoomBookingClaims は room_booking_claims の全行を主キー順に返す。
func ReadRoomBookingClaims(ctx context.Context, t *testing.T, pool *pgxpool.Pool) []sqlcgen.RoomBookingClaim {
	t.Helper()
	rows, err := sqlcgen.New(pool).ReadRoomBookingClaims(ctx)
	require.NoError(t, err)
	for i := range rows {
		rows[i].StartsAt = rows[i].StartsAt.UTC()
		rows[i].EndsAt = rows[i].EndsAt.UTC()
		rows[i].CreatedAt = rows[i].CreatedAt.UTC()
	}
	return rows
}

// SeedTentativeHoldDeadlines は tentative_hold_deadlines に rows を投入する。
func SeedTentativeHoldDeadlines(ctx context.Context, t *testing.T, pool *pgxpool.Pool, rows []sqlcgen.TentativeHoldDeadline) {
	t.Helper()
	copyFrom(ctx, t, pool, "tentative_hold_deadlines",
		[]string{"reservation_id", "expires_at", "created_at"},
		rows, func(r sqlcgen.TentativeHoldDeadline) []any {
			return []any{r.ReservationID, r.ExpiresAt, r.CreatedAt}
		})
}

// ReadTentativeHoldDeadlines は tentative_hold_deadlines の全行を主キー順に返す。
func ReadTentativeHoldDeadlines(ctx context.Context, t *testing.T, pool *pgxpool.Pool) []sqlcgen.TentativeHoldDeadline {
	t.Helper()
	rows, err := sqlcgen.New(pool).ReadTentativeHoldDeadlines(ctx)
	require.NoError(t, err)
	for i := range rows {
		rows[i].ExpiresAt = rows[i].ExpiresAt.UTC()
		rows[i].CreatedAt = rows[i].CreatedAt.UTC()
	}
	return rows
}

// SeedReservationBaseEvents は reservation_base_events に rows を投入する。
// id を明示して投入するので、投入後に identity の採番を最大の id の次へ進める。
func SeedReservationBaseEvents(ctx context.Context, t *testing.T, pool *pgxpool.Pool, rows []sqlcgen.ReservationBaseEvent) {
	t.Helper()
	copyFrom(ctx, t, pool, "reservation_base_events",
		[]string{"id", "reservation_id", "event_type", "version", "actor_code", "occurred_at"},
		rows, func(r sqlcgen.ReservationBaseEvent) []any {
			return []any{r.ID, r.ReservationID, r.EventType, r.Version, r.ActorCode, r.OccurredAt}
		})
	require.NoError(t, sqlcgen.New(pool).SyncReservationBaseEventsIdentity(ctx))
}

// ReadReservationBaseEvents は reservation_base_events の全行を主キー順に返す。
func ReadReservationBaseEvents(ctx context.Context, t *testing.T, pool *pgxpool.Pool) []sqlcgen.ReservationBaseEvent {
	t.Helper()
	rows, err := sqlcgen.New(pool).ReadReservationBaseEvents(ctx)
	require.NoError(t, err)
	for i := range rows {
		rows[i].OccurredAt = rows[i].OccurredAt.UTC()
	}
	return rows
}

// SeedReservationTentativeCreatedEvents は reservation_tentative_created_events に rows を投入する。
func SeedReservationTentativeCreatedEvents(ctx context.Context, t *testing.T, pool *pgxpool.Pool, rows []sqlcgen.ReservationTentativeCreatedEvent) {
	t.Helper()
	copyFrom(ctx, t, pool, "reservation_tentative_created_events",
		[]string{"id", "base_event_id", "room_code", "customer_code", "starts_at", "ends_at", "expires_at"},
		rows, func(r sqlcgen.ReservationTentativeCreatedEvent) []any {
			return []any{r.ID, r.BaseEventID, r.RoomCode, r.CustomerCode, r.StartsAt, r.EndsAt, r.ExpiresAt}
		})
	require.NoError(t, sqlcgen.New(pool).SyncReservationTentativeCreatedEventsIdentity(ctx))
}

// ReadReservationTentativeCreatedEvents は reservation_tentative_created_events の全行を主キー順に返す。
func ReadReservationTentativeCreatedEvents(ctx context.Context, t *testing.T, pool *pgxpool.Pool) []sqlcgen.ReservationTentativeCreatedEvent {
	t.Helper()
	rows, err := sqlcgen.New(pool).ReadReservationTentativeCreatedEvents(ctx)
	require.NoError(t, err)
	for i := range rows {
		rows[i].StartsAt = rows[i].StartsAt.UTC()
		rows[i].EndsAt = rows[i].EndsAt.UTC()
		rows[i].ExpiresAt = rows[i].ExpiresAt.UTC()
	}
	return rows
}

// SeedReservationConfirmedEvents は reservation_confirmed_events に rows を投入する。
func SeedReservationConfirmedEvents(ctx context.Context, t *testing.T, pool *pgxpool.Pool, rows []sqlcgen.ReservationConfirmedEvent) {
	t.Helper()
	copyFrom(ctx, t, pool, "reservation_confirmed_events", []string{"id", "base_event_id"},
		rows, func(r sqlcgen.ReservationConfirmedEvent) []any { return []any{r.ID, r.BaseEventID} })
	require.NoError(t, sqlcgen.New(pool).SyncReservationConfirmedEventsIdentity(ctx))
}

// ReadReservationConfirmedEvents は reservation_confirmed_events の全行を主キー順に返す。
func ReadReservationConfirmedEvents(ctx context.Context, t *testing.T, pool *pgxpool.Pool) []sqlcgen.ReservationConfirmedEvent {
	t.Helper()
	rows, err := sqlcgen.New(pool).ReadReservationConfirmedEvents(ctx)
	require.NoError(t, err)
	return rows
}

// SeedReservationCancelledEvents は reservation_cancelled_events に rows を投入する。
func SeedReservationCancelledEvents(ctx context.Context, t *testing.T, pool *pgxpool.Pool, rows []sqlcgen.ReservationCancelledEvent) {
	t.Helper()
	copyFrom(ctx, t, pool, "reservation_cancelled_events", []string{"id", "base_event_id"},
		rows, func(r sqlcgen.ReservationCancelledEvent) []any { return []any{r.ID, r.BaseEventID} })
	require.NoError(t, sqlcgen.New(pool).SyncReservationCancelledEventsIdentity(ctx))
}

// ReadReservationCancelledEvents は reservation_cancelled_events の全行を主キー順に返す。
func ReadReservationCancelledEvents(ctx context.Context, t *testing.T, pool *pgxpool.Pool) []sqlcgen.ReservationCancelledEvent {
	t.Helper()
	rows, err := sqlcgen.New(pool).ReadReservationCancelledEvents(ctx)
	require.NoError(t, err)
	return rows
}

// SeedReservationExpiredEvents は reservation_expired_events に rows を投入する。
func SeedReservationExpiredEvents(ctx context.Context, t *testing.T, pool *pgxpool.Pool, rows []sqlcgen.ReservationExpiredEvent) {
	t.Helper()
	copyFrom(ctx, t, pool, "reservation_expired_events", []string{"id", "base_event_id"},
		rows, func(r sqlcgen.ReservationExpiredEvent) []any { return []any{r.ID, r.BaseEventID} })
	require.NoError(t, sqlcgen.New(pool).SyncReservationExpiredEventsIdentity(ctx))
}

// ReadReservationExpiredEvents は reservation_expired_events の全行を主キー順に返す。
func ReadReservationExpiredEvents(ctx context.Context, t *testing.T, pool *pgxpool.Pool) []sqlcgen.ReservationExpiredEvent {
	t.Helper()
	rows, err := sqlcgen.New(pool).ReadReservationExpiredEvents(ctx)
	require.NoError(t, err)
	return rows
}

// copyFrom は行型のスライスを COPY で投入する。SQL 文を組み立てず、列名と値の並びだけを渡す。
func copyFrom[R any](ctx context.Context, t *testing.T, pool *pgxpool.Pool, table string, columns []string, rows []R, values func(R) []any) {
	t.Helper()
	if len(rows) == 0 {
		return
	}
	src := make([][]any, 0, len(rows))
	for _, r := range rows {
		src = append(src, values(r))
	}
	n, err := pool.CopyFrom(ctx, pgx.Identifier{table}, columns, pgx.CopyFromRows(src))
	require.NoError(t, err)
	require.Equal(t, int64(len(rows)), n)
}
```

`copyFrom` の列名は DDL の列と 1:1 で、行型のフィールドの並びと同じ順に書く。列が増えたら `Seed{Table}` の列名と `values` の両方に足す（片方だけ足すと `CopyFrom` が列数不一致で落ちる）。
