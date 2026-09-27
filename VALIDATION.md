# Validation

受入検査は次で実行します。

```bash
bash scripts/validate.sh
```

依存するコマンドは `bash` / `find` / `jq` / `python3` / `rg` で、無ければ FAIL になります。`go` は任意です（あれば `go 1.27` を `GOTOOLCHAIN=auto` で取得します）。

機械検査は決定論的な述語だけです。文体・整合性・規約の妥当性は script で判定せず、レビュー（エージェントによる読み合わせ）で確かめます。

## 配布契約（root 契約と identity）

兄弟checkout `../harness-tools/tools/validate-plugin-repository.py`（保守toolの唯一の参照元）で、package 境界の契約（公開・インストール対象がpackage 1件であること、Codex / Claude manifest の同一性、manifestが宣言した直接公開skillの実在、symlink不在）を確認します。`../harness-tools/` が無い環境では検査を止めます（省略も fixture による代用もしません）。CI は `.github/workflows/validate.yml` で `harness-tools` を兄弟checkoutし、`harness-tools/ci/validate.sh` で local と同じ command を実行します。

続けて、両 marketplace の identity（名前・version・source）が manifest と一致すること、manifest が `skills/` 配下の9skillを直接宣言すること、各directoryの`SKILL.md`とnameが一致することを確認します。

## 規約の資料と例

全skillについて、`SKILL.md` から `references/*.md` への直接リンクが過不足なく在ること、reference 間のリンク先が在ることを確認します。テストの形の skill については、`references/examples.md` と `tests/examples/` のテストコードの一致と、shell 構文を確認します。

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

`go` があれば `tests/examples/`（`go.mod` の `go` 指示は 1.27。手元の `go` が古くても `GOTOOLCHAIN=auto` なら 1.27 を取得して実行します）で `gofmt -l`、`go vet ./...`、`go test -shuffle=on -count=1 ./...` を実行します。`-shuffle=on` が入れ替えるのはテスト関数の順序だけで、サブテストの順序は変えません。続けて、`write-go-code/references/tooling.md` の `.golangci.yml`（yaml のブロックちょうど1個）を取り出し、module path だけを見本のものへ置き換えて、`tests/examples/` の複製に `go run github.com/golangci/golangci-lint/v2/cmd/golangci-lint@<版>` をかけます。見本が同じ plugin の lint の設定でそのまま通ることを確かめるためで、設定を検査の側へ写しません。`go` が無ければこの4つは「省略」と表示し、失敗にはしません。

## 言えること

これらが通ったとき言えるのは、判定した述語が成り立ったことだけです。規約の文章が曖昧さなく読めるか、例が規約の意図を写しているかは目視で確認します。

## check-bdd-coverage.py（repository 全体の BDD の追跡）

`plugins/go-convention/skills/apply-go-test-convention/scripts/check-bdd-coverage.py` は、資料の一つの BDD を repository 全体でちょうど一つのテストが名乗る、という規則の構造を検査します。

