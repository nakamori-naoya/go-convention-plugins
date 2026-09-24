# ツール

機械で言えることは機械に言わせ、人は機械で言えないことだけを読む。フォーマット、import の順、禁止する API、import の向き、和の型（封じた interface で表す「A か B か」）の分岐の網羅は、規則として覚えるのではなく、ツールが落とす状態にする。

例の module path は `example.com/library` である。

# `go.mod`

`go 1.27` を明示する。`go mod init` はツールチェーンの一つ前の版を書くので、生成した後に `go 1.27` へ上げる。`toolchain` の行は書かず、CI とローカルで同じ版の Go を入れる。

開発ツールは `tool` directive で `go.mod` に固定し、`go tool <名前>` で呼ぶ。ツールの版が `go.sum` で固定され、CI とローカルで同じ版が走る。`go install ...@latest` を手順に書かない。

```
module example.com/library

go 1.27

tool (
	github.com/golangci/golangci-lint/v2/cmd/golangci-lint
	github.com/sqlc-dev/sqlc/cmd/sqlc
	go.uber.org/mock/mockgen
	golang.org/x/tools/cmd/goimports
	golang.org/x/vuln/cmd/govulncheck
)
```

`go mod tidy` を通した状態をコミットする。本番の module に `replace` を残さない。

# フォーマット

`gofmt` と `goimports -local example.com/library` を使い、出力に手を入れない。import は、標準、サードパーティ、自分の module の三群に空行で分ける。import の別名は、名前の衝突を解くときだけ付ける。

# `go vet`

`go vet ./...` を CI で走らせる。1.27 からは `stdversion` も既定で走り、`go.mod` の `go` の版より新しい標準ライブラリの記号を使っていれば報告する。vet の警告を `//nolint` や `_ =` で黙らせない。

# golangci-lint

golangci-lint v2 を `go tool` で固定し、設定はリポジトリの直下に `.golangci.yml` を一つ置く。有効にする linter と、それぞれが落とすものは次のとおりである。

| linter | 落とすもの |
|---|---|
| `govet` | vet の全部。`copylocks` を含める |
| `staticcheck` | 非推奨の API、到達しないコード、誤った比較 |
| `errcheck` | 捨てられた error |
| `unused` | 使われていない関数、型、フィールド |
| `exhaustive` | 外部ライブラリの定数列挙の `switch` の漏れ |
| `gochecksumtype` | `//sumtype:decl` を付けた和の型スイッチの漏れ |
| `forbidigo` | `fmt.Print*`、`log.Print*` / `log.Fatal*`、`panic`、`slog.Default`、`slog.SetDefault` |
| `depguard` | 禁じた import（下の設定） |
| `nakedret` | naked return |
| `noctx` | ctx を渡していない HTTP と DB の呼び出し |
| `errorlint` | `==` でのエラーの比較 |

`depguard` は、依存の向きをコンパイルの次に早い段階で守る。全 package で、`math/rand`（v1）、`io/ioutil`、標準の `errors` を禁じる。標準の `errors` を import してよいのは、エラーの分類を持つ package だけである（handle-errors が定める）。ドメインの package では、さらに `log/slog`、`encoding/json`、pgx、connect を禁じる。ドメインは、記録、JSON、永続化、要求を受けるときのプロトコル（Connect）を知らないからである。

```yaml
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
          msg: 記録は注入された logger で行う
        - pattern: ^log\.(Print|Fatal|Panic).*$
          msg: 記録は注入された logger で行う
        - pattern: ^slog\.(Default|SetDefault)$
          msg: logger は組み立てで作って注入する
        - pattern: ^panic$
          msg: panic を書かない。error を返す
    depguard:
      rules:
        all:
          files:
            - "$all"
            - "!**/internal/crosscutting/errors/**"
          deny:
            - pkg: math/rand$
              desc: math/rand/v2 を使う
            - pkg: io/ioutil
              desc: os と io を使う
            - pkg: errors$
              desc: エラーの分類を持つ package を使う
        domain:
          files:
            - "**/domain/**"
          deny:
            - pkg: log/slog
              desc: ドメインは記録しない
            - pkg: encoding/json
              desc: ドメインの型に JSON を持ち込まない
            - pkg: github.com/jackc/pgx
              desc: ドメインは永続化を知らない
            - pkg: connectrpc.com/connect
              desc: ドメインは入口のプロトコルを知らない
  exclusions:
    paths:
      - sqlcgen
      - gen
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
        - example.com/library
```

`//nolint` を付けるなら、linter の名前と理由を書く（`//nolint:errcheck // 閉じ損ねても結果に影響しない`）。`enable-all` で全部入れてから、うるさい linter を場当たりで外すことはしない。

エラーの分類をキーにする表の網羅は、linter ではなく、分類の一覧を回すテストで確かめる（handle-errors と write-logs が定める）。

# `go fix`

`go fix ./...` を依存の更新と同じ機会に走らせ、差分を読んでコミットする。1.26 から `go fix` は modernizer の置き場で、`min` / `max`、`for range n`、`slices` / `maps`、`strings.Cut`、`sync.WaitGroup.Go` などへ自動で書き換える。modernizer の判断は版で変わるので、差分を読まずにコミットしない。

# `go test`

既定のフラグは `-race -shuffle=on -count=1` である。`-race` はデータ競合を実行で見つける唯一の手段で、`-shuffle=on` はテスト関数の間の順序依存を落とし、`-count=1` はキャッシュされた結果を見せない。build tag でテストを分けず、`go test ./...` で全部が走るようにする。テストの形と何をテストするかは、apply-go-test-convention が決める。

# 生成コード

sqlc の生成先の package は `sqlcgen`、mock の生成先は所有する package の直下の `mock` である。生成は `go:generate` で行い、生成コードはコミットし、CI で生成し直して差分が無いことを確かめる。生成コードを手で直さず、lint の対象から外す。

# 脆弱性

`go tool govulncheck ./...` を CI で走らせる。到達する脆弱性だけが報告される。

# コミットの前

次の五つが通った状態だけをコミットする。

```bash
gofmt -l .
go tool goimports -local example.com/library -l .
go vet ./...
go tool golangci-lint run ./...
go test -race -shuffle=on -count=1 ./...
```

最初の二つは、出力が空であることを確かめる。
