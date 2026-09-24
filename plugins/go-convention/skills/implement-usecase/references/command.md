# command の形（戦術的 DDD）

command の流れ（集約を見つける、コマンドを一回呼ぶ、結果を適用する）と、usecase が判断も材料集めもしない理由は、development-convention の `apply-layer-convention` が持つ。この文書は、それを Go で書く形だけを示す。

# 形

一つの業務イベントに、一つの型と一つの `Execute` を置く。名前は資料の業務の語にする（`BorrowBook`、`ReturnBook`、`MarkOverdue`）。返すものがあれば `(Output, error)`、無ければ `error` を返す。公開するのは `Execute` だけである。

```go
// ReturnBook は、貸出中または延滞の貸出を返却済みにする。
type ReturnBook struct {
	tx    tx.Manager
	loans domain.LoanRepository
}

type ReturnBookInput struct {
	Loan domain.LoanID
}

func NewReturnBook(txm tx.Manager, loans domain.LoanRepository) *ReturnBook {
	return &ReturnBook{tx: txm, loans: loans}
}

func (u *ReturnBook) Execute(ctx context.Context, in ReturnBookInput) error {
	return u.tx.Run(ctx, returnTxOptions, func(ctx context.Context) error {
		loan, err := u.loans.FindLoan(ctx, in.Loan)
		if err != nil {
			return err
		}
		res, err := loan.Return()
		if err != nil {
			return err
		}
		return u.loans.ApplyReturned(ctx, res.Event)
	})
}
```

入力は値オブジェクトで受ける。プリミティブから値オブジェクトへの変換は入口（implement-handler）が行い、usecase は検証しない。

依存は、`tx.Manager`、ドメインの永続化ポート、採番器、制御できない外部の境界のポートだけである。`usecase/query` の読み取りのポートは import しない。判断の材料は、`FindPendingLoan` のような Find が初期状態の型へ持たせて返す。

Go では、型スイッチ、状態の比較、件数の解釈、時刻の比較を usecase に書かない。和型の `Loan` のコマンドを呼べば、状態ごとの型が受けるか拒むかを決める。コマンドを和型に置けない（受けない状態の拒む理由が資料に無い）間は、その usecase を書かない（implement-domain-model）。

エラーは、包まずにそのまま返す（handle-errors）。記録しない（write-logs）。

# 生成

材料が要る生成は、初期状態の型を Find で得てコマンドを呼ぶ。材料が要らない生成は、usecase が初期状態の型を直接作ってコマンドを呼ぶ。

```go
func (u *BorrowBook) Execute(ctx context.Context, in BorrowBookInput) (BorrowBookOutput, error) {
	loanID := domain.NewLoanIDFromUUID(u.ids.NewID())
	var out BorrowBookOutput
	err := u.tx.Run(ctx, borrowTxOptions, func(ctx context.Context) error {
		pending, err := u.loans.FindPendingLoan(ctx, in.User, in.Book)
		if err != nil {
			return err
		}
		res, err := pending.Borrow(loanID, in.LentAt, u.calendar)
		if err != nil {
			return err
		}
		if err := u.loans.ApplyLent(ctx, res.Event); err != nil {
			return err
		}
		out = BorrowBookOutput{Loan: res.Event.LoanID(), Due: res.Event.Due()}
		return nil
	})
	if err != nil {
		return BorrowBookOutput{}, err
	}
	return out, nil
}
```

応答に返し、以後その集約を指す識別子は、usecase が採番器から取って、コマンドへ渡す。採番はトランザクションの外で行う。直列化の失敗で手順が呼び直されても、同じ識別子を使うためである。

出力は、コマンドの結果のイベントから作る。`Apply` の戻り値から作らない。

日付が要るコマンドへ渡す図書館の暦（`LibraryCalendar`）は、組み立て（main）が設定から一度だけ作り、usecase のコンストラクタで受けて持つ。入力には載せない。要求ごとに変わる値ではないからである。

# 時刻

業務の時刻は、入力の値オブジェクトとしてコマンドへ渡す（入口が Clock から取る）。usecase は Clock を持たない。記録だけの時刻は、リポジトリが取る。

# 拒まないコマンド

`(Result, bool)` を返すコマンドの `false` は、「何も起きなかった」である。usecase は `Apply` を呼ばずに `nil` を返す。`false` をエラーにしない。

# 物理設計の指定を渡す

分離レベルと、トランザクションの中でのやり直し（どの失敗を、何回までやり直すか）は、物理設計の資料が操作ごとに決める。usecase は、その指定を名前のある `tx.Options` の変数に写して渡すだけで、自分では選ばない。変数の上のコメントに、物理設計のどの節から写したかを一行書く。

```go
// borrowTxOptions は、物理設計の「分離性判断: 貸出上限」の指定である。
// SERIALIZABLE で、直列化の失敗（40001）だけを最大3回やり直す。
var borrowTxOptions = tx.Options{Isolation: tx.Serializable, RetryOn: tx.SerializationFailure, MaxRetries: 3}

// returnTxOptions は、物理設計の「分離性判断: 延滞にするのと返却が重なる」の指定である。
// READ COMMITTED で、やり直さない。
var returnTxOptions = tx.Options{Isolation: tx.ReadCommitted}
```

`tx.Options` のゼロ値は、指定が無いことを表す。トランザクションの管理は、分離レベルの無い指定を受けたら、張らずに分類不能を返す。既定の分離レベルに頼ると、物理設計の指定を渡し忘れたことに誰も気づかないからである。やり直しの回数も `tx.Options` が運び、トランザクションの管理の側に既定の回数を置かない。

Find の読み取りは、この指定のトランザクションの中で行われる。論理データモデルに並行実行の保証が書かれているのに、物理設計に指定が無ければ、推測で補わずに物理設計の資料へ返す。

やり直しは、トランザクションの管理が行う。usecase に再試行のループを書かない。

# 複数の集約と、後続の処理

一つの command が書く集約は、一つを基本にする。後続の処理が別の時点でよいなら、発生元の集約のイベントの `Apply` が、同じトランザクションで Outbox の要求を記録し、別の手順が別のトランザクションで処理する（延滞にすると、延滞の通知の要求が同じトランザクションで記録される）。

資料が「二つの集約を同じ時点で成立させる」と定めているときだけ、二つの集約を一つのトランザクションで操作する command を、横断の置き場（apply-go-package-layout の `orchestration`）に置く。先の集約のコマンドの結果を、次の集約のコマンドへ値として渡す。usecase が usecase を呼ばない。

資料に、同じ時点か別の時点かが書かれていなければ、推測せずに資料の持ち主へ問う。
