# 出す層と出さない層

**ログは最外境界が 1 回だけ出す。内側はエラーに文脈を足して返し、返す直前にログしない。** 境界へ返らない情報だけが、発生した場所で途中ログになる。

## 1. ログの横断的関心事とは何か

ログは「その処理で何が起きたか」を、運用者があとから読める形で 1 行残すことである。次のものではない。

| ログではないもの | 誰の関心か | ログはどう関わるか |
|---|---|---|
| エラーの分類 | エラーの規約（sentinel と `errors.Is`、層境界での包み方） | 分類の結果（どの sentinel か・どの `connect.Code` になったか）を読んでレベルを決めるだけ。ログの都合でエラーの型や文言を変えない |
| 監査記録の正本 | データモデル（イベント系テーブル）と usecase | 「確定した」「取り消した」の正本はイベント行である。ログは消えてもよい二次情報。ログを頼りに業務を復元しない |
| メトリクス・トレース | 計測基盤 | 件数を数えたいなら `msg` を定型にして数える（[severity-and-attributes.md](severity-and-attributes.md) §3）。ログ行をメトリクスの代わりに設計しない |

## 2. 出す層・出さない層

| 層 | 出すか | 何を |
|---|---|---|
| 最外境界: Connect の interceptor / HTTP middleware | **出す。RPC 1 回につき 1 行** | 返ったエラー（または成功）と、ctx の属性（`request_id` / `caller`）、`procedure`、`duration_ms`、`code` |
| 最外境界: worker の supervisor | **出す** | panic（stack 付き）、予期せぬ終了と再起動、隔離 |
| worker の `Run` | **境界へ返らない情報だけ** | 1 件ずつ usecase を呼ぶループで、飲み込んだ 1 件の失敗、1 件ごとの成功、サイクルの完了サマリ（§4） |
| 最外境界: 外部受信（Webhook / メッセージ購読） | **出す** | ack して破棄するか、再配信させるかの判断と理由 |
| handler の server 実装（`ReservationServer` のメソッド） | 出さない | エラーを返す。interceptor が拾う |
| usecase | **境界へ返らない情報だけ** | 再試行の各回、部分失敗して続行した 1 件（§4）。1 件 1 tx の command（`ExpireReservation` 等）は error を返すだけで、途中ログを持たない |
| リポジトリ / query service | 出さない | エラーを sentinel へ翻訳して返す |
| ドメイン（値オブジェクト・集約・イベント） | 出さない。**`log/slog` を import しない** | 純粋な値か error を返す |

ドメイン package が `log/slog` を import しないのは、ログの出し方（属性語彙・秘匿・レベル）が変わるたびにドメインが変わるのを防ぐためである。ドメインが運用者に伝えたいことは、sentinel と遷移結果型で外へ出る。

## 3. 二重ログ禁止

**error を `return` する直前に `slog.Error` / `slog.Warn` を置かない。** 返した error は最外境界が 1 回だけ記録する。内側で記録すると、同じ失敗が層の数だけ並び、件数が信用できなくなる。

判定式は 1 つ。

> **返すなら書かない。飲み込むなら書く。**

`ConfirmReservation.Execute` の中、`tx.Run` の閉包で復元するところ:

```go
// しない: 返す error を記録している。interceptor でもう 1 回出る
r, err := u.repo.FindByID(ctx, id)
if err != nil {
	slog.ErrorContext(ctx, "予約の取得に失敗", slog.Any("err", err))
	return fmt.Errorf("予約 %s の確定: %w", in.ReservationID, err)
}

// する: 文脈を足して返すだけ。記録は最外境界に任せる
r, err := u.repo.FindByID(ctx, id)
if err != nil {
	return fmt.Errorf("予約 %s の確定: %w", in.ReservationID, err)
}
```

**ログを握りつぶしの代替にしない。** error を記録して処理を終える（`return nil` する）のは「飲み込む」であり、それが意図なら §4 の許可基準を満たしているかを問う。満たさないなら `return err` する。

```go
// しない: 記録して黙る。呼び出し側は成功したと思う
if err := u.repo.ApplyConfirmed(ctx, res.Event); err != nil {
	slog.ErrorContext(ctx, "確定の保存に失敗", slog.Any("err", err))
}
return nil
```

## 4. 途中ログの許可基準

