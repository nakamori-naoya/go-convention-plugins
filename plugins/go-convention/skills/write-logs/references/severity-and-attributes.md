# レベルと属性

**レベルは「運用者に何をしてほしいか」で決め、属性は snake_case の固定語彙を型付き helper で渡す。`msg` は定型で、値を埋め込まない。**

## 1. レベル表

| レベル | 意味 | 運用者の反応 | 題材の例 |
|---|---|---|---|
| `Debug` | 開発時だけ要る内訳。本番の既定（`Info`）では出ない | 見ない | 読み取りポートが返した候補 ID の一覧、interceptor が読んだヘッダ名 |
| `Info` | 正常で、数えたい事象。**業務上の拒否・NotFound も `Info`** | 数える | RPC の完了、仮押さえを期限切れにした、確定が `ErrHoldDeadlinePassed` で拒まれた |
| `Warn` | 異常だが継続できた。再試行・部分失敗・楽観ロック競合 | 増えたら見る | 1 件の期限切れ処理に失敗して次へ進んだ、`rdb.ErrConflict` で `Aborted` を返した |
| `Error` | 想定外で、運用者の対応が要る | 今見る | `Internal` を返した、worker が panic した、隔離した |

業務上の拒否（`ErrNotOwner` / `ErrAlreadyConfirmed` / `rdb.ErrNotFound`）は、システムが正しく動いた結果である。`Error` にすると、対応が要る行と要らない行が同じ色で並び、`Error` を見る意味が無くなる。「クライアントが失敗した」と「システムが失敗した」を分けるのがレベルの仕事である。

`Debug` を本番で出す前提の設計にしない。出力の閾値は `applog.New` に渡す `slog.Leveler` が決め、本番は `slog.LevelInfo`。

## 2. Code からレベルへ

interceptor は翻訳後の `connect.Code` からレベルを決める（[middleware.md](middleware.md) §2 の `levelOf`）。sentinel を直接レベルに結び付けない。sentinel → Code の表はエラーの規約が持ち、この規約は Code → レベルの表だけを持つ。

| `connect.Code` | レベル | 理由 |
|---|---|---|
| `Internal` / `Unknown` / `DataLoss` / `Unimplemented` | `Error` | 想定外。コードの不備 |
| `Aborted` / `Unavailable` / `DeadlineExceeded` / `ResourceExhausted` | `Warn` | クライアントが再試行すれば通る。増えたら見る |
| それ以外（`InvalidArgument` / `NotFound` / `PermissionDenied` / `Unauthenticated` / `FailedPrecondition` / `AlreadyExists` / `Canceled` / `OutOfRange`） | `Info` | 正しく拒んだ |

worker の事象は [boundaries.md](boundaries.md) §6 の表に従う。

## 3. `msg` は定型

`msg` は「何が起きたか」を書く定型の文で、**値を埋め込まない**。値は属性へ出す。`msg` が定型なら、同じ事象を `msg` で数えられる。数える目的で別のキー（`event` 等）を足さない。

```go
// しない: 値が msg に入り、同じ事象が別の文字列になる
logger.InfoContext(ctx, fmt.Sprintf("予約 %s を期限切れにした", id))

// する: msg は定型、値は属性
logger.InfoContext(ctx, "仮押さえを期限切れにした", slog.String("reservation_id", id))
```

| 規則 | 内容 |
|---|---|
| 言葉 | 日本語。句点なし。「〜した」「〜に失敗したため次へ進む」のように、事象と取った行動を書く |
| 1 事象 1 文 | 「〜に失敗（同期は継続）」のように括弧で 2 つ目の情報を足さない。継続は `msg` の動詞で言う |
| `err` の文言を `msg` に写さない | `err` は属性で出る。`msg` に写すと `err` を変えたときに 2 か所ずれる |

## 4. 属性の語彙

キーは英語の `snake_case`。同じ意味に 2 つのキーを作らない。新しいキーを足すときはこの表に足す。

| キー | 型 / helper | 誰が付けるか | 意味 |
|---|---|---|---|
| `request_id` | `slog.String` | ctx handler（[middleware.md](middleware.md) §1） | 1 リクエストの識別子 |
| `caller` | `slog.String` | ctx handler | 認証済みの主体（顧客 ID）。未認証なら付かない |
| `procedure` | `slog.String` | interceptor | `req.Spec().Procedure` |
| `duration_ms` | `slog.Int64(…, d.Milliseconds())` | interceptor | 所要時間。ミリ秒 |
| `code` | `slog.String(…, code.String())` | interceptor | 翻訳後の `connect.Code` |
| `err` | `slog.Any` | 記録する側 | 翻訳前の error。JSON handler は `Error()` の文字列を出す |
| `panic` / `stack` | `slog.Any` / `slog.String` | recover した境界 | panic の値と `debug.Stack()` |
| `worker` | `slog.String` | supervisor | worker 名 |
| `backoff` | `slog.Duration` | supervisor | 再起動までの待ち |
| `attempt` / `attempts` | `slog.Int` | 再試行する側 | 何回目か / 何回試したか |
| `candidates` / `expired` | `slog.Int` | worker サイクルの完了サマリ | 件数 |
| `reservation_id` / `customer_id` / `room_code` | `slog.String` | 途中ログ | 業務 ID。primitive で渡す（[redaction.md](redaction.md) §1） |

| 規則 | 理由 |
|---|---|
| 型付き helper だけ（`slog.String` / `slog.Int` / `slog.Int64` / `slog.Duration` / `slog.Time` / `slog.Any`） | `"key", value` の交互引数は数がずれても動く。helper は型がキーと一緒に読める |
| `LogAttrs` か `*Context` 版 | どちらも `ctx` を取る。`ctx` を取らない `slog.Info` を書かない |
| 単位はキーに書き、値と一致させる | `slog.Duration` は JSON ではナノ秒の整数になる。`duration_ms` に `slog.Duration` を渡さない。`backoff` のようにキーに単位が無い所でだけ `slog.Duration` を使う |
| 時刻は `slog.Time` で UTC | `time.Time` を `slog.String` で整形しない。`Time` は RFC 3339 で出る |
| `err` のキーは `err` | `error` と混ぜない。`slog.Any("err", err)` |
| `slog.Group` を使わない | 語彙が平らなら検索も平らで済む。入れ子が要るほどの属性を 1 行に載せない |

## 5. `logger.With` の使い所

同じ属性を複数行に付けるなら `logger.With(slog.String("worker", name))` で子 logger を作る。worker のサイクル内の途中ログはこれで `worker` を持つ。子 logger も DI で渡す。`With` した logger を ctx に入れない（[boundaries.md](boundaries.md) §5）。
