# テーブルの形

**Given は `Restore*` / `New*` の引数、When は操作の引数、Then は `Next` の値・発したイベントの値・sentinel。** ドメインのテストは資源を持たないので、Given は全部データで書け、`setup func` も操作列も要らない。

## 1. 共通規則の要約（この規約で使う分だけ）

| 規則 | 内容 |
|---|---|
| 単位 | 対象（1 つの生成関数・1 つのメソッド・1 つの絞り込み関数）につきテスト関数は 1 つ。`Test{型}_{メソッド}` / `Test{関数}`。状態型ごとに同名メソッドがあれば別のテスト関数 |
| package | `{pkg}_test`（外部テストパッケージ）。非公開には触れない |
| テーブル | 無名 struct のスライス。フィールドは識別 → Given → When → Then の順。ケースは複数行で書く |
| 識別 | `id` / `name` / `description` を必ずこの 3 つ・この順・各 1 行始まりで。`id` はディレクトリ内で一意・不変。資料にあるケースは資料の ID・見出し文・gherkin ブロックをそのまま写す |
| Given / When | 引数名そのままのフィールド。`in` / `args` の袋に包まない |
| Then | `want` / `want{何}` / `wantErr error`（sentinel）/ `wantOK bool`。`expected` / `errMsg` / `wantErr bool` は使わない |
| ループ本体 | `t.Run(tt.id+" "+tt.name, ...)`。実行と検証を 1 回。ケースを選り分ける分岐を書かない |
| `require` / `assert` | 前提と、失敗したら後続が無意味になるもの（`NoError` / `ErrorIs`）は `require`。独立した期待は `assert` |
| 並列 | `t.Parallel()` をテスト関数の先頭とサブテストの先頭の両方に置く。メモリ上の不変の値なので共有資源は無い |
| 依存 | ケース間の依存を作らない。各ケースが自分の値を `Restore*` で組む |
| ファイルスコープ | `Test*` だけ。ヘルパー関数・パッケージ変数・`TestMain` を置かない |

## 2. 表の前に置くもの

表の前に置いてよいのは、**ケース間で共有する値オブジェクトの生成**と、**イベントの射影 struct の宣言**だけ。関数（ヘルパー・クロージャ）は置かない。

```go
func TestTentative_Confirm(t *testing.T) {
	t.Parallel()

	// 表で使う値オブジェクト。資料の Given に現れない予約番号と版は全ケース同じ値を使う。
	reservationID, err := reservation.NewID("R-1")
	require.NoError(t, err)
	owner, err := reservation.NewCustomerID("C-1")
	require.NoError(t, err)
	other, err := reservation.NewCustomerID("C-2")
	require.NoError(t, err)
	room, err := reservation.NewRoomCode("large")
	require.NoError(t, err)
	slot, err := reservation.NewTimeSlot(room, time.Date(2026, 9, 18, 10, 0, 0, 0, time.UTC), time.Date(2026, 9, 18, 11, 30, 0, 0, time.UTC))
	require.NoError(t, err)
	v1, err := reservation.NewVersion(1)
	require.NoError(t, err)

	// confirmed は発したイベントの射影。型は ConfirmResult が決めているので、値だけを getter で並べて比べる。
	type confirmed struct {
		reservationID reservation.ID
		version       int
		occurredAt    time.Time
		by            reservation.CustomerID
	}
```

| 規則 | 理由 |
|---|---|
| VO は `New*` ＋ `require.NoError` で作る。`Restore*` で作れる VO（`RestoreHoldDeadline`）はケースの中で直接組む | 生成の条件は VO のテストが確かめ済み。ここで失敗するなら表以前の問題で、`require` が止める |
| 資料の Given に現れない復元引数（予約番号・版）は全ケース同じ値 | 表を縦に読んで差分が分かるのは、資料が言及する値だけが変わるときである |
| 射影 struct はテスト関数の中で宣言する | `{pkg}_test` は 1 つの名前空間。関数の中なら `TestHold` と `TestTentative_Confirm` が別の `held` / `confirmed` を持てる |
| 時刻は `time.UTC` で書く | VO が UTC に正規化するので、期待値も UTC で書けば `==` と `assert.Equal` がそのまま使える |

## 3. Given

| 対象 | Given のフィールド | 型 |
|---|---|---|
| 状態型のメソッド・絞り込み | `Restore*` の引数名（`customer` / `slot` / `deadline` / `noShowAt`）。`id` だけはケースの識別 `id` と衝突するので `reservationID`（表の前で固定するなら省く） | VO の型。`Restore*` はループ本体で 1 回 |
| 生成関数 | 生成関数の引数のうち、資料の `Given:` に写るもの（`customer` / `slot` / `eligibility`） | VO の型。`eligibility` は `NewEligibility(...)` をケースの中で組む |
| 絞り込み関数 | 引数名そのまま `r`。`Restore*` で組んだ状態型の値 | 和型 `reservation.Reservation` |
| VO の `New*` と操作 | `New*` の引数（`room` / `start` / `end`）。組み立てはループ本体 | primitive と他の VO |

