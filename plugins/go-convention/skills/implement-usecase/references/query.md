# query の形

query の usecase は、読み取りのポートを呼び、読み取りモデルを返す。集約を復元せず、書き込まず、トランザクションを張らない。

読み取りのポートと読み取りモデルは、`usecase/query` の package が所有する（apply-go-package-layout）。ポートの実装は、implement-query-service が書く。読み取りモデルも、業務の概念を値オブジェクトで持つ。

```go
// ListOverdueCandidates は、確かめた時点で返却期限を過ぎた、貸出中の貸出を返す。
type ListOverdueCandidates struct {
	loans OverdueCandidateReader
}

func (u *ListOverdueCandidates) Execute(ctx context.Context, at domain.CheckedAt) ([]domain.LoanID, error) {
	return u.loans.ListOverdueCandidates(ctx, at)
}
```

入力は値オブジェクトで受ける。入力から、どの読み取りのポートを呼ぶかを選ぶ（進行中なら現在の表、終わったなら履歴）のは usecase の関心で、SQL、並び、集計は実装の関心である。

command の usecase は、query の usecase も読み取りのポートも呼ばない。一覧を選んで一件ずつ command を呼ぶのは、入口（巡回、implement-handler）の仕事である。
