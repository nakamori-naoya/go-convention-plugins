# テーブルの形

**リポジトリのテストは、資料の Before を `seed{Table}`、When の引数、資料の After を `want{Table}` に写した表で書き、ループ本体は「`Reset` → 全 `Seed` → `Run` の中で復元 → 操作 → 保存 → 全 `Read` → 全 `assert.Equal`」を 1 回だけ書く。** テストの形の共通規則（無名 struct のスライス・`id` / `name` / `description`・`want*` と `wantErr error`・`require` は前提で `assert` は独立した期待）はそのまま使う。ここではこの層で決まる分だけを書く。

## 1. 単位と置き場

| 項目 | 規則 |
|---|---|
| テスト関数 | リポジトリのメソッド 1 つに `Test{Repository}_{Method}` 1 つ（`TestReservationRepository_ApplyHeld` / `_ApplyConfirmed` / `_ApplyCancelled` / `_ApplyExpired` / `_FindByID`）。query service は `Test{Query}_{Method}` |
| package | `rdb_test`（外部テストパッケージ）。marshaller と `translateConstraint` は非公開のままで、公開メソッドを通して観測する |
| ファイル | `rdb/reservation_repository_test.go`（本体と 1:1）と `rdb/main_test.go` |
| `setup` | 置かない。全ケースが同じ資源（`TestMain` の `pool`）を使うので、ケースごとに違う Given が無い |
| ファイルスコープ | `Test*` だけ。表を支える型（`hold` / `confirm`）はテスト関数の中。ヘルパーは `rdbtest` へ |

## 2. フィールド

識別 → Given → When → Then の順。Given と Then は**資料に登場する全テーブル**を持つ。

| 区分 | フィールド | 内容 |
|---|---|---|
| 識別 | `id` / `name` / `description` | 資料の BDD はその ID・見出し文・gherkin ブロック（字下げと `NOTE:` を含めて改変せず転記）。資料に無いケースは生成した id と業務の言葉の 1 文 |
| Given | `seed{Table} []sqlcgen.{Row}` × 全テーブル | 資料の Before の表の行。0 行のテーブルは書かない（nil） |
| When | 集約の操作の引数（`at` / `by`）と、復元する集約の `reservationID`。生成なら `Hold` の引数 | 対象メソッドの引数はイベントだが、イベントは実物の操作から得るので表に書かない。表に書くのは操作の引数 |
| When（同時実行） | `holds []hold` / `confirms []confirm` のように When をスライスにする | 2 件以上なら並走。1 件なら直列と同じ |
| Then | `wantErr error` | 最後の When が受ける sentinel。nil なら成立 |
| Then | `want{Table} []sqlcgen.{Row}` × 全テーブル | 資料の After の表の行。0 行のテーブルは書かない（nil）。**1 テーブルも省かない** |

- `want{Table}` を書かないケースは、そのテーブルが空であることを期待している。`Read{Table}` が 0 行で nil を返すので `assert.Equal(nil, nil)` が成り立つ。「検証していない」のではなく「空を検証している」
- 拒まれるケース（DB 制約・競合）の After は Before と同じなので、`want{Table}` に `seed{Table}` と同じ行を書く。省くと「空」の期待になり落ちる
- 実装が資料に無いテーブル（題材では仮定の 9 表目 `reservation_no_show_recorded_events`）を置くなら、そのテーブルの `seed{Table}` / `want{Table}` も全ケースに並べる。例は資料の 8 表で書いている
- 資料の識別子（`BE-0101-01` / `TE-0101-01`）は identity 列の `1, 2, ...` に写る。`Reset` が採番を戻し、`Seed` が明示した `id` の次へ進めるので、After の `id` は表に書ける
- 資料の時刻は表の直前で変数にする（`start := time.Date(2026, 9, 18, 10, 0, 0, 0, time.UTC)`）。時刻は UTC で書く。表の前に置くのは値だけで、関数は置かない
- `FindByID` の表は `want reservation.Reservation`（`Restore*` で組み立てる）と `wantErr` を持ち、`want{Table}` を持たない。読み取りは Before を変えないので、After は `seed{Table}` と突き合わせる

## 3. ループ本体

```go
			ctx := t.Context()
			rdbtest.Reset(ctx, t, pool)
			rdbtest.SeedReservations(ctx, t, pool, tt.seedReservations)
			// ... 資料の全テーブル分の Seed
			repo := rdb.NewReservationRepository()

			// rdbtest.Run の中で 復元 → 絞り込み → 実物の操作 → 保存
			// error の検証

			// After は資料の 8 テーブルを全行で突き合わせる。want を書かないテーブルは nil（0 行）と一致する。
			assert.Equal(t, tt.wantReservations, rdbtest.ReadReservations(ctx, t, pool))
			// ... 資料の全テーブル分の Read と assert.Equal
```

| 規則 | 理由 |
|---|---|
| `Reset` → 全 `Seed` → `Run` → 全 `Read` → 全 `assert.Equal` の順。全 `Read` と全 `assert.Equal` は error の分岐の外に置く | 成立でも拒否でも After を全テーブルで見る。分岐の中に置くと片方の経路で検証が抜ける |
| `Seed` と `Read` は資料の全テーブル分を毎回並べる。まとめる関数を作らない | 1 テーブルの抜けが目で見える。まとめると抜けが関数の中に隠れる |
| error は `require.ErrorIs` / `require.NoError`。After の突き合わせは `assert.Equal` | error の不一致は後続の意味が無い。テーブルの不一致は互いに独立で、全部報告させる |
| `ctx` は `t.Context()`。フィールドにしない | キャンセルの持ち主をサブテストにする |
| ループ直前のコメントで共有 DB を名指しし、`t.Parallel()` を書かない | apply-go-test-convention の実 DB の規則 |

## 4. 同時実行の書き方

