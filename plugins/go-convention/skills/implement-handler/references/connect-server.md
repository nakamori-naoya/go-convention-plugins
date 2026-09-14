# Connect-RPC の server 実装

**server 実装は、生成された `roomflowv1connect.ReservationServiceHandler` を満たす struct で、各メソッドは「主体を読む → 要求を入力へ写す（時刻はサーバーの `Clock` から）→ usecase を 1 つ呼ぶ → 出力を応答へ写す」の 4 行だけを持つ。** 判断・分岐・記録はここに置かない。変換は [dto-mapping.md](dto-mapping.md)、記録と翻訳と認証は [interceptors.md](interceptors.md)、組み立ては [wiring.md](wiring.md)。

## 1. handler とは何か

handler は、外の世界（HTTP・protobuf）と内の世界（usecase の入出力）の境界である。境界でしか分からないこと（呼び手が誰か、要求に何が欠けているか）を確かめ、それ以外は usecase に渡す。

| 観点 | handler が持つ | handler が持たない（誰が持つか） |
|---|---|---|
| 入力の形 | proto の要求から usecase の入力への写し | 値オブジェクトの生成（usecase が `NewID` 等を呼び、拒否は sentinel で返る） |
| 呼び手 | ctx の主体を読んで入力に載せる | 本人かどうかの判断（集約が `ErrNotOwner` で拒む） |
| 時刻 | `Clock.Now()` を 1 回呼び、入力の `At` に載せる | 期限が到来したか（集約が `ErrHoldDeadlinePassed` で拒む）。要求の本文から時刻を受け取ること |
| 欠け | 必須の要素が無いことの検出（nil の Timestamp） | 値の妥当性（利用開始が利用終了より前か、は値オブジェクトが拒む） |
| 手順 | usecase を 1 つ呼ぶ | 復元・操作・保存の順序、複数集約の協調、tx（usecase） |
| 出力の形 | usecase の出力から proto の応答への写し | 読み取りモデルの生成（query service）、集約の復元（リポジトリ） |
| 失敗 | error をそのまま返す | 分類（翻訳表）、記録（interceptor） |

「handler が持つ」列に無いものが要ると感じたら、それは usecase か interceptor の関心である。handler に書いて埋めない。

## 2. proto と生成物

proto は `roomflow.v1`。生成物は protobuf の package `roomflowv1`（`example.com/roomflow/gen/roomflowv1`）と Connect の package `roomflowv1connect`（`example.com/roomflow/gen/roomflowv1/roomflowv1connect`）で、生成物はコミットし、手で編集しない。

`proto/roomflow/v1/reservation.proto`:

```proto
syntax = "proto3";

package roomflow.v1;

import "google/protobuf/timestamp.proto";

option go_package = "example.com/roomflow/gen/roomflowv1;roomflowv1";

// RPC 名は資料の操作の語（仮押さえ予約を成立させる・確定する）。技術語（Set / Sync / Process）で置き換えない。
service ReservationService {
  rpc HoldReservation(HoldReservationRequest) returns (HoldReservationResponse);
  rpc ConfirmReservation(ConfirmReservationRequest) returns (ConfirmReservationResponse);
}

message HoldReservationRequest {
  string room_code = 1;
  google.protobuf.Timestamp starts_at = 2;
  google.protobuf.Timestamp ends_at = 3;
}

message HoldReservationResponse {
  string reservation_id = 1;
  google.protobuf.Timestamp expires_at = 2;
}

message ConfirmReservationRequest {
  string reservation_id = 1;
}

message ConfirmReservationResponse {}
```

操作の時刻（確定した時刻・仮押さえが成立した時刻）は要求の message に置かない。期限の判定に使う時刻をクライアントの申告で決めさせないためで、サーバーの `Clock` が決めて usecase の入力の `At` に載せる。利用枠の `starts_at` / `ends_at` は操作の時刻ではなく予約の内容なので、要求が運ぶ。

`buf.gen.yaml`（生成の手段は上位の規約が決める。ここでは生成物の置き場が決まることだけが要る）:

