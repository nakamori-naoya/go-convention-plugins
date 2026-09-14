# tx の張り方

**tx を張るのは command の usecase だけである。`u.tx.Run(ctx, func(ctx context.Context) error { ... })` の中で復元・読み取り・操作・保存を行い、error を返せば rollback、nil を返せば commit される。張る単位は 1 業務イベント。query の usecase は張らない。** リポジトリと読み取りポートの実装は ctx に載った tx に乗るだけで、自分では張らない。

## 1. `tx.Manager.Run`

```go
// package tx（永続化の規約が実装する。usecase は呼ぶだけ）
func (m *Manager) Run(ctx context.Context, fn func(ctx context.Context) error) error
func From(ctx context.Context) (pgx.Tx, bool)
```

| 事実 | usecase が守ること |
|---|---|
| `Run` は `Begin` し、`pgx.Tx` を載せた新しい ctx で `fn` を呼ぶ | `fn` の引数の ctx を使う。外の ctx を使うと tx に乗らない |
| `fn` が error を返せば `Rollback` して、その error を返す。rollback 自体が失敗したときだけ `errors.Join` で束ねる（`errors.Is` は通る） | 文脈は `fn` の中で足す。`Run` の返り値をもう一度包まない |
| `fn` が nil を返せば `Commit` する。commit の失敗は `tx` が文脈を足して返す | commit の失敗を usecase で判定しない。返す |
| リポジトリは `tx.From(ctx)` で取り出し、無ければ error（`ErrNoTransaction`）を返す。読み取りポートの実装は無ければ pool で読む | `Run` の外でリポジトリを呼ばない。読み取りポートは `Run` の外（query の `Execute`）からも呼べる |

```go
func (u *ConfirmReservation) Execute(ctx context.Context, in ConfirmReservationInput) error {
	// Run の外: 入力の解決（DB を触らない）
	id, err := reservation.NewID(in.ReservationID)
	if err != nil {
		return fmt.Errorf("予約の確定の入力: %w", err)
	}
	by, err := reservation.NewCustomerID(in.CustomerID)
	if err != nil {
		return fmt.Errorf("予約 %s の確定の入力: %w", in.ReservationID, err)
	}
	// Run の中: 復元 → 絞り込み → 操作 → 保存。引数の ctx を使う（名前を同じにして外の ctx を隠す）
	return u.tx.Run(ctx, func(ctx context.Context) error {
		r, err := u.repo.FindByID(ctx, id)
		if err != nil {
			return fmt.Errorf("予約 %s の確定: %w", in.ReservationID, err)
		}
		t, err := reservation.AsTentative(r)
		if err != nil {
			return fmt.Errorf("予約 %s の確定: %w", in.ReservationID, err)
		}
		res, err := t.Confirm(in.At, by)
		if err != nil {
			return fmt.Errorf("予約 %s の確定: %w", in.ReservationID, err)
		}
		if err := u.repo.ApplyConfirmed(ctx, res.Event); err != nil {
			return fmt.Errorf("予約 %s の確定: %w", in.ReservationID, err)
		}
		return nil
	})
}
```

`fn` の引数名を外の `ctx` と同じにする。別名（`txCtx`）にすると、外の `ctx` を渡す取り違えがコンパイルを通る。

## 2. 単位は 1 業務イベント

| 場面 | tx の数 | 理由 |
|---|---|---|
| 1 つの command の `Execute` | 1 | 業務イベント 1 つが、成立するか、しないか |
| 同じ tx で 2 集約を操作する協調（[cross-aggregate.md](cross-aggregate.md) §2） | 1 | 資料が「同じ操作」で一貫させると決めた組は、片方だけ残さない |
| worker が期限切れを 100 件掃く | 100（1 件に 1 回 `Execute`） | 1 件の失敗（競合・データ破損）が他の 99 件を巻き込まない。1 tx に束ねると 1 件の error で全部が rollback し、次の周期でも同じ 1 件で止まる |
| ドメインイベントを受けて別の usecase が続ける（[cross-aggregate.md](cross-aggregate.md) §3） | 2（起こす側と受ける側で別） | 資料が「結果整合」と決めた組。受ける側は起こす側の commit 後に走る |
| query の `Execute` | 0 | 読むだけで rollback するものが無い。読み取りポートの実装が pool で読む（[query.md](query.md) §1） |