```go
		customer    reservation.CustomerID  // Given: 予約者（RestoreTentative の引数名）
		slot        reservation.TimeSlot    // Given: 利用枠
		deadline    reservation.HoldDeadline // Given: 仮押さえ期限
```

## 4. When

操作の引数名そのまま。題材では `at`（時刻）と `by`（呼び手）。

```go
		at          time.Time              // When:  確定時刻
		by          reservation.CustomerID // When:  呼び手
```

生成関数のように引数が多い対象は、資料の `Given:` に写る引数を Given、`When:` に写る引数（時刻）を When に置く。どちらも引数名そのままで、区別はコメントだけ。

## 5. Then

| 期待 | フィールド | 突き合わせ |
|---|---|---|
| 次の状態 | `wantNext reservation.Confirmed`。`Restore*` で Given と同じ値から組み、版だけ `v1.Next()` | `assert.Equal(t, tt.wantNext, got.Next)`。状態型は非公開フィールドの値で比べられる |
| 発したイベント | `wantEvent confirmed`（射影 struct） | ループ本体で `got.Event` の getter から同じ struct を組み、`assert.Equal` 1 回 |
| 拒む | `wantErr error`（sentinel） | `require.ErrorIs(t, err, tt.wantErr)` の後に `assert.Zero(t, got)` |
| 拒まない操作 | `wantOK bool` ＋ `wantNext` ＋ `wantEvent` | `require.Equal(t, tt.wantOK, ok)`。`false` なら `assert.Zero(t, got)` |
| 絞り込み | `want reservation.Tentative` ＋ `wantErr` | 成功なら `assert.Equal(t, tt.want, got)` |
| VO の判定 | `want bool` | `assert.Equal(t, tt.want, s.Overlaps(o))` |
| VO の生成 | `want reservation.TimeSlot`（`New*` を 2 回呼んで比べるなら省く）＋ `wantErr` | `assert.Equal` または `assert.True(t, got == want)` |

イベントの**型**はテストで確かめない。`ConfirmResult = Transition[Confirmed, ConfirmedEvent]` の型引数がコンパイル時に決めている。確かめるのは**値**（予約番号・版・発生時刻・呼び手）で、版は `wantNext` の版と同じ数にする。

## 6. ループ本体

### 遷移 `(Result, error)`

```go
	for _, tt := range tests {
		t.Run(tt.id+" "+tt.name, func(t *testing.T) {
			t.Parallel()

			tentative := reservation.RestoreTentative(reservationID, tt.customer, tt.slot, tt.deadline, v1)

			got, err := tentative.Confirm(tt.at, tt.by)
			if tt.wantErr != nil {
				require.ErrorIs(t, err, tt.wantErr)
				assert.Zero(t, got)
				return
			}
			require.NoError(t, err)
			assert.Equal(t, tt.wantNext, got.Next)
			assert.Equal(t, tt.wantEvent, confirmed{
				reservationID: got.Event.ReservationID(),
				version:       got.Event.Version().Value(),
				occurredAt:    got.Event.OccurredAt(),
				by:            got.Event.By(),
			})
		})
	}
```

### 拒まない操作 `(Result, bool)`

`TestTentative_Expire` の Then は `wantOK` / `wantNext` / `wantEvent`（射影 struct `expired`: 予約番号・版・発生時刻・利用枠）。`false` 側は `Next` も `Event` もゼロ値。

```go
			tentative := reservation.RestoreTentative(reservationID, tt.customer, tt.slot, tt.deadline, v1)

			got, ok := tentative.Expire(tt.at)
			require.Equal(t, tt.wantOK, ok)
			if !ok {
				assert.Zero(t, got)
				return
			}
			assert.Equal(t, tt.wantNext, got.Next)
			assert.Equal(t, tt.wantEvent, expired{
				reservationID: got.Event.ReservationID(),
				version:       got.Event.Version().Value(),
				occurredAt:    got.Event.OccurredAt(),
				slot:          got.Event.Slot(),
			})
```

### 絞り込み `As*`

```go
			got, err := reservation.AsTentative(tt.r)
			if tt.wantErr != nil {
				require.ErrorIs(t, err, tt.wantErr)
				assert.Zero(t, got)
				return
			}
			require.NoError(t, err)
			assert.Equal(t, tt.want, got)
```

### VO の操作

```go
			s, err := reservation.NewTimeSlot(tt.room, tt.start, tt.end)
			require.NoError(t, err)
			o, err := reservation.NewTimeSlot(tt.oRoom, tt.oStart, tt.oEnd)
			require.NoError(t, err)

			assert.Equal(t, tt.want, s.Overlaps(o))
```

どの形でも、検証はループ本体に 1 回。`verify func` は使わない。ドメインの返り値は全部 `assert.Equal` で書ける（絶対パスやソート順のような「表を書く時点で決まらない性質」が無い）。
