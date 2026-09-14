---
name: write-logs
description: Go のログを `log/slog` で、最外境界（Connect の interceptor・worker の supervisor・外部受信境界）が 1 回だけ出す形に書く・直す。出す層と出さない層、二重ログ禁止、途中ログの許可基準、レベル表、属性語彙、値オブジェクトの秘匿を定める。「ログを出して」「このログを規約に合わせて」「どこでログを出すべきか」「interceptor でログを拾いたい」と言われたときに使う。エラーの分類と翻訳表の中身、監査記録の永続化、メトリクス・トレースの設計は対象外として、それぞれの規約へ返す。
---

# write-logs

これは、**ログを最外境界に集め、1 回だけ、同じ語彙で出すための規約**である。内側はエラーを返し、境界が拾って記録する。

これは、**エラーの分類**ではない（どの sentinel をどの `connect.Code` にするかはエラーの規約が決める。この規約は Code からレベルを決めるだけ）。**監査記録の正本**でもない（確定・取消の正本はイベント行で、ログは消えてもよい二次情報）。**メトリクス・トレース**でもない（数えたいなら `msg` を定型にする。ログ行を計測の代わりに設計しない）。

前提: Go 1.27・`log/slog`・`connectrpc.com/connect` v1.21.0（v2 alpha は採らない）。

| する | しない |
|---|---|
| 最外境界（interceptor / supervisor / 外部受信）で 1 回記録する | error を `return` する直前に `slog.Error` を置く |
| 境界へ返らない情報（部分失敗して続行・再試行の各回・成功した業務監査イベント）だけ途中ログを出す | ログを握りつぶしの代替にする（記録して `return nil`） |
| logger を境界の構造体へ DI する | logger を ctx に入れる。`nil` を `slog.Default()` へ丸める |
| 常に `*Context` 版 / `LogAttrs` で ctx を渡す | ドメイン package で `log/slog` を import する |
| 属性は snake_case の固定語彙、型付き helper、primitive だけ | 値オブジェクトや集約を `slog.Any` で丸ごと渡す。`msg` に値を埋め込む |
| 業務上の拒否・NotFound を `Info` にする | 拒否を `Error` にして対応が要る行と混ぜる |

## 規約

| # | 柱 | 一言で | 正本 |
|---|---|---|---|
| 1 | 出す層と出さない層 | 最外境界が 1 回。usecase は境界へ返らない情報だけ。リポジトリとドメインは出さない。判定式「返すなら書かない、飲み込むなら書く」 | [boundaries.md](references/boundaries.md) |
| 2 | middleware が拾う | 最外の interceptor `handler.Logging` が返ったエラーと ctx の属性から 1 回記録し、`codeTable` で `connect.Code` へ翻訳する。応答は sentinel の文言だけ。ctx から属性を足す `slog.Handler` のラッパ。worker は `worker.Supervise`。組み立ては `run` が `handler.NewMux(Deps)` と worker に同じ logger を渡す | [middleware.md](references/middleware.md) |
| 3 | レベルと属性 | Debug / Info / Warn / Error の表。Code → レベル。snake_case の語彙、型付き helper、`msg` は定型 | [severity-and-attributes.md](references/severity-and-attributes.md) |
| 4 | 秘匿 | primitive だけ渡す・`String()` を書かない・JSON handler・`ReplaceAttr` の安全網。`LogValuer` をドメインに置かない | [redaction.md](references/redaction.md) |

## 手順