```yaml
version: v2
plugins:
  - local: [go, tool, google.golang.org/protobuf/cmd/protoc-gen-go]
    out: gen
    opt: module=example.com/roomflow/gen
  - local: [go, tool, connectrpc.com/connect/cmd/protoc-gen-connect-go]
    out: gen
    opt: module=example.com/roomflow/gen
```

| 生成物 | package | 中身 |
|---|---|---|
| `gen/roomflowv1/reservation.pb.go` | `roomflowv1` | 要求・応答の型。`GetReservationId()` 等の getter |
| `gen/roomflowv1/roomflowv1connect/reservation.connect.go` | `roomflowv1connect` | `ReservationServiceHandler` interface、`NewReservationServiceHandler(svc, opts...) (string, http.Handler)`、`NewReservationServiceClient` |

呼び手の主体（顧客 ID）は要求の message に置かない。認証の interceptor が ctx に載せる（[interceptors.md](interceptors.md) §4）。要求に `customer_id` があると、handler がそれを信じるか主体と突き合わせるかの分岐が生まれる。

## 3. `ReservationServer`

`handler/reservation_server.go`:

```go
package handler

import (
	"context"

	"connectrpc.com/connect"

	"example.com/roomflow/gen/roomflowv1"
	"example.com/roomflow/gen/roomflowv1/roomflowv1connect"
	"example.com/roomflow/usecase"
)

// ReservationServer は ReservationService の server 実装。RPC ごとに usecase を 1 つ持ち、操作の時刻を決める Clock を 1 つ持つ。
type ReservationServer struct {
	confirm *usecase.ConfirmReservation
	hold    *usecase.HoldReservation
	clock   Clock
}

// 生成 interface を満たすことをコンパイル時に確かめる。Unimplemented* を埋め込まないので、RPC を足したら実装しないとここで止まる。
var _ roomflowv1connect.ReservationServiceHandler = (*ReservationServer)(nil)

func NewReservationServer(confirm *usecase.ConfirmReservation, hold *usecase.HoldReservation, clock Clock) *ReservationServer {
	return &ReservationServer{confirm: confirm, hold: hold, clock: clock}
}

// ConfirmReservation は操作「確定する」の入口。主体 → 変換（時刻は Clock から）→ usecase → 応答。
func (s *ReservationServer) ConfirmReservation(
	ctx context.Context,
	req *connect.Request[roomflowv1.ConfirmReservationRequest],
) (*connect.Response[roomflowv1.ConfirmReservationResponse], error) {
	caller, err := callerFrom(ctx)
	if err != nil {
		return nil, err
	}
	in := confirmRequestToInput(req.Msg, caller, s.clock.Now())
	if err := s.confirm.Execute(ctx, in); err != nil {
		return nil, err // 記録しない。翻訳しない。Logging が両方やる
	}
	return connect.NewResponse(&roomflowv1.ConfirmReservationResponse{}), nil
}

// HoldReservation は操作「仮押さえ予約を成立させる」の入口。形は ConfirmReservation と同じで、出力があるので応答へ写す。
func (s *ReservationServer) HoldReservation(
	ctx context.Context,
	req *connect.Request[roomflowv1.HoldReservationRequest],
) (*connect.Response[roomflowv1.HoldReservationResponse], error) {
	caller, err := callerFrom(ctx)
	if err != nil {
		return nil, err
	}
	in, err := holdRequestToInput(req.Msg, caller, s.clock.Now())
	if err != nil {
		return nil, err
	}
	out, err := s.hold.Execute(ctx, in)
	if err != nil {
		return nil, err
	}
	return connect.NewResponse(holdOutputToResponse(out)), nil
}
```

`handler/clock.go`。usecase は時計を持たない（時刻は Input の `At`）ので、サーバーの時計は handler が持つ。本番は `time.Now` を返す実装、テストは固定時計を組み立てで渡す:

```go
package handler

import "time"

// Clock は操作の時刻（確定した・仮押さえが成立した）を決めるサーバーの時計。RPC 1 回につき Now() を 1 回だけ呼ぶ。
type Clock interface {
	Now() time.Time
}
```