When をスライスにし、要素ごとに `rdbtest.Run` を goroutine で走らせる。**先頭が先に成立する**ように揃える。

| 手順 | 先頭（`i == 0`） | 残り（`i > 0`） |
|---|---|---|
| 1 | tx を張り、復元（または生成）→ 操作 → 保存まで進む | tx を張り、復元 → 操作まで進む |
| 2 | 合流点 `arrived` に着き、`release` を待つ（tx は開いたまま） | 合流点 `arrived` に着き、`release` を待つ（保存はまだ） |
| 3 | main が `arrived.Wait()` → `close(release)` | 同左 |
| 4 | commit する | 保存に入る。先頭の行ロック・排他制約と衝突し、先頭の commit を待ってから拒まれる |

```go
			var arrived sync.WaitGroup
			arrived.Add(len(tt.confirms))
			release := make(chan struct{})
			errs := make([]error, len(tt.confirms))
			var wg sync.WaitGroup
			for i, c := range tt.confirms {
				wg.Go(func() {
					arrive := sync.OnceFunc(arrived.Done)
					defer arrive() // 途中で返っても合流する
					errs[i] = rdbtest.Run(ctx, t, pool, func(ctx context.Context) error {
						// 復元 → 絞り込み → 実物の操作（省略）
						if i > 0 {
							arrive()
							<-release
						}
						err = repo.ApplyConfirmed(ctx, res.Event)
						arrive()
						<-release
						return err
					})
				})
			}
			arrived.Wait()
			close(release)
			wg.Wait()

			last := len(errs) - 1
			for _, err := range errs[:last] {
				require.NoError(t, err)
			}
			if tt.wantErr != nil {
				require.ErrorIs(t, errs[last], tt.wantErr)
			} else {
				require.NoError(t, errs[last])
			}
```

| 規則 | 理由 |
|---|---|
| `wantErr` は最後の When が受ける error。先頭から最後の 1 つ前は `require.NoError` | 成立する側を先頭に固定すれば After が 1 通りに決まり、表に書ける |
| 残りは復元を終えてから合流する。合流の前に先頭が commit しない | 残りが commit 後に復元すると版が進んだ集約を復元し、`AsTentative` が拒む（`ErrAlreadyConfirmed`）。それは集約の拒否で、楽観ロック競合ではない |
| `arrive` は `sync.OnceFunc` で 1 回だけ数え、`defer` でも呼ぶ | `fn` が途中で error を返しても main の `arrived.Wait()` が進む。数え忘れは hang になる |
| goroutine の中で `require` を呼ばない。error は `errs[i]` に集め、`wg.Wait()` の後で検証する | `FailNow` は呼んだ goroutine しか止めない |
| 1 件の When でも同じループを通す | 分岐を作らない。1 件なら合流点は自分だけで、揃った直後に commit する |
| `sync.WaitGroup.Go` を使う。`Add` / `Done` を手で書かない | Go 1.25 以降の形。数え間違いが消える |

## 5. 完全な例 `rdb/reservation_repository_test.go`

資料「RDB論理設計 — 貸会議室の予約」の BDD-001・BDD-005・BDD-008（`ApplyHeld`）と BDD-003（`ApplyConfirmed`）、資料に無い楽観ロック競合・復元・NotFound を写した抜粋である。実ファイルには `ApplyCancelled`（BDD-004・BDD-006）と `ApplyExpired`（BDD-009）、`ApplyHeld` の BDD-010 も同じ形で並び、末尾コメントと合わせて資料の 10 件が全部現れる。**書き始める前に一度読み、この形を写す。**

```go
package rdb_test

import (
	"context"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"example.com/roomflow/rdb"
	"example.com/roomflow/rdb/rdbtest"
	"example.com/roomflow/rdb/sqlcgen"
	"example.com/roomflow/reservation"
)

func TestReservationRepository_ApplyHeld(t *testing.T) {
	// hold は仮押さえの申込み 1 件。When の引数（生成 Hold の引数）をそのまま持つ。
	type hold struct {
		id       string
		customer string
		room     string
		start    time.Time
		end      time.Time
		at       time.Time
	}

	// 資料の時刻。表の中で何度も書くので、表の直前で値にする（関数は置かない）。
	start := time.Date(2026, 9, 18, 10, 0, 0, 0, time.UTC)
	end := time.Date(2026, 9, 18, 11, 30, 0, 0, time.UTC)
	heldAt := time.Date(2026, 9, 1, 9, 0, 0, 0, time.UTC)
	expiresAt := heldAt.Add(15 * time.Minute)
	confirmedAt := time.Date(2026, 9, 1, 9, 5, 0, 0, time.UTC)
	endAt11 := time.Date(2026, 9, 18, 11, 0, 0, 0, time.UTC)
	endAt12 := time.Date(2026, 9, 18, 12, 0, 0, 0, time.UTC)
	heldAt2 := time.Date(2026, 9, 1, 9, 10, 0, 0, time.UTC)
	expiresAt2 := heldAt2.Add(15 * time.Minute)

	tests := []struct {
		id                                    string
		name                                  string
		description                           string
		seedReservations                      []sqlcgen.Reservation                      // Given: 資料の Before。書かないテーブルは 0 行
		seedRoomBookingClaims                 []sqlcgen.RoomBookingClaim                 // Given
		seedTentativeHoldDeadlines            []sqlcgen.TentativeHoldDeadline            // Given
		seedReservationBaseEvents             []sqlcgen.ReservationBaseEvent             // Given
		seedReservationTentativeCreatedEvents []sqlcgen.ReservationTentativeCreatedEvent // Given
		seedReservationConfirmedEvents        []sqlcgen.ReservationConfirmedEvent        // Given
		seedReservationCancelledEvents        []sqlcgen.ReservationCancelledEvent        // Given
		seedReservationExpiredEvents          []sqlcgen.ReservationExpiredEvent          // Given
		holds                                 []hold                                     // When:  仮押さえの申込み。2 件以上なら並走させ、先頭を先に成立させる
		wantErr                               error                                      // Then:  最後の申込みが受ける error。nil なら成立。先頭から最後の 1 つ前までは成立を要求する
		wantReservations                      []sqlcgen.Reservation                      // Then:  資料の After。書かないテーブルは 0 行
		wantRoomBookingClaims                 []sqlcgen.RoomBookingClaim                 // Then
		wantTentativeHoldDeadlines            []sqlcgen.TentativeHoldDeadline            // Then
		wantReservationBaseEvents             []sqlcgen.ReservationBaseEvent             // Then
		wantReservationTentativeCreatedEvents []sqlcgen.ReservationTentativeCreatedEvent // Then
		wantReservationConfirmedEvents        []sqlcgen.ReservationConfirmedEvent        // Then
		wantReservationCancelledEvents        []sqlcgen.ReservationCancelledEvent        // Then
		wantReservationExpiredEvents          []sqlcgen.ReservationExpiredEvent          // Then
	}{
		{
			id:   "BDD-001",
			name: "空き枠を仮押さえする",
			description: `Given: 顧客C-4102は予約可能顧客である
  And: 会議室M-301の2026年9月18日 10:00から11:30までの利用枠には予約枠占有がない
  And: 現在日時は2026年9月1日 09:00である
