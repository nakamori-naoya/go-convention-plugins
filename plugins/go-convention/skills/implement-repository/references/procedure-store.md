# 単純なパターンの口

単純なパターン（トランザクションスクリプト）の手順も、DB へのアクセスはリポジトリ相当の口に置く。その代表が Outbox である。発生元の `Apply` が同じトランザクションで要求を一行追加し、別の手順がそれを回収して外へ送り、成功か失敗を記録する。この文書の口は、その Outbox の回収と完了の記録を担う。どの処理を単純なパターンで書くかは、apply-layer-convention が決める。口の interface は、手順（`{procedure}/usecase`）が所有し、ここで実装する。

# 形

口のメソッドは、手順が一度に確定させる一つの記録に一つである。延滞の通知の発行なら、回収できる要求を選ぶ（`ListClaimable`）、一件を回収する（`Claim`）、送った（`RecordSucceeded`）、打ち切った（`RecordFailed`）の四つになる。

口は、戦術的 DDD のリポジトリと同じく、ctx のトランザクションを必須とし、自分では張らない。張るかどうかを口ごとに変えると、「どこで確定したか」を手順から読めなくなる。トランザクションを張り、外部との通信をその外に置くのは、手順（usecase）である。

口は、読み取りの口を呼ばない。書き込みの判断に要る読み取り（回収できる要求を探す）は、口のメソッドの中で、自分の SQL として行う。その SQL は、物理設計の読み取りの台帳（Read-003 のような）に載っているものに限る。

口は、判断をしない。技術的な処理の段階（回収済みか、リースが切れたか）で読む行を選び、頼まれた記録を書くことだけを行う。回収の回数が上限に達したかの比較は、手順（usecase）が行う。

時刻（回収した時点、送った時点）は、口が Clock から一度だけ取る。記録の行の識別子は、口が採番器から取る。

# 一件ずつ回収する

回収は、一件ごとに別のトランザクションで確定させる。図書館の物理設計は、同時の回収を `request_id, version` の一意制約で守り、後の一方は次の候補へ進む、と決めている。PostgreSQL では、一意制約に違反したトランザクションはその場で中断するので、複数の回収を一つのトランザクションに入れると、一件の衝突で残りの回収もできなくなる。

口は、一意制約の違反を翻訳表で「同時更新で競合した」へ写して返す。手順は、それを一件に閉じた失敗として扱い、次の候補へ進む（handle-errors の処理の表）。物理設計が候補の読み取りに `FOR UPDATE SKIP LOCKED` を足したときだけ、`ListClaimable` の SQL にそれを付ける。

# 回収の回数の上限

回収の回数が、データモデルの資料の決めた上限に達した要求は、回収せずに失敗として記録し、以後の候補から外す。上限との比較は手順が行い、候補が運ぶ次の回収の版が上限を超えていれば、`Claim` を呼ばずに `RecordFailed` を呼ぶ。口は、比較の結果を受けて記録するだけである。上限が無いと、送れない要求が無限に回収され続ける。

# 成功と失敗はどちらか一つ

図書館の物理設計は、成功と失敗の記録を次の形で守ると決めている。分離レベルは READ COMMITTED で、書く前に要求の行（`overdue_notice_requested_events`）を `SELECT … FOR UPDATE` でロックし、同じトランザクションの中で、もう一方の表にその要求が無いことを確かめてから書く。やり直しはしない。口の `RecordSucceeded` と `RecordFailed` は、この順で SQL を呼び、他方が先にあれば書かずに終える。確かめ方を実装の側で変えない。

`RecordFailed` は要求を受け取り、失敗の行が指す回収（打ち切った回収）には、その要求の最新の回収を自分の SQL で読んで使う。送れなかった直後なら、それは今回の回収であり、上限で打ち切るなら、最後にリースが切れた回収である。

# 例