`handler/caller.go`:

```go
package handler

import (
	"context"

	"example.com/roomflow/reqctx"
)

// callerFrom は認証の interceptor が Scope に書いた呼び手を返す。
// 無いのは組み立ての誤り（Auth が chain に無い）で、翻訳表に無いので Internal になる。既定の主体へ倒さない。
func callerFrom(ctx context.Context) (string, error) {
	s, ok := reqctx.From(ctx)
	if !ok || s.Caller == "" {
		return "", errNoCaller
	}
	return s.Caller, nil
}
```

| 規則 | 理由 |
|---|---|
| `Unimplemented*` を埋め込まない。`var _ Interface = (*T)(nil)` で満たすことを確かめる | 埋め込むと未実装の RPC が実行時に `Unimplemented` を返す。RPC を足して実装を忘れた事故がコンパイルで止まらない |
| メソッドは「主体 → 変換 → `Execute` → 応答」で、error はすべて `return nil, err` | 分岐が無いので、RPC ごとの違いは変換関数と usecase の型だけになる。読む側は 1 メソッドを見れば全部分かる |
| 時刻は `s.clock.Now()` を 1 回呼び、変換関数の引数で渡す。要求の本文から受けない。`time.Now()` を直に書かない | 期限の判定に使う時刻はサーバーが決める。`Clock` を引数にすると、テストが固定時計で期限前後を表に書ける |
| usecase を 1 つだけ呼ぶ | 2 つ呼ぶと、その間の順序・失敗時の扱い・tx の境界を handler が持つことになる。それは usecase の関心 |
| `errors.Is` で分岐しない | 「この error なら別の応答」は翻訳表の仕事。handler が分岐すると翻訳が 2 か所になる |
| `slog` を import しない | Logging が返った error と ctx から 1 回記録する。handler が書くと二重になる |
| `connect.NewError` を書かない | Code を決めるのは翻訳表。handler が書くと同じ sentinel が RPC ごとに違う Code になる |
| RPC 名は資料の操作の語。usecase の型名と揃える | `ConfirmReservation` RPC ↔ `usecase.ConfirmReservation` ↔ 操作「確定する」が 1 本の線で追える |
| `req.Msg` の getter（`GetReservationId()`）で読む | nil の message でも panic しない。Opaque API の生成物でも同じ書き方になる |

## 4. 読み取り RPC

一覧・空き状況などの読み取り RPC も同じ形で、呼ぶのが usecase の読み取り（query service の DTO を返すもの）になるだけである。handler が query service を直接呼ばない（依存は usecase 経由で 1 方向に保つ）。応答への変換は DTO の primitive を proto へ写す関数 `{DTO}ToProto` で、[dto-mapping.md](dto-mapping.md) §3 の形。集約（`reservation.Reservation`）を応答に写す関数は書かない。集約が応答に要るなら、usecase が出力型（primitive の struct）へ写してから返す。

## 5. 置き場

| path | 中身 |
|---|---|
| `handler/reservation_server.go` | `ReservationServer` と RPC ごとのメソッド |
| `handler/reservation_mapping.go` | `{元}To{先}` の変換関数（[dto-mapping.md](dto-mapping.md)） |
| `handler/caller.go` | `callerFrom` |
| `handler/clock.go` | `Clock` |
| `handler/errors.go` | handler の公開 sentinel（`ErrStartsAtRequired` / `ErrEndsAtRequired`）と `errNoCaller` / `errInternal` |
| `handler/logging_interceptor.go` | `Logging` と `levelOf`（[interceptors.md](interceptors.md) §3） |
| `handler/auth_interceptor.go` | `Auth` と `Verifier`（同 §4） |
| `handler/error_table.go` | `codeTable` と `toConnectError`（同 §5） |
| `handler/mux.go` | `Deps` と `NewMux`（[wiring.md](wiring.md) §3） |
| `reqctx/` | `Scope` / `New` / `From`（[interceptors.md](interceptors.md) §2） |
| `gen/roomflowv1/`、`gen/roomflowv1/roomflowv1connect/` | 生成物。手で編集しない |
