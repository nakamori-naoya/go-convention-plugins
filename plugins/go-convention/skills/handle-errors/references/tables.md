# 境界の表

境界は、エラーから分類を取り出し、分類をキーにした表で扱いを決める。この規約が持つ表は二つで、応答の表と処理の表である。三つ目のログレベルの表は、write-logs が持つ。

三つの表は、別々の関心なので別々に持つ。応答は呼び手に何を返すか、処理は次に何をするか、ログレベルは運用者に何を求めるかである。一つの割り当てから別のものを導くと（「WARN の分類は再試行する」のように）、片方を変えたときにもう一方が黙って変わる。

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

func codeOf(err error) connect.Code {
	code, ok := codeTable[errors.Category(err)]
	if !ok {
		return codeTable[errors.ErrUnclassified]
	}
	return code
}
```

表に無い分類に当たったときは、「分類不能」として扱う。網羅はテストで確かめるので、この経路に来るのは表の更新漏れだけである。

表は、最も外の interceptor の package に一つだけ置く。handler の本文と、要求と応答の変換関数では、`connect.NewError` を作らない。内側で `connect.Error` が作られていたら、境界はそれを「分類不能」として扱う。

# 処理の表

分類ごとに、二つの性質を決める。

**再試行で通りうるか**は、同じ操作をもう一度行えば通る見込みがあるかである。ワーカーは、これで再試行するかを決める。技術処理のライフサイクルが定める二つの終わり方（一時失敗と恒久失敗）のどちらで終えるかも、これで決める。「はい」なら一時失敗、「いいえ」なら恒久失敗である。ライフサイクルの型そのものは、データモデルの資料が決める。

**全体に及ぶか**は、その失敗が一件に閉じず、同じ処理の残りの件も同じ理由で失敗するかである。巡回や一件ずつの発行のように複数件を順に処理する場面で、「いいえ」なら記録して次の一件へ進み、「はい」なら残りを試さずに打ち切って返す。依存先が落ちているときに全件を試し続けて、同じ失敗を件数分出さないためである。

| 分類 | 再試行で通りうる | 全体に及ぶ |
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

処理の表は、横断的関心事の package に二つの関数（`errors.Retryable(err) bool`、`errors.Spreads(err) bool`）として置き、ワーカーと手順の境界が呼ぶ。実装のコードが呼ぶものだけを公開する。

# 網羅のテスト

二つの表が15の分類を過不足なく持つことは、テストで確かめる。テストの側に、15の分類と期待の値を並べた表を持ち、公開の関数（`codeOf` を使う境界の翻訳、`Retryable`、`Spreads`）を通して一つずつ確かめる。実装の側に、分類の一覧を返す入口を足さない。

```go
func TestRetryable(t *testing.T) {
	tests := []struct {
		id       string
		name     string
		category errors.Base
		want     bool
	}{
		{id: "retryable-conflict", name: "同時更新で競合した失敗は再試行で通りうる", category: errors.ErrConflict, want: true},
		// 15の分類をすべて並べる
	}
	for _, tt := range tests {
		t.Run(tt.id+" "+tt.name, func(t *testing.T) {
			assert.Equal(t, tt.want, errors.Retryable(errors.Wrap(tt.category, "テスト")))
		})
	}
}
```

分類は増やさないので、期待の表が15行で固定される。表の行が欠けると、欠けた分類は「分類不能」として扱われ、期待と食い違ってテストが落ちる。テストの形は apply-go-test-convention に従う。
