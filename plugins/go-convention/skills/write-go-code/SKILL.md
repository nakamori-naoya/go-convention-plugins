---
name: write-go-code
description: Go 1.27 のコードを、層を問わない言語レベルの規約（返り値は最大 2 つ、naked return 禁止、ctx 第一引数、値渡し既定、使う側で定義する小さな interface、封じた struct の列挙、init 禁止、明示・丸めない・フォールバックしない・ガード節、標準ライブラリの 1.27 idiom、gofmt / go vet / golangci-lint / go fix）で書く・直す。「この Go コードを規約に合わせて」「Go の書き方を確認したい」「この関数のシグネチャを直して」「1.27 の書き方にして」と言われたとき、また層別の実装規約（ドメイン・永続化・usecase・handler）がこの規約を土台に指定したときに使う。ドメインモデルの設計、リポジトリと query service の形、usecase と handler の形、エラーの定義と翻訳、ログの置き場、テストの形と厚みは対象外としてそれぞれの規約へ返す。
---

# write-go-code

[工程順序の定義](playbook.yml)を最初に読み、同じagentが\`steps\`を宣言順に実行する。YAMLは工程順序を決め、各工程の判断内容と根拠はこの本文と参照資料を実読して評価する。失敗時は成功扱いせず停止して、完了工程、根拠、未決を残し、再開時は最初の未完了工程から続ける。

これは、**Go 1.27 のコードを、どの層でも同じ言語レベルの形で書くための規約**である。関数の形（返り値・引数・レシーバ）、型と interface の切り方、命名、標準ライブラリの選び方、ツールの構成を一つに揃える。

これは、**何を作るか（設計）を決めるものではない。** 値オブジェクト・集約・イベントの構造と操作はドメインモデルの規約が、永続化ポートの実装と行の変換は永続化の規約が、トランザクション境界と協調は usecase の規約が、入口と DTO 変換は handler の規約が、sentinel の定義・文言・包み方・翻訳はエラーの規約が、どの層がログを出すかはログの規約が、テストの形と何をテストするかはテストの規約が決める。この規約はそれらが共通に載る言語の土台で、言語に依存しない設計原則（YAGNI・層の定義・ディレクトリ構成）は上位の開発規約に置く。

前提: Go 1.27（`go.mod` の `go 1.27`）。標準ライブラリを優先し、外部依存は `golang.org/x/sync/errgroup`、`golang.org/x/tools`（goimports）、golangci-lint v2、および層別の規約が指定するもの（`github.com/jackc/pgx/v5`、`github.com/sqlc-dev/sqlc`、`connectrpc.com/connect` v1.21.0（v2 alpha は採らない）、`google.golang.org/protobuf`、`github.com/stretchr/testify`、`github.com/ory/dockertest/v4`）だけ。例の題材は貸会議室予約（module `example.com/roomflow`。ディレクトリ構成は上位の開発規約が決めるので、例は import path を短くするため package を平らに置いている）。

## 入力

- 書く・直す対象のpackageと型・関数、その層。既存のcodeとテストがあればそのpath。
- `references`: 追加で従う資料の絶対path配列。任意。手順の最初に読み、以降の判断でこの規約と併せて従う。

プロジェクト固有の規約（置き場、命名、追加で従う資料）は、対象repositoryのAGENTS.md / CLAUDE.mdと`references`で渡される。この入口は既定値を持たず、指示文へ展開もしない。

## 規約

| # | 柱 | 一言で | 基準資料 |
|---|---|---|---|
| 1 | 基本 | 明示を選ぶ・丸めない・フォールバックしない・ガード節。返り値は最大 2 つ、naked return 禁止、ctx 第一引数、引数が多いなら struct、値渡し既定、レシーバ統一、フィールド名付きリテラル、`init` 禁止、`main` は `run(ctx) error`、いまの呼び出しが要らないものを書かない | [basics.md](references/basics.md) |
| 2 | 命名 | package は短い小文字で `util` / `common` 禁止、getter に `Get` 無し、`Equal`、頭字語は `ID` / `URL`、レシーバ 1〜2 文字、`New` / `Restore`、`Err*`、`{元}To{先}` | [naming.md](references/naming.md) |
| 3 | 型と interface | interface は使う側で小さく（例外: 永続化ポートと和型はドメインが定義）、`any` は decode 境界だけ、generics は 2 条件、ジェネリックメソッドは既定で使わない、列挙は封じた struct、`default` は error、sealed interface、ゼロ値 | [types-and-interfaces.md](references/types-and-interfaces.md) |
| 4 | 標準ライブラリ | `min` / `max` / `clear`、`range n`、`slices` / `maps` / `iter`、`strings.Lines` / `SplitSeq` / `CutLast`、UTC、`math/rand/v2`、`os.Root`、`WaitGroup.Go` / `errgroup`、`synctest`、`testing` の 1.24〜1.26 API、`encoding/json/v2` ＋ `jsontext`、`errors.AsType`、`slog.NewMultiHandler` | [stdlib-1.27.md](references/stdlib-1.27.md) |
| 5 | ツール | `go 1.27`、`tool` directive、gofmt / goimports、`go vet`（1.27 は `stdversion` 既定）、golangci-lint v2 の linter 一覧と設定、`go fix` modernizer、`-race -shuffle=on -count=1` | [tooling.md](references/tooling.md) |

**書き始める前に 5 本を一度読む。** 各規則は「する／しない」と理由で書いてあり、理由が当てはまらない場面は無い。

## 手順

1. **対象と層を決める。** `references` があれば先に読む。直す・書くファイルと、それがどの層（ドメイン・永続化・query service・usecase・handler・main）かを言う。層固有の形（型の構造・ポート・tx・DTO）は層別の規約に従い、この規約は言語レベルだけを見る。完了条件: 対象ファイルの一覧と、各ファイルの層が 1 行で言える
2. **`go.mod` とツールを確かめる。** `go 1.27`、`tool` directive、`.golangci.yml` が [tooling.md](references/tooling.md) の形になっている。無ければ先に整える。完了条件: `go tool golangci-lint run ./...` が実行できる
3. **関数の形を揃える。** 返り値の数、`ctx` の位置、引数の数、値／ポインタ、レシーバ、naked return、ガード節を [basics.md](references/basics.md) に合わせる。既定値への丸め・フォールバックが見つかったら消して `error` を返す形にする（フォールバックが要ると判断した場合は停止条件）。完了条件: 各関数のシグネチャが §基本 の表のどれかに一致し、`else` の入れ子と naked return が無い
4. **型と interface を揃える。** interface の定義場所（使う側。例外はドメインのポートと和型）、`any` と generics の使用箇所、列挙の形、`switch` の `default` を [types-and-interfaces.md](references/types-and-interfaces.md) に合わせる。完了条件: 各 interface について「誰が使うから誰が定義した」と「依存方向か差し替えか」が言え、`default` が全部 `error` を返す
5. **名前を揃える。** package 名、型名、getter、頭字語、レシーバ名、sentinel、変換関数を [naming.md](references/naming.md) に合わせる。完了条件: `go vet` と `staticcheck` の命名の警告が無く、`Get` 接頭辞・`Impl` 接尾辞・`util` package が無い
6. **標準ライブラリに置き換える。** 自前の補助関数（同じ module に既にある関数の再実装を含む）・古い API・`x := x`・`sort.Slice`・`math/rand` v1・`encoding/json` v1 を [stdlib-1.27.md](references/stdlib-1.27.md) の表で置き換える。`go fix ./...` を先に走らせ、残りを手で直す。完了条件: `go fix ./...` が差分を出さず、表の「書かない」列の綴りがコードに無く、同じ入出力の関数が module 内に二つ無い
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

止まるのは、資料または規約の契約に反する要求、正式な定義に無い決定が要る、利用者の許可が要る、toolが失敗した、のどれかに当たるときで、それ以外の判断の揺れでは止まらない。欠けているのが業務事実（操作・状態・拒む理由・資料が未決と明示した値）なら止まり、命名・分割・定義場所・並び・テストの置き場のような設計判断の揺れなら仮説を明示して進む。

- **フォールバックが要ると判断した**（一次手段の失敗時に別の手段で続行しないと要件を満たせない）→ 書かずに止まる。一次手段、失敗の条件、代替手段、続行したときに隠れる失敗を利用者に示し、許可を得てから書く。許可が無ければ `error` を返す形にする
- 既定値への丸めが「仕様」だと主張されている（「無ければ 0 として扱う」が資料に書いてある）→ 丸めをコードに書かず止まる。資料のその行を示し、`error` を返す形にできないか利用者に確かめる
- 前提の列挙と層別の規約の指定に無い外部依存が要ると判断した → `go.mod` へ足さずに止まる。標準ライブラリと既存依存で書けない理由、候補と版、依存が増えて背負うもの（更新・脆弱性・ビルド）を利用者に示し、許可を得てから足す
- `go.mod` が `go 1.27` 未満で上げられない → 書かずに止まる。この規約は 1.27 だけを対象にし、旧版向けに機能を避けて書く経路を持たない
- 対象が生成コード（`sqlcgen` / `gen/`）→ 直さない。生成元（SQL / proto）を直すことを提案して止まる

止まるときは、書いた範囲と書かなかった範囲を分け、返す先（資料、実装の規約、利用者）と必要な決定を報告に示す。

判断の揺れでは、その時点の根拠から最も筋の良い形を仮説として採り、仮説であることと採らなかった形を報告に明示して進む。

- 返り値を3つ以上にしないとシグネチャが決まらない: 結果structを仮に置き、名前と中身は層別の規約（ドメインの遷移結果型・usecaseの結果）で確定する未決として報告に示す。
- interfaceの定義場所が「使う側」でも「ドメインのポート／和型」でもない（例: 2つのusecaseが同じ読み取りinterfaceを要る）: usecase側の読み取りポートの置き場に置く仮説を採り、usecaseの規約で確定する未決として報告に示す。

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
- [ ] interface は使う側で定義し、呼ぶメソッドだけを持つ。例外はドメインの永続化ポートと和型だけ。各 interface に「依存の向きを内向きに保つため」か「テストで差し替えるため（採番・時計など環境で差し替えるもの）」のどちらかの理由が言え、同じ package の具象型や内向きに依存して済む相手を包んだだけの interface が無い
- [ ] `any` は decode 境界だけ。generics は「同じアルゴリズムを複数の型に」「補助型の量産を避ける」のどちらか。ジェネリックメソッドを使っていない
- [ ] 列挙は封じた struct。`switch` の `default` は `error` を返し、丸めも `panic` もしていない
- [ ] `time.Now()` は境界で 1 回。時刻は UTC で保持している
- [ ] 裸の `go` に「誰が待つか」「いつ止まるか」がある
- [ ] `encoding/json/v2` を使い、ドメインの型に json タグが無い
- [ ] package 名に `util` / `common` が無く、getter に `Get` が無く、`Impl` 接尾辞が無い
- [ ] 標準ライブラリ（`slices` / `maps` / `strings` / `cmp` / `time`）と、同じ module に既にある関数で書ける処理を、自前の関数にしていない
- [ ] 環境で変わる値（接続先・ポート・鍵・ログの出力先）だけが環境変数で、業務の数・規則・固定の名前は定数になっている
- [ ] 使われない引数・フィールド、本文が無いか `TODO` だけの関数、いま呼ばれない分岐・オプションが無い
- [ ] この変更で `go.mod` に外部依存を足していない。足したなら停止条件で許可を得た記録がある

## 報告

- 対象ファイルと層（1 行ずつ）
- 直したシグネチャ（前 → 後）と、その規則番号（`basics.md §5` のように）
- 消した丸め・フォールバック・`else` の入れ子の箇所と、代わりに返す `error`
- 標準ライブラリへ置き換えた箇所（`go fix` が直した分と手で直した分を分けて）
- 機械検査の結果（上の 5 コマンド）
- 停止条件に当たって利用者に返した論点と、その回答
- 層別の規約へ返した論点（型の構造・ポート・tx・DTO・エラー・ログ・テスト）
