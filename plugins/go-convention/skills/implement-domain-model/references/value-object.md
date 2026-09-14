# 値オブジェクト

**値オブジェクトは、非公開フィールドの struct を `NewX` だけが作り、生成後に変わらず、`==` で比べられる値である。** 資料の「持つもの」がフィールド、「生成の条件」が `NewX` の検査、「不変条件」が型の形で守られる。同じ値なら同じものであり、同一性を持たない。

## 1. 形

```go
// TimeSlot は利用枠。「会議室、利用開始、利用終了」の組で、時間帯は半開区間 [start, end)。
type TimeSlot struct {
	room  RoomCode
	start time.Time // UTC
	end   time.Time // UTC
}

// NewTimeSlot は生成の条件「会議室と、利用開始より後の利用終了が揃うこと」を確かめる。
// 時刻は UTC に正規化し、== で比べられる値にする。
func NewTimeSlot(room RoomCode, start, end time.Time) (TimeSlot, error) {
	start, end = start.UTC(), end.UTC()
	if !start.Before(end) {
		return TimeSlot{}, ErrTimeSlotNotOrdered
	}
	return TimeSlot{room: room, start: start, end: end}, nil
}

func (s TimeSlot) Room() RoomCode   { return s.room }
func (s TimeSlot) Start() time.Time { return s.start }
func (s TimeSlot) End() time.Time   { return s.end }

// Overlaps は操作「重なるか」。同じ会議室で時間帯が一部でも重なるとき真。隣接（end == 次の start）は偽。
func (s TimeSlot) Overlaps(o TimeSlot) bool {
	return s.room == o.room && s.start.Before(o.end) && o.start.Before(s.end)
}
```

| 規則 | 内容 | 理由 |
|---|---|---|
| 非公開フィールドの struct | フィールドは全部非公開。1 値でも `struct{ v string }` | 他 package が `NewX` を通らずに値を作れない。ゼロ値以外の不正な値が存在しない |
| defined basic type は VO と呼ばない | `type ID string` を書かない | 任意の `string` が型変換 `ID("")` で入り、生成の条件を迂回できる |
| ゼロ値は無効 | `TimeSlot{}` は資料に無い値。ゼロ値に意味を持たせない | 「未設定」が業務上必要なら、それは和型か `(T, bool)` で表す（`Confirmed.NoShowAt() (time.Time, bool)`） |
| `NewX(...) (X, error)` | 生成の条件に拒む組があるときだけ `error` を返す。無ければ `NewX(...) X` | 拒む組が無いのに `error` を返すと、呼ぶ側に決して起きない分岐が増える。`NewHoldDeadline` / `NewEligibility` は `error` を返さない |
| 生成後に変わらない | setter を書かない。値を変える操作は新しい値を返す | 集約が持つ VO を外から差し替えられない |
| `==` で比べられる | `NewX` で正規化する。`time.Time` は `UTC()`、文字列は資料に正規化の規則があるときだけ | `time.Time` の `==` は `Location` と単調時計に依存する。`UTC()` はその両方を落とす。`Equals` メソッドを書かない |
| VO を返す操作は `NewX` で再生成 | `return NewTimeSlot(s.room, s.start.Add(d), s.end.Add(d))` の形。題材の資料には VO を返す操作が無いので、例には置かない | 生成の条件を 2 か所に書かない。操作の結果も条件を満たす |
| `String()` を書かない | `fmt.Stringer` を実装しない。値の取り出しは `Value()` か名前付きの getter | ログ・`%v` に暗黙に載る。表示は境界の関心 |
| getter | 1 値なら `Value()`。複数なら資料の語の名前（`Room()` / `Start()`）。`Get` を付けない | 資料の「持つもの」と 1:1 で読める |
| 判定と計算 | 資料の操作（「重なるか」「到来したか」「新しい申込みができるか」）を `bool` か値を返すメソッドで置く。拒まない操作は `error` を返さない | 判定は VO に閉じ、集約と呼ぶ側は結果だけを使う |
| `Restore` | `NewX` が引数から値を導く（引数と持つ値が違う）ときだけ `RestoreX(保存済みの値) X` を置く | `NewHoldDeadline(heldAt)` は 15 分後を導くので、期限の時刻そのものから戻す `RestoreHoldDeadline(at)` が要る。`NewTimeSlot` は引数をそのまま持つので `Restore` は要らない |

## 2. 識別子

予約番号・予約者・会議室のような識別子は、資料の要素一覧に載らない（同じ値なら同じものを指す以上の規則を持たない）が、Go では VO にする。

```go
// ID は予約番号。
type ID struct{ v string }

// NewID は空でない予約番号を作る。
func NewID(s string) (ID, error) {
	if s == "" {
		return ID{}, ErrIDRequired
	}
	return ID{v: s}, nil
}

func (id ID) Value() string { return id.v }
```

- 型ごとに別の struct にする（`ID` と `CustomerID` は別の型）。取り違えをコンパイラが止める
- 集約の package では集約自身の識別子を `ID` と呼ぶ（`reservation.ID`）。他の集約の識別子は資料の語（`CustomerID`）
- 採番はしない。`NewID` は与えられた文字列を検査するだけで、生成は呼ぶ側の関心（[aggregate-typestate.md](aggregate-typestate.md) §6）

## 3. 導出される値

資料で「〜から決まる値」と書かれた要素（顧客の予約資格）は、材料を受け取って `NewX` の中で決める。決め方が生成の条件そのものである。

```go
// NewEligibility は生成の条件そのもの。判定時刻から 30 日前までに無断不利用が 3 回起きていて、
// 3 回目から 14 日が経っていなければ仮押さえ停止中（停止開始は 3 回目の時刻）、それ以外は予約可能。
// 拒む組が無いので error を返さない。
func NewEligibility(customer CustomerID, noShowAt []time.Time, at time.Time) Eligibility {
```

- 材料（無断不利用の時刻の列、判定時刻）は引数。材料を集めるのは呼ぶ側
- 資料の数（30 日・3 回・14 日）は package の非公開定数にし、リテラルを式に埋めない
- 状態（予約可能／仮押さえ停止中）は値の違いで表し、型を分けない。資料の「状態と型の分割」が「分けない」と言っている

## 4. 時刻

- 持つ時刻は `NewX` / `RestoreX` で `UTC()` にしてから持つ。比較は `Before` / `After` / `Equal` で行い、`==` は VO 全体の比較にだけ使う
- 「同時刻は到来」「利用開始と同時刻は利用開始前でない」のような境界は、資料の文をそのまま条件にする（`!at.Before(d.at)`）。境界の向きを行末コメントに書く
- `time.Now()` を呼ばない。判定時刻は引数で受ける

## 5. 書かないもの

| 書かない | 理由 |
|---|---|
| `IsValid()` / `Validate()` | 生成の条件は `NewX` の中にある。生成後の値は常に有効 |
| `Equals` / `Clone` | `==` と値渡しで足りる |
| `MarshalJSON` / `Scan` / `Value() (driver.Value, error)` | 永続化と表現は境界の関心。ドメインの package は永続化・RPC・ログの package を import しない |
| `[]VO` を返す getter の防御的コピー用の「コレクション VO」 | 資料に要素として無いものを作らない。列が要るなら `slices.Clone` を返す |
| 資料に無い判定・計算 | 「あると便利」は書かない。資料の操作だけを置く |
