# 単純なパターンの口

単純なパターン（トランザクションスクリプト）の手順も、DB へのアクセスはリポジトリ相当の口に置く。その代表が Outbox である。発生元の `Apply` が同じトランザクションで要求を一行追加し、別の手順がそれを回収して外へ送り、成功か失敗を記録する。この文書の口は、その Outbox の回収と完了の記録を担う。どの処理を単純なパターンで書くかは、apply-layer-convention が決める。口の interface は、手順（`{procedure}/usecase`）が所有し、ここで実装する。

# 形

口のメソッドは、手順が一度に確定させる一つの記録に一つである。延滞の通知の発行なら、回収できる要求を選ぶ（`ListClaimable`）、一件を回収する（`Claim`）、送った（`RecordSucceeded`）、打ち切った（`RecordFailed`）の四つになる。

口は、戦術的 DDD のリポジトリと同じく、ctx のトランザクションを必須とし、自分では張らない。張るかどうかを口ごとに変えると、「どこで確定したか」を手順から読めなくなる。トランザクションを張り、外部との通信をその外に置くのは、手順（usecase）である。

口は、読み取りの口を呼ばない。書き込みの判断に要る読み取り（回収できる要求を探す）は、口のメソッドの中で、自分の SQL として行う。その SQL は、物理設計の読み取りの台帳（Read-003 のような）に載っているものに限る。

口は、業務の判断をしない。技術的な処理の段階（回収済みか、リースが切れたか、回収の回数が上限に達したか）で、読む行と書く記録を選ぶことだけを行う。

時刻（回収した時点、送った時点）は、口が Clock から一度だけ取る。記録の行の識別子は、口が採番器から取る。

# 一件ずつ回収する

回収は、一件ごとに別のトランザクションで確定させる。図書館の物理設計は、同時の回収を `request_id, version` の一意制約で守り、後の一方は次の候補へ進む、と決めている。PostgreSQL では、一意制約に違反したトランザクションはその場で中断するので、複数の回収を一つのトランザクションに入れると、一件の衝突で残りの回収もできなくなる。

口は、一意制約の違反を翻訳表で「同時更新で競合した」へ写して返す。手順は、それを一件に閉じた失敗として扱い、次の候補へ進む（handle-errors の処理の表）。物理設計が候補の読み取りに `FOR UPDATE SKIP LOCKED` を足したときだけ、`ListClaimable` の SQL にそれを付ける。

# 回収の回数の上限

回収の回数が、データモデルの資料の決めた上限に達した要求は、回収せずに失敗として記録し、以後の候補から外す。これを決めるのは口の `Claim` で、候補が運ぶ次の回収の版が上限を超えていれば、最後の回収を指して失敗を記録し、回収しなかったことを返す。上限を手順に置かないのは、それが技術的な処理の段階で、要求の行から口が決められるからである。上限が無いと、送れない要求が無限に回収され続ける。

# 成功と失敗はどちらか一つ

物理設計が「成功と失敗はどちらか一つ」を、書く前に他方が無いことを同じトランザクションで確かめる形で決めているなら、口はそのとおりに確かめ、他方が先にあれば書かずに終える。確かめ方を実装の側で変えない。

# 例

```go
// OverdueNoticeRequests は、延滞の通知の要求の回収と完了を記録する。
type OverdueNoticeRequests struct {
	clock clock.Clock
	ids   idgen.Generator
}

// maxClaims は、打ち切るまでの回収の回数である。データモデルの資料の仮置き（5回。仮説）。
const maxClaims = 5

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

// Claim は、候補の次の版の回収を記録する。回収の回数が上限を超えるなら、回収せずに失敗を記録し、false を返す。
func (s *OverdueNoticeRequests) Claim(ctx context.Context, relay contract.RelayID, c contract.ClaimCandidate) (contract.Claim, bool, error) {
	q, err := s.queries(ctx)
	if err != nil {
		return contract.Claim{}, false, err
	}
	now := s.clock.Now()
	if c.NextVersion().Int64() > maxClaims {
		if err := q.InsertOverdueNoticeFailedEvent(ctx, exhaustedParams(c, now)); err != nil {
			return contract.Claim{}, false, rdb.Translate(ctx, err, claimConstraints)
		}
		return contract.Claim{}, false, nil
	}
	claimID := s.ids.NewID()
	if err := q.InsertOverdueNoticeClaimedEvent(ctx, claimedParams(claimID, c, now)); err != nil {
		// 同じ版の回収が先にあれば、同時更新で競合した、になる。
		return contract.Claim{}, false, rdb.Translate(ctx, err, claimConstraints)
	}
	return contract.NewClaim(claimID, c, relay), true, nil
}
```

リースの長さ（`claimLease`）と、打ち切るまでの回収の回数（`maxClaims`）は、データモデルの資料が決めた値を名前のある定数にする。資料が仮置きした値なら、その仮置きをコメントに書く。
