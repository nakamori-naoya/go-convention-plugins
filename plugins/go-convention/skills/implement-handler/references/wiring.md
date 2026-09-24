# 組み立てと起動

# `main` と `run`

`main` は、シグナルを ctx に変え、logger を作り、`run(ctx, logger)` を呼び、結果を記録して終了コードを決めるだけにする。組み立て、起動、停止待ち、後始末の `defer` は `run` に書く。`os.Exit` は `defer` を実行しないので、`main` に `defer` を書かない。

```go
func main() {
	logger := log.New(os.Stdout, slog.LevelInfo)
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	err := run(ctx, logger)
	stopRequested := ctx.Err() != nil
	stop()
	os.Exit(process.Exit(ctx, logger, stopRequested, err))
}
```

`process.Exit` は、プロセスの境界として、終了の理由を分類し、表のレベルで一度だけ記録し、終了コードを返す（write-logs のプロセスの境界）。停止の要求による終了は、正常の終了コードにする。

# 設定

設定は、環境変数から名前付きの型で読み込み、読み込みの時点で検証する（write-go-code）。欠けていたら、既定値へ倒さずに起動しない。読み込みの失敗は、環境の不備として「回復不能」に分類される。読み込んだ値は、すぐに値オブジェクトへ変換して内側へ渡す。

# `run`

`run` は、環境で変わるもの（接続の pool、読み取り専用の pool、logger、Clock、採番器、外部の境界の実装）を作り、組み立ての関数に渡す。起動のときの依存先のエラー（接続できない）も、handle-errors の翻訳表を通してから返す。

```go
mux := app.NewMux(app.Deps{
	Pool:          pool,
	ReadPool:      readPool,
	Logger:        logger,
	Clock:         clock.NewSystem(),
	IDs:           idgen.NewUUIDv7(),
	TokenVerifier: authn.NewVerifier(cfg.Issuer),
})
```

# 組み立ての関数

組み立ての関数（`NewMux`）は、`Deps` から、トランザクションの管理、リポジトリ、Query の実装、usecase、handler、interceptor の列を、内側から外側へ順に組み立てる。配線と interceptor の並びは、この一か所に閉じる。本番の `run` とテストが、同じ関数を呼ぶ。テストと本番で配線が違うことが無いようにするためである。

`Deps` に渡すのは、環境で変わるものだけである。usecase やリポジトリを `run` で組まない。logger は、記録する構造体（interceptor、受信境界、ワーカー、手順、Query の実装、トランザクションの管理）へ、組み立ての関数が同じものを渡す。

ワーカーの組み立ても、同じ形の関数に置く。常駐するワーカーは、見張りの関数（`Supervise`）で起動し、`run` が返る前に必ず終わりを待つ。

# 停止

ctx が取り消されたら、HTTP のサーバーを、取り消されていない別の ctx（期限付き）で停止する。取り消し済みの ctx を渡すと、処理中の要求がすぐに切れる。ワーカーが止まってから、接続の pool を閉じる。
