# interceptor

interceptor の列は、外から順に、記録、認証、認可、頻度の制限である。並べ方は、組み立ての関数（`NewMux`）の一か所で決め、本番とテストが同じ関数を呼ぶ。

# 記録（最も外）

最も外の interceptor が、リクエストの識別子を ctx に載せ、panic を回収し、RPC 一回につき一行を記録し、返ったエラーを応答へ翻訳する。応答の Code は handle-errors の応答の表から、ログのレベルは write-logs のレベルの表から決める。表に分類が無いときは、分類不能として扱い、`unclassified` の属性を付ける。応答の文言は、分類の package が返す公開してよい文言だけにする。内側で `connect.Error` が作られていたら、分類不能として扱う。

翻訳と記録を一つの interceptor に置くのは、同じエラーから Code とレベルを一度に決めるためである。panic の回収も、ここ一か所に置く。

# 認証

認証の interceptor は、要求の認証情報（Authorization のヘッダ）から主体を確かめ、ctx に載せる。主体を確かめられなければ、「認証されていない」を土台にしたエラーを返し、内側を呼ばない。

トークンの検証は、制御できない外部の境界のポート（`TokenVerifier`）に任せる。認証の interceptor は、そのポートを使う側で、ポートを所有する。テストでは、このポートだけを gomock で差し替える（apply-go-test-convention）。

# 認可

認可の interceptor は、手続き（Procedure）ごとの方針の表で、主体を、このサービスの操作の主体（登録済みの利用者など）へ一度だけ解決し、ctx に載せる。

```go
// policies は、手続きごとに求める主体である。例: "/lending.v1.LoanService/BorrowBook" は登録済みの利用者。
var policies = map[string]policy{
	loanv1connect.LoanServiceBorrowBookProcedure: requireRegisteredUser,
	loanv1connect.LoanServiceReturnBookProcedure: requireRegisteredUser,
}
```

表に無い手続きは、拒む。新しい RPC を足して表に書き忘れると、拒まれるので気付ける。handler の本文は、`RequireActor(ctx)` で解決済みの主体を受け取るだけにする。usecase とリポジトリに、「登録済みか」「本人か」を解決するメソッドを置かない。

認可の方針の表は、RPC の手続きに依存するので、API のプロセスの内側に置く。ワーカーと共有する横断的関心事には置かない。

# 頻度の制限

入口が課す時間当たりの回数の上限は、頻度の制限の interceptor が守り、超えたら「利用上限に達した」を土台にしたエラーを返す。業務知識が定める数量の上限（貸出の冊数）は、ここではなく集約のコマンドが守る。どの入口に頻度の制限を置くかは、資料（品質要求）が決める。

# Connect を通らない入口

ヘルスチェックのように Connect を通らない HTTP の入口は、interceptor の列の外に置き、同じ役割（記録と翻訳）の HTTP の middleware を一つ置く。
