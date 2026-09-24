# command の形（戦術的 DDD）

command の usecase は、**集約を見つける → コマンドを一回呼ぶ → 結果を適用する**、の三つだけで書く。どの処理をこの形で書くかは、apply-layer-convention が決める。

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
	return u.tx.Run(ctx, tx.Options{}, func(ctx context.Context) error {
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

依存は、トランザクションの管理、ドメインの永続化ポート、採番器、制御できない外部の境界のポートだけである。**読み取りのポート（`usecase/query`）は呼ばない。** 判断の材料は、リポジトリの Find が集めて初期状態の型へ持たせる。材料を usecase が集めると、材料を集めるための分岐と逐次の呼び出しが usecase に入り込み、材料と保存が同じトランザクションで行われる保証も崩れる。

usecase は、状態を見て分岐しない。型スイッチ、状態の比較、件数の解釈、時刻の比較を書かない。受けるか拒むかは、和型のコマンドを呼べば、状態ごとの型が決める。コマンドを和型に置けない（受けない状態の拒む理由が資料に無い）間は、その usecase を書かない（implement-domain-model）。

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
		res, err := pending.Borrow(loanID, in.LentAt)
		if err != nil {
			return err
		}
		if err := u.loans.ApplyLent(ctx, res.Event); err != nil {
			return err
		}
		out = BorrowBookOutput{Loan: res.Next.ID(), Due: res.Next.Due()}
		return nil
	})
	if err != nil {
		return BorrowBookOutput{}, err
	}
	return out, nil
}
```

応答に返し、以後その集約を指す識別子は、usecase が採番器から取って、コマンドへ渡す。採番はトランザクションの外で行う。直列化の失敗で手順が呼び直されても、同じ識別子を使うためである。

出力は、コマンドの結果から作る。`Apply` の戻り値から作らない。

# 時刻

業務の時刻は、入力の値オブジェクトとしてコマンドへ渡す（入口が Clock から取る）。usecase は Clock を持たない。記録だけの時刻は、リポジトリが取る。

# 拒まないコマンド

`(Result, bool)` を返すコマンドの `false` は、「何も起きなかった」である。usecase は `Apply` を呼ばずに `nil` を返す。`false` をエラーにしない。

# 物理設計の指定を渡す

分離レベルと、トランザクションの中でのやり直し（直列化の失敗だけを、回数を限ってやり直す）は、物理設計の資料が操作ごとに決める。usecase は、その指定を `tx.Options` に渡すだけで、自分では選ばない。既定の分離レベルに頼らない。

```go
// borrowTxOptions は、物理設計の「分離性判断: 貸出上限」の指定である。
var borrowTxOptions = tx.Options{Isolation: tx.Serializable, Retry: tx.RetrySerializationFailures}
```

Find の読み取りは、この指定のトランザクションの中で行われる。論理データモデルに並行実行の保証が書かれているのに、物理設計に指定が無ければ、推測で補わずに物理設計の資料へ返す。

やり直しは、トランザクションの管理が行う。usecase に再試行のループを書かない。

# 複数の集約と、後続の処理

一つの command が書く集約は、一つを基本にする。後続の処理が別の時点でよいなら、発生元の集約のイベントの `Apply` が、同じトランザクションで Outbox の要求を記録し、別の手順が別のトランザクションで処理する（延滞にすると、延滞の通知の要求が同じトランザクションで記録される）。

資料が「二つの集約を同じ時点で成立させる」と定めているときだけ、二つの集約を一つのトランザクションで操作する command を、横断の置き場（apply-go-package-layout の `orchestration`）に置く。先の集約のコマンドの結果を、次の集約のコマンドへ値として渡す。usecase が usecase を呼ばない。

資料に、同じ時点か別の時点かが書かれていなければ、推測せずに資料の持ち主へ問う。
