# ツール

**機械で言えることは機械に言わせ、人は機械で言えないことだけを読む。** フォーマット・import 順・型の網羅・未処理のエラー・禁止 API は、規則として覚えるのではなく、ツールが落とす状態にする。

## 1. `go.mod`

**する:**
- `go 1.27` を明示する。`go mod init` は 1.26 からツールチェーンの 1 つ前の版を書く（Go 1.27 で実行すると `go 1.26.0`）ので、生成後に `go 1.27` へ上げる
- `toolchain` 行は書かない（CI とローカルで同じ版の Go を入れる。版はこの行ではなく環境で揃える）
- 開発ツールは `tool` directive（1.24）で `go.mod` に固定し、`go tool {name}` で呼ぶ。`go install ...@latest` をドキュメントに書かない
- `go mod tidy` を通した状態をコミットする。1.27 からは `go 1.27` 以上のモジュールで `require` ブロックを直接依存と間接依存の 2 つに自動で統合する

```
module example.com/roomflow

go 1.27

tool (
	github.com/golangci/golangci-lint/v2/cmd/golangci-lint
	github.com/sqlc-dev/sqlc/cmd/sqlc
	golang.org/x/tools/cmd/goimports
	golang.org/x/vuln/cmd/govulncheck
)
```

```bash
go get -tool github.com/golangci/golangci-lint/v2/cmd/golangci-lint@latest
go tool golangci-lint run ./...
```

**しない:** `replace` を本番のモジュールに残す。`go 1.27` より低い版のままにして 1.27 の機能（ジェネリックメソッド・`encoding/json/v2`）を使う（コンパイルが落ちるか、`stdversion` が落とす）。

理由: `tool` directive はツールの版を `go.sum` で固定し、CI とローカルで同じ版が走る。`go 1.27` を明示しないと、言語機能とライブラリ API の使用可否が読み手に分からない。

## 2. フォーマット

**する:** `gofmt` と `goimports -local example.com/roomflow`。import は標準 → サードパーティ → 自モジュールの 3 群に空行で分け、`goimports` に並べさせる。コミット前に `gofmt -l .` が空であることを確かめる。
**しない:** `gofmt` の出力に手を入れる。import の別名（alias）を衝突以外で付ける（`sqlcgen` のように package 名そのものが十分に短い名前なら別名は要らない）。

```go
import (
	"context"
	"errors"
	"fmt"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	"example.com/roomflow/reservation"
	"example.com/roomflow/rdb/sqlcgen"
)
```

理由: フォーマットの議論を無くす。import の 3 群は「この package が何に依存しているか」を上から順に読ませる。

## 3. `go vet`

**する:** `go vet ./...` を CI で走らせる。`go test` は vet の一部（`atomic` / `bool` / `buildtags` / `directive` / `errorsas` / `ifaceassert` / `nilfunc` / `printf` / `stringintconv` / `tests`）を自動で走らせ、**1.27 からは `stdversion` も既定で走る**。`stdversion` は `go.mod` の `go` 指示より新しい標準ライブラリの記号を使っていると報告する。
**しない:** vet の警告を `//nolint` や `_ =` で黙らせる。`go test -vet=off`。

理由: `go test` が vet を走らせるので、テストが通れば vet の主要な検査は通っている。`stdversion` は「`go 1.26` のまま 1.27 の API を使った」を、古い Go でビルドする前に落とす。

## 4. golangci-lint

**する:** golangci-lint v2 を `go tool` で固定し、次の linter を有効にする。設定は `.golangci.yml` をリポジトリ直下に 1 つ。

| linter | 落とすもの |
|---|---|
| `govet` | vet 全部。`copylocks`（`sync.Mutex` を持つ値のコピー）を含めて有効 |
| `staticcheck` | 非推奨 API、到達不能コード、誤った比較、`time` の誤用 |
| `errcheck` | 捨てられた `error`（`defer f.Close()` を含めるかは設定で決める） |
| `unused` | 使われていない関数・型・フィールド |
| `exhaustive` | 定数列挙の `switch` の漏れ（封じた struct の列挙は `default` が `error` を返すので対象外。外部ライブラリの `iota` 列挙で効く） |
| `gochecksumtype` | `//sumtype:decl` を付けた sealed interface の型スイッチの漏れ |
| `forbidigo` | 禁止 API。`fmt.Print*`、`log.Print*` / `log.Fatal*`、`panic`。`_test.go` は対象から外す（`log.Fatal*` を許すのは `TestMain` だけで、他のテストコードは `t.Fatal` / `require` を使う） |
| `depguard` | import 禁止。全 package で `math/rand`（v1）と `io/ioutil`。ドメイン package は `log/slog` / `encoding/json` / `pgx` / `connect` も |
| `nakedret` | naked return |
| `noctx` | `context.Context` を渡していない HTTP / DB 呼び出し |
| `errorlint` | `==` でのエラー比較、`%v` での包み込み（`%w` を使う） |

