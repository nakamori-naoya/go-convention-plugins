---
name: go-convention-internal-write-go-code
description: Go 1.27 のコードを、層を問わない言語レベルの規約（返り値は最大 2 つ、naked return 禁止、ctx 第一引数、値渡し既定、使う側で定義する小さな interface、封じた struct の列挙、init 禁止、明示・丸めない・フォールバックしない・ガード節、標準ライブラリの 1.27 idiom、gofmt / go vet / golangci-lint / go fix）で書く・直す。「この Go コードを規約に合わせて」「Go の書き方を確認したい」「この関数のシグネチャを直して」「1.27 の書き方にして」と言われたとき、また層別の実装規約（ドメイン・永続化・usecase・handler）がこの規約を土台に指定したときに使う。ドメインモデルの設計、リポジトリと query service の形、usecase と handler の形、エラーの定義と翻訳、ログの置き場、テストの形と厚みは対象外としてそれぞれの規約へ返す。
---

# write-go-code

これは、**Go 1.27 のコードを、どの層でも同じ言語レベルの形で書くための規約**である。関数の形（返り値・引数・レシーバ）、型と interface の切り方、命名、標準ライブラリの選び方、ツールの構成を一つに揃える。

これは、**何を作るか（設計）を決めるものではない。** 値オブジェクト・集約・イベントの構造と操作はドメインモデルの規約が、永続化ポートの実装と行の変換は永続化の規約が、トランザクション境界と協調は usecase の規約が、入口と DTO 変換は handler の規約が、sentinel の定義・文言・包み方・翻訳はエラーの規約が、どの層がログを出すかはログの規約が、テストの形と何をテストするかはテストの規約が決める。この規約はそれらが共通に載る言語の土台で、言語に依存しない設計原則（YAGNI・層の定義・ディレクトリ構成）は上位の開発規約に置く。

前提: Go 1.27（`go.mod` の `go 1.27`）。標準ライブラリを優先し、外部依存は `golang.org/x/sync/errgroup`、`golang.org/x/tools`（goimports）、golangci-lint v2、および層別の規約が指定するもの（`github.com/jackc/pgx/v5`、`github.com/sqlc-dev/sqlc`、`connectrpc.com/connect` v1.21.0（v2 alpha は採らない）、`google.golang.org/protobuf`、`github.com/stretchr/testify`、`github.com/ory/dockertest/v4`）だけ。例の題材は貸会議室予約（module `example.com/roomflow`。ディレクトリ構成は上位の開発規約が決めるので、例は import path を短くするため package を平らに置いている）。

## 規約

| # | 柱 | 一言で | 正本 |
|---|---|---|---|
| 1 | 基本 | 明示を選ぶ・丸めない・フォールバックしない・ガード節。返り値は最大 2 つ、naked return 禁止、ctx 第一引数、引数が多いなら struct、値渡し既定、レシーバ統一、フィールド名付きリテラル、`init` 禁止、`main` は `run(ctx) error` | [basics.md](references/basics.md) |
| 2 | 命名 | package は短い小文字で `util` / `common` 禁止、getter に `Get` 無し、`Equal`、頭字語は `ID` / `URL`、レシーバ 1〜2 文字、`New` / `Restore`、`Err*`、`{元}To{先}` | [naming.md](references/naming.md) |
| 3 | 型と interface | interface は使う側で小さく（例外: 永続化ポートと和型はドメインが定義）、`any` は decode 境界だけ、generics は 2 条件、ジェネリックメソッドは既定で使わない、列挙は封じた struct、`default` は error、sealed interface、ゼロ値 | [types-and-interfaces.md](references/types-and-interfaces.md) |
| 4 | 標準ライブラリ | `min` / `max` / `clear`、`range n`、`slices` / `maps` / `iter`、`strings.Lines` / `SplitSeq` / `CutLast`、UTC、`math/rand/v2`、`os.Root`、`WaitGroup.Go` / `errgroup`、`synctest`、`testing` の 1.24〜1.26 API、`encoding/json/v2` ＋ `jsontext`、`errors.AsType`、`slog.NewMultiHandler` | [stdlib-1.27.md](references/stdlib-1.27.md) |
| 5 | ツール | `go 1.27`、`tool` directive、gofmt / goimports、`go vet`（1.27 は `stdversion` 既定）、golangci-lint v2 の linter 一覧と設定、`go fix` modernizer、`-race -shuffle=on -count=1` | [tooling.md](references/tooling.md) |