When: C-4102が会議室M-301の2026年9月18日 10:00から11:30までを仮押さえする
Then: 予約R-20260901-0101が会議室M-301の2026年9月18日 10:00から11:30までの仮押さえ予約として成立する
  And: 予約の現在versionと基底イベントのversionは1で一致する
  And: 仮押さえ成立イベントに成立時点の予約内容が残る`,
			holds: []hold{
				{id: "R-20260901-0101", customer: "C-4102", room: "M-301", start: start, end: end, at: heldAt},
			},
			wantReservations: []sqlcgen.Reservation{
				{ReservationID: "R-20260901-0101", RoomCode: "M-301", CustomerCode: "C-4102", StartsAt: start, EndsAt: end, Status: "tentative", CurrentVersion: 1, CreatedAt: heldAt, UpdatedAt: heldAt},
			},
			wantRoomBookingClaims: []sqlcgen.RoomBookingClaim{
				{ReservationID: "R-20260901-0101", RoomCode: "M-301", StartsAt: start, EndsAt: end, CreatedAt: heldAt},
			},
			wantTentativeHoldDeadlines: []sqlcgen.TentativeHoldDeadline{
				{ReservationID: "R-20260901-0101", ExpiresAt: expiresAt, CreatedAt: heldAt},
			},
			wantReservationBaseEvents: []sqlcgen.ReservationBaseEvent{
				{ID: 1, ReservationID: "R-20260901-0101", EventType: "tentative_created", Version: 1, ActorCode: "C-4102", OccurredAt: heldAt},
			},
			wantReservationTentativeCreatedEvents: []sqlcgen.ReservationTentativeCreatedEvent{
				{ID: 1, BaseEventID: 1, RoomCode: "M-301", CustomerCode: "C-4102", StartsAt: start, EndsAt: end, ExpiresAt: expiresAt},
			},
		},
		{
			id:   "BDD-005",
			name: "同じ空き時間への同時仮押さえは一方だけ成立する",
			description: `Given: 顧客C-4102と顧客C-5821は予約可能顧客である
  And: 会議室M-301の2026年9月18日 10:00から11:30までの利用枠には予約枠占有がない
When: 二人が会議室M-301の2026年9月18日 10:00から11:30までを同時に仮押さえする
Then: 先に成立した一方だけが現在version 1の仮押さえ予約になる
  And: 成立した予約のリソース系3行とイベント系2行だけが追加される
  And: もう一方に属する行は8テーブルのどこにも作られない`,
			holds: []hold{
				{id: "R-20260901-0101", customer: "C-4102", room: "M-301", start: start, end: end, at: heldAt},
				{id: "R-20260901-0102", customer: "C-5821", room: "M-301", start: start, end: end, at: heldAt},
			},
			wantErr: reservation.ErrOverlappingSlot,
			wantReservations: []sqlcgen.Reservation{
				{ReservationID: "R-20260901-0101", RoomCode: "M-301", CustomerCode: "C-4102", StartsAt: start, EndsAt: end, Status: "tentative", CurrentVersion: 1, CreatedAt: heldAt, UpdatedAt: heldAt},
			},
			wantRoomBookingClaims: []sqlcgen.RoomBookingClaim{
				{ReservationID: "R-20260901-0101", RoomCode: "M-301", StartsAt: start, EndsAt: end, CreatedAt: heldAt},
			},
			wantTentativeHoldDeadlines: []sqlcgen.TentativeHoldDeadline{
				{ReservationID: "R-20260901-0101", ExpiresAt: expiresAt, CreatedAt: heldAt},
			},
			wantReservationBaseEvents: []sqlcgen.ReservationBaseEvent{
				{ID: 1, ReservationID: "R-20260901-0101", EventType: "tentative_created", Version: 1, ActorCode: "C-4102", OccurredAt: heldAt},
			},
			wantReservationTentativeCreatedEvents: []sqlcgen.ReservationTentativeCreatedEvent{
				{ID: 1, BaseEventID: 1, RoomCode: "M-301", CustomerCode: "C-4102", StartsAt: start, EndsAt: end, ExpiresAt: expiresAt},
			},
		},
		{
			id:   "BDD-008",
			name: "確定予約に隣接する利用枠を仮押さえする",
			description: `Given: 顧客C-4102の確定予約R-20260901-0101がある
  And: 予約は会議室M-301の2026年9月18日 10:00から11:00までを占有している
  And: 顧客C-5821は予約可能顧客である
