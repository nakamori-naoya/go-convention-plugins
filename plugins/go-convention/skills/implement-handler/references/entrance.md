# 入口

入口は、外から来た要求を usecase の入力へ写し、usecase を一つ呼び、結果を応答へ写して返す。入口の種類は、RPC の handler、メッセージ購読の受信境界、ワーカーの巡回である。

# 値オブジェクトへの変換は入口で一度だけ

要求のプリミティブは、入口で値オブジェクトへ変換してから、usecase の入力に詰める。usecase は検証済みの値しか受け取らない。`New*` が拒んだエラーは、入口がそのまま返す。「入力が不正」に分類されているので、境界の表が応答を決める。

```go
func (s *LoanServer) BorrowBook(ctx context.Context, req *loanv1.BorrowBookRequest) (*loanv1.BorrowBookResponse, error) {
	actor, err := authorization.RequireActor(ctx)
	if err != nil {
		return nil, err
	}
	book, err := vo.NewBookNo(req.GetBookNumber())
	if err != nil {
		return nil, err
	}
	out, err := s.borrowBook.Execute(ctx, command.BorrowBookInput{
		User:   actor.UserNo(),
		Book:   book,
		LentAt: domain.NewLentAt(s.clock.Now()),
	})
	if err != nil {
		return nil, err
	}
	return borrowBookOutputToResponse(out), nil
}
```

要求に欠けた値（nil の Timestamp、空の文字列）は、値オブジェクトの生成が「入力が不正」で拒む。欠けた値を既定値へ丸めない。

応答への写しは、`<元>To<先>` の変換の関数に置き、値を取り出して詰めるだけにする。計算しない。

# 業務の時刻は、入口の Clock から一度だけ

コマンドが業務の時刻を引数で受けるなら、入口が Clock から一度だけ取り、値オブジェクトにして入力に載せる。要求の本文から操作の時刻を受け取らない。ワーカーの巡回は、一回の巡回の始めに一度だけ取り、その巡回のすべての件に同じ値を渡す。記録だけの時刻は、入口では取らない（リポジトリが取る）。

# 主体は、認可の interceptor が決めたものを使う

操作の主体（誰が借りるか）は、要求の本文から受け取らない。認証の interceptor が確かめ、認可の interceptor が解決した主体を ctx から受け取り、値オブジェクトとして usecase の入力に載せる。入口は、本人かどうかを自分で判断しない。資源の持ち主と主体の一致が要る判断は、集約のコマンドの事前条件にする。

# 入口は判断せず、記録せず、翻訳しない

handler の本文は、業務の判断を持たない。`errors.Is` でエラーを見て分岐しない。usecase のエラーは `return nil, err` でそのまま返す。`connect.NewError` を作らず、記録もしない。翻訳と記録は、最も外の interceptor が一度だけ行う。

一つの RPC は、一つの usecase を呼ぶ。RPC の中で usecase を組み合わせない。

# ワーカーの巡回と受信境界

ワーカーの巡回は、query の usecase で候補を選び、一件ごとに command の usecase を呼ぶ。ループと失敗の閉じ込め（処理の表の「全体に及ぶか」）は、巡回が持つ。command の usecase は、読み取りの口を呼ばない。

メッセージ購読の受信境界は、メッセージをプロセス間の契約の型へ変換し、手順の usecase を呼ぶ。処理の表の「再処理で通りうるか」で、受け取りを確定するか、再処理させるかを決め、記録する（write-logs）。
