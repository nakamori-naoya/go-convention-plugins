# ドメインイベント

**ドメインイベントは、集約の操作が成立したことを知らせる不変の値で、操作が遷移結果型の `Event` として 1 つ返す。** 資料「ドメインイベント」の表の 1 行が Go の 1 つの型になる。イベントは事実の置き場ではなく、事実は集約が持つ。

完全な例は [example-reservation.md](example-reservation.md)。

## 1. 形

```go
// Event は予約のドメインイベントの和型。
//
//sumtype:decl
type Event interface {
	ReservationID() ID
	Version() Version
	OccurredAt() time.Time
	isEvent()
}

// base は全イベントが持つ値。version は Next.Version() と一致する。
type base struct {
	reservationID ID
	version       Version
	occurredAt    time.Time // UTC
}

func (b base) ReservationID() ID     { return b.reservationID }
func (b base) Version() Version      { return b.version }
func (b base) OccurredAt() time.Time { return b.occurredAt }
func (base) isEvent()                {}

// Held は「仮押さえ予約が成立した」。生成のイベントなので、予約の値を全部持つ。
type Held struct {
	base
	customer CustomerID
	slot     TimeSlot
	deadline HoldDeadline
}

func (e Held) Customer() CustomerID   { return e.customer }
func (e Held) Slot() TimeSlot         { return e.slot }
func (e Held) Deadline() HoldDeadline { return e.deadline }

// ConfirmedEvent は「予約が確定した」。状態型 Confirmed と名前が衝突するので Event 接尾辞を付ける。
type ConfirmedEvent struct {
	base
	by CustomerID
}
```

| 規則 | 内容 | 理由 |
|---|---|---|
| 集約ごとに封じた和型 `Event` | 非公開マーカー `isEvent()` と、全イベントに共通の getter（集約の識別子・版・発生時刻）。宣言に `//sumtype:decl` を付ける | 永続化ポートの `Apply{Event}` と遷移結果型の型引数 `E Event` が、この集約のイベントだけを受け取る |
| 共通の値は非公開 struct `base` に集めて埋め込む | 集約の識別子、版、発生時刻の 3 つ | 同じ getter をイベントの数だけ書かない |
| イベントごとに 1 つの struct | 資料「ドメインイベント」の表の行と 1:1。名前は資料の語を英語の過去分詞にする（`Held` / `NoShowRecorded`） | 型がそのままイベントの種類。`Kind` フィールドで種類を分ける 1 つの struct にしない |
| 状態名と衝突するイベントは `Event` 接尾辞 | `Confirmed`（状態）と `ConfirmedEvent`（イベント）、`Cancelled` と `CancelledEvent`、`Expired` と `ExpiredEvent`。衝突しないものは付けない（`Held` / `NoShowRecorded`） | 同じ package に同じ名前を 2 つ置けない。状態型の名前を資料の状態の語のまま残し、イベント側に接尾辞を付ける |
| フィールドは非公開、getter で読む | VO と同じ形。`String()` を書かない | 生成後に変わらない。永続化とログの表現は境界の関心 |
| 生成は操作の中だけ | イベントの `New` を公開しない。`Confirm` が `ConfirmedEvent{...}` を組み立てる | イベントは操作が成立したときにだけ存在する。他 package が「成立していないイベント」を作れない |
| 版は `Next.Version()` と同じ | 操作が進めた版を `Next` と `Event` の両方に入れる。生成のイベントは 1 | イベント型の永続化が楽観ロック（`current_version = 版 - 1` の行を更新）に使う |
| 発生時刻は操作の引数 | `at.UTC()` を `occurredAt` に入れる。`time.Now()` を呼ばない | 時刻は呼ぶ側が渡す |

## 2. 何を持つか

| 持つ | 持たない |
|---|---|
| 生成のイベントは集約の値を全部（`Held` の予約者・利用枠・期限）。永続化がこれだけで行を作れる | 集約の値を全部写した「スナップショット」を毎回。`ConfirmedEvent` は確定に要る値だけ |
| 操作の引数のうち、受け手や永続化が要るもの（`by` → 行為者） | 操作が拒んだ理由。拒んだときイベントは無い |
| 資料「集約どうしの協働」で「渡すもの」に書かれた値（「予約が取り消された（利用枠を含む）」→ `CancelledEvent.slot`） | 受け手が判断に使わない値 |
| 資料に無く永続化に要る値（版） | 永続化の都合の識別子（イベント行の ID、`created_at`）。イベント行の ID は永続化が採番する |

## 3. 返し方

- 操作は `Transition[Next, Event]` の `Event` に 1 つ入れて返す（[aggregate-typestate.md](aggregate-typestate.md) §2）。集約の中にイベントの列を溜めない。`PendingEvents()` / `ClearEvents()` を書かない
- 1 操作が 2 つ以上のイベントを発することは資料に無い。資料がそう書いたら、それは 2 つの操作である
- 発したイベントを配送する仕組み（dispatcher / bus / handler）はドメインに置かない。イベントを永続化ポートへ渡すのも、別の集約の判断を始めるのも、呼ぶ側（usecase）の関心
- 「この文脈では判断を始めない」イベント（`Held` / `ConfirmedEvent` / `NoShowRecorded`）も同じ形で返す。永続化がイベント型なら保存に要る

## 4. 書かないもの

| 書かない | 理由 |
|---|---|
| 資料の業務イベントのうち集約の操作が発しないもの（「仮押さえ停止期間が始まった」「顧客の利用登録が完了した」） | 資料「ドメインイベント」の節と「捨てた割り当て」に、発する操作が無いと書いてある |
| イベントから状態を再構築する `Apply(evt)` / `Replay` | 復元は `Restore*` が保存済みの現在の値から行う。イベント列からの再構築は採らない |
| イベントの `MarshalJSON` / proto 変換 | 表現は境界の関心 |
| `EventID` / `AggregateType` / `Metadata` のような汎用フィールド | 資料に無い。永続化の都合は永続化が持つ |