When: C-5821が同じ会議室の2026年9月18日 11:00から12:00までを仮押さえする
Then: 予約R-20260901-0201が会議室M-301の2026年9月18日 11:00から12:00までの仮押さえ予約として成立する
  And: 二つの予約枠占有は境界で接するだけで重ならない
  And: R-20260901-0201のversion 1イベントと仮押さえ期限が追加される`,
			seedReservations: []sqlcgen.Reservation{
				{ReservationID: "R-20260901-0101", RoomCode: "M-301", CustomerCode: "C-4102", StartsAt: start, EndsAt: endAt11, Status: "confirmed", CurrentVersion: 2, CreatedAt: heldAt, UpdatedAt: confirmedAt},
			},
			seedRoomBookingClaims: []sqlcgen.RoomBookingClaim{
				{ReservationID: "R-20260901-0101", RoomCode: "M-301", StartsAt: start, EndsAt: endAt11, CreatedAt: heldAt},
			},
			seedReservationBaseEvents: []sqlcgen.ReservationBaseEvent{
				{ID: 1, ReservationID: "R-20260901-0101", EventType: "tentative_created", Version: 1, ActorCode: "C-4102", OccurredAt: heldAt},
				{ID: 2, ReservationID: "R-20260901-0101", EventType: "confirmed", Version: 2, ActorCode: "C-4102", OccurredAt: confirmedAt},
			},
			seedReservationTentativeCreatedEvents: []sqlcgen.ReservationTentativeCreatedEvent{
				{ID: 1, BaseEventID: 1, RoomCode: "M-301", CustomerCode: "C-4102", StartsAt: start, EndsAt: endAt11, ExpiresAt: expiresAt},
			},
			seedReservationConfirmedEvents: []sqlcgen.ReservationConfirmedEvent{
				{ID: 1, BaseEventID: 2},
			},
			holds: []hold{
				{id: "R-20260901-0201", customer: "C-5821", room: "M-301", start: endAt11, end: endAt12, at: heldAt2},
			},
			wantReservations: []sqlcgen.Reservation{
				{ReservationID: "R-20260901-0101", RoomCode: "M-301", CustomerCode: "C-4102", StartsAt: start, EndsAt: endAt11, Status: "confirmed", CurrentVersion: 2, CreatedAt: heldAt, UpdatedAt: confirmedAt},
				{ReservationID: "R-20260901-0201", RoomCode: "M-301", CustomerCode: "C-5821", StartsAt: endAt11, EndsAt: endAt12, Status: "tentative", CurrentVersion: 1, CreatedAt: heldAt2, UpdatedAt: heldAt2},
			},
			wantRoomBookingClaims: []sqlcgen.RoomBookingClaim{
				{ReservationID: "R-20260901-0101", RoomCode: "M-301", StartsAt: start, EndsAt: endAt11, CreatedAt: heldAt},
				{ReservationID: "R-20260901-0201", RoomCode: "M-301", StartsAt: endAt11, EndsAt: endAt12, CreatedAt: heldAt2},
			},
			wantTentativeHoldDeadlines: []sqlcgen.TentativeHoldDeadline{
				{ReservationID: "R-20260901-0201", ExpiresAt: expiresAt2, CreatedAt: heldAt2},
			},
			wantReservationBaseEvents: []sqlcgen.ReservationBaseEvent{
				{ID: 1, ReservationID: "R-20260901-0101", EventType: "tentative_created", Version: 1, ActorCode: "C-4102", OccurredAt: heldAt},
				{ID: 2, ReservationID: "R-20260901-0101", EventType: "confirmed", Version: 2, ActorCode: "C-4102", OccurredAt: confirmedAt},
				{ID: 3, ReservationID: "R-20260901-0201", EventType: "tentative_created", Version: 1, ActorCode: "C-5821", OccurredAt: heldAt2},
			},
			wantReservationTentativeCreatedEvents: []sqlcgen.ReservationTentativeCreatedEvent{
				{ID: 1, BaseEventID: 1, RoomCode: "M-301", CustomerCode: "C-4102", StartsAt: start, EndsAt: endAt11, ExpiresAt: expiresAt},
				{ID: 2, BaseEventID: 3, RoomCode: "M-301", CustomerCode: "C-5821", StartsAt: endAt11, EndsAt: endAt12, ExpiresAt: expiresAt2},
			},
			wantReservationConfirmedEvents: []sqlcgen.ReservationConfirmedEvent{
				{ID: 1, BaseEventID: 2},
			},
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
			rdbtest.SeedReservationBaseEvents(ctx, t, pool, tt.seedReservationBaseEvents)
			rdbtest.SeedReservationTentativeCreatedEvents(ctx, t, pool, tt.seedReservationTentativeCreatedEvents)
			rdbtest.SeedReservationConfirmedEvents(ctx, t, pool, tt.seedReservationConfirmedEvents)
			rdbtest.SeedReservationCancelledEvents(ctx, t, pool, tt.seedReservationCancelledEvents)
			rdbtest.SeedReservationExpiredEvents(ctx, t, pool, tt.seedReservationExpiredEvents)
			repo := rdb.NewReservationRepository()

			// 生成は実物の Hold。顧客の予約資格は予約可能にする（資格で拒む条件は集約の関心で、ここでは扱わない）。
			events := make([]reservation.Held, len(tt.holds))
			for i, h := range tt.holds {
				id, err := reservation.NewID(h.id)
				require.NoError(t, err)
				customer, err := reservation.NewCustomerID(h.customer)
				require.NoError(t, err)
				room, err := reservation.NewRoomCode(h.room)
				require.NoError(t, err)
				slot, err := reservation.NewTimeSlot(room, h.start, h.end)
				require.NoError(t, err)
				res, err := reservation.Hold(id, customer, slot, reservation.NewEligibility(customer, nil, h.at), h.at)
				require.NoError(t, err)
				events[i] = res.Event
			}

			// 保存は申込みごとに tx を張って並走させる。先頭は保存の後、全員が揃うまで tx を開いたまま待つ。
			// 残りは保存の直前で揃い、揃ってから保存に入る。先頭の占有と重なれば排他制約が先頭の commit を待たせてから弾き、
			// ErrOverlappingSlot になる。1 件なら揃うのは自分だけで、そのまま commit する。
			var arrived sync.WaitGroup
			arrived.Add(len(events))
			release := make(chan struct{})
			errs := make([]error, len(events))
			var wg sync.WaitGroup
			for i, evt := range events {
				wg.Go(func() {
					arrive := sync.OnceFunc(arrived.Done)
					defer arrive() // 途中で返っても合流する
					errs[i] = rdbtest.Run(ctx, t, pool, func(ctx context.Context) error {
						if i > 0 {
							arrive()
							<-release
						}
						err := repo.ApplyHeld(ctx, evt)
						arrive()
						<-release
						return err
					})
				})
			}
			arrived.Wait()
			close(release)
			wg.Wait()

			last := len(errs) - 1
			for _, err := range errs[:last] {
				require.NoError(t, err)
			}
			if tt.wantErr != nil {
				require.ErrorIs(t, errs[last], tt.wantErr)
			} else {
				require.NoError(t, errs[last])
			}

			// After は資料の 8 テーブルを全行で突き合わせる。want を書かないテーブルは nil（0 行）と一致する。
			assert.Equal(t, tt.wantReservations, rdbtest.ReadReservations(ctx, t, pool))
			assert.Equal(t, tt.wantRoomBookingClaims, rdbtest.ReadRoomBookingClaims(ctx, t, pool))
			assert.Equal(t, tt.wantTentativeHoldDeadlines, rdbtest.ReadTentativeHoldDeadlines(ctx, t, pool))
			assert.Equal(t, tt.wantReservationBaseEvents, rdbtest.ReadReservationBaseEvents(ctx, t, pool))
			assert.Equal(t, tt.wantReservationTentativeCreatedEvents, rdbtest.ReadReservationTentativeCreatedEvents(ctx, t, pool))
			assert.Equal(t, tt.wantReservationConfirmedEvents, rdbtest.ReadReservationConfirmedEvents(ctx, t, pool))
			assert.Equal(t, tt.wantReservationCancelledEvents, rdbtest.ReadReservationCancelledEvents(ctx, t, pool))
			assert.Equal(t, tt.wantReservationExpiredEvents, rdbtest.ReadReservationExpiredEvents(ctx, t, pool))
		})
	}
}

func TestReservationRepository_ApplyConfirmed(t *testing.T) {
	// confirm は確定の呼び出し 1 回。When の引数（Tentative.Confirm の引数）をそのまま持つ。
	type confirm struct {
		at time.Time
		by string
	}

	start := time.Date(2026, 9, 18, 10, 0, 0, 0, time.UTC)
	end := time.Date(2026, 9, 18, 11, 30, 0, 0, time.UTC)
	heldAt := time.Date(2026, 9, 1, 9, 0, 0, 0, time.UTC)
	expiresAt := heldAt.Add(15 * time.Minute)
	confirmedAt := time.Date(2026, 9, 1, 9, 5, 0, 0, time.UTC)

	tests := []struct {
		id                                    string
		name                                  string
		description                           string
		seedReservations                      []sqlcgen.Reservation                      // Given: 資料の Before。書かないテーブルは 0 行
		seedRoomBookingClaims                 []sqlcgen.RoomBookingClaim                 // Given
		seedTentativeHoldDeadlines            []sqlcgen.TentativeHoldDeadline            // Given
		seedReservationBaseEvents             []sqlcgen.ReservationBaseEvent             // Given
		seedReservationTentativeCreatedEvents []sqlcgen.ReservationTentativeCreatedEvent // Given
		seedReservationConfirmedEvents        []sqlcgen.ReservationConfirmedEvent        // Given
		seedReservationCancelledEvents        []sqlcgen.ReservationCancelledEvent        // Given
		seedReservationExpiredEvents          []sqlcgen.ReservationExpiredEvent          // Given
		reservationID                         string                                     // When:  復元する予約
		confirms                              []confirm                                  // When:  確定の呼び出し。2 回以上なら並走させ、先頭を先に成立させる
		wantErr                               error                                      // Then:  最後の呼び出しが受ける error。nil なら成立。先頭から最後の 1 つ前までは成立を要求する
		wantReservations                      []sqlcgen.Reservation                      // Then:  資料の After。書かないテーブルは 0 行
		wantRoomBookingClaims                 []sqlcgen.RoomBookingClaim                 // Then
		wantTentativeHoldDeadlines            []sqlcgen.TentativeHoldDeadline            // Then
		wantReservationBaseEvents             []sqlcgen.ReservationBaseEvent             // Then
		wantReservationTentativeCreatedEvents []sqlcgen.ReservationTentativeCreatedEvent // Then
		wantReservationConfirmedEvents        []sqlcgen.ReservationConfirmedEvent        // Then
		wantReservationCancelledEvents        []sqlcgen.ReservationCancelledEvent        // Then
		wantReservationExpiredEvents          []sqlcgen.ReservationExpiredEvent          // Then
	}{
		{
			id:   "BDD-003",
			name: "仮押さえ予約を確定する",
			description: `Given: 予約R-20260901-0101は現在version 1の仮押さえ予約である
  And: 利用枠は会議室M-301の2026年9月18日 10:00から11:30までである
  And: version 1の仮押さえ成立イベントと仮押さえ期限がある
  And: 現在日時は期限前の2026年9月1日 09:05である
