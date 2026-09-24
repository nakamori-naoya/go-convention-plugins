# 記録の場所

# 規則は一つ

**返すなら記録しない。飲み込むなら記録する。**

エラーを返す場所は、記録しない。返したエラーは、最も外の境界が一度だけ記録する。内側で記録すると、同じ失敗が層の数だけ並ぶ。

エラーを飲み込んで先へ進む場所は、そのエラーが境界へ届かないので、飲み込んだ場所で一度記録する。飲み込んでよいのは、失敗の影響を一件に閉じ込める場面（一覧から壊れた一件を除く、巡回や発行で一件の失敗を記録して次へ進む）だけである。どの失敗を一件に閉じ込めてよいかは、handle-errors の処理の表の「全体に及ぶ」で決まる。

記録を、失敗を握りつぶす代わりにしない。記録して `return nil` するのは「飲み込む」であり、上の場面に当たらないなら `return err` にする。

# 層ごとの記録

最も外の境界（RPC の interceptor、メッセージ購読の受信境界、ワーカーの巡回、プロセスの起動と終了）は、記録する。

ワーカーの巡回と、手順の usecase（単純なパターン）は、一件ずつ処理して飲み込む失敗だけを記録する。

Query の実装は、一覧から壊れた一件を除くときだけ、除いた場所で記録する。それ以外は記録しない。

usecase（戦術的 DDD の command）、リポジトリ、handler の本文は、記録しない。エラーを返す。

ドメイン（値オブジェクト、集約、イベント）は、記録しない。`log/slog` を import しない。ドメインが運用者に伝えたいことは、エラーとコマンドの結果で外へ出る。

例外は一つだけある。トランザクションの取り消しに失敗したとき、本来の失敗（または panic）を伝えるために、取り消しの失敗を戻り値に載せられない。これはトランザクションの管理が、注入された logger で記録する。

# logger の渡し方

logger は、`run` がプロセスの組み立てで一つ作り、記録する構造体（interceptor、受信境界、ワーカー、一件ずつ処理する手順、壊れた一件を除く Query の実装、トランザクションの管理）へ引数で渡す。記録しない構造体には、logger のフィールドを置かない。フィールドがあれば、誰かが使う。

`slog.SetDefault` と `slog.Default()` に頼らない。どこから何が記録されるかを、組み立ての引数から辿れるようにするためである。nil の logger を既定の logger へ丸めない。外部のライブラリが logger を受け取れるなら、同じ logger を渡す。

ctx に logger を入れない。ctx に logger があると「どこでも書ける」になり、層の線が消える。ctx で運ぶのは、属性の元になる値（リクエストの識別子）だけである。ctx から属性を足す handler を logger に重ねれば、すべての行にリクエストの識別子が付く。

```go
// contextHandler は、ctx に載ったリクエストの識別子を各レコードへ足す。
type contextHandler struct{ slog.Handler }

func (h contextHandler) Handle(ctx context.Context, record slog.Record) error {
	if id, ok := requestID(ctx); ok {
		record = record.Clone()
		record.AddAttrs(slog.String("request_id", id))
	}
	return h.Handler.Handle(ctx, record)
}

func (h contextHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	return contextHandler{Handler: h.Handler.WithAttrs(attrs)}
}
```

`WithAttrs` を包み直さないと、`logger.With` の結果からこの handler が外れる。

テストでは `slog.New(slog.DiscardHandler)` を渡す。失敗のときに読みたければ、`t.Output()` に繋いだ handler を渡す。ログが出たかをテストで確かめない。

# 境界ごとの記録

## RPC の interceptor

最も外の interceptor が、RPC 一回につき一行を記録する。成功は INFO、失敗はエラーの分類からレベルの表で決める。同じ interceptor が、handle-errors の応答の表でエラーを Code へ写し、panic を回収する。

