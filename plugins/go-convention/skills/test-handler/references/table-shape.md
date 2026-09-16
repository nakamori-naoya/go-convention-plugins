# テーブルの形

**Given は投入する行と主体、When は proto の request、Then は Code・公開文言・応答の射影・反映の射影。** 無名 struct のスライスに識別 → Given → When → Then の順で置き、実行と検証はループ本体に 1 回書く。表の値はすべてデータで、`setup` は使わない（資源は `newTestServer(t)` と `pool` が持つ）。

## 1. フィールド

| 順 | 区分 | フィールド | 型 | 規則 |
|---|---|---|---|---|
| 1 | 識別 | `id` / `name` / `description` | `string` | この 3 つ・この順。API 仕様の資料があるならそこから写し、無ければ生成した id・業務語の 1 文・Given / When / Then |
| 2 | Given | `seed{Table}` | `[]sqlcgen.{Row}` | RPC が読む行と、書き込みが DB 制約で要求する行だけ。テーブルごとに 1 フィールドで、投入は永続化層のテスト支援 `rdbtest.Seed{Table}` |
| 2 | Given | `caller` | `string` | 主体の識別子。空は主体無し |
| 3 | When | `req` | `*roomflowv1.{RPC}Request` | proto そのもの。変換前の値を表に書く |
| 4 | Then | `wantCode` | `connect.Code` | 0 は成功。`connect` に値 0 の Code は無い |
| 4 | Then | `wantMessage` | `string` | 公開された sentinel の `.Error()`。空なら見ない（主体無しのように、文言が公開 API の契約でないケース）。handler の欠け sentinel が非公開で参照できないなら、公開するよう実装側へ返す |
| 4 | Then | `wantResp` | 射影の struct | 成功時の応答。値が入るフィールドだけを持つ struct をテスト関数の中で宣言する。応答が空の message（`ConfirmReservationResponse`）なら持たない |
| 4 | Then | `want{Table}` | `[]{射影}` | 成功時に反映が起きるテーブルだけ。識別子・状態・版の射影。拒否ケースには書かない |

| 使わない | 代わりに | 理由 |
|---|---|---|
| `wantErr error` | `wantCode` + `wantMessage` | クライアントに届くのは sentinel ではなく `*connect.Error`。`errors.Is(err, reservation.ErrNotOwner)` は HTTP を越えると偽になる |
| `wantErr bool` / `errContains` | `wantCode` + `wantMessage` | Code が違っても緑になる。文言は完全一致で、sentinel の `.Error()` を参照する |
| `setup func(t *testing.T) fixture` | `newTestServer(t)` と `pool` | 資源は全ケースで同じ。ケースごとに違う Given は行と主体のデータで書ける |
| `*roomflowv1.{RPC}Response` の `wantResp` | 射影の struct | proto message を `assert.Equal` すると内部フィールドで不一致になる |
| `[]sqlcgen.{Row}` の `want{Table}` | 射影の struct | 全カラムの突き合わせは永続化層のテストの関心。`updated_at` の値まで見ると、このテストが usecase の時刻の扱いを再検証することになる |
| `at` / `now` のフィールド | 固定 `Clock`（`main_test.go` の `now`）。期限前・期限後は前提の `expires_at` を `now` の前後に置いて表す | 時刻は server が決め、要求は運ばない。表に別の時刻を持つと、どちらが効いたか読めない。ケースごとに server を作らない |

## 2. 題材の完全な例 — `ConfirmReservation`

`handler/reservation_server_test.go`。`main_test.go`（`pool` / `now` / `newTestServer`）は [server-setup.md](server-setup.md) §2。

