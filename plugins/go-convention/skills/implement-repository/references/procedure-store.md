# 単純なパターンの口

単純なパターン（トランザクションスクリプト）の手順も、DB へのアクセスはリポジトリ相当の口に置く。どの処理を単純なパターンで書くかは、apply-layer-convention が決める。口の interface は、手順（`{procedure}/usecase`）が所有し、ここで実装する。

# 形

口のメソッドは、手順が一度に確定させる一つの記録に一つである。延滞の通知の発行なら、回収する（`Claim`）、送った（`RecordSucceeded`）、打ち切った（`RecordFailed`）の三つになる。

口は、戦術的 DDD のリポジトリと同じく、ctx のトランザクションを必須とし、自分では張らない。張るかどうかを口ごとに変えると、「どこで確定したか」を手順から読めなくなる。トランザクションを張り、外部との通信をその外に置くのは、手順（usecase）である。

口は、読み取りの口を呼ばない。書き込みの判断に要る読み取り（回収できる要求を探す）は、同じメソッドの中で、自分の SQL として行う。その SQL は、物理設計の読み取りの台帳（Read-003 のような）に載っているものに限る。

口は、業務の判断をしない。技術的な処理の段階（回収済みか、リースが切れたか）で読む行を選ぶことだけを行う。

時刻（回収した時点、送った時点）は、口が Clock から一度だけ取る。記録の行の識別子は、口が採番器から取る。

# 同時に回収したとき

二つの送り手が同じ要求を同時に回収すると、同じ版の回収の一意制約（`request_id, version`）が、後の一方を拒む。口は、その違反を翻訳表で「同時更新で競合した」へ写して返す。手順は、それを一件に閉じた失敗として扱い、次の候補へ進む（handle-errors の処理の表）。物理設計が `FOR UPDATE SKIP LOCKED` を指定したときだけ、候補の読み取りにそれを付ける。

# 成功と失敗はどちらか一つ

物理設計が「成功と失敗はどちらか一つ」を、書く前に他方が無いことを同じトランザクションで確かめる形で決めているなら、口はそのとおりに確かめ、他方が先にあれば書かずに終える。確かめ方を実装の側で変えない。

# 例

```go
// OverdueNoticeRequests は、延滞の通知の要求の回収と完了を記録する。
type OverdueNoticeRequests struct {
	clock clock.Clock
	ids   idgen.Generator
}

// Claim は、回収できる要求を古い順に最大 limit 件選び、それぞれに次の版の回収を記録する。
func (s *OverdueNoticeRequests) Claim(ctx context.Context, relay contract.RelayID, limit contract.BatchSize) ([]contract.OverdueNoticeRequest, error) {
	q, err := s.queries(ctx)
	if err != nil {
		return nil, err
	}
	now := s.clock.Now()
	rows, err := q.ListClaimableOverdueNoticeRequests(ctx, sqlcgen.ListClaimableOverdueNoticeRequestsParams{
		LeaseExpiredBefore: now.Add(-claimLease),
		Limit:              limit.Int32(),
	})
	if err != nil {
		return nil, rdb.Translate(ctx, err, nil)
	}
	claimed := make([]contract.OverdueNoticeRequest, 0, len(rows))
	for _, row := range rows {
		if err := q.InsertOverdueNoticeClaimedEvent(ctx, claimedParams(s.ids.NewID(), row, now)); err != nil {
			return nil, rdb.Translate(ctx, err, claimConstraints)
		}
		req, err := claimableRowToRequest(row)
		if err != nil {
			return nil, err
		}
		claimed = append(claimed, req)
	}
	return claimed, nil
}
```

リースの長さ（`claimLease`）と、打ち切るまでの回収の回数は、データモデルの資料が決めた値を名前のある定数にする。資料が仮置きした値なら、その仮置きをコメントに書く。
