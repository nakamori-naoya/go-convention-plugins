# 起動と差し替え

# 本番と同じ組み立てで起動する

API のテストは、本番の `run` と同じ組み立ての関数（`NewMux`）で handler を組み、`httptest.NewServer` に載せ、生成したクライアントから公開の API として叩く。handler の単体のテスト（server の構造体のメソッドを直接呼ぶ）は書かない。interceptor の列、変換、usecase、リポジトリ、トランザクションの管理が、本番と同じ順に並んで通ることを確かめるためである。

# 差し替えるのは、外部の境界と時計と採番だけ

`Deps` のうち、差し替えるのは、外部の認証基盤のトークンを検証するポート、時計、採番器だけで、gomock を使う（apply-go-test-convention の差し替えてよい境界）。認証と認可の interceptor そのものは差し替えない。差し替えると、すべての API のテストが本番の認可（主体の解決、方針の表）を通らなくなる。

```go
ctrl := gomock.NewController(t)
verifier := mock_authn.NewMockTokenVerifier(ctrl)
verifier.EXPECT().Verify(gomock.Any(), "token-U-0001").Return(subjectU0001, nil).AnyTimes()

mux := app.NewMux(app.Deps{
	Pool:          suite.Database.Client(),
	ReadPool:      suite.Reader,
	Logger:        slog.New(slog.DiscardHandler),
	Clock:         clk,
	IDs:           ids,
	TokenVerifier: verifier,
})
server := httptest.NewServer(mux)
t.Cleanup(server.Close)
client := loanv1connect.NewLoanServiceClient(server.Client(), server.URL)
```

主体は、要求の Authorization のヘッダに、mock が知っているトークンを載せて決める。主体の無い要求と、他人の要求は、ヘッダで作る。

# 実 DB

実 DB の基盤と直列の規則は、apply-go-test-convention の実 DB の規則に従う。前提は、持ち主の書き込み経路で作る。
