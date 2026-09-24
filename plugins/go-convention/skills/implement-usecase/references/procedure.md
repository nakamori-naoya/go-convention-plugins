# 手順の形（単純なパターン）

単純なパターンの usecase は、手順として、リポジトリ相当の口を順に呼ぶ。集約や状態の型は作らない。これは戦術的 DDD の例外ではなく、並ぶ二つ目の形である。どの処理をこの形で書くかは、apply-layer-convention が決める。

単純なパターンの手順の代表は、Outbox の回収と発行である。メールや通知の送信、投稿の後のタイムラインの更新のように、業務の変更と同期で行うと外部の遅延や失敗が業務の変更を止める処理に使う。command が業務の変更と同じトランザクションで要求だけを記録し（[command の形](command.md) の「複数の集約と、後続の処理」）、この手順が別のトランザクションで要求を回収して処理する。要求を記録する側と回収する側は、一つの Outbox の両端である。

# どのパターンでも守ること

値は値オブジェクトで組み立てる。DB へのアクセスは、手順が所有するリポジトリ相当の口に置き、usecase は SQL も DB のドライバも知らない。手順は usecase に置き、トランザクションの境界も手順の一部として usecase が持つ。

外部との通信を挟む手順では、さらに三つを守る。**外部への通信は、トランザクションの外で行う。** 一つのトランザクションに外部との通信を含めない。**処理は冪等にする。** 同じ要求が繰り返し届いても、結果が一つになるようにする。**進捗は、一件ごとのトランザクションで確定させる。** 途中で止まっても、確定した分をやり直さない。

# 例：延滞の通知の発行

```go
// PublishOverdueNotices は、延滞の通知の要求を一件ずつ回収し、送り、記録する。
type PublishOverdueNotices struct {
	tx        tx.Manager
	requests  OverdueNoticeRequests // 手順が所有する口
	publisher NoticePublisher       // 手順が所有する外部の副作用の口
	logger    *slog.Logger          // 飲み込む失敗を記録する
	relay     contract.RelayID
	batch     contract.BatchSize
}

// claimTxOptions は、物理設計の「分離性判断: 通知の要求の回収」の指定である。READ COMMITTED で、やり直さない。
var claimTxOptions = tx.Options{Isolation: tx.ReadCommitted}

// recordTxOptions は、物理設計の制約「成功と失敗はどちらか一つ」を確かめて書くトランザクションの指定である。
// 見本の物理設計は分離レベルを書いていないので、ここでは READ COMMITTED を仮置きし、物理設計へ返している。
var recordTxOptions = tx.Options{Isolation: tx.ReadCommitted}

func (u *PublishOverdueNotices) Execute(ctx context.Context) error {
	var candidates []contract.ClaimCandidate
	err := u.tx.Run(ctx, claimTxOptions, func(ctx context.Context) error {
		var err error
		candidates, err = u.requests.ListClaimable(ctx, u.batch)
		return err
	})
	if err != nil {
		return err
	}
	for _, c := range candidates {
		err := u.publishOne(ctx, c)
		if err == nil {
			continue
		}
		handling, handlingFound := errors.HandlingOf(err)
		level, levelFound := log.Level(err)
		if !handlingFound || !levelFound || handling.Spreads {
			return err
		}
		// 一件に閉じた失敗は飲み込むので、ここで一度だけ記録する。
		u.logger.LogAttrs(ctx, level, "延滞の通知の一件を送れなかったため次へ進む",
			slog.String("request_id", c.RequestID().Value()),
			slog.Bool("reprocessable", handling.Reprocessable),
			slog.Any("err", err),
		)
	}
	return nil
}

// publishOne は、一件を回収し、送り、送ったことを記録する。回収と記録はそれぞれのトランザクションで確定させ、送るのはその間の外で行う。
func (u *PublishOverdueNotices) publishOne(ctx context.Context, c contract.ClaimCandidate) error {
	var claim contract.Claim
	var claimed bool
	err := u.tx.Run(ctx, claimTxOptions, func(ctx context.Context) error {
		var err error
		claim, claimed, err = u.requests.Claim(ctx, u.relay, c)
		return err
	})
	if err != nil || !claimed {
		return err // claimed が false なら、回収の回数が上限に達し、口が打ち切りを記録した
	}
	if err := u.publisher.Publish(ctx, claim.RequestID(), claim.Notice()); err != nil {
		return u.recordFailed(ctx, claim, err)
	}
	return u.tx.Run(ctx, recordTxOptions, func(ctx context.Context) error {
		return u.requests.RecordSucceeded(ctx, claim)
	})
}

// recordFailed は、再処理しても通らない失敗だけを失敗として記録する。再処理で通りうる失敗は記録せず、リースが切れた後の回収に任せる。
// どちらの場合も元の失敗を返し、呼び手が一件に閉じて記録する。
func (u *PublishOverdueNotices) recordFailed(ctx context.Context, claim contract.Claim, cause error) error {
	handling, found := errors.HandlingOf(cause)
	if !found || handling.Spreads || handling.Reprocessable {
		return cause
	}
	if err := u.tx.Run(ctx, recordTxOptions, func(ctx context.Context) error {
		return u.requests.RecordFailed(ctx, claim, contract.FailureReasonOf(cause))
	}); err != nil {
		return err
	}
	return cause
}
```

候補を選ぶのは一つのトランザクションで、一件ごとの回収、送ったことの記録、失敗の記録は、それぞれ別のトランザクションで確定させる。外部への発行は、どのトランザクションの外でも行う。同時の回収の衝突は、口が「同時更新で競合した」を返し、処理の表で一件に閉じた失敗として次の候補へ進む。回収の回数の上限は、口の `Claim` が判断する（implement-repository の単純なパターンの口）。手順は、上限の数を知らない。

# 失敗の扱い

一件の失敗で残りを続けるか打ち切るかは、handle-errors の処理の表の「全体に及ぶか」で決める。全体に及ぶ失敗（依存先が利用できない、時間切れ）は、残りを試さずに返す。一件に閉じた失敗は、次の一件へ進む。

一件に閉じた失敗をどう終えるかは、処理の表の「再処理で通りうるか」で、技術的な処理のライフサイクル（W1 の資料）の二つの終わり方のどちらかへ写す。再処理で通りうるなら一時失敗として何も記録せず、リースが切れた後に再び回収される。通らないなら恒久失敗として、失敗を記録し、以後回収されないようにする。作業待ちの行を、記録せずに黙って除かない。

一件に閉じた失敗を飲み込むので、それは手順の中で記録する（write-logs の「飲み込むなら記録する」）。手順は、そのために logger を注入される。

# 冪等

外部への発行の口には、要求の識別子を冪等の鍵として渡し、受け手が重複を捨てる。発行に成功した後で記録に失敗すると、要求は再び回収されて、もう一度発行されるからである。受け手が冪等を約束できない外部なら、実装で補わずに、資料の持ち主へ返す。

# 分岐してよいもの

手順が分岐してよいのは、技術的な処理の段階と、要求が運んできた閉じた列挙値と、処理の表だけである。閾値や可否のような業務の判断は、発生元の集約のコマンドで確定させ、要求に載せて運ぶ。手順の中で業務の判断が要ると分かったら、書かずに apply-layer-convention と資料へ返す。

再試行のループは書かない。一時失敗の後に同じ要求をもう一度処理するのは、リースが切れた後の回収である。トランザクションの中のやり直しは、物理設計の指定でトランザクションの管理が行う。