```go
res, err = next(ctx, req)
attrs := []slog.Attr{
	slog.String("procedure", req.Spec().Procedure),
	slog.Int64("duration_ms", time.Since(started).Milliseconds()),
}
if err == nil {
	l.logger.LogAttrs(ctx, slog.LevelInfo, "RPCを完了した", attrs...)
	return res, nil
}
code, codeFound := rpcerr.Code(err)
level, levelFound := log.Level(err)
if !codeFound || !levelFound || errors.Is(errors.Category(err), errors.ErrUnclassified) {
	// 分類不能、または表の更新漏れ。実装を直す合図として区別する。
	code, level = connect.CodeInternal, slog.LevelError
	attrs = append(attrs, slog.Bool("unclassified", true))
}
attrs = append(attrs, slog.String("code", code.String()), slog.Any("err", err))
l.logger.LogAttrs(ctx, level, "RPCを完了できなかった", attrs...)
return nil, connect.NewError(code, fmt.Errorf("%s", errors.Message(err))) // 応答には公開してよい文言だけを載せ、連鎖を渡さない
```

記録する `err` は翻訳の前のエラーで、原因がログにだけ残る。応答には、handle-errors が決めた公開の文言だけが出る。panic は、この interceptor が回収し、stack を付けて ERROR で記録し、分類不能として応答する。panic を回収する場所を、ほかに重ねない。

内側の interceptor（認証、認可、頻度の制限）と handler の本文は、記録しない。エラーを返す。

interceptor の並びと組み立ては implement-handler が決める。

## メッセージ購読の受信境界

メッセージを受けて手順を呼ぶ受信境界は、一件のメッセージにつき一行を記録する。処理の表で、再試行させる（受け取りを確定しない）か、確定して終えるかを決め、その判断を記録に残す。黙って捨てない。

## ワーカーの巡回

巡回は、その回の判断に使う時刻を最初に一度だけ取り、候補を選ぶ query を呼び、一件ごとに command を呼ぶ。ループと失敗の閉じ込めは、巡回（境界）が持つ。

```go
func (w *OverdueChecker) runOnce(ctx context.Context) error {
	// 巡回の判断に使う時刻。Clock から一度だけ取り、資料の「延滞にする」の引数の値オブジェクトにする。
	at := w.checkedAt()
	candidates, err := w.listCandidates.Execute(ctx, at)
	if err != nil {
		return err
	}
	marked := 0
	for _, loan := range candidates {
		err := w.markOverdue.Execute(ctx, command.MarkOverdueInput{Loan: loan, At: at})
		if err == nil {
			marked++
			continue
		}
		handling, handlingFound := errors.HandlingOf(err)
		level, levelFound := log.Level(err)
		if !handlingFound || !levelFound {
			return err // 表の更新漏れ。巡回を打ち切り、見張りが分類不能として記録する
		}
		if handling.Spreads {
			return err
		}
		w.logger.LogAttrs(ctx, level, "貸出を延滞にできなかったため次へ進む",
			slog.String("loan_id", loan.Value()),
			slog.Any("err", err),
		)
	}
	w.logger.LogAttrs(ctx, slog.LevelInfo, "延滞の確認の巡回を終えた",
		slog.Int("candidates", len(candidates)),
		slog.Int("overdue", marked),
	)
	return nil
}
```

候補を選べなかった失敗と、全体に及ぶ失敗は、返す。返したエラーは、巡回を動かすもの（下の常駐の見張り）が記録する。一件に閉じた失敗は、飲み込んで記録する。

## 常駐の見張り

常駐するワーカーは、裸の `go` で起動しない。goroutine の中の panic と予期しない終了を、誰も見られないからである。見張りの関数（`Supervise(ctx, name, logger, fn)`）で起動し、見張りが panic（stack 付き）と予期しない終了を ERROR で記録して、間隔を広げながら起動し直す。ctx の終了による停止は記録しない。

## プロセスの起動と終了

プロセスの境界も、同じ表で分類して記録する。`run` が返したエラーを、`main` が作って渡した logger で、分類のレベルで一度記録し、終了コードを決める。

起動のときの依存先のエラーも、handle-errors の翻訳表を通してから返す。PostgreSQL に接続できなければ「依存先が利用できない」、設定の値が不正なら「回復不能」になる。翻訳されない素のエラーで、プロセスが終わることはない。

停止の要求による終了は、「中断された」として INFO で記録し、正常の終了コードで終える。停止の要求を受けた後に依存先のクライアントが分類できない形のエラーを返すことがあるので、停止を要求したかどうかは ctx で確かめる。
