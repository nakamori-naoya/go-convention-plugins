# Validation

受入検査は次で実行します。

```bash
bash scripts/validate.sh
```

依存するコマンドは `bash` / `find` / `jq` / `python3` / `rg` で、無ければ FAIL になります。`go` は任意です（あれば `go 1.27` を `GOTOOLCHAIN=auto` で取得します）。

機械検査は決定論的な述語だけです。文体・整合性・規約の妥当性は script で判定せず、レビュー（エージェントによる読み合わせ）で確かめます。

## 配布契約（root 契約と identity）

workspace root の `scripts/validate-plugin-repository.py` で、package 境界の契約（公開・インストール対象が playbook package 1 件であること、manifest の `metadata.harness.playbooks` / `internalPlugins` の宣言、Codex / Claude manifest の同一性、内部 skill の自己完結＝`skills/**/*.md` に兄弟 skill 名と「playbook」「プレイブック」が現れないこと）を確認します。workspace root が無い環境では「省略」と表示します。

続けて、両 marketplace の identity（名前・version・source）が manifest と一致すること、manifest が 14 の入口と 14 の内部 skill を宣言し `skills` が入口だけであること、各入口 `playbooks/go-convention/<name>/` に `SKILL.md` / `playbook.yml` / `scripts/prepare.sh` / `scripts/resolve.sh` が在り、`prepare.sh` が成功し、`resolve.sh` が同名の内部 skill を返し、`playbook.yml` が同名の内部 skill へ 1 工程で振り、`skills/<name>/SKILL.md` が在ることを確認します。入口と内部 skill の directory がそれぞれ 14 であることも確認します。

## 規約の資料と例

全内部 skill について、`SKILL.md` から `references/*.md` への直接リンクが過不足なく在ること、reference 間のリンク先が在ることを確認します。テストの形の skill については、`references/examples.md` と `tests/examples/` のテストコードの一致、`table.md` / `given.md` / `then.md` / `case-identity.md` の Go ブロックが `tests/examples/` の部分文字列であること、shell 構文を確認します。

## check-cases.py

`plugins/go-convention/skills/apply-go-test-convention/scripts/check-cases.py` が判定する述語は、その docstring が正本です。通ったとき言えるのは次の5つだけです。

1. package 行が `{pkg}_test` である
2. `func Test*`（`TestMain` を除く）ごとに、`id:` 行が1つ以上あり、値は空でなく、同じディレクトリの `*_test.go` 全体で重複しない
3. `id:` / `name:` / `description:` は各1行で始まり、この順に隣接する
4. `name:` の値が同じディレクトリの `*_test.go` 全体で重複しない
5. `description:` は raw string で、`Given:` / `When:` / `Then:` を行頭にこの順で各1回持ち、`And:` は行頭または字下げで `Given:` か `Then:`（またはその `And:`）の後にだけ現れ、`NOTE:` で始まる行とそれに続く字下げ行は無視する

`tests/examples/` を受理する正常系（字下げした `And:` と `NOTE:` を含む）に加え、`numseq_test.go` を1点だけ変えた複製（または同じディレクトリに1ファイル足した複製）に対して次を実行します。

| 種別 | 変更 | 期待 |
|---|---|---|
| 負例 | 同じファイル内の `id` 重複 | 拒否（`ディレクトリ内で重複`） |
| 負例 | 別ファイルのテスト関数に同じ `id` を持つケースを足す | 拒否（`ディレクトリ内で重複`） |
| 負例 | `name` 重複 | 拒否（`ディレクトリ内で重複`） |
| 負例 | 空の `id`（`""`） | 拒否（`id が空`） |
| 負例 | `Given` / `When` の逆順 | 拒否（`行頭にこの順で各1回でない`） |
| 負例 | `When:` を行頭でなく TAB で字下げ | 拒否（`行頭にこの順で各1回でない`） |
| 負例 | 内部パッケージ（`package numseq`） | 拒否（`_test でない`） |
| 負例 | 1行に `id` と `name` を並べたケース | 拒否（`複数行で書く`） |
| 負例 | `When:` 直後の字下げした `And:` | 拒否（`の後以外にある`） |
| 正例 | `Then:` の後に行頭の `And:` を足す | 受理（`And:` は行頭でも字下げでもよい） |
| 正例 | `Then:` の後に `NOTE:` 行と、字下げした `When:` / `Reason:` 行を足す | 受理（`NOTE:` に続く字下げ行は見出しに数えない） |
| 正例 | `Test` と同じ `id` / `name` を本文に持つ `Benchmark*` を末尾に足す | 受理（`Benchmark*` を直前の `Test` に併合しない） |
| 正例 | ループ本体に `id: "L-1"` を持つ被験体の構造体リテラルを足す | 受理（ケースと見なさない） |
| 正例 | `name` にエスケープした引用符を入れる | 受理 |
| 正例 | 同じディレクトリに `func TestMain(m *testing.M) { os.Exit(m.Run()) }` だけを持つ `main_test.go` を足す | 受理（`TestMain` を `Test*` として扱わない） |

負例は、拒否されたうえで出力に期待の文言が含まれることまで見ます。資料の BDD ID が `id:` か末尾コメントに現れるかは、この script の述語ではありません。

## Go

`go` があれば `tests/examples/`（`go.mod` の `go` 指示は 1.27。手元の `go` が古くても `GOTOOLCHAIN=auto` なら 1.27 を取得して実行します）で `gofmt -l`、`go vet ./...`、`go test -shuffle=on -count=1 ./...` を実行します。`-shuffle=on` が入れ替えるのはテスト関数の順序だけで、サブテストの順序は変えません。`go` が無ければこの3つは「省略」と表示し、失敗にはしません。

## 言えること

これらが通ったとき言えるのは、判定した述語が成り立ったことだけです。規約の文章が曖昧さなく読めるか、例が規約の意図を写しているかは目視で確認します。
