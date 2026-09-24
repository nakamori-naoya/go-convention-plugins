# 手順の形（単純なパターン）

単純なパターンの usecase は、手順として、リポジトリ相当の口を順に呼ぶ。集約や状態の型は作らない。これは戦術的 DDD の例外ではなく、並ぶ二つ目の形である。どの処理をこの形で書くかは、apply-layer-convention が決める。

# どのパターンでも守ること

値は値オブジェクトで組み立てる。DB へのアクセスは、手順が所有するリポジトリ相当の口に置き、usecase は SQL も DB のドライバも知らない。手順は usecase に置き、トランザクションの境界も手順の一部として usecase が持つ。

外部との通信を挟む手順では、さらに三つを守る。**外部への通信は、トランザクションの外で行う。** 一つのトランザクションに外部との通信を含めない。**処理は冪等にする。** 同じ要求が繰り返し届いても、結果が一つになるようにする。**進捗は、一件ごとのトランザクションで確定させる。** 途中で止まっても、確定した分をやり直さない。

# 例：延滞の通知の発行

```go
// PublishOverdueNotices は、延滞の通知の要求を回収し、一件ずつ送って記録する。
type PublishOverdueNotices struct {
	tx        tx.Manager
	requests  OverdueNoticeRequests // 手順が所有する口
	publisher NoticePublisher       // 手順が所有する外部の副作用の口
	relay     contract.RelayID
	batch     contract.BatchSize
}

func (u *PublishOverdueNotices) Execute(ctx context.Context) error {
	var claimed []contract.OverdueNoticeRequest
	err := u.tx.Run(ctx, tx.Options{}, func(ctx context.Context) error {
		var err error
		claimed, err = u.requests.Claim(ctx, u.relay, u.batch)
		return err
	})
	if err != nil {
		return err
	}
	for _, req := range claimed {
		err := u.publishOne(ctx, req)
		if err == nil {
			continue
		}
		handling, found := errors.HandlingOf(err)
		if !found || handling.Spreads {
			return err
		}
		if !handling.Reprocessable {
			if err := u.recordFailed(ctx, req, err); err != nil {
				return err
			}
		}
	}
	return nil
}

func (u *PublishOverdueNotices) publishOne(ctx context.Context, req contract.OverdueNoticeRequest) error {
	if err := u.publisher.Publish(ctx, req.ID(), req); err != nil {
		return err
	}
	return u.tx.Run(ctx, tx.Options{}, func(ctx context.Context) error {
		return u.requests.RecordSucceeded(ctx, req.ID())
	})
}
```

回収は一つのトランザクションで確定させ、外部への発行はその外で行い、送ったことは一件ごとに別のトランザクションで確定させる。

# 失敗の扱い

一件の失敗で残りを続けるか打ち切るかは、handle-errors の処理の表の「全体に及ぶか」で決める。全体に及ぶ失敗（依存先が利用できない、時間切れ）は、残りを試さずに返す。一件に閉じた失敗は、次の一件へ進む。

一件に閉じた失敗をどう終えるかは、処理の表の「再処理で通りうるか」で、技術的な処理のライフサイクル（W1 の資料）の二つの終わり方のどちらかへ写す。再処理で通りうるなら一時失敗として何も記録せず、リースが切れた後に再び回収される。通らないなら恒久失敗として、失敗を記録し、以後回収されないようにする。作業待ちの行を、記録せずに黙って除かない。

一件に閉じた失敗を飲み込むので、それは手順の中で記録する（write-logs の「飲み込むなら記録する」）。手順は、そのために logger を注入される。

# 冪等

外部への発行の口には、要求の識別子を冪等の鍵として渡し、受け手が重複を捨てる。発行に成功した後で記録に失敗すると、要求は再び回収されて、もう一度発行されるからである。受け手が冪等を約束できない外部なら、実装で補わずに、資料の持ち主へ返す。

# 分岐してよいもの

手順が分岐してよいのは、技術的な処理の段階と、要求が運んできた閉じた列挙値と、処理の表だけである。閾値や可否のような業務の判断は、発生元の集約のコマンドで確定させ、要求に載せて運ぶ。手順の中で業務の判断が要ると分かったら、書かずに apply-layer-convention と資料へ返す。

再試行のループは書かない。一時失敗の後に同じ要求をもう一度処理するのは、リースが切れた後の回収である。トランザクションの中のやり直しは、物理設計の指定でトランザクションの管理が行う。