```text
基準資料: bdd-discovery-and-formulation の write-bdd の「BDDの番号は資料の中で一意か」（見出しは `### [BDD-<3桁以上の連番>] <業務結果>`、資料の種類の接頭辞を足さない）、引数で渡した資料の見出し、apply-go-test-convention の SKILL.md の「ケースの識別」の宣言と列挙の形
入力: repository root 配下の全 *_test.go（.git と vendor を除く）と、引数の資料
正規化: 資料の path は repository root からの相対 path にそろえる。`id:` 行は直後が `name:` のときだけケースと見なす
合格述語: 各資料に見出しが1つ以上あり資料内で ID が重複しない。BDD の id か列挙を持つファイルは `// BDD の資料:` をちょうど1つ持ち、それが引数の資料である。その id と列挙の ID は宣言した資料にある。各資料の各 ID は、その資料を宣言したファイル全体で、id: か列挙のどちらかにちょうど1回現れる。列挙は1ファイルに1つで、最後にあり、各行に理由がある。`--stopped` の一覧の各行は `<資料の path> <BDD-ID> <理由と返し先>` で、資料は引数のどれか、ID はその資料にあり、理由が空でなく、一覧の中で重複せず、どのテストにも現れない。一覧の ID は未対応に数えず、`止めた BDD:` の行として出す
失敗時の診断: 資料と ID、現れた場所（ファイル:行）、宣言の数、列挙の形の違反
正例: tests/bdd-coverage
反例: 別の package の同じ BDD、どこにも現れない BDD、資料の宣言の無いファイル、資料に無い ID、資料の種類の接頭辞を足した ID（`BDD-OUT-004`）、id と列挙の両方、理由の無い列挙、最後に無い列挙、理由の無い止めた BDD、資料に無い止めた BDD、引数に無い資料の止めた BDD、止めたのにテストが名乗る BDD
境界例: どのテストも担わない BDD を列挙で持つ（受理）、理由付きで止めた BDD（受理し、止めた BDD として出す）
意味評価として残す範囲: どのテストがその BDD を主に担うべきか、列挙の理由が正しいか、description が資料の gherkin と一致するか
```

## 検証の eval

層の skill が、業務の資料から利用者の原則に沿った実装をテスト駆動で書けるかは、root の `evals/` の下のケースで確かめる。一つのケースは、一つのお題の一つの業務の一つの層を、テストから書かせる課題である。実行は `claude plugin eval` が受け持ち、出来の採点は、作業したエージェントとは別の Claude（採点役）が、条件ごとに判定と根拠の引用を書いて受け持つ。今は、ドメイン層（develop-domain-model）の二つのケース（X のクローンのフォロー、電子チケットの分配）を置いている。横断の skill（write-go-code、handle-errors、apply-go-test-convention など）は単独のケースを持たず、層のケースの条件で効いたかを見る。

永続化、usecase、入口の層のケースは置いていない。eval の実行はサンドボックスの中で動き、外への接続も、localhost の TCP も、Docker のソケットも拒まれるので、実物の PostgreSQL を dockertest で起動する規約のテストを緑にできないからである。

置き場は次のとおりである。`evals/criteria/` には、採点役への指示 `brief.md` と、成果の種類ごとの共通の条件（今は `domain-layer.md`）を置く。`evals/scaffold.sh` は、作業場所に手元だけの git repository（`out/`）を作り、`evals/go-module/` の Go の module の土台、お題の資料、ケースが先に置く内側の層（ケースの `fixture/`）を入れる。サンドボックスの中では module を取れないので、利用者の module cache を読むだけの `GOPROXY` を作業場所の go env に書き、依存とツールを先に build する。skill が名前で指す development-convention と testing-strategy の skill は隔離環境に入らないので、兄弟 checkout から `harness/` へ写し、無ければ exit 2 で止まる。マージ前の branch の skill で回すときは、その branch を兄弟 checkout に置いてから回す。`evals/<お題>/materials/` には、実行の担当に渡した資料（業務知識と、それから作ったドメインモデル）を置く。ドメインモデルは、bdd の評価で85点以上だった業務知識から model-domain の現行版で作ったもので、採点していない。`evals/<お題>/<ケース>/` には、実行の指示 `prompt.md` と `case.yaml`、共通の準備を呼ぶ `scaffold.sh`、`graders/`、ケースに固有の条件 `grading/criteria.md`、較正の資料 `grading/calibration/` を置く。

plugin eval の `graders/` には、読まずに判定できることだけを置く。skill を使ったか、テストを走らせたか、赤から始めたかである。赤から始めたかは、実装のファイル（テストと `builders/` を除く）を書く前に、ビルドの失敗かテストの失敗が作業の記録に現れたかを見る。Bash の here document で書いた実装は見分けられないので、この判定は下限である。採点役は作業の記録を読まないので、条件にはしない。

実行と採点は次のとおりである。`--case` は一つずつ渡す。

```bash
claude plugin eval . --case x-clone-follow-domain-model \
  --runs 1 --ablation none --keep-temp \
  --scaffold --allow-tools Write Edit Bash \
  --max-cost-usd 25 --no-publish
bash /Users/naoya-nakamoriq/Documents/Github/harness-pluginsv2/harness-tools/tools/grade-eval.sh \
  "$(pwd)/evals/x-clone/x-clone-follow-domain-model" /private/tmp/e-XXXXXX
```

条件の重みは、利用者の原則の芯を3、骨組みを2、細部を1とし、採点役を3回回した多数決から100点満点の点数を出す。85点以上は「実用に足る」、70点以上は「手直しで使える」、70点未満は「作り直しが要る」である。条件や採点役への指示を変えたら、`grading/calibration/` の二本（実際の成果と、既知の欠陥を埋めた写し）に採点役をかけ、それぞれの `expected.md` を三つ目の引数に渡して一致を確かめる。較正の資料の報告は `out/trace.jsonl` の result の行に置いてある。実行と採点の結果は `evals/results/` に書かれ、git の管理から外してある。
