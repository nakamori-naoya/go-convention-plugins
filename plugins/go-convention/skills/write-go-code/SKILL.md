---
name: write-go-code
description: Go 1.27 のコードを、層を問わない言語の規約（業務の概念を型で運ぶ、丸めずフォールバックしない、関数の形、interface の置き場、名前とコメントの Go の形、package の木と import の向き、ツール）で書く・直す。「この Go コードを規約に合わせて」「このシグネチャを直して」「この責務をどの package に置くか」と言われたとき、また層の skill が土台にするときに使う。
---

# write-go-code

守るものは二つある。**失敗を隠さず、原因の行を読み手の近くに置くこと**と、**型が業務の意味を運ぶこと**である。値を丸めると失敗の痕跡が消えて別の場所で「なぜかこの値」として現れ、業務の概念を `string` のまま運ぶと取り違えをコンパイラが止められない。前提は Go 1.27 で、外部の依存は層の skill が指定するものと `golang.org/x/sync/errgroup`、golangci-lint v2、goimports だけにする。

## 業務の概念は型で運ぶ

業務や運用の意味を持つ値は、フィールド、引数と戻り値、イベント、入出力、読み取りモデル、テストデータのどこでも、`string`、数、`bool`、`time.Time` のまま持たず、値オブジェクト（非公開フィールドの struct と検証する `New*`）にする。外部サービスの応答を写した型も例外にしない。プリミティブへ戻すのは、外部の形式（DB の生成型、proto、ログの属性）へ写す変換の内側だけである。作る前に同じ意味の型が既にないかを探す。

取りうる値が有限なら、封じた型（非公開フィールドの struct と package 変数）にする。`type Status string` と `const` の組は、型変換で列挙の外の値を作れるので使わない。値は所有する package に一度だけ定義し、変換もテストの期待もその定義を使う。

```go
type Status struct{ v string }

var (
	StatusOnLoan   = Status{"on_loan"}
	StatusReturned = Status{"returned"}
)

func ParseStatus(s string) (Status, error) {
	switch s {
	case StatusOnLoan.v:
		return StatusOnLoan, nil
	case StatusReturned.v:
		return StatusReturned, nil
	default:
		return Status{}, ErrUnknownStatus
	}
}
```

設定値は、`UnmarshalText` で検証する名前付きの型で受け、読み込んだ直後に値オブジェクトへ変換し、欠けていれば起動しない。環境変数にするのは配備環境で変わる値だけで、業務の規則の数は資料が決めた定数にする。

## 丸めない、フォールバックしない

条件を満たさない値は、既定値に丸めずに error を返す。`switch` は取りうる値をすべて列挙して残りを error にし、`map` を引けなかったときも同じにする。一次手段が失敗したら別の手段で黙って続ける形（設定が読めなければ組み込みの値で起動する、トランザクションが無ければ pool で続ける）は書かない。要ると判断したら、書く前に止まり、一次手段、失敗の条件、代替手段、続行したときに隠れる失敗を示して利用者の許可を得る。

## 関数の形を一つに揃える

拒む条件をガード節で先に返し、本筋を最後に置く。返り値は `(T, error)` か `(T, bool)` までで、超えるなら結果の struct を返す。`context.Context` は I/O をする関数とそれを呼ぶ関数の第一引数にだけ置き、struct に持たない。引数が四つを超えるならフィールド名で渡す struct にする（集約のコマンドは資料の引数に対応させる）。値渡しを既定にし、ポインタは状態を変える協力者と nil が意味を持つ引数だけにする。不変の型は値レシーバ、状態を変える型はポインタレシーバにする。`init` を書かず、`main` は `run(ctx) error` を呼んで終了コードを決めるだけにする。

## interface は使う側で小さく切る

interface は、それを引数に取る package が呼ぶメソッドだけで定義し、実装側は具象の struct を返して `var _ Port = (*Impl)(nil)` で確かめる。例外は三つで、集約の永続化ポートと状態の和型はドメインが、時計と採番器は横断的関心事の package が一つだけ持つ。振る舞いが一つで状態を持たないなら関数型にする。

interface は自分の名前のファイルに単独で置き（同じファイルに置くのは `go:generate` と固有のエラーだけ）、実装する型はその型の名前のファイルに置く。契約の差分と実装の差分を混ぜないためである。struct を埋め込んで実装を共有しない。公開メソッドが外側の API に昇格するからである。

## 名前とコメントの Go の形

名前を業務の言葉で付けること、英名を資料のユビキタス言語から取り無ければ止まること、コメントを自分の責務だけで業務の言葉で書き外部の値にサンプルを添えることは、development-convention の `write-readable-code` に従う。ここに置くのは Go の形だけである。

名前は `package.Name` の形で一回で意味が通るようにし、型名に package 名を繰り返さない（`clock.ClockInterface` にしない）。形の決まった名前は次のとおりである。生成は `New<型>`、永続化からの組み立て直しは `Restore<型>`、コマンドの結果は `<コマンド名>Result`、usecase の入出力は `<usecase名>Input` と `<usecase名>Output`、変換は `<元>To<先>`、エラーは `Err<何が拒まれたか>`。値を返すメソッドに `Get` を付けず、頭字語は `ID`、`URL` のように揃える。`util`、`common`、`helpers`、`types` のような何でも入る package とファイルを作らない。コメントを書くときは、識別子の名前で始める（godoc の形）。

## package の木と import の向き

置き場と import の向きは [package の木と import の向き](references/package-layout.md) に従う。import は外側から内側へだけ向かい、置き場はどれも一つの責務を持つ。論理の責務とパターンは development-convention の `apply-layer-convention` が決め、ここではそれを package へ写すだけにする。

## 標準ライブラリとツールに任せる

機械で言えること（フォーマット、import の順、禁止する API と import、和型の網羅、naked return）は規則として覚えず、ツールに落とさせる。設定は [ツール](references/tooling.md) にある。書き換えの多くは `go fix ./...` の modernizer が行うので先に走らせて差分を読む。機械では決まらない 1.27 の選択は、UUID を標準の `uuid` で採番すること、JSON は境界の型だけで `encoding/json/v2` を使うこと、外部の型のエラーを `errors.AsType[T]` で判定することである。goroutine は、誰が終わりを待ち、いつ止まるかが読める形でだけ起動する。

コミットの前に次を通す。最初の二つは出力が空であること。

```bash
gofmt -l .
go tool goimports -local <module path> -l .
go vet ./...
go tool golangci-lint run ./...
go test -race -shuffle=on -count=1 ./...
```

## 止まるとき

フォールバックや前提に無い外部依存が要ると判断したとき、既定値への丸めが資料に仕様として書いてあるとき、`go.mod` を `go 1.27` にできないときは、書かずに止まって理由と候補を返す。対象が生成コードなら、生成元（SQL、proto）を直すことを提案する。技術の部品の名前や分割の揺れでは止まらず、最も筋の良い形を採って報告に示す。業務の概念の名前か英名が資料に無いときは `write-readable-code` に、要求されない公開面を作らない判断は `apply-yagni` に従う（どちらも development-convention）。