```go
package handler_test

import (
	"errors"
	"testing"
	"time"

	"connectrpc.com/connect"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"example.com/roomflow/gen/roomflowv1"
	"example.com/roomflow/handler/handlertest"
	"example.com/roomflow/rdb"
	"example.com/roomflow/rdb/rdbtest"
	"example.com/roomflow/rdb/sqlcgen"
	"example.com/roomflow/reservation"
)

func TestReservationServer_ConfirmReservation(t *testing.T) {
	// 応答は空の message なので、応答の射影は持たない（採番する RPC の射影は §4）。

	// reservationState は reservations の射影。反映の有無を識別子・状態・版で見る。
	type reservationState struct {
		ID      string
		Status  string
		Version int32
	}

	tests := []struct {
		id                         string
		name                       string
		description                string
		seedReservations           []sqlcgen.Reservation                 // Given: reservations の前提行
		seedTentativeHoldDeadlines []sqlcgen.TentativeHoldDeadline       // Given: tentative_hold_deadlines の前提行
		caller                     string                                // Given: 主体。空は主体無し
		req                        *roomflowv1.ConfirmReservationRequest // When
		wantCode                   connect.Code                          // Then: 0 は成功
		wantMessage                string                                // Then: 公開文言。空なら見ない
		wantReservations           []reservationState                    // Then: 成功時に reservations で確かめる射影
	}{
		{
			id:   "c4e1a8",
			name: "期限前の仮押さえ予約を予約者が確定できる",
			description: `Given: 予約 R-20260901-0101 は顧客 C-4102 の仮押さえ予約で、仮押さえ期限は 2026年9月1日 09:15 である
  And: 現在時刻は 2026年9月1日 09:05 である
When: C-4102 が R-20260901-0101 の確定を求める
Then: 成功する
  And: reservations の R-20260901-0101 は確定予約で、現在 version は 2 になる`,
			seedReservations: []sqlcgen.Reservation{{
				ReservationID:  "R-20260901-0101",
				RoomCode:       "M-301",
				CustomerCode:   "C-4102",
				StartsAt:       time.Date(2026, 9, 18, 10, 0, 0, 0, time.UTC),
				EndsAt:         time.Date(2026, 9, 18, 11, 30, 0, 0, time.UTC),
				Status:         "tentative",
				CurrentVersion: 1,
				CreatedAt:      time.Date(2026, 9, 1, 9, 0, 0, 0, time.UTC),
				UpdatedAt:      time.Date(2026, 9, 1, 9, 0, 0, 0, time.UTC),
			}},
			seedTentativeHoldDeadlines: []sqlcgen.TentativeHoldDeadline{{
				ReservationID: "R-20260901-0101",
				ExpiresAt:     time.Date(2026, 9, 1, 9, 15, 0, 0, time.UTC),
				CreatedAt:     time.Date(2026, 9, 1, 9, 0, 0, 0, time.UTC),
			}},
			caller:           "C-4102",
			req:              &roomflowv1.ConfirmReservationRequest{ReservationId: "R-20260901-0101"},
			wantReservations: []reservationState{{ID: "R-20260901-0101", Status: "confirmed", Version: 2}},
		},
		{
			id:   "7d0f2b",
			name: "仮押さえ期限を過ぎた確定は成立しない",
			description: `Given: 予約 R-20260901-0101 は顧客 C-4102 の仮押さえ予約で、仮押さえ期限は 2026年9月1日 09:00 である
  And: 現在時刻は 2026年9月1日 09:05 である