When: 予約者C-4102が予約を確定する
Then: 予約は現在version 2の確定予約になる
  And: 確定予約の利用枠は会議室M-301の2026年9月18日 10:00から11:30までのままである
  And: 仮押さえ期限は削除される
  And: version 2の基底イベントと予約確定イベントが追加される`,
			seedReservations: []sqlcgen.Reservation{
				{ReservationID: "R-20260901-0101", RoomCode: "M-301", CustomerCode: "C-4102", StartsAt: start, EndsAt: end, Status: "tentative", CurrentVersion: 1, CreatedAt: heldAt, UpdatedAt: heldAt},
			},
			seedRoomBookingClaims: []sqlcgen.RoomBookingClaim{
				{ReservationID: "R-20260901-0101", RoomCode: "M-301", StartsAt: start, EndsAt: end, CreatedAt: heldAt},
			},
			seedTentativeHoldDeadlines: []sqlcgen.TentativeHoldDeadline{
				{ReservationID: "R-20260901-0101", ExpiresAt: expiresAt, CreatedAt: heldAt},
			},
			seedReservationBaseEvents: []sqlcgen.ReservationBaseEvent{
				{ID: 1, ReservationID: "R-20260901-0101", EventType: "tentative_created", Version: 1, ActorCode: "C-4102", OccurredAt: heldAt},
			},
			seedReservationTentativeCreatedEvents: []sqlcgen.ReservationTentativeCreatedEvent{
				{ID: 1, BaseEventID: 1, RoomCode: "M-301", CustomerCode: "C-4102", StartsAt: start, EndsAt: end, ExpiresAt: expiresAt},
			},
			reservationID: "R-20260901-0101",
			confirms:      []confirm{{at: confirmedAt, by: "C-4102"}},
			wantReservations: []sqlcgen.Reservation{
				{ReservationID: "R-20260901-0101", RoomCode: "M-301", CustomerCode: "C-4102", StartsAt: start, EndsAt: end, Status: "confirmed", CurrentVersion: 2, CreatedAt: heldAt, UpdatedAt: confirmedAt},
			},
			wantRoomBookingClaims: []sqlcgen.RoomBookingClaim{
				{ReservationID: "R-20260901-0101", RoomCode: "M-301", StartsAt: start, EndsAt: end, CreatedAt: heldAt},
			},
			wantReservationBaseEvents: []sqlcgen.ReservationBaseEvent{
				{ID: 1, ReservationID: "R-20260901-0101", EventType: "tentative_created", Version: 1, ActorCode: "C-4102", OccurredAt: heldAt},
				{ID: 2, ReservationID: "R-20260901-0101", EventType: "confirmed", Version: 2, ActorCode: "C-4102", OccurredAt: confirmedAt},
			},
			wantReservationTentativeCreatedEvents: []sqlcgen.ReservationTentativeCreatedEvent{
				{ID: 1, BaseEventID: 1, RoomCode: "M-301", CustomerCode: "C-4102", StartsAt: start, EndsAt: end, ExpiresAt: expiresAt},
			},
			wantReservationConfirmedEvents: []sqlcgen.ReservationConfirmedEvent{
				{ID: 1, BaseEventID: 2},
			},
		},
		{
			id:   "8f2c4d",
			name: "同じ仮押さえ予約を同時に2回確定すると一方だけ成立する",
			description: `Given: 予約R-20260901-0101は現在version 1の仮押さえ予約である
  And: version 1の仮押さえ成立イベントと仮押さえ期限がある
