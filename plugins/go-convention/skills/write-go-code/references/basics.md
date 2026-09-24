# 基本

ここに並ぶ規則は、どれも一つのことのためにある。**失敗を隠さず、原因の行を読み手の近くに置く**ことである。関数の形、分岐の形、初期化の形を一つに揃え、「なぜこの値になったか」を辿らずに済むコードにする。

例の題材は図書館の貸出である。`errors` は、エラーの分類を持つプロジェクトの package（handle-errors が定める）を指す。

# 明示する

## 値の出どころを行で示す

値がどこから来たかを、コードの行で示す。変換は名前のある関数を呼び、規則は名前のある定数にする。型変換、既定値の補完、初期化を、読み手が知らない場所（`init`、ゼロ値の特別扱い、埋め込みによるメソッドの昇格、`String()` による暗黙の文字列化）で起こさない。

```go
// 貸出期間は業務の規則なので、名前のある定数にする。関数は引数から結果を作るだけにする。
const loanPeriodDays = 14

func DueFrom(lentOn LentOn) Due {
	return Due{on: lentOn.date().AddDate(0, 0, loanPeriodDays)}
}
```

暗黙の動作は、失敗の原因を失敗した行から遠い場所へ移す。「この返却期限はなぜ14日後なのか」に答えるために実装を辿る時間が、暗黙一つごとに増える。

## 未指定や不正な値を、既定値に丸めない

受け取った値が条件を満たさなければ、error を返す。「無ければ0」「不正なら既定へ」「範囲外なら端に寄せる」を書かない。

```go
var ErrVersionNotPositive = errors.Define(errors.ErrInvalidInput, "1未満の版")

func NewVersion(n int) (Version, error) {
	if n < 1 {
		return Version{}, ErrVersionNotPositive
	}
	return Version{v: n}, nil
}
```

丸めは失敗を成功に見せる。DB の行が壊れていても、入力が欠けていても、丸めた瞬間に痕跡が消える。

## 取りうる値を列挙し、残りは error にする

`switch` は取りうる値をすべて `case` に並べ、`default` は error を返す。`default` に来た値を既定の値へ丸めたり、`panic` したりしない。`map` を引けなかったとき、型の判定に失敗したときも同じで、黙って既定値で続けない。

`default` を「残りの範囲がすべてその値」と言える場合に使うなら、その根拠をコメントに書く。

## フォールバックを書かない

一次手段が失敗したら error を返し、境界で記録して終える。「A が失敗したら B を試す」「設定が読めなければ組み込みの値で起動する」「キャッシュが無ければ空として続ける」を、自分の判断で書かない。どうしても要ると判断したら、書く前に利用者へ理由と代替手段を示して許可を得る。

トランザクションが要る場面で、ctx にトランザクションが無ければ pool で続ける、という切り替えもフォールバックである。リポジトリは ctx のトランザクションを必須とし、無ければ「分類不能」のエラーを返す。Query の実装は、読み取り専用の pool だけから読み、ctx のトランザクションを見ない。

フォールバックは「失敗したのに動いている」状態を作り、失敗を見つける時点を、利用者からの問い合わせまで遠ざける。要るかどうかは業務と運用の判断で、コードを書いている最中に決めることではない。

# 関数の形

## 分岐はガード節で書く

拒む条件を先に並べて `return` し、本筋を字下げ無しで最後に書く。`else` の中に本筋を置かない。

```go
func (p PendingLoan) Borrow(id LoanID, lentOn LentOn) (BorrowResult, error) {
	if p.standing.HasOverdue() {
		return BorrowResult{}, ErrUserHasOverdue
	}
	if p.standing.ReachedLimit() {
		return BorrowResult{}, ErrLoanLimitReached
	}
	next := OnLoan{id: id, user: p.user, book: p.book, lentOn: lentOn, due: DueFrom(lentOn), version: FirstVersion}
	return BorrowResult{Next: next, Event: Lent{loan: next}}, nil
}
```

ガード節は、拒む理由と拒む行を隣り合わせにする。上から読むと、資料の拒む理由の順に並んでいる。

## 返り値は二つまで

返り値は `(T, error)` か `(T, bool)` か一つにする。三つ目が要るなら、結果の struct を一つ返す。`(T, bool)` は、拒まないが何も変えないことがある操作と、存在の問い合わせに使う。拒む理由があるなら `(T, error)` である。両方が要る操作は、設計を分ける。

返り値が三つ以上になると、呼び出し側で `_` が増え、何を捨てたかが読めなくなる。結果の struct はフィールド名が説明になる。

## naked return を書かない

`return x, err` と値を書く。名前付きの結果は、`defer` で結果を書き換えるときだけ使い、そのときも `return` には値を書く。naked return は、「この行で何が返るか」を関数の先頭まで戻って読ませる。

## ctx は、I/O をする関数の第一引数にだけ置く

`context.Context` は第一引数で、名前は `ctx` である。struct に持たない。`context.Background()` と `context.TODO()` は、`main` とテストの外で使わない。

ctx を受け取るのは、I/O（DB、ネットワーク、外部プロセス、時刻待ち）をするか、それをする関数を呼ぶ関数だけである。値オブジェクトと集約は I/O をしないので、ctx を受け取らない。使わない ctx は引数ごと外す。呼ぶ側の interface が要求する場合だけ、使わなくても第一引数に置く。