途中ログは「境界へ返らず失われる情報」にだけ許す。error 鎖に載って境界へ届く情報は、途中で書かない。

| 許す | 理由 | レベル |
|---|---|---|
| 部分失敗して続行した 1 件 | `continue` した失敗は境界へ届かない | `Warn` |
| 再試行の各回 | 最終エラーだけでは回数と待ち時間が復元できない | `Warn` |
| 成功した業務監査イベント（worker が 1 件ずつ処理した結果） | error ではないので境界へ返らない | `Info` |
| worker サイクルの完了サマリ（件数） | 正常結果は error 鎖に載らない | `Info` |

題材: 仮押さえ期限の掃除。usecase `ExpireReservation` は 1 件 1 tx で、`Input{ReservationID, At}` を受けて期限到来を反映し、error を返すだけである（途中ログを持たない）。ループは worker `HoldExpirer.Run` が持ち、1 件の失敗で残りを止めないので、その失敗は境界（supervisor）へ返らない。ここが途中ログの置き場になる。

`worker/hold_expirer.go`。`NewHoldExpirer` は worker 側の composition root で、環境で変わるもの（pool・logger・時計・周期）だけを `Deps` で受け、tx・リポジトリ・usecase・query service は内部で組む。`run` はこれらを組まない:

```go
package worker

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"example.com/roomflow/query"
	"example.com/roomflow/rdb"
	"example.com/roomflow/tx"
	"example.com/roomflow/usecase"
)

// DueHoldReader は期限が到来した仮押さえの予約番号を返す読み取りポート。実物は query.DueHoldQuery。
type DueHoldReader interface {
	ListDueHoldIDs(ctx context.Context, at time.Time) ([]string, error)
}

// Clock は判定時刻の持ち主。1 サイクルにつき 1 回だけ読み、全件を同じ時刻で判定する。
type Clock interface {
	Now() time.Time
}

// Deps は環境で変わるものだけ。run は本番の値を、テストは実 DB・固定時計・短い周期を渡す。
type Deps struct {
	Pool   *pgxpool.Pool
	Logger *slog.Logger // 途中ログを持つので DI で受ける
	Clock  Clock
	Every  time.Duration
}

// HoldExpirer は周期ごとに期限到来の仮押さえを 1 件ずつ期限切れにする常駐 worker。Supervise で起動する。
type HoldExpirer struct {
	due    DueHoldReader
	expire *usecase.ExpireReservation
	clock  Clock
	every  time.Duration
	logger *slog.Logger
}

// NewHoldExpirer は tx.Manager・リポジトリ・usecase・query service を組む。配線はここにだけある。
func NewHoldExpirer(d Deps) *HoldExpirer {
	manager := tx.NewManager(d.Pool)
	return &HoldExpirer{
		due:    query.NewDueHoldQuery(d.Pool),
		expire: usecase.NewExpireReservation(manager, rdb.NewReservationRepository()),
		clock:  d.Clock,
		every:  d.Every,
		logger: d.Logger,
	}
}

// Run は ctx が終わるまで周期ごとに 1 サイクル動かす。サイクル全体の失敗は返す（supervisor が記録して再起動する）。
func (w *HoldExpirer) Run(ctx context.Context) error {
	ticker := time.NewTicker(w.every)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ticker.C:
			if err := w.runOnce(ctx); err != nil {
				return err // 記録しない。supervisor が記録する
			}
		}
	}
}

// runOnce は 1 サイクル。一覧の失敗は返し、1 件の失敗は記録して次へ進む。
func (w *HoldExpirer) runOnce(ctx context.Context) error {
	at := w.clock.Now().UTC()
	ids, err := w.due.ListDueHoldIDs(ctx, at)
	if err != nil {
		return fmt.Errorf("期限到来の仮押さえの取得: %w", err) // 返す。記録しない
	}
	expired := 0
	for _, id := range ids {
		in := usecase.ExpireReservationInput{ReservationID: id, At: at}
		if err := w.expire.Execute(ctx, in); err != nil {
			// 1 件の失敗で残りを止めない。この失敗は境界へ返らないので、ここで記録する
			w.logger.WarnContext(ctx, "仮押さえの期限切れ処理に失敗したため次へ進む",
				slog.String("reservation_id", id),
				slog.Any("err", err),
			)
			continue
		}
		expired++
		// 成功した業務監査イベント。supervisor は 1 件ごとの結果を知らない
		w.logger.InfoContext(ctx, "仮押さえを期限切れにした", slog.String("reservation_id", id))
	}
	w.logger.InfoContext(ctx, "仮押さえ期限の掃除が完了した",
		slog.Int("candidates", len(ids)),
		slog.Int("expired", expired),
	)
	return nil
}
```