1. **境界を確かめる。** 対象のプロセスに、最外の interceptor（`handler.Logging`）と worker の supervisor（`worker.Supervise`）があるかを見る。無ければ [middleware.md](references/middleware.md) の形で置き、`handler.NewMux` の interceptor の並びで先頭（最外）にする。既にあるなら足さない。完了条件: RPC 1 回・worker 1 サイクルにつき、記録する場所が 1 か所に決まっている
2. **出したい行が境界へ返るかを問う。** その情報は error 鎖に載って境界へ届くか。届くなら書かない（`return err` で足りる）。届かない（`continue` で飲み込む・再試行の各回・1 件ごとの成功）なら途中ログにする。完了条件: 書く行ごとに [boundaries.md](references/boundaries.md) §4 のどの行に当たるかを言える
3. **層を確かめる。** 途中ログを書く場所が worker の `Run` か usecase である。リポジトリ・query service・ドメインなら書かず、エラーを返す形に戻す。1 件 1 tx の command は error を返すだけで、ループと途中ログは worker が持つ。完了条件: ドメイン package に `log/slog` の import が無い
4. **レベルと `msg` と属性を決める。** [severity-and-attributes.md](references/severity-and-attributes.md) の表からレベルを選び、`msg` を定型の日本語 1 文にし、属性を語彙表のキーと型付き helper で書く。語彙に無いキーが要るなら表に足す。完了条件: `msg` に値が無く、属性のキーが全部語彙表にある
5. **秘匿を確かめる。** 属性に渡す値が primitive で、値オブジェクトは getter で取り出している。新しい秘匿キーがあれば `secretKeys` とテストに足す。完了条件: `slog.Any` に渡しているのが `err` / `panic` だけ
6. **機械で見られる分を通す。**
   ```bash
   go vet ./...                                                   # slog の key/value 対の不整合
   grep -rln '"log/slog"' ./reservation                           # ドメイン package。0 件であること
   grep -rnE '\bslog\.(Debug|Info|Warn|Error)\(' --include='*.go' . # ctx を取らない呼び出し。0 件であること
   ```
   完了条件: 3 つとも指摘が無い
7. **報告する。** 「報告」の項目

## 停止条件

- ドメイン package（値オブジェクト・集約・イベント）にログを求められた → 書かない。sentinel か遷移結果型で外へ出す設計を提案して止まる
- error を記録して `return nil` する要求で、[boundaries.md](references/boundaries.md) §4 の許可基準に当たらない → 書かない。`return err` にするか、継続を制御フローで明示する設計を返す
- ログを監査記録の正本にする要求（ログから業務状態を復元する前提） → 対象外。イベント行の設計へ返す
- メトリクス・トレース・アラートの配線 → 対象外。計測基盤の規約へ返す
- 出したい値が値オブジェクトの中にあり、primitive を取り出す getter が無い → 書かない。その値が運用に要るかをドメインの規約へ返す
- sentinel と `connect.Code` の対応を変えたい → 対象外。エラーの規約へ返す（この規約が持つのは Code → レベルだけ）

## チェックリスト（機械で言えないことだけ）

- [ ] 同じ失敗が 2 行にならない。`return` する error の直前に `slog.Error` / `slog.Warn` が無い
- [ ] 途中ログの各行が「境界へ返らない情報」である（部分失敗して続行・再試行の各回・1 件ごとの成功・完了サマリ）
- [ ] 記録して `return nil` している箇所は、継続が意図であることが制御フロー（`continue`）で読める
- [ ] handler の server 実装と内側の interceptor が記録していない。記録は最外の interceptor だけ
- [ ] worker は `worker.Supervise` で起動している。`go fn()` が無い
- [ ] logger は構造体へ DI され、ctx に入っていない。`nil` を既定へ丸めていない。途中ログを持つ worker の `Run` は logger を DI で受けている
- [ ] 業務上の拒否・NotFound が `Info`、想定外だけが `Error`
- [ ] `msg` が定型の日本語 1 文で、値を含まない
- [ ] 属性のキーが語彙表にあり、`duration_ms` に `slog.Duration` を渡していない
- [ ] `slog.Any` に渡しているのが `err` / `panic` だけ。値オブジェクトに `String()` / `LogValue` が無い
- [ ] テストの logger が `slog.DiscardHandler` か `t.Output()` で、ログの有無を検証していない

## 報告

- 置いた境界（interceptor / supervisor / HTTP middleware）と、その組み立て位置（`run` の中で最外か）
- 途中ログを書いた箇所と、それぞれが許可基準のどの行に当たるか
- 語彙表に足したキーと、`secretKeys` に足したキー
- 停止条件に当たって返した論点（ドメインの getter、エラーの翻訳表、監査記録、計測）