usecase が usecase を呼ばない。呼ぶと `Run` が入れ子になり、内側の rollback が外側に伝わらない形（内側が error を握る）か、外側の commit まで内側の書き込みが見えない形になる。2 つの業務イベントを続けるなら、それはイベントを受ける別 usecase である。

## 3. `Run` の中と外

| `Run` の外（前） | `Run` の中 | `Run` の外（後） |
|---|---|---|
| VO の解決（`NewID` / `NewTimeSlot`） | 復元（`FindByID`）、材料の読み取り（読み取りポート。同じ tx） | Output を返す |
| 採番（`IDGenerator.NewReservationID()`） | 生成（`Hold`）、絞り込み（`AsTentative`）、操作（`Confirm`） | — |
| 時刻は Input の `At` を使う（usecase は時計を持たない） | 保存（`Apply{Event}` / `Create` / `Update`） | — |

| する | しない | 理由 |
|---|---|---|
| DB を触らないことは `Run` の前に済ませる | `Run` の中で `NewID` の error を返す | 入力不正で tx を開かない。開始と rollback が無駄になる |
| Output は `Run` の外の変数に書き、`Run` が nil を返したら返す | `Run` の中から `return out, nil` を試みる | `fn` は error しか返せない |
| `Run` の中は DB への読み書きだけ | メール送信・決済・外部 API の呼び出し | rollback で取り消せない。commit 前に送れば、成立しなかった予約の通知が届く。要るなら commit 後か、イベントを受ける側で |
| `Run` の中は 1 goroutine | `Run` の中で goroutine を起こしてリポジトリを呼ぶ | ctx の tx は 1 接続で、並行に使えない |
| command の 1 `Execute` に `Run` は 1 回 | `Run` を 2 回呼ぶ、`Run` の中で `Run`、query の `Execute` で `Run` | 2 回目は別の tx で、1 回目の commit 後の状態を見る。1 業務イベントが 2 つに割れる。query は張る理由が無い |

## 4. 分離レベルと競合

| 事象 | 誰が守るか | usecase がすること |
|---|---|---|
| 同じ空き枠への同時の仮押さえ（資料「同時に起きたとき」） | DB の排他制約。リポジトリが違反を `ErrOverlappingSlot` に翻訳する | 読み取りポートで先に確かめて返す（先に分かる拒否を先に）。保証は DB に任せる |
| 同じ予約への同時の操作（確定と期限到来） | イベント型の楽観ロック（`current_version` の照合）。リポジトリが 0 行を `rdb.ErrConflict` に翻訳する | `ErrConflict` をそのまま返す。再試行しない。境界が Aborted に翻訳し、呼ぶ側がやり直す |
| 分離レベル | `tx.Manager` の既定（READ COMMITTED） | 選ばない。`SERIALIZABLE` や `FOR UPDATE` が要ると思ったら、それは DB 制約かイベント型で表す関心で、データモデル資料へ返す |

usecase が「読んでから書く」あいだに他の tx が書いた事実は、読み取り検査では防げない。防ぐのは DB 制約と版であり、usecase は翻訳された sentinel を受け取って返すだけである。

## 5. error と rollback

| `fn` が返すもの | `Run` がすること | 結果 |
|---|---|---|
| nil | commit | 保存が残る。`(Result, bool)` の false で nil を返したときは、書き込みが無いまま commit される |
| ドメインの sentinel（文脈付き） | rollback | 何も残らない。境界が業務上の拒否として Info で記録する |
| `rdb.ErrNotFound` / `rdb.ErrConflict`（文脈付き） | rollback | 何も残らない |
| 読み取りポートや DB の失敗（文脈付き） | rollback | 何も残らない。境界が Internal として記録する |

途中で失敗した command は 1 行も残さない。2 集約を同じ tx で操作したなら、後の集約の保存が失敗したとき前の集約の保存も消える。これが「同じ操作」で一貫させるということで、usecase は補償の手順を書かない。