When: 予約者C-4102が同じ予約を2026年9月1日 09:05に同時に2回確定する
Then: 先に成立した一方だけが予約を現在version 2の確定予約にする
  And: もう一方は対象が別の操作で更新されたと拒まれる
  And: version 2の基底イベントと予約確定イベントは1組だけ追加される`,
			seedReservations: []sqlcgen.Reservation{
				{ReservationID: "R-20260901-0101", RoomCode: "M-301", CustomerCode: "C-4102", StartsAt: start, EndsAt: end, Status: "tentative", CurrentVersion: 1, CreatedAt: heldAt, UpdatedAt: heldAt},
			},
			seedRoomBookingClaims: []sqlcgen.RoomBookingClaim{
				{ReservationID: "R-20260901-0101", RoomCode: "M-301", StartsAt: start, EndsAt: end, CreatedAt: heldAt},
			},
			seedTentativeHoldDeadlines: []sqlcgen.TentativeHoldDeadline{
				{ReservationID: "R-20260901-0101", ExpiresAt: expiresAt, CreatedAt: heldAt},
			},
			seedReservationBaseEvents: []sqlcgen.ReservationBaseEvent{
				{ID: 1, ReservationID: "R-20260901-0101", EventType: "tentative_created", Version: 1, ActorCode: "C-4102", OccurredAt: heldAt},
			},
			seedReservationTentativeCreatedEvents: []sqlcgen.ReservationTentativeCreatedEvent{
				{ID: 1, BaseEventID: 1, RoomCode: "M-301", CustomerCode: "C-4102", StartsAt: start, EndsAt: end, ExpiresAt: expiresAt},
			},
			reservationID: "R-20260901-0101",
			confirms:      []confirm{{at: confirmedAt, by: "C-4102"}, {at: confirmedAt, by: "C-4102"}},
			wantErr:       rdb.ErrConflict,
			wantReservations: []sqlcgen.Reservation{
				{ReservationID: "R-20260901-0101", RoomCode: "M-301", CustomerCode: "C-4102", StartsAt: start, EndsAt: end, Status: "confirmed", CurrentVersion: 2, CreatedAt: heldAt, UpdatedAt: confirmedAt},
			},
			wantRoomBookingClaims: []sqlcgen.RoomBookingClaim{
				{ReservationID: "R-20260901-0101", RoomCode: "M-301", StartsAt: start, EndsAt: end, CreatedAt: heldAt},
			},
			wantReservationBaseEvents: []sqlcgen.ReservationBaseEvent{
				{ID: 1, ReservationID: "R-20260901-0101", EventType: "tentative_created", Version: 1, ActorCode: "C-4102", OccurredAt: heldAt},
				{ID: 2, ReservationID: "R-20260901-0101", EventType: "confirmed", Version: 2, ActorCode: "C-4102", OccurredAt: confirmedAt},
			},
			wantReservationTentativeCreatedEvents: []sqlcgen.ReservationTentativeCreatedEvent{
				{ID: 1, BaseEventID: 1, RoomCode: "M-301", CustomerCode: "C-4102", StartsAt: start, EndsAt: end, ExpiresAt: expiresAt},
			},
			wantReservationConfirmedEvents: []sqlcgen.ReservationConfirmedEvent{
				{ID: 1, BaseEventID: 2},
			},
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
			rdbtest.SeedReservationBaseEvents(ctx, t, pool, tt.seedReservationBaseEvents)
			rdbtest.SeedReservationTentativeCreatedEvents(ctx, t, pool, tt.seedReservationTentativeCreatedEvents)
			rdbtest.SeedReservationConfirmedEvents(ctx, t, pool, tt.seedReservationConfirmedEvents)
			rdbtest.SeedReservationCancelledEvents(ctx, t, pool, tt.seedReservationCancelledEvents)
			rdbtest.SeedReservationExpiredEvents(ctx, t, pool, tt.seedReservationExpiredEvents)
			repo := rdb.NewReservationRepository()
			id, err := reservation.NewID(tt.reservationID)
			require.NoError(t, err)
			bys := make([]reservation.CustomerID, len(tt.confirms))
			for i, c := range tt.confirms {
				bys[i], err = reservation.NewCustomerID(c.by)
				require.NoError(t, err)
			}

			// 呼び出しごとに tx を張り、usecase と同じ手順（復元 → 絞り込み → 実物の操作 → 保存）を同じ tx の中で行う。
			// 先頭は保存の後、全員が揃うまで tx を開いたまま待つ。残りは復元を終えて保存の直前で揃い、揃ってから保存に入る。
			// 残りの UPDATE は先頭の commit を待ってから版の照合に失敗し、ErrConflict になる。1 回なら揃うのは自分だけで、そのまま commit する。
			var arrived sync.WaitGroup
			arrived.Add(len(tt.confirms))
			release := make(chan struct{})
			errs := make([]error, len(tt.confirms))
			var wg sync.WaitGroup
			for i, c := range tt.confirms {
				wg.Go(func() {
					arrive := sync.OnceFunc(arrived.Done)
					defer arrive() // 途中で返っても合流する
					errs[i] = rdbtest.Run(ctx, t, pool, func(ctx context.Context) error {
						found, err := repo.FindByID(ctx, id)
						if err != nil {
							return err
						}
						tentative, err := reservation.AsTentative(found)
						if err != nil {
							return err
						}
						res, err := tentative.Confirm(c.at, bys[i])
						if err != nil {
							return err
						}
						if i > 0 {
							arrive()
							<-release
						}
						err = repo.ApplyConfirmed(ctx, res.Event)
						arrive()
						<-release
						return err
					})
				})
			}
			arrived.Wait()
			close(release)
			wg.Wait()

			last := len(errs) - 1
			for _, err := range errs[:last] {
				require.NoError(t, err)
			}
			if tt.wantErr != nil {
				require.ErrorIs(t, errs[last], tt.wantErr)
			} else {
				require.NoError(t, errs[last])
			}

			// After は資料の 8 テーブルを全行で突き合わせる。want を書かないテーブルは nil（0 行）と一致する。
			assert.Equal(t, tt.wantReservations, rdbtest.ReadReservations(ctx, t, pool))
			assert.Equal(t, tt.wantRoomBookingClaims, rdbtest.ReadRoomBookingClaims(ctx, t, pool))
			assert.Equal(t, tt.wantTentativeHoldDeadlines, rdbtest.ReadTentativeHoldDeadlines(ctx, t, pool))
			assert.Equal(t, tt.wantReservationBaseEvents, rdbtest.ReadReservationBaseEvents(ctx, t, pool))
			assert.Equal(t, tt.wantReservationTentativeCreatedEvents, rdbtest.ReadReservationTentativeCreatedEvents(ctx, t, pool))
			assert.Equal(t, tt.wantReservationConfirmedEvents, rdbtest.ReadReservationConfirmedEvents(ctx, t, pool))
			assert.Equal(t, tt.wantReservationCancelledEvents, rdbtest.ReadReservationCancelledEvents(ctx, t, pool))
			assert.Equal(t, tt.wantReservationExpiredEvents, rdbtest.ReadReservationExpiredEvents(ctx, t, pool))
		})
	}
}

func TestReservationRepository_FindByID(t *testing.T) {
	start := time.Date(2026, 9, 18, 10, 0, 0, 0, time.UTC)
	end := time.Date(2026, 9, 18, 11, 30, 0, 0, time.UTC)
	heldAt := time.Date(2026, 9, 1, 9, 0, 0, 0, time.UTC)
	expiresAt := heldAt.Add(15 * time.Minute)

	// want は Restore* で組み立てる。値オブジェクトは表の直前で作る（表の中では error を扱えない）。
	id0101, err := reservation.NewID("R-20260901-0101")
	require.NoError(t, err)
	c4102, err := reservation.NewCustomerID("C-4102")
	require.NoError(t, err)
	m301, err := reservation.NewRoomCode("M-301")
	require.NoError(t, err)
	slot, err := reservation.NewTimeSlot(m301, start, end)
	require.NoError(t, err)
	v1, err := reservation.NewVersion(1)
	require.NoError(t, err)

	tests := []struct {
		id                                    string
		name                                  string
		description                           string
		seedReservations                      []sqlcgen.Reservation                      // Given: 資料の Before。書かないテーブルは 0 行
		seedRoomBookingClaims                 []sqlcgen.RoomBookingClaim                 // Given
		seedTentativeHoldDeadlines            []sqlcgen.TentativeHoldDeadline            // Given
		seedReservationBaseEvents             []sqlcgen.ReservationBaseEvent             // Given
		seedReservationTentativeCreatedEvents []sqlcgen.ReservationTentativeCreatedEvent // Given
		seedReservationConfirmedEvents        []sqlcgen.ReservationConfirmedEvent        // Given
		seedReservationCancelledEvents        []sqlcgen.ReservationCancelledEvent        // Given
		seedReservationExpiredEvents          []sqlcgen.ReservationExpiredEvent          // Given
		reservationID                         string                                     // When:  対象メソッドの引数
		want                                  reservation.Reservation                    // Then:  復元された集約。Restore* で組み立てる
		wantErr                               error                                      // Then:  nil なら成功を期待
	}{
		{
			id:   "c1d7e0",
			name: "仮押さえ予約を期限つきで復元する",
			description: `Given: 予約R-20260901-0101は現在version 1の仮押さえ予約である
  And: 利用枠は会議室M-301の2026年9月18日 10:00から11:30までである
  And: 仮押さえ期限は2026年9月1日 09:15である
