# テーブルの形

ドメインのテストの Given は、初期状態の型と `Restore*` と `New*` に渡す値、When はコマンドの引数、Then は `Next` の値と `Event` の値と具体エラーである。ドメインのテストは資源を持たないので、Given はすべてデータで書け、`setup` も操作列も要らない。テストの形の共通の規則（識別、表、ループ本体）は apply-go-test-convention に従う。

# 例：`TestPendingLoan_Borrow`

```go
package domain_test

// BDD の資料: docs/lending/業務知識.md

func TestPendingLoan_Borrow(t *testing.T) {
	t.Parallel()

	user := vobuilders.NewUserNoBuilder().Build(t)
	book := vobuilders.NewBookNoBuilder().Build(t)
	loanID := domainbuilders.NewLoanIDBuilder().Build(t)
	lentAt := domain.NewLentAt(time.Date(2026, 10, 1, 10, 0, 0, 0, time.UTC))

	// lent は、発したイベントの射影である。値だけを取り出しの関数で並べて比べる。
	type lent struct {
		loanID  domain.LoanID
		version domain.Version
		lentAt  domain.LentAt
	}

	tests := []struct {
		id          string
		name        string
		description string
		standing    domain.Standing // Given: 借りる瞬間の貸出状況
		wantNext    domain.OnLoan   // Then
		wantEvent   lent            // Then
		wantErr     error           // Then: nil なら受ける
	}{
		{
			id:   "BDD-001",
			name: "延滞の無い利用者が本を借りると貸出中の貸出が生まれる",
			description: `Given: 利用者番号 U-0001 の利用者は本を1冊も借りておらず、延滞の貸出も無い
  And: 資料番号 B-1001 の本はどの貸出にも属していない
When: 利用者 U-0001 が2026年10月1日に本 B-1001 を借りる
Then: 利用者 U-0001 と本 B-1001 の貸出が貸出中で生まれる
  And: 貸出日は2026年10月1日、返却期限は2026年10月15日である`,
			standing:  domain.NewStanding(domainbuilders.NewLentCountBuilder().WithValue(0).Build(t), false),
			wantNext:  domain.RestoreOnLoan(loanID, user, book, lentAt, domain.DueFrom(lentAt), domain.FirstVersion),
			wantEvent: lent{loanID: loanID, version: domain.FirstVersion, lentAt: lentAt},
		},
		{
			id:   "BDD-003",
			name: "5冊借りている利用者は6冊目を借りられない",
			description: `…資料の gherkin をそのまま…`,
			standing: domain.NewStanding(domainbuilders.NewLentCountBuilder().WithValue(5).Build(t), false),
			wantErr:  domain.ErrLoanLimitReached,
		},
		{
			id:   "a71c3e",
			name: "延滞があり上限にも達している利用者は延滞の理由で拒まれる",
			description: `Given: 利用者は延滞の貸出を持ち、借りている冊数は5冊である
When: 利用者が本を借りる
Then: 延滞の貸出がある利用者が本を借りるとして拒まれる`,
			standing: domain.NewStanding(domainbuilders.NewLentCountBuilder().WithValue(5).Build(t), true),
			wantErr:  domain.ErrUserHasOverdue,
		},
	}
	for _, tt := range tests {
		t.Run(tt.id+" "+tt.name, func(t *testing.T) {
			t.Parallel()

			pending := domain.NewPendingLoan(user, book, tt.standing)

			got, err := pending.Borrow(loanID, lentAt)
			if tt.wantErr != nil {
				require.ErrorIs(t, err, tt.wantErr)
				assert.Zero(t, got)
				return
			}
			require.NoError(t, err)
			assert.Equal(t, tt.wantNext, got.Next)
			assert.Equal(t, tt.wantEvent, lent{loanID: got.Event.LoanID(), version: got.Event.Version(), lentAt: got.Event.LentAt()})
		})
	}
}
```

# Given

Given のフィールドは、初期状態の型の生成関数の引数、または `Restore*` の引数のうち、資料の `Given:` に写るものである。資料の `Given:` に現れない引数（識別子、版）は、表の前で Builder から一度だけ作り、全ケースで同じ値を使う。表を縦に読んで差分が分かるのは、資料が言及する値だけが変わるときだからである。

テストの対象（ここでは `PendingLoan.Borrow`）が受け取る値は、`New*` と `Restore*` で直接組む。対象の外側にある値オブジェクト（利用者番号、資料番号）は、Builder で作る（apply-go-test-convention のテストデータの規則）。

# When

When は、コマンドの引数名そのままのフィールドにする。表の全ケースで同じ値なら、表の前で一度作ってループ本体で渡す（上の例の `loanID` と `lentAt`）。業務の時刻は、時点の値オブジェクトで渡す。

# Then

受ける場合は、`wantNext` に次の状態の型を `Restore*` で Given と同じ値から組み、版だけを進める。`wantEvent` は、イベントの取り出しの関数の値を並べた射影の struct で、版は `wantNext` の版と同じにする。この二つで、「識別子や返却期限を引き継ぎ、版だけが進む」ことを確かめる。

拒む場合は、`wantErr` に資料の拒む理由の具体エラーを入れ、`require.ErrorIs` の後に `assert.Zero(t, got)` で結果がゼロ値であることを見る。

拒まないコマンド（`(Result, bool)`）は、`wantOK` を足し、`false` のときに結果がゼロ値であることを見る。

イベントの型は、テストで確かめない。`<コマンド名>Result` の `Event` の型が、コンパイルで決めている。

# 状態ごとのテスト関数

和型のコマンドは、状態の型ごとにテスト関数を置く。受けない状態のテストは、Given の `Restore*` とコマンドの呼び出しと `wantErr` だけの短い表になる。

```go
func TestReturnedLoan_Return(t *testing.T) {
	// …表の前は同じ…
	tests := []struct {
		id          string
		name        string
		description string
		wantErr     error
	}{
		{
			id:   "BDD-009",
			name: "返却済みの貸出の本は返せない",
			description: `…資料の gherkin をそのまま…`,
			wantErr: domain.ErrAlreadyReturned,
		},
	}
	for _, tt := range tests {
		t.Run(tt.id+" "+tt.name, func(t *testing.T) {
			t.Parallel()

			returned := domain.RestoreReturnedLoan(loanID, user, book, lentAt, domain.DueFrom(lentAt), v2)

			got, err := returned.Return()
			require.ErrorIs(t, err, tt.wantErr)
			assert.Zero(t, got)
		})
	}
}
```

# 並列

ドメインのテストは共有する資源を持たないので、`t.Parallel()` をテスト関数の先頭とサブテストの先頭の両方に置く。
