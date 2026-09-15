# テーブルの形

**usecase のテストは、テストの形の共通規則（無名 struct のテーブル・`id` / `name` / `description`・`want*` / `wantErr`・ループ本体 1 回・`require` / `assert`）の上に、`seed{Table}` → `ids` → `in` → `want{Table}` という usecase 固有の並びを足した形で書く。** ここには usecase のテストに要る分だけを自分の言葉で書く。完全な例は §5。

## 1. 単位とファイル

| 項目 | 規則 |
|---|---|
| テスト関数 | usecase 1 つに `Test{Usecase}_Execute` 1 つ（`TestConfirmReservation_Execute`）。サフィックス付きの 2 つ目を作らない |
| ファイル | usecase の実装ファイルと 1 対 1（`confirm_reservation.go` ↔ `confirm_reservation_test.go`）。複数の usecase を 1 ファイルにまとめない |
| package | `usecase_test`（外部テスト package）。usecase の非公開関数に触れない |
| `main_test.go` | `pool`（または `*rdbtest.DB`）・`TestMain`・起動と組み立てを支える関数だけ（[setup.md](setup.md) §3） |
| ファイルスコープ | `Test*` と（`main_test.go` の）`TestMain` / `pool` 以外を置かない。ヘルパー関数は `rdbtest` / `usecasetest` へ |

## 2. フィールド

識別 → Given → When → Then の順。

| 順 | 区分 | フィールド | 規則 |
|---|---|---|---|
| 1 | 識別 | `id` / `name` / `description` | §3 |
| 2 | Given | `seed{Table} []sqlcgen.{Row}` | 前提の行。テーブルごとに 1 フィールド。観点が読むテーブルだけ。投入しないケースは書かない（nil） |
| 2 | Given | `ids []string` | `IDGenerator` が順に返す固定値。usecase が `IDGenerator` を持つときだけ。ID の生成規則は検証しない |
| 3 | When | `in usecase.{Usecase}Input` | `Execute(ctx, in)` の引数名そのまま。時刻は `in.At` の固定値で渡す。`ctx` はフィールドにせず、ループ本体で `t.Context()` を渡す |
| 4 | Then | `wantErr error` | sentinel（ドメインの `reservation.Err*` か永続化層の `rdb.Err*`）。nil なら成功を期待。usecase が文脈を包んでも `errors.Is` は通る |
| 4 | Then | `want {Output}` | command が返り値を持つなら（`usecase.HoldReservationOutput`）。query は DTO（`query.RoomAvailability`）をそのまま |
| 4 | Then | `want{Table} []sqlcgen.{Row}` | 観点 1・2・4・5 で見るテーブルだけ。全テーブルを見ない。無いことの期待は書かない（nil） |

`in` は共通規則が禁じる「引数の袋」ではない。`Execute` の引数がその struct 1 つで、名前が `in` なので、引数名そのままである。struct のフィールドをテーブルに分解しない（`description` の `When:` と `in` の対応が 1 対 1 になる）。

## 3. ケースの識別

| フィールド | usecase での規則 |
|---|---|
| `id` | 生成した id。usecase の観点は資料の BDD ではないので、`BDD-NNN` を付けない。同じディレクトリの `*_test.go` 全体で一意・不変 |
| `name` | 業務語の 1 文で、読めばどの観点かが分かる（「他の顧客の無断不利用は数えず仮押さえが成立する」→ 協調）。技術語（`nil` / `rollback` / 関数名）を入れない |
| `description` | raw string。`Given:` / `When:` / `Then:` を行頭にこの順で各 1 回。`And:` は空白 2 つで字下げ。拒むケースは `NOTE: Rule:` と `Reason:` を書き、`Reason:` に usecase の配線として何が起きたかを書く |
| 末尾コメント | 「テストしない BDD」の列挙は書かない。usecase のテストは資料の BDD を対象にしない |

`description` の各行はフィールドに写る。`Given:` → `seed{Table}` / `ids`、`When:` → `in`（時刻を含む）、`Then:` → `wantErr` / `want` / `want{Table}`。写せない行があれば、それは usecase の観点ではなく別の層の検証である。