When: 予約R-20260901-0101を取得する
Then: 仮押さえ予約として、予約者、利用枠、期限、version 1が復元される`,
			seedReservations: []sqlcgen.Reservation{
				{ReservationID: "R-20260901-0101", RoomCode: "M-301", CustomerCode: "C-4102", StartsAt: start, EndsAt: end, Status: "tentative", CurrentVersion: 1, CreatedAt: heldAt, UpdatedAt: heldAt},
			},
			seedRoomBookingClaims: []sqlcgen.RoomBookingClaim{
				{ReservationID: "R-20260901-0101", RoomCode: "M-301", StartsAt: start, EndsAt: end, CreatedAt: heldAt},
			},
			seedTentativeHoldDeadlines: []sqlcgen.TentativeHoldDeadline{
				{ReservationID: "R-20260901-0101", ExpiresAt: expiresAt, CreatedAt: heldAt},
			},
			seedReservationBaseEvents: []sqlcgen.ReservationBaseEvent{
				{ID: 1, ReservationID: "R-20260901-0101", EventType: "tentative_created", Version: 1, ActorCode: "C-4102", OccurredAt: heldAt},
			},
			seedReservationTentativeCreatedEvents: []sqlcgen.ReservationTentativeCreatedEvent{
				{ID: 1, BaseEventID: 1, RoomCode: "M-301", CustomerCode: "C-4102", StartsAt: start, EndsAt: end, ExpiresAt: expiresAt},
			},
			reservationID: "R-20260901-0101",
			want:          reservation.RestoreTentative(id0101, c4102, slot, reservation.RestoreHoldDeadline(expiresAt), v1),
		},
		{
			id:   "5a90b3",
			name: "無い予約番号は見つからないと返る",
			description: `Given: 予約は一つも無い
