# Validation

受入検査は次で実行します。

```bash
bash scripts/validate.sh
```

依存するコマンドは `bash` / `find` / `jq` / `python3` / `rg` で、無ければ FAIL になります。`go` は任意です（あれば `go 1.27` を `GOTOOLCHAIN=auto` で取得します）。

機械検査は決定論的な述語だけです。文体・整合性・規約の妥当性は script で判定せず、レビュー（エージェントによる読み合わせ）で確かめます。

## 配布契約（root 契約と identity）

兄弟checkout `../harness-tools/tools/validate-plugin-repository.py`（保守toolの唯一の参照元）で、package 境界の契約（公開・インストール対象がpackage 1件であること、Codex / Claude manifest の同一性、manifestが宣言した直接公開skillの実在、symlink不在）を確認します。`../harness-tools/` が無い環境では検査を止めます（省略も fixture による代用もしません）。CI は `.github/workflows/validate.yml` で `harness-tools` を兄弟checkoutし、`harness-tools/ci/validate.sh` で local と同じ command を実行します。

続けて、両 marketplace の identity（名前・version・source）が manifest と一致すること、manifest が `skills/` 配下の15skillを直接宣言すること、各directoryの`SKILL.md`とnameが一致することを確認します。各skill直下の`playbook.yml` v2についてidentity、宣言順、`agent_work: invoking_agent`、実値を宣言した場合のneeds/provides接続も正例・負例で確認します。存在確認だけのprepare、外側の単一routing、入口別manifestは検査対象にしません。

## develop-go-unit（TDD の 1 単位）の工程順

```text
基準資料: manifest の skills（同 package の公開入口の集合）と、develop-go-unit の隣接 playbook.yml
入力: plugins/go-convention/.claude-plugin/plugin.json、skills/develop-go-unit/playbook.yml
正規化: playbook.yml は yq v4 で JSON 化し、steps を宣言順の list として読む
合格述語: develop-go-unit が manifest にあり、`skill: test-*` の工程が全部 `id: run-red`（agent_work）より前、`skill: implement-*` の工程が全部 run-red と `id: run-green`（agent_work）の間、`skill: write-go-code` が run-green より後にある。test-* と implement-* の工程はどれも `when` を持ち、両者の `when` の集合が一致する。`skill:` の値はすべて manifest の公開入口で、`apply-go-test-convention` を呼ばない
失敗時の診断: 欠けた工程、順序違反、層の不一致、公開入口でない skill 名
正例: 現行の develop-go-unit
反例: 実装工程がテスト工程より前、run-red の欠落、実装の層が一つ欠ける、apply-go-test-convention を合成入口から呼ぶ
境界例: when の値が層の名前として正しいかは判定しない（両者の集合の一致だけを見る）
意味評価として残す範囲: 赤の理由の分類が正しいか、実装中にテストを変えていないか、整える前後で振る舞いが同じか、層の対応が正しいか
```

## 規約の資料と例

全skillについて、`SKILL.md` から `references/*.md` への直接リンクが過不足なく在ること、reference 間のリンク先が在ることを確認します。テストの形の skill については、`references/examples.md` と `tests/examples/` のテストコードの一致、`table.md` / `given.md` / `then.md` / `case-identity.md` の Go ブロックが `tests/examples/` の部分文字列であること、shell 構文を確認します。

## check-cases.py

`plugins/go-convention/skills/apply-go-test-convention/scripts/check-cases.py` が判定する述語は、その docstring が契約定義です。通ったとき言えるのは次の5つだけです。

1. package 行が `{pkg}_test` である
2. `func Test*`（`TestMain` を除く）ごとに、`id:` 行が1つ以上あり、値は空でなく、同じディレクトリの `*_test.go` 全体で重複しない
3. `id:` / `name:` / `description:` は各1行で始まり、この順に隣接する
4. `name:` の値が同じディレクトリの `*_test.go` 全体で重複しない
5. `description:` は raw string で、`Given:` / `When:` / `Then:` を行頭にこの順で各1回持ち、`And:` は行頭または字下げで `Given:` か `Then:`（またはその `And:`）の後にだけ現れ、`NOTE:` で始まる行とそれに続く字下げ行は無視する

`tests/examples/` を受理する正常系（字下げした `And:` と `NOTE:` を含む）に加え、`lending_test.go` を1点だけ変えた複製（または同じディレクトリに1ファイル足した複製）に対して次を実行します。

| 種別 | 変更 | 期待 |
|---|---|---|
| 負例 | 同じファイル内の `id` 重複 | 拒否（`ディレクトリ内で重複`） |
| 負例 | 別ファイルのテスト関数に同じ `id` を持つケースを足す | 拒否（`ディレクトリ内で重複`） |
| 負例 | `name` 重複 | 拒否（`ディレクトリ内で重複`） |
| 負例 | 空の `id`（`""`） | 拒否（`id が空`） |
| 負例 | `Given` / `When` の逆順 | 拒否（`行頭にこの順で各1回でない`） |
| 負例 | `When:` を行頭でなく TAB で字下げ | 拒否（`行頭にこの順で各1回でない`） |
| 負例 | 内部パッケージ（`package lending`） | 拒否（`_test でない`） |
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

## check-bdd-coverage.py（repository 全体の BDD の追跡）

`plugins/go-convention/skills/apply-go-test-convention/scripts/check-bdd-coverage.py` は、資料の一つの BDD を repository 全体でちょうど一つのテストが名乗る、という規則の構造を検査します。

```text
基準資料: bdd-discovery-and-formulation の write-bdd の「BDDの番号は資料の中で一意か」（見出しは `### [BDD-<3桁以上の連番>] <業務結果>`、資料の種類の接頭辞を足さない）、引数で渡した資料の見出し、apply-go-test-convention の references/case-identity.md の宣言と列挙の形
入力: repository root 配下の全 *_test.go（.git と vendor を除く）と、引数の資料
正規化: 資料の path は repository root からの相対 path にそろえる。`id:` 行は直後が `name:` のときだけケースと見なす
合格述語: 各資料に見出しが1つ以上あり資料内で ID が重複しない。BDD の id か列挙を持つファイルは `// BDD の資料:` をちょうど1つ持ち、それが引数の資料である。その id と列挙の ID は宣言した資料にある。各資料の各 ID は、その資料を宣言したファイル全体で、id: か列挙のどちらかにちょうど1回現れる。列挙は1ファイルに1つで、最後にあり、各行に理由がある
失敗時の診断: 資料と ID、現れた場所（ファイル:行）、宣言の数、列挙の形の違反
正例: tests/bdd-coverage
反例: 別の package の同じ BDD、どこにも現れない BDD、資料の宣言の無いファイル、資料に無い ID、資料の種類の接頭辞を足した ID（`BDD-OUT-004`）、id と列挙の両方、理由の無い列挙、最後に無い列挙
境界例: どのテストも担わない BDD を列挙で持つ（受理）
意味評価として残す範囲: どのテストがその BDD を主に担うべきか、列挙の理由が正しいか、description が資料の gherkin と一致するか
```