When: C-4102 が R-20260901-0101 の確定を求める
Then: FailedPrecondition で拒まれ、文言は「仮押さえ期限以降は確定できない」である
  NOTE: Rule: 確定予約は仮押さえ期限より前にだけ成立する
    Reason: 現在時刻が期限より後で、確定できる期間に含まれないため`,
			seedReservations: []sqlcgen.Reservation{{
				ReservationID:  "R-20260901-0101",
				RoomCode:       "M-301",
				CustomerCode:   "C-4102",
				StartsAt:       time.Date(2026, 9, 18, 10, 0, 0, 0, time.UTC),
				EndsAt:         time.Date(2026, 9, 18, 11, 30, 0, 0, time.UTC),
				Status:         "tentative",
				CurrentVersion: 1,
				CreatedAt:      time.Date(2026, 9, 1, 9, 0, 0, 0, time.UTC),
				UpdatedAt:      time.Date(2026, 9, 1, 9, 0, 0, 0, time.UTC),
			}},
			seedTentativeHoldDeadlines: []sqlcgen.TentativeHoldDeadline{{
				ReservationID: "R-20260901-0101",
				ExpiresAt:     time.Date(2026, 9, 1, 9, 0, 0, 0, time.UTC), // now（09:05）より前
				CreatedAt:     time.Date(2026, 9, 1, 8, 45, 0, 0, time.UTC),
			}},
			caller:      "C-4102",
			req:         &roomflowv1.ConfirmReservationRequest{ReservationId: "R-20260901-0101"},
			wantCode:    connect.CodeFailedPrecondition,
			wantMessage: reservation.ErrHoldDeadlinePassed.Error(),
		},
		{
			id:   "e93a61",
			name: "他人の仮押さえ予約は確定できない",
			description: `Given: 予約 R-20260901-0101 は顧客 C-4102 の仮押さえ予約で、仮押さえ期限は 2026年9月1日 09:15 である
  And: 現在時刻は 2026年9月1日 09:05 である
When: 別の顧客 C-5821 が R-20260901-0101 の確定を求める
Then: PermissionDenied で拒まれ、文言は「他人の予約は操作できない」である
  NOTE: Rule: 仮押さえ予約を確定できるのはその予約の予約者だけである
    Reason: 求めたのが予約者本人ではなく、本人の利用意思を第三者が示そうとしているため`,
			seedReservations: []sqlcgen.Reservation{{
				ReservationID:  "R-20260901-0101",
				RoomCode:       "M-301",
				CustomerCode:   "C-4102",
				StartsAt:       time.Date(2026, 9, 18, 10, 0, 0, 0, time.UTC),
				EndsAt:         time.Date(2026, 9, 18, 11, 30, 0, 0, time.UTC),
				Status:         "tentative",
				CurrentVersion: 1,
				CreatedAt:      time.Date(2026, 9, 1, 9, 0, 0, 0, time.UTC),
				UpdatedAt:      time.Date(2026, 9, 1, 9, 0, 0, 0, time.UTC),
			}},
			seedTentativeHoldDeadlines: []sqlcgen.TentativeHoldDeadline{{
				ReservationID: "R-20260901-0101",
				ExpiresAt:     time.Date(2026, 9, 1, 9, 15, 0, 0, time.UTC),
				CreatedAt:     time.Date(2026, 9, 1, 9, 0, 0, 0, time.UTC),
			}},
			caller:      "C-5821",
			req:         &roomflowv1.ConfirmReservationRequest{ReservationId: "R-20260901-0101"},
			wantCode:    connect.CodePermissionDenied,
			wantMessage: reservation.ErrNotOwner.Error(),
		},
		{
			id:   "d8b72c",
			name: "確定済みの予約は再確定できない",
			description: `Given: 予約 R-20260901-0101 は顧客 C-4102 の確定済み予約である
When: C-4102 が R-20260901-0101 の確定を再び求める
Then: FailedPrecondition で拒まれ、文言は「確定済みの予約は再確定できない」である`,
			seedReservations: []sqlcgen.Reservation{{
				ReservationID:  "R-20260901-0101",
				RoomCode:       "M-301",
				CustomerCode:   "C-4102",
				StartsAt:       time.Date(2026, 9, 18, 10, 0, 0, 0, time.UTC),
				EndsAt:         time.Date(2026, 9, 18, 11, 30, 0, 0, time.UTC),
				Status:         "confirmed",
				CurrentVersion: 2,
				CreatedAt:      time.Date(2026, 9, 1, 9, 0, 0, 0, time.UTC),
				UpdatedAt:      time.Date(2026, 9, 1, 9, 5, 0, 0, time.UTC),
			}},
			caller:      "C-4102",
			req:         &roomflowv1.ConfirmReservationRequest{ReservationId: "R-20260901-0101"},
			wantCode:    connect.CodeFailedPrecondition,
			wantMessage: reservation.ErrAlreadyConfirmed.Error(),
		},
		{
			id:   "52b7c0",
			name: "存在しない予約は確定できない",
			description: `Given: 予約は 1 件も無い
