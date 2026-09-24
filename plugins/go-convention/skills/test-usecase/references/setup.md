# 実物で通す

# 何を実物にし、何を差し替えるか

usecase のテストは、実物の PostgreSQL（dockertest）、実物のリポジトリ、実物の Query の実装、実物のトランザクションの管理を使う。組み立ては、本番と同じコンストラクタで行う。実 DB の基盤は、apply-go-test-convention の実 DB の規則に従う。

差し替えるのは、時計、採番器、制御できない外部の境界のポート（延滞の通知を外部へ発行するポート）だけで、gomock を使う（apply-go-test-convention の差し替えてよい境界）。業務の時刻は入力で渡すので、command のテストで Clock の mock が要るのは、リポジトリが記録の時刻を取るときである。

```go
ctrl := gomock.NewController(t)
clk := mock_clock.NewMockClock(ctrl)
clk.EXPECT().Now().Return(returnedAt).AnyTimes()
ids := mock_idgen.NewMockGenerator(ctrl)
ids.EXPECT().NewID().Return(eventID).AnyTimes()

loans := repository.NewLoanRepository(clk, ids)
sut := command.NewReturnBook(tx.NewPostgresManager(suite.Database.Client(), logger), loans)
```

# 前提は持ち主の書き込み経路で

前提の行は、持ち主のコマンドと書き込み経路を順に通して作る（apply-go-test-convention のテストデータの規則）。延滞の貸出が前提なら、本を借りる → `ApplyLent` → 延滞にする → `ApplyOverdue` を、実物の集約と実物のリポジトリで通す Builder を使う。行を直接入れない。

# 観測

観測するのは、返り値（出力と具体エラー）と、そのケースの観点が見るテーブルだけである。行を読むテスト専用の SQL は、test-repository の置き場のものを使う。全テーブルを毎ケース突き合わせない。行の形の網羅は、永続化層のテストの関心だからである。

# 直列

同じ実 DB を全ケースが共有するので、`t.Parallel()` を書かない。ループの直前のコメントで、共有する資源を名指しする。