**書き始める前に 5 本を一度読む。** 各規則は「する／しない」と理由で書いてあり、理由が当てはまらない場面は無い。

## 手順

1. **対象と層を決める。** 直す・書くファイルと、それがどの層（ドメイン・永続化・query service・usecase・handler・main）かを言う。層固有の形（型の構造・ポート・tx・DTO）は層別の規約に従い、この規約は言語レベルだけを見る。完了条件: 対象ファイルの一覧と、各ファイルの層が 1 行で言える
2. **`go.mod` とツールを確かめる。** `go 1.27`、`tool` directive、`.golangci.yml` が [tooling.md](references/tooling.md) の形になっている。無ければ先に整える。完了条件: `go tool golangci-lint run ./...` が実行できる
3. **関数の形を揃える。** 返り値の数、`ctx` の位置、引数の数、値／ポインタ、レシーバ、naked return、ガード節を [basics.md](references/basics.md) に合わせる。既定値への丸め・フォールバックが見つかったら消して `error` を返す形にする（フォールバックが要ると判断した場合は停止条件）。完了条件: 各関数のシグネチャが §基本 の表のどれかに一致し、`else` の入れ子と naked return が無い
4. **型と interface を揃える。** interface の定義場所（使う側。例外はドメインのポートと和型）、`any` と generics の使用箇所、列挙の形、`switch` の `default` を [types-and-interfaces.md](references/types-and-interfaces.md) に合わせる。完了条件: 各 interface について「誰が使うから誰が定義した」が言え、`default` が全部 `error` を返す
5. **名前を揃える。** package 名、型名、getter、頭字語、レシーバ名、sentinel、変換関数を [naming.md](references/naming.md) に合わせる。完了条件: `go vet` と `staticcheck` の命名の警告が無く、`Get` 接頭辞・`Impl` 接尾辞・`util` package が無い
6. **標準ライブラリに置き換える。** 自前の補助関数・古い API・`x := x`・`sort.Slice`・`math/rand` v1・`encoding/json` v1 を [stdlib-1.27.md](references/stdlib-1.27.md) の表で置き換える。`go fix ./...` を先に走らせ、残りを手で直す。完了条件: `go fix ./...` が差分を出さず、表の「書かない」列の綴りがコードに無い
7. **機械検査を通す。** 完了条件: 次が全部通る
   ```bash
   gofmt -l .                                            # 空
   go tool goimports -local <module path> -l .           # 空
   go vet ./...
   go tool golangci-lint run ./...
   go test -race -shuffle=on -count=1 ./...
   ```
8. **報告する。** 下の「報告」の項目を書く

## 停止条件

- **フォールバックが要ると判断した**（一次手段の失敗時に別の手段で続行しないと要件を満たせない）→ 書かずに止まる。一次手段、失敗の条件、代替手段、続行したときに隠れる失敗を利用者に示し、許可を得てから書く。許可が無ければ `error` を返す形にする
- 既定値への丸めが「仕様」だと主張されている（「無ければ 0 として扱う」が資料に書いてある）→ 丸めをコードに書かず止まる。資料のその行を示し、`error` を返す形にできないか利用者に確かめる
- 返り値を 3 つ以上にしないとシグネチャが決まらない → 結果 struct を提案して止まる。struct の名前と中身は層別の規約（ドメインの遷移結果型・usecase の結果）が決めるので、そこへ返す
- interface をどこで定義するかが「使う側」でも「ドメインのポート／和型」でもない（例: 2 つの usecase が同じ読み取り interface を要る）→ 定義場所を決めずに止まる。usecase の規約（読み取りポートの置き場）へ返す
- `go.mod` が `go 1.27` 未満で上げられない事情がある → 1.27 の機能（ジェネリックメソッド・`encoding/json/v2`・`strings.CutLast`）を使わずに書けるかを確かめ、使わないと書けないなら止まる
- 対象が生成コード（`sqlcgen` / `gen/`）→ 直さない。生成元（SQL / proto）を直すことを提案して止まる