When: C-4102 が R-20260901-0999 の確定を求める
Then: NotFound で拒まれ、文言は「対象が見つからない」である`,
			caller:      "C-4102",
			req:         &roomflowv1.ConfirmReservationRequest{ReservationId: "R-20260901-0999"},
			wantCode:    connect.CodeNotFound,
			wantMessage: rdb.ErrNotFound.Error(),
		},
		{
			id:   "a1d48e",
			name: "予約番号が空の確定は受け付けない",
			description: `Given: 予約は 1 件も無い
When: C-4102 が予約番号を空にして確定を求める
Then: InvalidArgument で拒まれ、文言は「予約番号が空の予約は作れない」である`,
			caller:      "C-4102",
			req:         &roomflowv1.ConfirmReservationRequest{ReservationId: ""},
			wantCode:    connect.CodeInvalidArgument,
			wantMessage: reservation.ErrIDRequired.Error(),
		},
		{
			id:   "f06c93",
			name: "主体が無い確定は受け付けない",
			description: `Given: 主体が指定されていない
When: 誰でもない呼び手が R-20260901-0101 の確定を求める
Then: Unauthenticated で拒まれる`,
			req:      &roomflowv1.ConfirmReservationRequest{ReservationId: "R-20260901-0101"},
			wantCode: connect.CodeUnauthenticated,
		},
	}

	client := newTestServer(t)

	// 同じ PostgreSQL（pool）を共有し、各ケースが Reset するため直列で走らせる。
	for _, tt := range tests {
		t.Run(tt.id+" "+tt.name, func(t *testing.T) {
			ctx := t.Context()
			rdbtest.Reset(ctx, t, pool)
			rdbtest.SeedReservations(ctx, t, pool, tt.seedReservations)
			rdbtest.SeedTentativeHoldDeadlines(ctx, t, pool, tt.seedTentativeHoldDeadlines)

			req := connect.NewRequest(tt.req)
			if tt.caller != "" {
				req.Header().Set(handlertest.CallerHeader, tt.caller)
			}
			got, err := client.ConfirmReservation(ctx, req)
			if tt.wantCode != 0 {
				require.Error(t, err)
				assert.Equal(t, tt.wantCode, connect.CodeOf(err))
				if tt.wantMessage != "" {
					cerr, ok := errors.AsType[*connect.Error](err)
					require.True(t, ok)
					assert.Equal(t, tt.wantMessage, cerr.Message())
				}
				assert.Nil(t, got)
				return
			}
			require.NoError(t, err)
			require.NotNil(t, got) // 応答は空の message。届いたことだけを見る

			// 反映は成功ケースだけ、反映が起きるテーブルだけを射影で見る。
			var gotReservations []reservationState
			for _, row := range rdbtest.ReadReservations(ctx, t, pool) {
				gotReservations = append(gotReservations, reservationState{
					ID:      row.ReservationID,
					Status:  row.Status,
					Version: row.CurrentVersion,
				})
			}
			assert.Equal(t, tt.wantReservations, gotReservations)
		})
	}
}
```

題材の proto（`roomflow.v1`）は `ConfirmReservationRequest { string reservation_id = 1; }` と `ConfirmReservationResponse {}`（空）。確定の時刻は server の `Clock`（`main_test.go` の `now` = 09:05）が決め、要求は運ばない。期限前・期限後の違いは前提の `tentative_hold_deadlines.expires_at` を `now` の後（09:15）と前（09:00）に置いて表す。`sqlcgen.Reservation` / `sqlcgen.TentativeHoldDeadline` は sqlc が生成した行の型で、NOT NULL の `timestamptz` は `time.Time`。

## 3. ループ本体