```go
// OverdueNoticeRequests は、延滞の通知の要求の回収と完了を記録する。
type OverdueNoticeRequests struct {
	clock clock.Clock
	ids   idgen.Generator
}

// ListClaimable は、回収できる要求を古い順に最大 limit 件選ぶ。物理設計の Read-003。
func (s *OverdueNoticeRequests) ListClaimable(ctx context.Context, limit contract.BatchSize) ([]contract.ClaimCandidate, error) {
	q, err := s.queries(ctx)
	if err != nil {
		return nil, err
	}
	rows, err := q.ListClaimableOverdueNoticeRequests(ctx, sqlcgen.ListClaimableOverdueNoticeRequestsParams{
		LeaseExpiredBefore: s.clock.Now().Add(-claimLease),
		Limit:              limit.Int32(),
	})
	if err != nil {
		return nil, rdb.Translate(ctx, err, nil)
	}
	candidates := make([]contract.ClaimCandidate, 0, len(rows))
	for _, row := range rows {
		c, err := claimableRowToCandidate(row)
		if err != nil {
			return nil, err
		}
		candidates = append(candidates, c)
	}
	return candidates, nil
}

// Claim は、候補の次の版の回収を記録する。上限との比較はしない。
func (s *OverdueNoticeRequests) Claim(ctx context.Context, relay contract.RelayID, c contract.ClaimCandidate) (contract.Claim, error) {
	q, err := s.queries(ctx)
	if err != nil {
		return contract.Claim{}, err
	}
	claimID := s.ids.NewID()
	if err := q.InsertOverdueNoticeClaimedEvent(ctx, claimedParams(claimID, c, s.clock.Now())); err != nil {
		// 同じ版の回収が先にあれば、同時更新で競合した、になる。
		return contract.Claim{}, rdb.Translate(ctx, err, claimConstraints)
	}
	return contract.NewClaim(claimID, c, relay), nil
}

// RecordSucceeded は、送ったことを記録する。要求の行をロックし、失敗が先にあれば書かずに終える。
func (s *OverdueNoticeRequests) RecordSucceeded(ctx context.Context, claim contract.Claim) error {
	q, err := s.queries(ctx)
	if err != nil {
		return err
	}
	req := rdb.IDColumn(claim.RequestID())
	// 物理設計の「成功と失敗はどちらか一つ」。要求の行を SELECT … FOR UPDATE でロックしてから確かめる。
	if err := q.LockOverdueNoticeRequest(ctx, req); err != nil {
		return rdb.Translate(ctx, err, nil)
	}
	failed, err := q.ExistsOverdueNoticeFailedEvent(ctx, req)
	if err != nil {
		return rdb.Translate(ctx, err, nil)
	}
	if failed {
		return nil
	}
	if err := q.InsertOverdueNoticeSucceededEvent(ctx, succeededParams(claim, s.clock.Now())); err != nil {
		return rdb.Translate(ctx, err, claimConstraints)
	}
	return nil
}

// RecordFailed は、要求を打ち切った失敗を記録する。要求の行をロックし、成功が先にあれば書かずに終える。
func (s *OverdueNoticeRequests) RecordFailed(ctx context.Context, req contract.RequestID, reason contract.FailureReason) error {
	q, err := s.queries(ctx)
	if err != nil {
		return err
	}
	// 物理設計の「成功と失敗はどちらか一つ」。要求の行を SELECT … FOR UPDATE でロックしてから確かめる。
	if err := q.LockOverdueNoticeRequest(ctx, rdb.IDColumn(req)); err != nil {
		return rdb.Translate(ctx, err, nil)
	}
	succeeded, err := q.ExistsOverdueNoticeSucceededEvent(ctx, rdb.IDColumn(req))
	if err != nil {
		return rdb.Translate(ctx, err, nil)
	}
	if succeeded {
		return nil
	}
	if err := q.InsertOverdueNoticeFailedEventForLatestClaim(ctx, failedParams(req, reason, s.clock.Now())); err != nil {
		return rdb.Translate(ctx, err, claimConstraints)
	}
	return nil
}
```

`LockOverdueNoticeRequest` は、物理設計のとおり `SELECT … FOR UPDATE` で要求の行を押さえる SQL である。二つの記録が同時に走っても、後の一方はロックを待ち、先の記録を見てから書かずに終える。

リースの長さ（`claimLease`）は、データモデルの資料が決めた値を名前のある定数にする。打ち切るまでの回収の回数は、比較する手順の側に同じ形で置く。資料が仮置きした値なら、その仮置きをコメントに書く。