## 4. 表の前とループ本体

| 置き場 | 置いてよいもの | 置かないもの |
|---|---|---|
| 表の前（テスト関数の中） | 複数ケースが共有する時刻の値、前提の行の値（`var ( heldAt = ...; tentative = sqlcgen.Reservation{...} )`） | 関数（クロージャを含む）。表の前の関数はケースから参照され、ファイルスコープのヘルパーと同じになる |
| ループ本体 | `Reset` → `Seed*` → DI → `Execute` → `wantErr` / `want` → `Read*` と `want{Table}` の突き合わせ | ケースを選り分ける分岐（`if tt.id == ...`）、`t.Parallel()` |

```go
	// 実 DB 1 つを package で共有するため直列で走らせる（t.Parallel() は書かない）。
	for _, tt := range tests {
		t.Run(tt.id+" "+tt.name, func(t *testing.T) {
			ctx := t.Context()
			rdbtest.Reset(ctx, t, pool)
			rdbtest.SeedReservations(ctx, t, pool, tt.seedReservations)
			// ... 観点が読むテーブルの Seed を、表のフィールドと同じ数だけ

			sut := usecase.NewConfirmReservation(tx.NewManager(pool), rdb.NewReservationRepository())

			err := sut.Execute(ctx, tt.in)
			if tt.wantErr != nil {
				require.ErrorIs(t, err, tt.wantErr)
			} else {
				require.NoError(t, err)
			}

			assert.Equal(t, tt.wantReservations, rdbtest.ReadReservations(ctx, t, pool))
			// ... 観点が見るテーブルの Read を、表のフィールドと同じ数だけ
		})
	}
```

- `wantErr` のケースでも `Read*` は走る。「拒まれて何も書かれない」が検証そのもの。エラー分岐で `return` しない
- 返り値がある usecase は、エラー時に `assert.Zero(t, got)`、成功時に `assert.Equal(t, tt.want, got)`
- `-run 'TestConfirmReservation_Execute/9f1c2a_'` で 1 ケースだけ走る。`id` の後の区切り `_` まで書く

## 5. 完全な例

題材の usecase の形は [five-viewpoints.md](five-viewpoints.md) §5、`main_test.go` と `usecasetest` は [setup.md](setup.md)。行の型は sqlc が生成した `sqlcgen.*`。無断不利用は資料に無い 9 表目 `reservation_no_show_recorded_events`（詳細イベント表。列は `id` と `base_event_id`）に、基底イベント `reservation_base_events` の `event_type = 'no_show_recorded'` の行とともに残る、と仮定している（題材のデータモデル資料は無断不利用を範囲外にしている。実装時は資料とリポジトリの実装の表に従う）。

### 5.1 `ConfirmReservation` — 入力解決・呼び分け・tx 境界

`confirm_reservation_test.go`:

```go
package usecase_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"example.com/roomflow/rdb"
	"example.com/roomflow/rdb/rdbtest"
	"example.com/roomflow/rdb/sqlcgen"
	"example.com/roomflow/reservation"
	"example.com/roomflow/tx"
	"example.com/roomflow/usecase"
)

func TestConfirmReservation_Execute(t *testing.T) {
	// 複数ケースが共有する時刻と前提の行。表を支える値だけをここに置き、関数は置かない。
	var (
		heldAt      = time.Date(2026, 9, 1, 9, 0, 0, 0, time.UTC)
		deadlineAt  = time.Date(2026, 9, 1, 9, 15, 0, 0, time.UTC)
		confirmAt   = time.Date(2026, 9, 1, 9, 5, 0, 0, time.UTC)
		reconfirmAt = time.Date(2026, 9, 1, 9, 10, 0, 0, time.UTC)
		slotStart   = time.Date(2026, 9, 18, 10, 0, 0, 0, time.UTC)
		slotEnd     = time.Date(2026, 9, 18, 11, 30, 0, 0, time.UTC)

		tentative       = sqlcgen.Reservation{ReservationID: "R-0101", RoomCode: "M-301", CustomerCode: "C-4102", StartsAt: slotStart, EndsAt: slotEnd, Status: "tentative", CurrentVersion: 1, CreatedAt: heldAt, UpdatedAt: heldAt}
		confirmed       = sqlcgen.Reservation{ReservationID: "R-0101", RoomCode: "M-301", CustomerCode: "C-4102", StartsAt: slotStart, EndsAt: slotEnd, Status: "confirmed", CurrentVersion: 2, CreatedAt: heldAt, UpdatedAt: confirmAt}
		deadline        = sqlcgen.TentativeHoldDeadline{ReservationID: "R-0101", ExpiresAt: deadlineAt, CreatedAt: heldAt}
		heldEvent       = sqlcgen.ReservationBaseEvent{ID: 1, ReservationID: "R-0101", EventType: "tentative_created", Version: 1, ActorCode: "C-4102", OccurredAt: heldAt}
		confirmedEvent  = sqlcgen.ReservationBaseEvent{ID: 2, ReservationID: "R-0101", EventType: "confirmed", Version: 2, ActorCode: "C-4102", OccurredAt: confirmAt}
		strayExpired    = sqlcgen.ReservationBaseEvent{ID: 2, ReservationID: "R-0101", EventType: "expired", Version: 2, ActorCode: "期限管理", OccurredAt: deadlineAt} // actor_code "期限管理" は資料の未決（期限切れを記録する主体）。物理設計で値が決まるまでの仮の値で、報告に載せる
		confirmedDetail = sqlcgen.ReservationConfirmedEvent{ID: 1, BaseEventID: 2}
	)

	tests := []struct {
		id                  string
		name                string
		description         string
		seedReservations    []sqlcgen.Reservation               // Given: reservations
		seedDeadlines       []sqlcgen.TentativeHoldDeadline     // Given: tentative_hold_deadlines
		seedBaseEvents      []sqlcgen.ReservationBaseEvent      // Given: reservation_base_events
		seedConfirmedEvents []sqlcgen.ReservationConfirmedEvent // Given: reservation_confirmed_events
		in                  usecase.ConfirmReservationInput     // When:  Execute の引数名そのまま
		wantErr             error                               // Then:  nil なら成功を期待
		wantReservations    []sqlcgen.Reservation               // Then:  観点 1・4・5 で見る
		wantConfirmedEvents []sqlcgen.ReservationConfirmedEvent // Then:  観点 5 で見る。無ければ書かない
	}{
		{
			id:   "9f1c2a",
			name: "予約番号が空なら入力の時点で拒まれ、予約は探されない",
			description: `Given: 仮押さえ予約 R-0101 がある
When: 予約番号を空にして予約者 C-4102 が確定する
Then: 予約番号が空のため拒まれる
  And: 予約 R-0101 は仮押さえのまま変わらず、確定イベントは積まれない
  NOTE: Rule: 入力が値オブジェクトに拒まれたらリポジトリへ進まない
    Reason: 予約番号が空で予約を指せないため。届いていれば「予約が見つからない」になる`,
			seedReservations: []sqlcgen.Reservation{tentative},
			seedDeadlines:    []sqlcgen.TentativeHoldDeadline{deadline},
			seedBaseEvents:   []sqlcgen.ReservationBaseEvent{heldEvent},
			in:               usecase.ConfirmReservationInput{ReservationID: "", CustomerID: "C-4102", At: confirmAt},
			wantErr:          reservation.ErrIDRequired,
			wantReservations: []sqlcgen.Reservation{tentative},
		},
		{
			id:   "4be7d0",
			name: "仮押さえ予約を確定すると確定予約になり確定イベントが 1 行積まれる",
			description: `Given: 仮押さえ予約 R-0101 がある
  And: 仮押さえ期限は 2026年9月1日 09:15 である