| 順 | すること | 規則 |
|---|---|---|
| 1 | `rdbtest.Reset(ctx, t, pool)` | 全テーブルを空にする。前のケースの行を残さない |
| 2 | `rdbtest.Seed{Table}(ctx, t, pool, tt.seed{Table})` | 表にある `seed{Table}` を全部、表の順に投入する。空スライスの投入は何もしない |
| 3 | `connect.NewRequest(tt.req)` に主体ヘッダを付けて呼ぶ | `caller` が空ならヘッダを付けない |
| 4 | `wantCode != 0` なら `require.Error` → `connect.CodeOf` → `wantMessage` があれば `Message()` → `assert.Nil(got)` → `return` | 成功の判定を先に `wantCode` で分岐する。`connect.CodeOf(nil)` は `CodeUnknown` を返すので、Code で成功を判定しない。エラー時に応答が nil であることも見る |
| 5 | `require.NoError` → `wantResp` を射影で突き合わせ | `got.Msg` の getter から射影 struct を作る。応答が空の message なら `require.NotNil(t, got)` だけ |
| 6 | `want{Table}` を読み取り関数の結果の射影と突き合わせ | 成功ケースだけ。観測した値を集める変数はゼロ値から始める（`var gotReservations []reservationState`） |

- ケースを選り分ける分岐（`if tt.id == ...`）を書かない。ケース固有のことはフィールドに戻す
- `t.Context()` を ctx にする。キャンセルの持ち主はサブテスト
- `verify` は使わない。この層の Then は Code・文言・射影で全部データとして書ける

## 4. 採番する RPC（仮押さえ）の応答と反映 — `wantResp` の例

`HoldReservation` のように識別子を server 側で採番する RPC は、応答の識別子を表に書けない。応答の射影から採番された値を除き、ループ本体で「応答の識別子 = 反映した行の識別子」を突き合わせる。期限（`expires_at`）は `Clock` が固定なので表に書ける。採番だけが表に書けない値であり、それ以外を `verify` に逃がさない。

題材の proto は `HoldReservationRequest { string room_code = 1; google.protobuf.Timestamp starts_at = 2; google.protobuf.Timestamp ends_at = 3; }` と `HoldReservationResponse { string reservation_id = 1; google.protobuf.Timestamp expires_at = 2; }`。`TestReservationServer_HoldReservation` の表の抜粋（`main_test.go` は §2 と同じ。import は §2 の例に `google.golang.org/protobuf/types/known/timestamppb` と `example.com/roomflow/handler` を足したもの）:

```go
func TestReservationServer_HoldReservation(t *testing.T) {
	// holdResp は応答の射影。採番される ReservationId は表に書けないので持たない。
	type holdResp struct {
		ExpiresAt time.Time
	}

	// reservationState は reservations の射影。
	type reservationState struct {
		ID      string
		Status  string
		Version int32
	}

	tests := []struct {
		id               string
		name             string
		description      string
		caller           string                             // Given: 主体。空は主体無し
		req              *roomflowv1.HoldReservationRequest // When
		wantCode         connect.Code                       // Then: 0 は成功
		wantMessage      string                             // Then: 公開文言。空なら見ない
		wantResp         holdResp                           // Then: 成功時の応答の射影
		wantReservations []reservationState                 // Then: 成功時に reservations で確かめる射影。ID は応答の値で埋める
	}{
		{
			id:   "9b3e57",
			name: "空いている利用枠を仮押さえすると期限付きの予約番号が返る",
			description: `Given: 会議室 M-301 の 2026年9月18日 10:00 から 11:30 に有効な予約は無い
  And: 現在時刻は 2026年9月1日 09:05 である
When: C-4102 が M-301 の 2026年9月18日 10:00 から 11:30 の仮押さえを求める
Then: 成功し、応答に採番された予約番号と仮押さえ期限 2026年9月1日 09:20 が入る
  And: reservations にその予約番号の仮押さえ予約が現在 version 1 で入る`,
			caller: "C-4102",
			req: &roomflowv1.HoldReservationRequest{
				RoomCode: "M-301",
				StartsAt: timestamppb.New(time.Date(2026, 9, 18, 10, 0, 0, 0, time.UTC)),
				EndsAt:   timestamppb.New(time.Date(2026, 9, 18, 11, 30, 0, 0, time.UTC)),
			},
			wantResp:         holdResp{ExpiresAt: now.Add(15 * time.Minute)},
			wantReservations: []reservationState{{Status: "tentative", Version: 1}},
		},
		{
			id:   "2c7f90",
			name: "利用開始の無い仮押さえは受け付けない",
			description: `Given: 現在時刻は 2026年9月1日 09:05 である
