# 例：本を借りる RPC

図書館の貸出の「本を借りる」RPC の入口、最も外の interceptor の要、`main`、API のテストの組み立てである。写すのは形で、名前と方針は対象の proto と資料から取る。

## handler

```go
func (s *LoanServer) BorrowBook(ctx context.Context, req *loanv1.BorrowBookRequest) (*loanv1.BorrowBookResponse, error) {
	actor, err := authorization.RequireActor(ctx) // 認可の interceptor が解決した主体
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
		LentAt: domain.NewLentAt(s.clock.Now()), // 業務の時刻は入口で一度だけ取る
	})
	if err != nil {
		return nil, err
	}
	return borrowBookOutputToResponse(out), nil
}

// policies は、手続きごとに求める主体である。表に無い手続きは拒む。
var policies = map[string]policy{
	loanv1connect.LoanServiceBorrowBookProcedure: requireRegisteredUser, // "/lending.v1.LoanService/BorrowBook"
	loanv1connect.LoanServiceReturnBookProcedure: requireRegisteredUser,
}
```

## 最も外の interceptor の要

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
	code, level = connect.CodeInternal, slog.LevelError // 分類不能か表の更新漏れ。実装を直す合図
	attrs = append(attrs, slog.Bool("unclassified", true))
}
attrs = append(attrs, slog.String("code", code.String()), slog.Any("err", err))
l.logger.LogAttrs(ctx, level, "RPCを完了できなかった", attrs...)
return nil, connect.NewError(code, fmt.Errorf("%s", errors.Message(err))) // 応答には公開してよい文言だけを載せる
```

panic の回収もこの interceptor が行い、stack を付けて ERROR で記録し、分類不能として応答する。

## main と組み立て

```go
func main() {
	logger := log.New(os.Stdout, slog.LevelInfo)
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	err := run(ctx, logger)
	stopRequested := ctx.Err() != nil
	stop()
	os.Exit(process.Exit(ctx, logger, stopRequested, err)) // 分類して一度だけ記録し、終了コードを返す
}

// run の中で、環境で変わるものだけを Deps に詰める。
mux := app.NewMux(app.Deps{
	Pool:          pool,
	ReadPool:      readPool,
	Logger:        logger,
	Clock:         clock.NewSystem(),
	IDs:           idgen.NewUUIDv7(),
	TokenVerifier: authn.NewVerifier(cfg.Issuer),
})
```

## API のテストの組み立て

```go
ctrl := gomock.NewController(t)
verifier := mock_authn.NewMockTokenVerifier(ctrl)
verifier.EXPECT().Verify(gomock.Any(), "token-U-0001").Return(subjectU0001, nil).AnyTimes()

server := httptest.NewServer(app.NewMux(app.Deps{
	Pool:          suite.Database.Client(),
	ReadPool:      suite.Reader,
	Logger:        slog.New(slog.DiscardHandler),
	Clock:         clk,
	IDs:           ids,
	TokenVerifier: verifier,
}))
t.Cleanup(server.Close)
client := loanv1connect.NewLoanServiceClient(server.Client(), server.URL)
```

ケースは、成功と反映、返しうる分類ごとの Code と文言、Authorization のヘッダの無い要求、登録していない利用者の要求、欠けた資料番号を並べる。