When: 予約者 C-4102 が 2026年9月1日 09:05 に確定する
Then: 予約 R-0101 は version 2 の確定予約になる
  And: 確定イベントが 1 行積まれる`,
			seedReservations:    []sqlcgen.Reservation{tentative},
			seedDeadlines:       []sqlcgen.TentativeHoldDeadline{deadline},
			seedBaseEvents:      []sqlcgen.ReservationBaseEvent{heldEvent},
			in:                  usecase.ConfirmReservationInput{ReservationID: "R-0101", CustomerID: "C-4102", At: confirmAt},
			wantReservations:    []sqlcgen.Reservation{confirmed},
			wantConfirmedEvents: []sqlcgen.ReservationConfirmedEvent{confirmedDetail},
		},
		{
			id:   "c03a8e",
			name: "確定済みの予約を再確定しても何も書かれない",
			description: `Given: 確定予約 R-0101 がある
  And: 確定イベントは 1 行積まれている
When: 予約者 C-4102 が 2026年9月1日 09:10 にもう一度確定する
Then: 確定済みのため拒まれる
  And: 予約 R-0101 は version 2 の確定予約のままで、確定イベントは 1 行のまま
  NOTE: Rule: 確定済み予約の再確定は拒む
    Reason: 復元した予約が仮押さえ予約へ絞り込めず、操作にも保存にも進まないため`,
			seedReservations:    []sqlcgen.Reservation{confirmed},
			seedBaseEvents:      []sqlcgen.ReservationBaseEvent{heldEvent, confirmedEvent},
			seedConfirmedEvents: []sqlcgen.ReservationConfirmedEvent{confirmedDetail},
			in:                  usecase.ConfirmReservationInput{ReservationID: "R-0101", CustomerID: "C-4102", At: reconfirmAt},
			wantErr:             reservation.ErrAlreadyConfirmed,
			wantReservations:    []sqlcgen.Reservation{confirmed},
			wantConfirmedEvents: []sqlcgen.ReservationConfirmedEvent{confirmedDetail},
		},
		{
			id:   "e71b45",
			name: "保存が途中で失敗すると予約は仮押さえのまま何も反映されない",
			description: `Given: 仮押さえ予約 R-0101 がある
  And: 基底イベントには version 2 が先に積まれている（現在の姿と食い違う前提）
When: 予約者 C-4102 が 2026年9月1日 09:05 に確定する
Then: 別の操作で更新されたとして拒まれる
  And: 予約 R-0101 は version 1 の仮押さえのままで、確定イベントは積まれない
  NOTE: Rule: Run の中は全成功か全未反映
    Reason: 現在の姿の更新と期限の削除が成功した後、基底イベント version 2 の追記が一意制約に弾かれ、成功した分も巻き戻るため`,
			seedReservations: []sqlcgen.Reservation{tentative},
			seedDeadlines:    []sqlcgen.TentativeHoldDeadline{deadline},
			seedBaseEvents:   []sqlcgen.ReservationBaseEvent{heldEvent, strayExpired},
			in:               usecase.ConfirmReservationInput{ReservationID: "R-0101", CustomerID: "C-4102", At: confirmAt},
			wantErr:          rdb.ErrConflict,
			wantReservations: []sqlcgen.Reservation{tentative},
		},
	}

	// 実 DB 1 つを package で共有するため直列で走らせる（t.Parallel() は書かない）。
	for _, tt := range tests {
		t.Run(tt.id+" "+tt.name, func(t *testing.T) {
			ctx := t.Context()
			rdbtest.Reset(ctx, t, pool)
			rdbtest.SeedReservations(ctx, t, pool, tt.seedReservations)
			rdbtest.SeedTentativeHoldDeadlines(ctx, t, pool, tt.seedDeadlines)
			rdbtest.SeedReservationBaseEvents(ctx, t, pool, tt.seedBaseEvents)
			rdbtest.SeedReservationConfirmedEvents(ctx, t, pool, tt.seedConfirmedEvents)

			// 本番と同じコンストラクタで組み立てる。差し替えは無い。
			sut := usecase.NewConfirmReservation(tx.NewManager(pool), rdb.NewReservationRepository())

			err := sut.Execute(ctx, tt.in)
			if tt.wantErr != nil {
				require.ErrorIs(t, err, tt.wantErr)
			} else {
				require.NoError(t, err)
			}

			// 観点で見るテーブルだけを読む。全テーブルの突き合わせは永続化層のテストの責務。
			assert.Equal(t, tt.wantReservations, rdbtest.ReadReservations(ctx, t, pool))
			assert.Equal(t, tt.wantConfirmedEvents, rdbtest.ReadReservationConfirmedEvents(ctx, t, pool))
		})
	}
}
```