## 機械検査で言えること

| 検査 | 通ったら言えること |
|---|---|
| `gofmt -l` / `goimports -l` が空 | フォーマットと import の順序は規約どおり |
| `go vet`（1.27 は `stdversion` 込み） | printf の書式、`copylocks`、`go 1.27` より新しい標準ライブラリの使用、はどれも見つからなかった |
| `golangci-lint`（`nakedret` / `noctx` / `errorlint` / `forbidigo` / `depguard` / `gochecksumtype` / `exhaustive`） | naked return、ctx の欠落、`==` でのエラー比較、`fmt.Print*` / `panic`、ドメインからの外側 import、sealed interface の型スイッチの漏れ、はどれも見つからなかった |
| `go fix ./...` が差分無し | modernizer が知っている旧 idiom は残っていない |
| `go test -race -shuffle=on` | データ競合とテスト関数間の順序依存は見つからなかった |

「明示的である」「丸めていない」「フォールバックが無い」「interface が使う側にある」「返り値が 2 つ以下」は機械では言えない。下のチェックリストを人が読む。

## チェックリスト（機械で言えないことだけ）

- [ ] 既定値への丸め（「無ければ 0」「不正なら既定へ」）が無い。不正値は `error` を返している
- [ ] フォールバック（失敗時に別の手段で続行）が無い。あるなら利用者の許可を得た記録がある
- [ ] 暗黙の変換・暗黙の既定・`init` による初期化が無い。値の出どころが行で追える
- [ ] 分岐はガード節。`else` の入れ子が無く、本筋が 1 段目にある
- [ ] 返り値は `(T, error)` か `(T, bool)` か 1 つ。3 つ以上は結果 struct になっている
- [ ] `ctx` は第一引数で、struct に持っていない。`context.Background()` / `context.TODO()` が `main` とテスト以外に無い
- [ ] ポインタは「状態を変える協力者」と「nil が意味を持つ引数」だけ。コンストラクタは値を返している（協力者を除く）
- [ ] interface は使う側で定義し、呼ぶメソッドだけを持つ。例外はドメインの永続化ポートと和型だけ
- [ ] `any` は decode 境界だけ。generics は「同じアルゴリズムを複数の型に」「補助型の量産を避ける」のどちらか。ジェネリックメソッドを使っていない
- [ ] 列挙は封じた struct。`switch` の `default` は `error` を返し、丸めも `panic` もしていない
- [ ] `time.Now()` は境界で 1 回。時刻は UTC で保持している
- [ ] 裸の `go` に「誰が待つか」「いつ止まるか」がある
- [ ] `encoding/json/v2` を使い、ドメインの型に json タグが無い
- [ ] package 名に `util` / `common` が無く、getter に `Get` が無く、`Impl` 接尾辞が無い

## 報告

- 対象ファイルと層（1 行ずつ）
- 直したシグネチャ（前 → 後）と、その規則番号（`basics.md §5` のように）
- 消した丸め・フォールバック・`else` の入れ子の箇所と、代わりに返す `error`
- 標準ライブラリへ置き換えた箇所（`go fix` が直した分と手で直した分を分けて）
- 機械検査の結果（上の 5 コマンド）
- 停止条件に当たって利用者に返した論点と、その回答
- 層別の規約へ返した論点（型の構造・ポート・tx・DTO・エラー・ログ・テスト）