```yaml
# .golangci.yml
version: "2"
linters:
  default: none
  enable:
    - govet
    - staticcheck
    - errcheck
    - unused
    - exhaustive
    - gochecksumtype
    - forbidigo
    - depguard
    - nakedret
    - noctx
    - errorlint
  settings:
    govet:
      enable:
        - copylocks
    nakedret:
      max-func-lines: 0
    forbidigo:
      analyze-types: true
      forbid:
        - pattern: ^fmt\.Print.*$
          msg: ログはログの規約に従い slog で出す
        - pattern: ^log\.(Print|Fatal|Panic).*$
          msg: ログはログの規約に従い slog で出す
        - pattern: ^panic$
          msg: panic を書かない。error を返す
    depguard:
      rules:
        all:
          files:
            - "$all"
          deny:
            - pkg: math/rand$
              desc: math/rand/v2 を使う
            - pkg: io/ioutil
              desc: os と io を使う
        domain:
          files:
            - "**/reservation/**"
          deny:
            - pkg: log/slog
              desc: ドメイン package はログを出さない
            - pkg: encoding/json
              desc: ドメインの型に JSON を持ち込まない
            - pkg: github.com/jackc/pgx
              desc: ドメインは永続化を知らない
            - pkg: connectrpc.com/connect
              desc: ドメインは入口プロトコルを知らない
  exclusions:
    rules:
      - path: _test\.go$
        linters:
          - forbidigo
formatters:
  enable:
    - gofmt
    - goimports
  settings:
    goimports:
      local-prefixes:
        - example.com/roomflow
```

**しない:** `//nolint` を理由無しで付ける（付けるなら `//nolint:errcheck // 閉じ損ねても結果に影響しない` のように linter 名と理由を書く）。`enable-all` で全部入れて「うるさい」と感じた linter を場当たりで外す。

理由: 基本の規約（naked return 禁止・panic 禁止・ctx 必須）と型の規約（sealed interface の網羅）は、機械が落とせるものは機械に落とさせる。`depguard` は層の依存の向き（ドメインが外側を知らない）をコンパイルの次に早い段階で守る。

## 5. `go fix`（1.26 で刷新）

**する:** `go fix ./...` を定期的に（依存の更新と同じタイミングで）走らせ、差分をレビューしてコミットする。1.26 で `go fix` は modernizer の置き場になり、`min` / `max`、`for range n`、`slices` / `maps`、`strings.Cut`、`sync.WaitGroup.Go`（1.27 で `waitgroupgo` に改名）、`atomictypes` / `embedlit` / `slicesbackward` / `unsafefuncs`（1.27 で追加）などを自動で書き換える。自前の API 移行は `//go:fix inline` を付けて `go fix` に呼び出し側を書き換えさせる。
**しない:** modernizer の差分を手で真似て書く（同じ結果なら機械に任せる）。`go fix` の差分を読まずにコミットする（`fmtappendf` は 1.27 で外されたように、modernizer の判断は版で変わる）。

理由: 「新しい書き方に揃える」を人の記憶に頼らない。差分を読むのは、書き換えが意味を変えていないことを人が言うためである。

## 6. `go test`

**する:** 既定のフラグは `-race -shuffle=on -count=1`。CI では `-json` で結果を集め（1.27 から `"OutputType"` フィールドで出力の種類が分かる）、成果物が要るテストは `-artifacts` で `t.ArtifactDir()` の中身を残す。
**しない:** `-race` を「遅いから」で外す。`-count=1` を外してキャッシュされた結果を見る。

```bash
go test -race -shuffle=on -count=1 ./...
go test -race -shuffle=on -count=1 -json -artifacts -outputdir=./test-results ./...
```

テストの形・何をテストするかはテストの規約が決める。

理由: `-race` はデータ競合を実行で検出する唯一の手段で、`-shuffle=on` はテスト関数間の順序依存を落とす。`-count=1` はテストの変更なしにコードだけ変えたときの取りこぼしを消す。

## 7. sqlc と生成コード

**する:** `sqlc.yaml` は `sql_package: "pgx/v5"`。生成先 package は `sqlcgen`。生成は `//go:generate go tool sqlc generate` をリポジトリ 1 か所に置き、`go generate ./...` で走らせる。生成コードはコミットし、CI で再生成して差分が無いことを確かめる。
**しない:** 生成コードを手で直す。生成コードに lint を掛ける（`.golangci.yml` の `exclusions` で `sqlcgen` と `gen/` を外す）。

理由: 生成物をコミットすれば、ビルドに生成ツールが要らず、差分レビューで SQL の変更がコードの変更として見える。

## 8. 脆弱性

**する:** `go tool govulncheck ./...` を CI で走らせる。到達可能な脆弱性だけが報告される。
**しない:** `go.sum` の依存を「使っていないから」で放置する（`go mod tidy` で消す）。

## 9. コミット前の順

```bash
gofmt -l .                                  # 空であること
go tool goimports -local example.com/roomflow -l .   # 空であること
go vet ./...
go tool golangci-lint run ./...
go test -race -shuffle=on -count=1 ./...
```

この 5 つが通った状態だけをコミットする。通らない状態を「後で直す」で残さない。