| ケース | 観点 | Given に置いた理由 | Then で見た理由 |
|---|---|---|---|
| `9f1c2a` | 1 入力解決 | 正しい入力なら成功する前提。届いたら `ErrNotFound` ではなく成功か別の結果になる | `ErrIDRequired` が返り、行が変わらない＝リポジトリに届いていない |
| `4be7d0` | 5 呼び分け（＋4 commit） | 復元と `AsTentative` が通る仮押さえの 3 行 | `confirmed` の行と確定イベント 1 行＝`ApplyConfirmed` が呼ばれ commit された |
| `c03a8e` | 5 呼び分け | `AsTentative` が拒む確定予約 | `ErrAlreadyConfirmed` が素通しで返り、行が変わらない＝保存に進んでいない |
| `e71b45` | 4 rollback | 3 手目の INSERT を一意制約で失敗させる `strayExpired` | 1 手目の UPDATE が成功したのに `tentative` のまま＝`Run` が巻き戻した |

`e71b45` の前提は資料の不変条件「現在 version は最後のイベント version と一致する」を破っている。これは途中失敗を mock 無しで起こすための手段で、`description` の `NOTE:` にそう書く。他の手（期限の DELETE・確定イベントの INSERT）で失敗させるケースを足さない。どの手で失敗しても `Run` の振る舞いは同じである。

### 5.2 `HoldReservation` — 複数集約の協調

`hold_reservation_test.go`:

```go
package usecase_test

import (
	"slices"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	query "example.com/roomflow/reservation/query"
	"example.com/roomflow/rdb"
	"example.com/roomflow/rdb/rdbtest"
	"example.com/roomflow/rdb/sqlcgen"
	"example.com/roomflow/reservation"
	"example.com/roomflow/tx"
	"example.com/roomflow/usecase"
	"example.com/roomflow/usecase/usecasetest"
)

func TestHoldReservation_Execute(t *testing.T) {
	var (
		now       = time.Date(2026, 9, 1, 9, 0, 0, 0, time.UTC)
		expiresAt = now.Add(15 * time.Minute)
		slotStart = time.Date(2026, 9, 18, 10, 0, 0, 0, time.UTC)
		slotEnd   = time.Date(2026, 9, 18, 11, 30, 0, 0, time.UTC)
		noShow1   = time.Date(2026, 8, 10, 10, 16, 0, 0, time.UTC)
		noShow2   = time.Date(2026, 8, 17, 10, 16, 0, 0, time.UTC)
		noShow3   = time.Date(2026, 8, 24, 10, 16, 0, 0, time.UTC)

		// 顧客 C-5821 の確定予約 3 件に無断不利用が記録されている。
		// 直近 30 日に 3 回で、3 回目（8月24日）から 14 日以内なので、9月1日 の C-5821 は仮押さえ停止中。
		// 読まれるのは無断不利用のイベントだけなので、version 1・2 のイベントは置かない（観点が読む行だけを投入する）。
		// actor_code "不利用判定" は資料の未決（無断不利用を記録する主体）。物理設計で値が決まるまでの仮の値で、報告に載せる。
		noShowHistory = []sqlcgen.Reservation{
			{ReservationID: "R-0101", RoomCode: "M-301", CustomerCode: "C-5821", StartsAt: time.Date(2026, 8, 10, 10, 0, 0, 0, time.UTC), EndsAt: time.Date(2026, 8, 10, 11, 0, 0, 0, time.UTC), Status: "confirmed", CurrentVersion: 3, CreatedAt: time.Date(2026, 8, 1, 9, 0, 0, 0, time.UTC), UpdatedAt: noShow1},
			{ReservationID: "R-0102", RoomCode: "M-301", CustomerCode: "C-5821", StartsAt: time.Date(2026, 8, 17, 10, 0, 0, 0, time.UTC), EndsAt: time.Date(2026, 8, 17, 11, 0, 0, 0, time.UTC), Status: "confirmed", CurrentVersion: 3, CreatedAt: time.Date(2026, 8, 1, 9, 0, 0, 0, time.UTC), UpdatedAt: noShow2},
			{ReservationID: "R-0103", RoomCode: "M-301", CustomerCode: "C-5821", StartsAt: time.Date(2026, 8, 24, 10, 0, 0, 0, time.UTC), EndsAt: time.Date(2026, 8, 24, 11, 0, 0, 0, time.UTC), Status: "confirmed", CurrentVersion: 3, CreatedAt: time.Date(2026, 8, 1, 9, 0, 0, 0, time.UTC), UpdatedAt: noShow3},
		}
		noShowBaseEvents = []sqlcgen.ReservationBaseEvent{
			{ID: 1, ReservationID: "R-0101", EventType: "no_show_recorded", Version: 3, ActorCode: "不利用判定", OccurredAt: noShow1},
			{ID: 2, ReservationID: "R-0102", EventType: "no_show_recorded", Version: 3, ActorCode: "不利用判定", OccurredAt: noShow2},
			{ID: 3, ReservationID: "R-0103", EventType: "no_show_recorded", Version: 3, ActorCode: "不利用判定", OccurredAt: noShow3},
		}
		noShowEvents = []sqlcgen.ReservationNoShowRecordedEvent{
			{ID: 1, BaseEventID: 1}, {ID: 2, BaseEventID: 2}, {ID: 3, BaseEventID: 3},
		}

		// 顧客 C-5821 の確定予約 R-0101 が M-301 の 9月18日 10:00 から 11:00 を占有している。
		occupying      = sqlcgen.Reservation{ReservationID: "R-0101", RoomCode: "M-301", CustomerCode: "C-5821", StartsAt: slotStart, EndsAt: time.Date(2026, 9, 18, 11, 0, 0, 0, time.UTC), Status: "confirmed", CurrentVersion: 2, CreatedAt: time.Date(2026, 8, 25, 9, 0, 0, 0, time.UTC), UpdatedAt: time.Date(2026, 8, 25, 9, 5, 0, 0, time.UTC)}
		occupyingClaim = sqlcgen.RoomBookingClaim{ReservationID: "R-0101", RoomCode: "M-301", StartsAt: slotStart, EndsAt: time.Date(2026, 9, 18, 11, 0, 0, 0, time.UTC), CreatedAt: time.Date(2026, 8, 25, 9, 0, 0, 0, time.UTC)}
	)

	tests := []struct {
		id               string
		name             string
		description      string
		seedReservations []sqlcgen.Reservation                    // Given: reservations（読まれる側の集約の行）
		seedClaims       []sqlcgen.RoomBookingClaim               // Given: room_booking_claims
		seedBaseEvents   []sqlcgen.ReservationBaseEvent           // Given: reservation_base_events（無断不利用の基底イベント）
		seedNoShowEvents []sqlcgen.ReservationNoShowRecordedEvent // Given: reservation_no_show_recorded_events
		ids              []string                                 // Given: 採番器が順に返す予約番号
		in               usecase.HoldReservationInput             // When:  Execute の引数名そのまま。At は判定時刻の固定値
		want             usecase.HoldReservationOutput            // Then:  成功時の返り値
		wantErr          error                                    // Then:  nil なら成功を期待
		wantReservations []sqlcgen.Reservation                    // Then:  観点 2 で見る
	}{
		{
			id:   "b2d90f",
			name: "直近 30 日に無断不利用が 3 回ある顧客は仮押さえできない",
			description: `Given: 顧客 C-5821 の確定予約 3 件に 2026年8月10日・8月17日・8月24日 の無断不利用が記録されている
  And: M-301 の 2026年9月18日 10:00 から 11:30 に有効な予約はない
