---
name: implement-handler
description: Connect-RPC（connectrpc.com/connect ＋ protobuf）の入口を Go で実装する・直す。生成された `{Service}Handler` を満たす薄い server 実装、proto の要求・応答と usecase の入出力を往復させる変換関数、返った error を 1 回だけ記録して `connect.Code` へ翻訳し呼び手の主体を ctx へ載せる interceptor、操作の時刻を決めるサーバーの `Clock`、`NewMux(Deps)` での依存の組み立てと `main` の `run(ctx) error` での起動と graceful shutdown を定める。「この RPC を実装して」「handler を書いて」「proto と usecase をつないで」「interceptor を置いて」「main の組み立てを書いて」と言われたときに使う。業務判断・トランザクション・永続化・エラーの分類表の中身・ログのレベルと語彙・何をテストするかは対象外として、それぞれの規約へ返す。
---

# implement-handler

これは、**RPC の要求を usecase の入力へ写し、usecase を 1 つ呼び、結果を応答へ写して返す薄い層の書き方**である。何を許し何を拒むかは集約と usecase が決め、handler はその入口と出口だけを持つ。

これは、**業務判断の置き場ではない**（期限・本人確認・重なりは集約が拒む）。**トランザクションの持ち主でもない**（tx は usecase が張る）。**永続化の呼び手でもない**（リポジトリも query service も usecase の向こうにある）。**エラーの分類器でもない**（どの sentinel をどの `connect.Code` にするかはエラーの規約が決め、この規約は対応表を置く場所と引き方だけを決める）。**ログの出し手でもない**（何をどのレベルで出すかはログの規約が決め、この規約は interceptor が 1 回だけ拾う形だけを決める）。

前提: Go 1.27・`connectrpc.com/connect` v1.21.0（v2 は alpha で採らない）・`google.golang.org/protobuf`（`timestamppb`）・`github.com/jackc/pgx/v5`（`pgxpool`。組み立てで使う）・標準の `uuid` package（採番の実物）。

| する | しない |
|---|---|
| 生成された `roomflowv1connect.ReservationServiceHandler` を `ReservationServer` で満たす。1 RPC = 1 usecase | 1 つの RPC から複数の usecase を呼ぶ。RPC の中で usecase を組み合わせる |
| 要求 → usecase の入力、usecase の出力 → 応答の変換を handler package の関数 `{元}To{先}` に置く | proto の型を usecase やドメインへ渡す。ドメインの型を proto へ直に写す |
| 欠けた入力（nil の Timestamp）を `InvalidArgument` になる公開 sentinel（`ErrStartsAtRequired`）で返す | 欠けた入力を既定値に丸める（nil の `AsTime()` が 1970 年になるのを通す） |
| 操作の時刻は server の `Clock.Now()` を 1 回呼び、usecase の入力の `At` に載せる | 要求の本文から操作の時刻（`confirmed_at`）を受け取る。`time.Now()` を handler に書く |
| 呼び手の主体を ctx から読み、usecase の入力（`CustomerID`）に載せる | 主体を要求の本文から信じる。handler の中で本人かどうかを判断する |
| usecase の error を `return nil, err` でそのまま返す | `connect.NewError` を server 実装に書く。`slog` を server 実装に書く。`errors.Is` で分岐する |
| interceptor: 最外が recover・ログ 1 回・翻訳、内側が認証と主体の記録 | 認証を server 実装の各メソッドに書く。翻訳表を RPC ごとに持つ |
| `main` は `run(ctx) error` を呼んで `os.Exit`。`run` は環境で変わるもの（`Deps`）を作り、`NewMux(Deps)` が tx・リポジトリ・query service・usecase・server・interceptor 列を内側から外側へ全部組み立てる | グローバル変数と `init` で依存を持つ。`run` の外で接続を開く。usecase やリポジトリを `run` で組む |

## 規約