When: 予約R-20260901-0999を取得する
Then: 予約が見つからないと拒まれる`,
			reservationID: "R-20260901-0999",
			wantErr:       rdb.ErrNotFound,
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
			rdbtest.SeedReservationBaseEvents(ctx, t, pool, tt.seedReservationBaseEvents)
			rdbtest.SeedReservationTentativeCreatedEvents(ctx, t, pool, tt.seedReservationTentativeCreatedEvents)
			rdbtest.SeedReservationConfirmedEvents(ctx, t, pool, tt.seedReservationConfirmedEvents)
			rdbtest.SeedReservationCancelledEvents(ctx, t, pool, tt.seedReservationCancelledEvents)
			rdbtest.SeedReservationExpiredEvents(ctx, t, pool, tt.seedReservationExpiredEvents)
			repo := rdb.NewReservationRepository()
			id, err := reservation.NewID(tt.reservationID)
			require.NoError(t, err)

			var got reservation.Reservation
			err = rdbtest.Run(ctx, t, pool, func(ctx context.Context) error {
				var err error
				got, err = repo.FindByID(ctx, id)
				return err
			})
			if tt.wantErr != nil {
				require.ErrorIs(t, err, tt.wantErr)
				assert.Nil(t, got)
			} else {
				require.NoError(t, err)
				assert.Equal(t, tt.want, got)
			}

			// 読み取りは Before を変えない。After は seed と 8 テーブル全行で突き合わせる。
			assert.Equal(t, tt.seedReservations, rdbtest.ReadReservations(ctx, t, pool))
			assert.Equal(t, tt.seedRoomBookingClaims, rdbtest.ReadRoomBookingClaims(ctx, t, pool))
			assert.Equal(t, tt.seedTentativeHoldDeadlines, rdbtest.ReadTentativeHoldDeadlines(ctx, t, pool))
			assert.Equal(t, tt.seedReservationBaseEvents, rdbtest.ReadReservationBaseEvents(ctx, t, pool))
			assert.Equal(t, tt.seedReservationTentativeCreatedEvents, rdbtest.ReadReservationTentativeCreatedEvents(ctx, t, pool))
			assert.Equal(t, tt.seedReservationConfirmedEvents, rdbtest.ReadReservationConfirmedEvents(ctx, t, pool))
			assert.Equal(t, tt.seedReservationCancelledEvents, rdbtest.ReadReservationCancelledEvents(ctx, t, pool))
			assert.Equal(t, tt.seedReservationExpiredEvents, rdbtest.ReadReservationExpiredEvents(ctx, t, pool))
		})
	}
}
```