When: C-5821 が 2026年9月1日 09:00 に M-301 の 2026年9月18日 10:00 から 11:30 を仮押さえする
Then: 仮押さえ停止中のため拒まれる
  And: 予約は 3 件のままで新しい行は増えない
  NOTE: Rule: 仮押さえ停止中顧客による新しい申込みは拒む
    Reason: usecase が同じ顧客の予約の無断不利用イベントから時刻を集めて資格を導き、停止中と判定されたため`,
			seedReservations: noShowHistory,
			seedBaseEvents:   noShowBaseEvents,
			seedNoShowEvents: noShowEvents,
			ids:              []string{"R-0201"},
			in:               usecase.HoldReservationInput{CustomerID: "C-5821", RoomCode: "M-301", StartsAt: slotStart, EndsAt: slotEnd, At: now},
			wantErr:          reservation.ErrCustomerSuspended,
			wantReservations: noShowHistory,
		},
		{
			id:   "5a6c13",
			name: "他の顧客の無断不利用は数えず仮押さえが成立する",
			description: `Given: 顧客 C-5821 の確定予約 3 件に無断不利用が記録されている
  And: 顧客 C-4102 の予約に無断不利用はない
  And: M-301 の 2026年9月18日 10:00 から 11:30 に有効な予約はない
When: C-4102 が 2026年9月1日 09:00 に M-301 の 2026年9月18日 10:00 から 11:30 を仮押さえする
Then: C-4102 に予約番号 R-0201 の仮押さえ予約が成立し、仮押さえ期限は 2026年9月1日 09:15 である
  And: 予約は 4 件になり、C-5821 の 3 件は変わらない`,
			seedReservations: noShowHistory,
			seedBaseEvents:   noShowBaseEvents,
			seedNoShowEvents: noShowEvents,
			ids:              []string{"R-0201"},
			in:               usecase.HoldReservationInput{CustomerID: "C-4102", RoomCode: "M-301", StartsAt: slotStart, EndsAt: slotEnd, At: now},
			want:             usecase.HoldReservationOutput{ReservationID: "R-0201", ExpiresAt: expiresAt},
			wantReservations: slices.Concat(noShowHistory, []sqlcgen.Reservation{
				{ReservationID: "R-0201", RoomCode: "M-301", CustomerCode: "C-4102", StartsAt: slotStart, EndsAt: slotEnd, Status: "tentative", CurrentVersion: 1, CreatedAt: now, UpdatedAt: now},
			}),
		},
		{
			id:   "d48e27",
			name: "同じ会議室の有効な予約と重なる利用枠は仮押さえできない",
			description: `Given: M-301 では C-5821 の確定予約 R-0101 が 2026年9月18日 10:00 から 11:00 を占有している
