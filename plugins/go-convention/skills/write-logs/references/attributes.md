# 属性と秘匿

# メッセージ

メッセージは、何が起きたかを書く定型の一文で、値を埋め込まない。値は属性に出す。メッセージが定型なら、同じ出来事をメッセージで数えられる。数えるために別のキーを足さない。

日本語で、句点を付けず、「〜した」「〜できなかったため次へ進む」のように、出来事と取った行動を書く。エラーの文言をメッセージに写さない。エラーは属性で出る。

```go
logger.LogAttrs(ctx, slog.LevelInfo, "延滞の通知の発行を終えた",
	slog.Int("candidates", len(candidates)),
	slog.Int("published", published),
)
```

# 属性の語彙

キーは英語の snake_case にする。同じ意味に二つのキーを作らない。新しいキーが要るときは、プロジェクトの語彙の表に足してから使う。

語彙の中心は、どのプロジェクトでも同じになる。リクエストの識別子（`request_id`）、手続きの名前（`procedure`）、所要時間のミリ秒（`duration_ms`）、応答の Code（`code`）、翻訳前のエラー（`err`）、分類不能の印（`unclassified`）、panic の値と stack（`panic`、`stack_trace`）、ワーカーの名前（`worker`）、件数（`candidates` など）である。業務の識別子（`loan_id`、`user_no`）は、プロジェクトの語彙に足す。

属性は型付きの helper（`slog.String`、`slog.Int`、`slog.Int64`、`slog.Bool`、`slog.Time`、`slog.Any`）で渡す。キーと値を交互に並べる形は、数がずれても動いてしまう。`slog.Any` に渡すのは、`err` と `panic` だけにする。単位はキーに書き、値と一致させる（`duration_ms` に `slog.Duration` を渡さない）。時刻は UTC の `slog.Time` で渡す。`slog.Group` で入れ子にせず、属性は平らに出す。平らなら検索も平らで済む。

同じ属性を複数の行に付けるなら、`logger.With` で子の logger を作る。子の logger も引数で渡し、ctx に入れない。

# 値オブジェクトは、記録する行で取り出す

ログの属性は、外部の形式への写しである。DB の生成型や proto への写しと同じく、変換の内側でプリミティブへ戻してよい。値オブジェクトは、記録する行で値を取り出して渡す。

```go
// row は DB の生成型の行である。値オブジェクトへ復元できなかったので、保存された値のまま出す。
logger.LogAttrs(ctx, slog.LevelError, "保存値の壊れた貸出を一覧から除いた",
	slog.String("loan_id", row.LoanID),
	slog.Any("err", err),
)

// 値オブジェクトからは、名前のある取り出しの関数で値を取る。
logger.LogAttrs(ctx, slog.LevelInfo, "貸出を延滞にした", slog.String("loan_id", loan.ID().Value()))
```

何を出して何を伏せるかは、その行で決める。型の側に記録の形を持たせると、何が出るかが記録する行から見えなくなるからである。値オブジェクトが何を実装し、何を実装しないかは、implement-domain-model が決める。ドメインは `log/slog` を import しない。

出してよいのは、業務の識別子、件数、時刻、Code である。個人を識別する値（メール、電話、氏名）、トークン、認証のヘッダ、接続文字列は出さない。迷ったら「問い合わせの対応で他人に見せて困るか」で決め、困るなら業務の識別子で追跡する。値を取り出す関数が値オブジェクトに無いなら、それは出さない値である。ログのために取り出す関数を足したくなったら、運用に要る値かをドメインの持ち主へ問う。

# 秘匿の安全網

logger を作るときに、JSON の handler を使い、`HandlerOptions.ReplaceAttr` で秘密のキーの値を伏せる。JSON の handler は、非公開のフィールドを出さない。安全網は、記録する行での判断を誤ったときの被害を「出ない」側に倒すためのもので、安全網があるから渡してよい、にはならない。

```go
// secretPhrases は、キーを小文字にし区切りを除いた形にこの語を含むなら、値を伏せる一覧である。
// 例: "access_token"、"clientSecret"、"database_url"。
var secretPhrases = []string{
	"password", "token", "secret", "credential", "authorization", "cookie", "session",
	"apikey", "privatekey", "mail", "phone", "databaseurl",
}

func redact(_ []string, a slog.Attr) slog.Attr {
	if isSecretKey(a.Key) {
		return slog.String(a.Key, "[REDACTED]")
	}
	return a
}
```

伏せるのはキーで決め、値の中身を走査しない。中身の走査は、誤った検出と見逃しの両方を生む。部分一致だと業務のキーを巻き込む語（`auth` は `author` に含まれる）は、区切りで分けた語の一致で判定する。秘密のキーを足したら、そのキーが伏せられることを確かめるテストを一つ足す。

安全網が働いた行（`[REDACTED]` が出た行）は、記録する行の判断を誤った印である。見つけたら、書いた側を直す。

ログの基盤が解釈するキー（重大度、時刻、メッセージのキーの名前）へ合わせる置き換えも、同じ `ReplaceAttr` で行う。どのキーにするかは、プロジェクトのログの基盤で決まる。
