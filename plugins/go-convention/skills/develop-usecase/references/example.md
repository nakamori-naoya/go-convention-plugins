# 例：図書館の貸出の usecase

図書館の貸出の資料を写した usecase と、そのテストの組み立てである。写すのは形で、名前、指定、上限の値は対象の資料から取る。

## command：本を借りる

```go
// BorrowBook は、利用者が本を借りる。
type BorrowBook struct {
	tx       tx.Manager
	loans    domain.LoanRepository
	ids      idgen.Generator
	calendar domain.LibraryCalendar
}

type BorrowBookInput struct {
	User   vo.UserNo
	Book   vo.BookNo
	LentAt domain.LentAt
}

type BorrowBookOutput struct {
	Loan domain.LoanID
	Due  domain.Due
}

func (u *BorrowBook) Execute(ctx context.Context, in BorrowBookInput) (BorrowBookOutput, error) {
	loanID := domain.NewLoanIDFromUUID(u.ids.NewID()) // トランザクションの外で採番する
	var out BorrowBookOutput
	err := u.tx.Run(ctx, borrowTxOptions, func(ctx context.Context) error {
		pending, err := u.loans.FindPendingLoan(ctx, in.User, in.Book)
		if err != nil {
			return err
		}
		res, err := pending.Borrow(loanID, in.LentAt, u.calendar)
		if err != nil {
			return err
		}
		if err := u.loans.ApplyLent(ctx, res.Event); err != nil {
			return err
		}
		out = BorrowBookOutput{Loan: res.Event.LoanID(), Due: res.Event.Due()}
		return nil
	})
	if err != nil {
		return BorrowBookOutput{}, err
	}
	return out, nil
}
```

本を返す command は、`FindLoan` で和型の `Loan` を得て `Return` を呼び、`ApplyReturned` に渡すだけで、返却済みかどうかを調べない。拒むのは返却済みの型の `Return` である。

## 手順：延滞の通知の発行

```go
// PublishOverdueNotices は、延滞の通知の要求を一件ずつ回収し、送り、記録する。
type PublishOverdueNotices struct {
	tx        tx.Manager
	requests  OverdueNoticeRequests // 手順が所有する口
	publisher NoticePublisher       // 手順が所有する外部の副作用の口
	logger    *slog.Logger
	relay     contract.RelayID
	batch     contract.BatchSize
}

func (u *PublishOverdueNotices) Execute(ctx context.Context) error {
	var candidates []contract.ClaimCandidate
	if err := u.tx.Run(ctx, claimTxOptions, func(ctx context.Context) error {
		var err error
		candidates, err = u.requests.ListClaimable(ctx, u.batch)
		return err
	}); err != nil {
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
			return err // 表の更新漏れか、全体に及ぶ失敗。残りを試さずに返す
		}
		if !handling.Reprocessable {
			level = slog.LevelError // 人が直すまで、リースが切れるたびに回収し直される
		}
		u.logger.LogAttrs(ctx, level, "延滞の通知の一件を送れなかったため、リースが切れた後の回収に任せて次へ進む",
			slog.String("request_id", c.RequestID().Value()),
			slog.Bool("reprocessable", handling.Reprocessable),
			slog.Any("err", err),
		)
	}
	return nil
}

// publishOne は、回収と記録をそれぞれのトランザクションで確定させ、送るのはその間の外で行う。
// 送れなかった要求は記録せずに残し、リースが切れた後の回収に任せる。
// コマンドデータモデルに打ち切りの表が無いので、この手順は打ち切らない。
func (u *PublishOverdueNotices) publishOne(ctx context.Context, c contract.ClaimCandidate) error {
	var claim contract.Claim
	if err := u.tx.Run(ctx, claimTxOptions, func(ctx context.Context) error {
		var err error
		claim, err = u.requests.Claim(ctx, u.relay, c)
		return err
	}); err != nil {
		return err
	}
	if err := u.publisher.Publish(ctx, claim.RequestID(), claim.Notice()); err != nil {
		return err
	}
	return u.tx.Run(ctx, recordTxOptions, func(ctx context.Context) error {
		return u.requests.RecordSucceeded(ctx, claim)
	})
}
```

## テストの組み立て

```go
ctrl := gomock.NewController(t)
clk := mock_clock.NewMockClock(ctrl)
clk.EXPECT().Now().Return(returnedAt).AnyTimes() // リポジトリが記録の時刻を取るときだけ要る
ids := mock_idgen.NewMockGenerator(ctrl)
ids.EXPECT().NewID().Return(eventID).AnyTimes()

loans := repository.NewLoanRepository(clk, ids)
sut := command.NewReturnBook(tx.NewPostgresManager(suite.Database.Client(), slog.New(slog.DiscardHandler)), loans)
```