When: C-4102 が 2026年9月1日 09:00 に M-301 の 2026年9月18日 10:30 から 11:30 を仮押さえする
Then: 重なる利用枠のため拒まれる
  And: 予約は R-0101 の 1 件のまま
  NOTE: Rule: 同じ会議室の重なる利用枠へ、現在有効な予約は一つしか存在しない
    Reason: usecase が同じ会議室の重なる利用枠の占有を集めて重なりを確かめ、生成に進まないため`,
			seedReservations: []sqlcgen.Reservation{occupying},
			seedClaims:       []sqlcgen.RoomBookingClaim{occupyingClaim},
			ids:              []string{"R-0201"},
			in:               usecase.HoldReservationInput{CustomerID: "C-4102", RoomCode: "M-301", StartsAt: time.Date(2026, 9, 18, 10, 30, 0, 0, time.UTC), EndsAt: slotEnd, At: now},
			wantErr:          reservation.ErrOverlappingSlot,
			wantReservations: []sqlcgen.Reservation{occupying},
		},
	}

	// 実 DB 1 つを package で共有するため直列で走らせる（t.Parallel() は書かない）。
	for _, tt := range tests {
		t.Run(tt.id+" "+tt.name, func(t *testing.T) {
			ctx := t.Context()
			rdbtest.Reset(ctx, t, pool)
			rdbtest.SeedReservations(ctx, t, pool, tt.seedReservations)
			rdbtest.SeedRoomBookingClaims(ctx, t, pool, tt.seedClaims)
			rdbtest.SeedReservationBaseEvents(ctx, t, pool, tt.seedBaseEvents)
			rdbtest.SeedReservationNoShowRecordedEvents(ctx, t, pool, tt.seedNoShowEvents)

			// 本番と同じコンストラクタ。差し替えは採番器だけ。読み取りポートは query service の実物。
			sut := usecase.NewHoldReservation(
				tx.NewManager(pool),
				rdb.NewReservationRepository(),
				query.NewActiveReservationQuery(pool),
				query.NewNoShowQuery(pool),
				usecasetest.FixedIDs(t, tt.ids...),
			)

			got, err := sut.Execute(ctx, tt.in)
			if tt.wantErr != nil {
				require.ErrorIs(t, err, tt.wantErr)
				assert.Zero(t, got)
			} else {
				require.NoError(t, err)
				assert.Equal(t, tt.want, got)
			}

			assert.Equal(t, tt.wantReservations, rdbtest.ReadReservations(ctx, t, pool))
		})
	}
}
```

| ケース | 観点 | Given に置いた理由 | Then で見た理由 |
|---|---|---|---|
| `b2d90f` | 2 協調（資格の導出） | 読まれる側＝同じ顧客の予約の無断不利用イベント 3 件 | `ErrCustomerSuspended`＝その記録が `NewEligibility` に渡った。行が増えていない |
| `5a6c13` | 2 協調（他人の記録は数えない）＋4 commit | 同じ 3 件を置き、申込者だけ変える | 成立して 4 件目が見え、期限が `At` の 15 分後＝他の顧客の記録は渡っていない。commit された |
| `d48e27` | 2 協調（重なり検査） | 読まれる側＝同じ会議室の占有中の利用枠 | `ErrOverlappingSlot`＝占有中の利用枠が `Overlaps` に渡った。行が増えていない |

`b2d90f` と `5a6c13` は同じ前提で申込者だけが違う。これは「同じルールで入力値だけ変えた」のではなく、「どの顧客の記録を集めたか」という配線の分岐である。30 日・3 回・14 日の境界は `NewEligibility` のテスト（ドメイン層）が持つので、ここで日付を動かしたケースを足さない。隣接する利用枠（重ならない）のケースも足さない。それは `Overlaps` のテスト（ドメイン層）が持つ。

## 6. query usecase の形

query usecase（一覧・件数を DTO で返す）の表は、`seed{Table}` → `in` → `want`（DTO）/ `wantErr` で、`want{Table}` を持たない（書き込みが無い）。

| フィールド | 規則 |
|---|---|
| `seed{Table}` | 読まれるソースの行。ソース選択（観点 3）があるなら、選ばれる側と選ばれない側の両方に、区別できる値の行を置く |
| `in` | `Execute` の引数名そのまま。入力解決（観点 1）があるなら、解決結果で読まれる行が変わる前提を置く |
| `want` | usecase側が所有する読み取りモデル（`query.RoomAvailability`）。usecaseが読み取りポートの返り値を組み替えないので、`want`は契約の型と同じ形になる |
| `wantErr` | 入力解決の sentinel。query service の error は素通し |

ループ本体は `Reset` → `Seed*` → DI（`usecase.New{Usecase}(query.New{Query}(pool))`）→ `Execute` → `require.NoError` / `require.ErrorIs` → `assert.Equal(t, tt.want, got)`。SQL の正しさ（JOIN / WHERE / 並び順）は永続化層のテストが見るので、ここでは「解決した入力を渡した結果、選ばれたソースの行が DTO に現れる」ことだけを見る。