| # | 柱 | 一言で | 正本 |
|---|---|---|---|
| 1 | server 実装 | `ReservationServer` が生成 interface を満たし、`Clock` を持つ。`Unimplemented*` を埋め込まない。メソッドは「主体 → 変換（時刻は `Clock` から）→ usecase → 応答」の 4 行 | [connect-server.md](references/connect-server.md) |
| 2 | 変換 | handler package の純粋関数 `{元}To{先}`。ID は文字列のまま、時刻は `timestamppb` ↔ `time.Time`（UTC）、操作の時刻 `At` は引数で受ける、欠けは公開 sentinel | [dto-mapping.md](references/dto-mapping.md) |
| 3 | interceptor | `Logging`（Scope・recover・ログ 1 回・翻訳表）と `Auth`（主体を Scope へ）。翻訳表は 1 か所、`connect.NewError` は interceptor だけが書く | [interceptors.md](references/interceptors.md) |
| 4 | 組み立てと起動 | `NewMux(Deps{Pool, Logger, Clock, Auth})` が配線の 1 か所（採番の実物 `idgen.NewRandom()` もここ）。`main` → `run(ctx) error`、`signal.NotifyContext`、`pgxpool.New`、`Deps`、h2c、graceful shutdown | [wiring.md](references/wiring.md) |

題材は貸会議室予約の `ConfirmReservation` RPC。module は `example.com/roomflow` で、ディレクトリ構成は上位の開発規約が決めるため、例は import path を短くするため平らにしている。

## 手順

1. **RPC と usecase を 1:1 に対応させる。** proto の `service` にある RPC を列挙し、それぞれが呼ぶ usecase（`usecase.ConfirmReservation` 等）と入力型・出力型を指す。usecase が無い RPC、2 つの usecase が要る RPC があれば停止条件へ。完了条件: RPC ごとに usecase の型名と `Execute` の入出力が 1 行で書けている
2. **変換関数を書く。** [dto-mapping.md](references/dto-mapping.md) の形で、要求 → 入力（`confirmRequestToInput`）と出力 → 応答（`holdOutputToResponse`）を handler package に置く。必須の Timestamp は `IsValid` で確かめ、欠けていれば handler の公開 sentinel を返す。操作の時刻は引数 `at` で受けて `At` に載せる。完了条件: 関数が proto の型・usecase の型・`time.Time` だけを引数・返り値に持ち、ドメインの型と `time.Now()` が現れない
3. **server 実装を書く。** [connect-server.md](references/connect-server.md) の形で `ReservationServer` のメソッドを書く。本体は「`callerFrom` → 変換（`s.clock.Now()` を 1 回渡す）→ `Execute` → `connect.NewResponse`」で、error はそのまま返す。完了条件: メソッドに `connect.NewError`・`slog`・`errors.Is`・`tx`・`time.Now()`・リポジトリの呼び出しが無い
4. **interceptor を確かめる。** `Logging` と `Auth` が [interceptors.md](references/interceptors.md) の形で handler package にあるかを見る。無ければ置く。あれば足さない。翻訳表 `codeTable` に、この RPC が新しく返しうる sentinel（handler の欠け sentinel、読み取り RPC なら `query` の sentinel を含む）の行があるかを見る。完了条件: `connect.NewError` を書いているファイルが interceptor と翻訳表のファイルだけ
5. **組み立てへつなぐ。** [wiring.md](references/wiring.md) の `NewMux(Deps)` に新しい usecase の生成と server への注入を足す。`run` は `Deps`（pool・logger・時計・認証）を作って `NewMux` を呼ぶだけで、変えない。完了条件: `NewMux` に usecase の生成と注入があり、`run` に usecase・リポジトリ・query service の生成が無く、interceptor の並びを変えていない
6. **機械で見られる分を通す。**
   ```bash
   go vet ./...
   go build ./...
   grep -rn 'connect\.NewError' --include='*.go' ./handler | grep -v -e '_interceptor\.go' -e 'error_table\.go' -e 'handlertest/'   # 0 件であること（handlertest/ はテスト用の主体注入 interceptor で、テストの規約が持つ）
   grep -rn '"log/slog"' --include='*.go' ./handler | grep -v -e '_interceptor\.go' -e 'mux\.go'                  # 0 件であること
   grep -rln 'gen/roomflowv1' --include='*.go' . | grep -v -e '^./handler/' -e '^./gen/' -e '_test\.go$'          # 0 件であること（proto の型が内側へ漏れていない）
   ```
   完了条件: 3 つの grep が 0 件で、`vet` と `build` に指摘が無い
