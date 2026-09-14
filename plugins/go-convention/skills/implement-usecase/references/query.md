# query の形

**query は、usecase 側に定義した読み取りポートを呼び、返った DTO をそのまま返す。集約を復元しない。永続化ポートを呼ばない。書かない。tx を張らない。** 入力の解決とソース選択は usecase の関心、SQL・並び順・集計・ページングは読み取りポートの実装（query service）の関心である。

## 1. する／しない

| する | しない | 理由 |
|---|---|---|
| Input の primitive を VO の `New*` で解決する（`NewRoomCode`） | 検証を自前で書く（`if in.RoomCode == ""`） | 入力不正の sentinel を command と同じ場所（VO）から出す |
| 対象期間を資料の語で決める（対象日 → 営業日、対象月 → 月初と月末） | 期間の計算を読み取りポートの実装に任せる | 「いつからいつまでを見るか」は資料の語で、SQL の語ではない |
| ソースを入力と時刻で選ぶ（進行中 → 現行、終了 → 履歴） | error を見て別のソースへ倒す | 選択は明示的な手順。フォールバックは失敗を隠す |
| 読み取りポートの DTO をそのまま Output にする | usecase で並び替える、集計する、業務の計算をする | 並び順と集計は SQL が 1 回で決める。usecase で二度計算しない |
| 読み取りポートを呼ぶだけ。`tx.Manager.Run` を張らない | query の `Execute` で `Run` を呼ぶ。`*tx.Manager` を query の依存に持つ | 読むだけで、rollback するものが無い。読み取りポートの実装は ctx に tx が無ければ pool で読む。command の `Run` の中で呼ぶ読み取りポートだけが同じ tx に乗る |
| フィルタ・ページングの値を Input で受け、そのまま渡す | 未指定の件数を既定値に丸める | 未指定は入力の解決で拒む。丸めは暗黙の既定 |

query は文脈を足して返すだけで、command と同じく分類もログもしない（[command.md](command.md) §6）。

## 2. 読み取りポート

読み取りポートは **usecase package に、その usecase が呼ぶメソッドだけを持つ interface として定義する。** 返すのは DTO（primitive のフィールドを持つ struct か、primitive のスライス）で、集約も VO も返さない。実装は query service で、組み立てで注入する。

```go
package usecase

import (
	"context"
	"time"

	"example.com/roomflow/query"
)

// RoomAvailabilityReader は会議室の空き状況を読む読み取りポート。query service が実装する。
type RoomAvailabilityReader interface {
	ListForDay(ctx context.Context, room string, day time.Time) (query.RoomAvailability, error)
}
```

| 項目 | 規則 | 理由 |
|---|---|---|
| 置き場 | usecase package。使う usecase と同じファイルか `usecase/readers.go` | 「interface は使う側で定義する」。永続化ポートと違い、読み取りは usecase ごとに要る形が違う |
| 名前 | `{何を}Reader`（`RoomAvailabilityReader` / `ActiveReservationReader` / `NoShowReader`）。メソッドは `List{何を}By{条件}` / `Get{何を}` | 役割の名詞。`QueryService` / `Repository` / `Finder` の接尾辞を混ぜない |
| 大きさ | usecase が呼ぶメソッドだけ。1 つの読み取りポートを複数の usecase が共有してよいのは、同じメソッドを同じ意味で呼ぶときだけ | 実装の全メソッドに依存すると、テストと差し替えの単位が「この usecase が要るもの」からずれる |
| 返す型 | `query` package の DTO（`query.RoomAvailability` / `query.ActiveSlot`）か `[]time.Time` のような primitive | 読み取りモデルはドメインを経由しない。DTO をどこに置くかは読み取りモデルの規約が決め、usecase はその型を使う |
| 引数 | primitive（`room string` / `day time.Time`）。VO を渡さない | 実装が VO を知らずに済む。usecase は解決した VO から `Value()` で取り出して渡す |
| 依存の向き | `usecase` → `query`（DTO の型のため）。`query` は `usecase` を import しない | interface は構造的に満たされる。循環しない |
| tx | 実装は ctx に tx があればそれに乗り、無ければ pool で読む。tx を張らない | command の `Run` の中で読む材料（[cross-aggregate.md](cross-aggregate.md) §4）は同じ tx に乗り、query の `Execute` からは pool で読む。同じ実装を両方から使える |

「無い」が失敗でない問い合わせ（先頭の 1 件、あれば）は `([]T, error)` で空を返すか `(T, bool)` で返し、`(T, bool, error)` にしない（返り値は最大 2 つ）。

## 3. `ListRoomAvailability`