When: C-4102 が利用開始を欠いた仮押さえを求める
Then: InvalidArgument で拒まれ、文言は「利用開始の無い仮押さえ要求は受け付けない」である`,
			caller: "C-4102",
			req: &roomflowv1.HoldReservationRequest{
				RoomCode: "M-301",
				EndsAt:   timestamppb.New(time.Date(2026, 9, 18, 11, 30, 0, 0, time.UTC)),
			},
			wantCode:    connect.CodeInvalidArgument,
			wantMessage: handler.ErrStartsAtRequired.Error(),
		},
	}

	client := newTestServer(t)

	// 同じ PostgreSQL（pool）を共有し、各ケースが Reset するため直列で走らせる。
	for _, tt := range tests {
		t.Run(tt.id+" "+tt.name, func(t *testing.T) {
			ctx := t.Context()
			rdbtest.Reset(ctx, t, pool)

			req := connect.NewRequest(tt.req)
			if tt.caller != "" {
				req.Header().Set(handlertest.CallerHeader, tt.caller)
			}
			got, err := client.HoldReservation(ctx, req)
			if tt.wantCode != 0 {
				require.Error(t, err)
				assert.Equal(t, tt.wantCode, connect.CodeOf(err))
				if tt.wantMessage != "" {
					cerr, ok := errors.AsType[*connect.Error](err)
					require.True(t, ok)
					assert.Equal(t, tt.wantMessage, cerr.Message())
				}
				assert.Nil(t, got)
				return
			}
			require.NoError(t, err)
			gotID := got.Msg.GetReservationId()
			assert.NotEmpty(t, gotID)
			assert.Equal(t, tt.wantResp, holdResp{ExpiresAt: got.Msg.GetExpiresAt().AsTime()})

			// 反映は応答の識別子で行を指す。表の wantReservations の ID は空なので、採番された値で埋めてから突き合わせる。
			want := make([]reservationState, len(tt.wantReservations))
			for i, w := range tt.wantReservations {
				w.ID = gotID
				want[i] = w
			}
			var gotReservations []reservationState
			for _, row := range rdbtest.ReadReservations(ctx, t, pool) {
				gotReservations = append(gotReservations, reservationState{
					ID:      row.ReservationID,
					Status:  row.Status,
					Version: row.CurrentVersion,
				})
			}
			assert.Equal(t, want, gotReservations)
		})
	}
}
```

入力不正の文言は handler の公開 sentinel（`handler.ErrStartsAtRequired`）を `.Error()` で参照する。非公開なら公開するよう実装側へ返す。

## 5. テストの形の共通規則との差分

| 共通規則 | この層 |
|---|---|
| `wantErr error` と `require.ErrorIs` | `wantCode connect.Code` と `wantMessage string`。sentinel は HTTP を越えない |
| `setup func(t *testing.T) fixture` | 使わない。資源は `newTestServer(t)` と package 変数 `pool` |
| `TestMain` は使わない | `main_test.go` の 1 点だけ置く（[server-setup.md](server-setup.md) §2）。他のファイルには置かない |
| `t.Parallel()` は両方に書くか、両方に書かない | 両方に書かない。ループ直前のコメントで `pool` を名指しする |
| ファイルスコープは `Test*` だけ | `main_test.go` だけ `pool` / `now` / `newTestServer` を持つ。他のファイルは共通規則のまま |
| 表を支える型はテスト関数の中 | 同じ。応答と行の射影 struct をテスト関数の中で宣言する |

それ以外（1 対象 1 テスト関数、`{pkg}_test`、`id` / `name` / `description` の規則、`require` / `assert` の使い分け、ケース間の独立）は共通規則のとおりである。