7. **報告する。** 「報告」の項目

## 停止条件

- RPC に対応する usecase が無い → 書かない。usecase を先に用意することを提案して止まる（handler に業務手順を書いて埋めない）
- 1 つの RPC が 2 つ以上の usecase を要する → 書かない。複数集約の協調は usecase の関心なので、それらを束ねる usecase を 1 つ作ることを提案して止まる
- 要求に無い値を「未指定なら既定値」で埋めるよう求められた（時刻・件数・列挙の `_UNSPECIFIED`） → 書かない。既定へ倒す前に利用者の許可を得る。許可があれば、既定を使ったことを応答で分かる形にする
- 認証の方式（トークンの形・検証先）が決まっていない → `Verifier` interface までを書き、実装は止まる。方式は上位の規約が決める
- server 実装からリポジトリ・query service・`tx.Manager` を直接呼ぶよう求められた → 書かない。usecase の読み取りポートか command を通す形を提案して止まる
- 応答にドメインの型をそのまま載せたい（`reservation.Reservation` を返す） → 書かない。usecase の出力型か query service の DTO を経由する形を提案して止まる

## チェックリスト（機械で言えないことだけ）

- [ ] RPC 1 つにつき usecase 1 つ。メソッド本体が「主体 → 変換 → `Execute` → 応答」で、それ以外の行が無い
- [ ] `ReservationServer` が `Unimplemented*` を埋め込まず、`var _ roomflowv1connect.ReservationServiceHandler = (*ReservationServer)(nil)` がある
- [ ] 変換関数の名前が `{元}To{先}` で、handler package にあり、proto の型と usecase の型だけを扱う
- [ ] 必須の Timestamp を `IsValid` で確かめ、nil を 1970 年に倒していない。`AsTime()` の結果をそのまま渡している（UTC）
- [ ] 文字列の ID を usecase の入力へそのまま渡し、handler で値オブジェクトを作っていない
- [ ] `CustomerID` は ctx の主体から取り、要求の本文から取っていない
- [ ] 翻訳表が 1 か所で、応答に出る文言が sentinel の文言だけ。内部の文脈・SQL・外部ライブラリの文言が出ない
- [ ] `Logging` が最外で、`Auth` がその内側。`NewMux` 以外で `WithInterceptors` を呼んでいない
- [ ] `NewMux(Deps)` が依存を内側から外側へ組み立て、`run` は `Deps` を作って渡すだけ、`main` は `run` を呼んで `os.Exit` するだけ
- [ ] 操作の時刻は `ReservationServer` の `Clock` から 1 回。要求の message に操作の時刻が無い
- [ ] 環境変数が欠けていれば `run` が error で止まり、既定のポートや接続先に倒れない

## 報告

- 実装した RPC と、対応する usecase の型名・入出力
- 変換関数の一覧（`{元}To{先}`）と、欠けを拒む sentinel
- 翻訳表に足した行（sentinel と `connect.Code`）。足さずに `Internal` にした sentinel とその理由
- `NewMux` に足した usecase と依存、`Deps` の 4 つ、interceptor の並び
- 機械検査の結果（`go vet` / `go build` / 3 つの grep）
- 停止条件で返した論点（usecase が無い RPC、既定値を求められた入力、認証方式）
