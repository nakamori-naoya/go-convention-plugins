# ツール

機械で言えることは機械に言わせ、人は機械で言えないことだけを読む。この資料は、新しい module でツールを整えるときと、設定を直すときに読む。例の module path は `example.com/library` である。

## `go.mod`

`go 1.27` を明示し、`toolchain` の行は書かない。開発ツールは `tool` directive で固定し、`go tool <名前>` で呼ぶ。`go install ...@latest` を手順に書かない。本番の module に `replace` を残さない。

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

## `.golangci.yml`

リポジトリの直下に一つ置く。`depguard` は依存の向きをコンパイルの次に早く守る。標準の `errors` を import してよいのはエラーの分類を持つ package だけで、ドメインは記録、JSON、永続化、入口のプロトコルを知らない。`//nolint` を付けるなら、linter の名前と理由を書く。`enable-all` から場当たりで外すことはしない。

```yaml
version: "2"
linters:
  default: none
  enable: [govet, staticcheck, errcheck, unused, exhaustive, gochecksumtype, forbidigo, depguard, nakedret, noctx, errorlint]
  settings:
    govet:
      enable: [copylocks]
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
          files: ["$all", "!**/internal/crosscutting/errors/**"]
          deny:
            - {pkg: math/rand$, desc: math/rand/v2 を使う}
            - {pkg: io/ioutil, desc: os と io を使う}
            - {pkg: errors$, desc: エラーの分類を持つ package を使う}
        domain:
          files: ["**/domain/**"]
          deny:
            - {pkg: log/slog, desc: ドメインは記録しない}
            - {pkg: encoding/json, desc: ドメインの型に JSON を持ち込まない}
            - {pkg: github.com/jackc/pgx, desc: ドメインは永続化を知らない}
            - {pkg: connectrpc.com/connect, desc: ドメインは入口のプロトコルを知らない}
  exclusions:
    paths: [sqlcgen, gen]
    rules:
      - {path: _test\.go$, linters: [forbidigo]}
formatters:
  enable: [gofmt, goimports]
  settings:
    goimports:
      local-prefixes: [example.com/library]
```

## 生成コードと CI

sqlc の生成先は `sqlcgen`、mock の生成先は所有する package の直下の `mock` である。生成は `go:generate` で行ってコミットし、CI で生成し直して差分が無いことを確かめる。生成コードを手で直さない。CI では、コミットの前の五つの検査に加えて `go tool govulncheck ./...` を走らせる。テストを build tag で分けず、`go test ./...` で全部が走るようにする。