```go
package usecase

import (
	"context"
	"fmt"
	"time"

	"example.com/roomflow/query"
	"example.com/roomflow/reservation"
)

// ListRoomAvailability は会議室の 1 日の空き状況を返す query。tx を張らない。
type ListRoomAvailability struct {
	reader RoomAvailabilityReader
}

func NewListRoomAvailability(reader RoomAvailabilityReader) *ListRoomAvailability {
	return &ListRoomAvailability{reader: reader}
}

type ListRoomAvailabilityInput struct {
	RoomCode string    // 会議室
	Day      time.Time // 対象日
}

func (u *ListRoomAvailability) Execute(ctx context.Context, in ListRoomAvailabilityInput) (query.RoomAvailability, error) {
	room, err := reservation.NewRoomCode(in.RoomCode)
	if err != nil {
		return query.RoomAvailability{}, fmt.Errorf("空き状況の一覧の入力: %w", err)
	}
	out, err := u.reader.ListForDay(ctx, room.Value(), in.Day)
	if err != nil {
		return query.RoomAvailability{}, fmt.Errorf("会議室 %s の空き状況の一覧: %w", in.RoomCode, err)
	}
	return out, nil
}
```

- `NewRoomCode` は検証のためだけに呼び、読み取りポートには `room.Value()` を渡す。VO を渡さない
- `Run` を張らない。`*tx.Manager` を依存に持たない。読み取りポートの実装が ctx に tx が無いことを見て pool で読む
- Output は DTO そのまま。`query.RoomAvailability` を usecase の Output 型に写し替えない（同じ列を 2 回定義しない）。RPC の DTO（proto）への変換は入口の規約が決める
- 空き状況の計算（占有の隙間を空き枠にする）は SQL か query service の関心で、usecase に `for` を書かない

## 4. ソース選択

同じ形の読み取りが複数のソース（現行のテーブルと履歴のテーブル、現行の DB と保管用の DB）にあるとき、どちらを読むかは **入力と時刻で決める。error で決めない。** 選んだソースを 1 回だけ呼ぶ。時刻は Input の `At` で、呼ぶ境界（RPC の入口）がサーバーの時計で 1 回決める（[command.md](command.md) §3）。

package と import は §3 と同じ。

```go
// ReservationSummaryReader は期間内の予約の要約を読む読み取りポート。現行と履歴で同じ interface を使う。
type ReservationSummaryReader interface {
	List(ctx context.Context, room string, from, to time.Time) ([]query.ReservationSummary, error)
}

// ListReservations は期間内の予約の一覧を返す query。終了した期間は履歴から、そうでなければ現行から読む。
type ListReservations struct {
	current ReservationSummaryReader // 現行（reservations）
	history ReservationSummaryReader // 履歴（保管先）。同じ interface の別実装
}

type ListReservationsInput struct {
	RoomCode string
	From     time.Time
	To       time.Time
	At       time.Time // 「終了した期間か」を判定する時刻。RPC の入口がサーバーの時計で 1 回決める
}

func (u *ListReservations) Execute(ctx context.Context, in ListReservationsInput) ([]query.ReservationSummary, error) {
	room, err := reservation.NewRoomCode(in.RoomCode)
	if err != nil {
		return nil, fmt.Errorf("予約の一覧の入力: %w", err)
	}
	// ソース選択。対象期間が終わっていれば履歴、そうでなければ現行。条件は入力と時刻で決める
	reader := u.current
	if !in.To.After(in.At) {
		reader = u.history
	}
	out, err := reader.List(ctx, room.Value(), in.From, in.To)
	if err != nil {
		return nil, fmt.Errorf("会議室 %s の予約の一覧: %w", in.RoomCode, err)
	}
	return out, nil
}
```

| する | しない | 理由 |
|---|---|---|
| 条件を入力（対象期間）と時刻（Input の `At`）で書く | `if err != nil { out, err = u.history.List(...) }` | error で倒すのはフォールバック。現行に無かったのか読めなかったのかが消える |
| 選択の条件を資料の語でコメントする | 条件を読み取りポートの実装に隠す | どのソースを見たかは業務の問い（終了した予約か）で、SQL の問いではない |
| 両方を同じ interface にする | ソースごとに別の interface を切り、`switch` で呼び分ける | 呼ぶ側は「どれを呼ぶか」だけを決め、呼び方は同じ |
| 両方から読んで結合する必要があるなら、それは 1 つの読み取りポートのメソッドにする | usecase で 2 回読んで `append` する | 結合の順序と重複の扱いは SQL の関心 |

## 5. command の中の読み取りポート

command が集約の外で守る不変条件や、他の要素から導く材料を読むときも、同じ読み取りポートを使う（[command.md](command.md) §3 の `ActiveReservationReader` / `NoShowReader`）。違いは呼ぶ場所が command の `Run` の中で、復元・操作・保存と同じ tx に乗ることだけである（実装は ctx の tx を選ぶ）。query の `Execute` は `Run` を張らないので、同じ実装が pool で読む。command が読み取りポートを呼ぶのは材料のためであり、表示のための一覧を command に混ぜない。