ctx は呼び出しの寿命（キャンセルと期限）である。struct に持たせると寿命が呼び出しと合わなくなり、途中で作り直すとキャンセルが伝わらない。

## 引数が四つを超えるなら struct にする

同じ型の引数が並ぶと、入れ違いをコンパイラが止められない。四つを超える引数は、意味の読める名前の struct（usecase の入力なら `<usecase名>Input`）にまとめ、フィールド名で渡す。業務の入力に `opts ...Option` を使わない。

集約のコマンドの引数は、資料のコマンドの引数と対応するので、この規則の対象外である（implement-domain-model が決める）。

## 値渡しを既定にする

値オブジェクト、集約の状態の型、イベント、入力と結果の struct は、値で受け渡し、コンストラクタは値を返す。ポインタにするのは二つの場合だけである。一つは、接続、プール、キャッシュを持つ協力者のように、メソッドが自分の状態を変える型である。もう一つは、nil が「無い」を意味する引数で、呼び出し側がその意味を知っている場合である。サイズや速度を理由にポインタを選ばない。「未指定」を `*string` で表さない。

値は共有されないので、渡した先で書き換えられる心配が無い。ポインタが増えると、「誰がいつ変えたか」と「nil か」を常に考えることになる。

## レシーバは型の中で揃える

不変の型（値オブジェクト、状態の型、イベント）は値レシーバにし、操作は新しい値を返す。状態を変える型（リポジトリの実装、usecase、トランザクションの管理）はポインタレシーバにする。同じ型に二つを混ぜない。`sync.Mutex` を持つ型を値レシーバにしない。

## struct リテラルはフィールド名を書く

位置指定のリテラルは、フィールドの追加や並べ替えで静かに意味が変わる。フィールド名を書く。例外は、フィールドが一つの封じた型の package 変数（`StatusOnLoan = Status{"on_loan"}`）だけである。

# 初期化と組み立て

## `init` を書かない

`init` は import した瞬間に走り、順序が import の関係で決まり、失敗を返せない。書かない。package 変数に置くのは、一度作れば変わらず失敗しないもの（エラーの定義、`regexp.MustCompile` の結果、封じた型の値）だけにする。接続、設定の読み込み、登録は、`main` の `run` から明示的に呼ぶ。

## `main` は `run(ctx) error` を呼ぶ

`main` は、シグナルを ctx に変え、`run` を呼び、結果で終了コードを決めるだけにする。組み立て、起動、停止待ち、後始末の `defer` は `run` に書く。`os.Exit` は `defer` を実行しないので、`main` に `defer` を書かない。`log.Fatal*` を呼ばない。

```go
func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	err := run(ctx)
	stop()
	if err != nil {
		os.Exit(1)
	}
}
```

`run` が返したエラーをどう分類して記録するかは、プロセスの境界として write-logs が決める。`main` は logger を作って `run` へ渡し、`run` の中の境界がそれを使う。

## 設定値は名前付きの型で受け、読み込みの時点で検証する

環境変数は、名前付きの型で受ける。その型が `UnmarshalText` で値を検証し、不正なら読み込みの時点で拒む。読み込んだ直後に値オブジェクトへ変換し、内側へは値オブジェクトで渡す。

```go
// PositiveInt は、1以上の整数の設定値である。例: "50"。0以下を許すと処理が進まない件数を表す。
type PositiveInt int

func (v *PositiveInt) UnmarshalText(text []byte) error {
	n, err := strconv.Atoi(string(text))
	if err != nil || n < 1 {
		return fmt.Errorf("%w: %q", ErrInvalidSetting, text)
	}
	*v = PositiveInt(n)
	return nil
}

type environment struct {
	DatabaseURL DatabaseURL `env:"DATABASE_URL,required,notEmpty"`
	BatchSize   PositiveInt `env:"NOTICE_BATCH_SIZE,required,notEmpty"`
}
```

`ErrInvalidSetting` は、環境の不備として「回復不能」を土台にする。設定値が値オブジェクトとして不正なときの分類の付け替えは、handle-errors が決める。

環境変数で受けるのは、接続先、ポート、鍵、件数や間隔のように配備環境で変わる値だけである。業務の規則（貸出期間、貸出上限）は、資料が決めた定数としてコードに置く。

# 宣言の順と、書かないもの

## ファイルの中の宣言の順

定数、型、コンストラクタ（`New*`、`Restore*`）、状態を変える公開メソッド、値を返す公開メソッド、非公開の関数とメソッドの順に並べる。型が複数あるなら型ごとにこの塊を並べ、非公開はファイルの末尾にまとめる。非公開の関数を、公開メソッドの間に挟まない。上から読むだけで「この型は何ができるか」が分かる。

## いまの呼び出しが要らないものを書かない

関数、引数、フィールド、分岐、オプションは、いまのテストか呼び出し側が要求するものだけ書く。空の関数、`TODO` だけの本文、`_ = x` で黙らせた引数、「後で使う」設定、いま呼ばれない分岐を書かない。公開シンボルは、実装のコードが実際に呼ぶものだけにし、テストのために公開を増やさない（`export_test.go` も作らない）。

使われない宣言は、読み手に「どこで使うのか」を探させる。