`ListDueHoldIDs` の失敗は `return` で境界（supervisor）へ返るので記録しない。1 件ごとの失敗は `continue` で飲み込むので記録する。同じ関数の中で、判定式がそのまま行動を決める。

`Execute` の中の失敗（`FindByID` の `rdb.ErrNotFound`、`AsTentative` の `ErrAlreadyConfirmed`、`ApplyExpired` の `rdb.ErrConflict`）はどれも `Execute` が文脈を足して返し、`runOnce` の `Warn` 1 行に `err` として載る。usecase の中で記録すると、同じ 1 件が 2 行になる。期限到来の直前に確定された予約は `ErrAlreadyConfirmed` で拒まれ、それは業務上正しい結果だが、一覧に載った予約が期限切れにならなかった事実は運用者が数えたいので `Warn` のままにする。

## 5. logger の受け渡し

| 規則 | 内容 |
|---|---|
| DI | logger を必要とする境界の構造体（interceptor・supervisor・途中ログを持つ worker や usecase）は `*slog.Logger` をコンストラクタで受け取る。`nil` を `slog.Default()` へ丸めるフォールバックを書かない。logger は `run` が 1 つ作り、`handler.Deps.Logger` と `worker.Deps.Logger` へ明示的に渡す |
| ctx に入れない | `context.WithValue` で logger を運ばない。ctx から取り出す関数を書かない。運ぶのは属性の元になる値（`request_id` / `caller`）であり、logger ではない（[middleware.md](middleware.md) §1） |
| 必要な構造体だけ | 途中ログを持たない usecase・リポジトリ・query service に logger のフィールドを置かない。フィールドがあれば誰かが使う |
| `main` で 1 回 | `run` の先頭で logger を 1 つ作り `slog.SetDefault` を 1 回呼ぶ。自分のコードで `slog.Default()` を呼ばない。`SetDefault` は標準 `log` と外部ライブラリの出力を同じ handler へ向けるためにある |
| 常に `*Context` 版 | `InfoContext` / `WarnContext` / `ErrorContext` / `DebugContext` / `LogAttrs` / `Log`。`ctx` の無い `slog.Info` を書かない。ctx から属性を足す handler（[middleware.md](middleware.md) §1）は ctx が無いと働かない |
| テストでは | `slog.New(slog.DiscardHandler)` を渡す。失敗時に読みたければ `slog.New(slog.NewTextHandler(t.Output(), nil))`。ログが出たかをテストで検証しない |

## 6. worker と外部受信の境界

常駐 worker は `go fn()` で起動しない。goroutine 内の panic と `Run` の予期せぬ終了を誰も観測できない。`worker.Supervise(ctx, name, logger, fn)` で起動し、supervisor が次を記録する（コードは [middleware.md](middleware.md) §4）。

| 事象 | 記録 | レベル |
|---|---|---|
| panic | `worker` / `panic` / `stack` を記録し、error にして再起動へ | `Error` |
| 予期せぬ `return` | `worker` / `backoff` / `err` を記録し、指数バックオフで再起動 | `Error` |
| `ctx` キャンセルによる終了 | 記録しない。正常終了 | — |
| 最大試行超過で 1 件を隔離 | `reservation_id` / `attempts` / `err` | `Error` |

worker の `Run` の中は usecase と同じ扱いである。サイクル全体の失敗は `return err` で supervisor へ返し、1 件の失敗を飲み込んで続けるなら §4 の途中ログを出す。途中ログを持つ worker の `Run` は logger を DI で受ける（§4 の `HoldExpirer`）。

外部受信境界（Webhook・メッセージ購読）では「ack して破棄する」「非 2xx で再配信させる」の判断を必ず記録する。黙って破棄しない。再送で直らない失敗（署名不正・壊れた envelope）は ack して `Warn`、一過性の失敗（DB 接続）は再配信させて `Error`。判断は受信 handler の外側の middleware が、返ったエラーから 1 回で行う。
