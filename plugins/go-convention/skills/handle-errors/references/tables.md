# 境界の表

境界は、エラーから分類を取り出し、分類をキーにした表で扱いを決める。この規約が持つ表は二つで、応答の表と処理の表である。三つ目のログレベルの表は、write-logs が持つ。

三つの表は、別々の関心なので別々に持つ。応答は呼び手に何を返すか、処理は次に何をするか、ログレベルは運用者に何を求めるかである。一つの割り当てから別のものを導くと（「WARN の分類は再処理する」のように）、片方を変えたときにもう一方が黙って変わる。

# 応答の表

分類から、Connect の Code を決める。go-convention の既定である。

| 分類 | Connect の Code |
|---|---|
| 入力が不正 | InvalidArgument |
| 認証されていない | Unauthenticated |
| 許可されていない | PermissionDenied |
| 存在しない | NotFound |
| すでに存在する | AlreadyExists |
| 業務ルールに反する | FailedPrecondition |
| 利用上限に達した | ResourceExhausted |
| 未対応の操作 | Unimplemented |
| 中断された | Canceled |
| 同時更新で競合した | Aborted |
| 容量の上限を超えた | ResourceExhausted |
| 時間切れ | DeadlineExceeded |
| 依存先が利用できない | Unavailable |
| 回復不能 | Internal |
| 分類不能 | Internal |

応答の文言は、分類の package の `Message` が返すものだけにする。回復不能と分類不能は固定の文言だけを返し、内部の文言（外部のライブラリの文言、付け替えで残した元の文言）を応答に出さない。

```go
// codeTable は、分類ごとに呼び手へ返す Code である。
var codeTable = map[error]connect.Code{
	errors.ErrInvalidInput: connect.CodeInvalidArgument,
	// 残りの14行
}

// Code は、エラーの分類の Code を返す。表に分類が無ければ false を返す。
func Code(err error) (connect.Code, bool) {
	code, ok := codeTable[errors.Category(err)]
	return code, ok
}
```

# 表に無い分類

表を引く関数は、表に分類が無いことを `false` で呼び手に返し、既定の値へ丸めない。write-go-code の「未知の値を丸めない（`map` を引けなかったら error を返す）」と同じ規則である。

表に無いことを受け取った境界は、それを表の更新漏れ、つまり実装の間違いとして扱う。応答は「分類不能」の Code と固定の文言にし、記録には `unclassified` の属性を付けて ERROR で残す。黙って既定の値で続けるのではなく、実装の間違いとして人に知らせる扱いなので、丸めにはならない。境界はエラーを受け取る最後の場所で、ここで error を返しても受け取る相手がいないので、この扱いを境界の中で閉じる。処理の表とログレベルの表も同じ形にする。

網羅はテストで確かめるので、本番でこの経路に来るのは、表の更新が漏れたときだけである。

表は、表を引く関数を公開する一つの package に置き、境界（interceptor）がそれを呼ぶ。handler の本文と、要求と応答の変換関数では、`connect.NewError` を作らない。内側で `connect.Error` が作られていたら、境界はそれを「分類不能」として扱う。

# 処理の表

分類ごとに、二つの性質を決める。

**再処理で通りうるか**は、同じ要求をもう一度処理すれば通る見込みがあるかである。ワーカーと受信境界は、これで要求をもう一度処理させるか（再処理）を決める。物理設計の「再試行」（一つのトランザクションの中でのやり直し）とは別のことで、語を分けている。トランザクションの中でやり直すかと、その回数は、物理設計が操作ごとに決め、usecase がその指定をトランザクションの管理へ渡す。この表は、その回数を決めない。技術処理のライフサイクルが定める二つの終わり方（一時失敗と恒久失敗）のどちらで終えるかも、これで決める。「はい」なら一時失敗、「いいえ」なら恒久失敗である。ライフサイクルの型そのものは、データモデルの資料が決める。

**全体に及ぶか**は、その失敗が一件に閉じず、同じ処理の残りの件も同じ理由で失敗するかである。巡回や一件ずつの発行のように複数件を順に処理する場面で、「いいえ」なら記録して次の一件へ進み、「はい」なら残りを試さずに打ち切って返す。依存先が落ちているときに全件を試し続けて、同じ失敗を件数分出さないためである。

| 分類 | 再処理で通りうる | 全体に及ぶ |
|---|---|---|
| 入力が不正 | いいえ | いいえ |
| 認証されていない | いいえ | いいえ |
| 許可されていない | いいえ | いいえ |
| 存在しない | いいえ | いいえ |
| すでに存在する | いいえ | いいえ |
| 業務ルールに反する | いいえ | いいえ |
| 利用上限に達した | はい | いいえ |
| 未対応の操作 | いいえ | いいえ |
| 中断された | いいえ | はい |
| 同時更新で競合した | はい | いいえ |
| 容量の上限を超えた | はい | はい |
| 時間切れ | はい | はい |
| 依存先が利用できない | はい | はい |
| 回復不能 | いいえ | いいえ |
| 分類不能 | いいえ | いいえ |

「回復不能」が「全体に及ぶ」でないのは、データの破損のように一件に閉じる場合が多いからである。設定の不備のように全体に及ぶ回復不能は、起動の時点でプロセスの境界が止める。

処理の表は、分類の package に一つの関数として置き、ワーカーと手順の境界が呼ぶ。

```go
// Handling は、失敗を処理する側が次に何をするかを決める二つの性質である。
type Handling struct {
	Reprocessable bool // 同じ要求をもう一度処理すれば通る見込みがある
	Spreads   bool // 同じ処理の残りの件も同じ理由で失敗する
}

// HandlingOf は、エラーの分類の Handling を返す。表に分類が無ければ false を返す。
func HandlingOf(err error) (Handling, bool)
```

# 網羅のテスト

三つの表が15の分類を過不足なく持つことは、テストで確かめる。テストの側に、15の分類と期待の値を並べた表を持ち、表を引く公開の関数（`Code`、`HandlingOf`、write-logs の `Level`）を通して一つずつ確かめる。確かめるのは、分類ごとに `true` が返ることと、期待の値である。実装の側に、分類の一覧を返す入口を足さない。

```go
func TestHandlingOf(t *testing.T) {
	tests := []struct {
		id       string
		name     string
		category errors.Base
		want     errors.Handling
	}{
		{id: "handling-conflict", name: "同時更新で競合した失敗は再処理で通りうるが一件に閉じる", category: errors.ErrConflict, want: errors.Handling{Reprocessable: true, Spreads: false}},
		// 15の分類をすべて並べる
	}
	for _, tt := range tests {
		t.Run(tt.id+" "+tt.name, func(t *testing.T) {
			got, ok := errors.HandlingOf(errors.Define(tt.category, "テスト"))
			require.True(t, ok)
			assert.Equal(t, tt.want, got)
		})
	}
}
```

分類は増やさないので、期待の表が15行で固定される。表のどの行が欠けても、その分類で `false` が返ってテストが落ちる。欠けた行の値が既定のどれかと偶然同じでも、見逃さない。テストの形は apply-go-test-convention に従う。
