# sentinel と文言

**資料の「拒む理由」1 行につき `errors.New` 1 つ。変数名は `Err{何が拒まれたか}`、文言は日本語で「何が拒まれたか」、行末コメントに資料の語。** 拒む理由は資料で閉じた集合なので、sentinel も閉じた集合になる。呼ぶ側は `errors.Is` で判定し、テストは `require.ErrorIs` で突き合わせる。文言を読んで分岐する箇所は作らない。

## 1. 資料のどこから sentinel が生まれるか

domain-model 資料の 3 か所を読む。どれも「拒まれる」ことが資料に書いてある場所で、資料に無い拒否を sentinel にしない。

| 資料の場所 | 生まれる sentinel | 返す場所 |
|---|---|---|
| 各操作の「拒む理由」 | 操作の事前条件が成り立たない拒否（`ErrHoldDeadlinePassed` / `ErrNotOwner` / `ErrSlotAlreadyStarted`） | 状態型のメソッド（`Tentative.Confirm` など） |
| 「生成の条件」 | 生成に渡された値が条件を満たさない拒否（`ErrCustomerSuspended` / `ErrEligibilityMismatch`、値オブジェクトの `ErrIDRequired` / `ErrTimeSlotNotOrdered`） | 生成関数（`Hold` / `NewID` など） |
| 「状態と型の分割」の「できない操作」 | 違う状態の予約に操作を求めた拒否（`ErrAlreadyConfirmed` / `ErrAlreadyCancelled` / `ErrAlreadyExpired`） | 絞り込み関数（`AsTentative` / `AsActive`）。状態型のメソッドは自分の状態しか知らないので、状態違いはここでだけ起きる |
| 「集約の境界」の「集約をまたぐ不変条件」 | 集約の内側では確かめられない拒否（`ErrOverlappingSlot`） | 生成を呼ぶ側（usecase が現在有効な予約を見て返す）と、DB 制約の翻訳（リポジトリが排他制約違反を写して返す）。集約自身は返さない |

同じ根拠が複数の操作に現れるなら sentinel は 1 つである。資料は「他人の予約の確定」と「他人の予約または予約待ちの取消」を別の操作の拒む理由として挙げるが、業務上の根拠は「予約者本人の意思を第三者が変えようとしている」の 1 つなので `ErrNotOwner` 1 つにする。逆に、根拠が違えば文言が似ていても分けない理由は無い（`ErrAlreadyCancelled` と `ErrAlreadyExpired` は資料が「人の取消と区別して残す」と言っている）。

「見つからない」「別の操作で更新された」は資料の拒む理由に無い。これらは永続化の都合なので、ドメインではなくリポジトリ package の sentinel にする（[translation.md](translation.md) §3）。「和型に nil が渡された」も資料に無い。これは Go の型の都合で、絞り込み関数の `default` が返す `ErrNoReservation` として値オブジェクトの sentinel と同じブロックに置く（§2）。

## 2. 形

`reservation/errors.go`:

```go
package reservation

import "errors"

// 資料「拒むときの理由」「状態と型の分割」と 1:1。
var (
	ErrOverlappingSlot     = errors.New("重なる利用枠には仮押さえできない")       // 重なる利用枠の仮押さえ（集約の外で守る。生成を呼ぶ側と DB 制約の翻訳が返す）
	ErrCustomerSuspended   = errors.New("仮押さえ停止中の顧客は新しい申込みができない") // 仮押さえ停止中顧客による新しい申込み
	ErrEligibilityMismatch = errors.New("予約資格の顧客が予約者と一致しない")      // 生成の条件「資格の顧客が予約者と同じ」
	ErrHoldDeadlinePassed  = errors.New("仮押さえ期限以降は確定できない")        // 仮押さえ期限以降の確定
	ErrAlreadyConfirmed    = errors.New("確定済みの予約は再確定できない")        // 確定済み予約の再確定
	ErrNotOwner            = errors.New("他人の予約は操作できない")           // 他人の予約の確定／他人の予約の取消
	ErrSlotAlreadyStarted  = errors.New("利用開始以降の予約は取り消せない")       // 利用開始以降の予約取消
	ErrAlreadyCancelled    = errors.New("取消済みの予約は操作できない")         // 状態と型の分割「取消済み予約: できる操作なし」
	ErrAlreadyExpired      = errors.New("期限切れの予約は操作できない")         // 状態と型の分割「期限切れ予約: できる操作なし」
)

// 資料の「拒むときの理由」には無いが Go の型の都合で要る sentinel。
// 値オブジェクトの生成の条件（「揃わない組は存在しない」）と、和型に nil が渡されたとき。
var (
	ErrIDRequired         = errors.New("予約番号が空の予約は作れない")          // 値オブジェクト「予約番号」の生成の条件
	ErrCustomerIDRequired = errors.New("予約者が空の予約は作れない")           // 値オブジェクト「予約者」の生成の条件
	ErrRoomCodeRequired   = errors.New("会議室が空の利用枠は作れない")          // 値オブジェクト「会議室」の生成の条件
	ErrTimeSlotNotOrdered = errors.New("利用終了が利用開始より後でない利用枠は作れない") // 値オブジェクト「利用枠」の生成の条件
	ErrVersionNotPositive = errors.New("1 未満の版は作れない")             // 値オブジェクト「版」（資料に無い。イベント型の永続化に要る）
	ErrNoReservation      = errors.New("予約が無い値は絞り込めない")           // 和型が nil。絞り込み関数の default
)
```

| 規則 | 内容 | 理由 |
|---|---|---|
| 生成 | `errors.New` だけ。`fmt.Errorf` で作らない。構造体を作らない | 比較可能な 1 つの値であることが `errors.Is` の前提。文脈は呼ぶ側が包んで足す |
| 変数名 | `Err` + 何が拒まれたか（`ErrHoldDeadlinePassed`）。`ErrInvalid` / `ErrFailed` / `ErrConfirm` のような「操作名」「一般語」にしない | 名前だけで「どの拒む理由か」が資料と突き合わせられる |
| 置き場 | 集約と同じ package の `errors.go` に `var (...)` を 2 つ。資料の「拒むときの理由」と 1:1 のブロックと、資料に無い Go の都合（値オブジェクトの生成の条件・和型の nil）のブロック | 資料と 1:1 の集合が 1 画面で照合でき、資料に無い sentinel がそこに紛れない |
| 行末コメント | 資料の語（操作名か「拒む理由」の文言）をそのまま書く。資料に無いブロックは「どの型の生成の条件か」 | 資料が変わったとき、どの sentinel を直すかがコメントで決まる |
| 順序 | 資料の操作の順（生成 → 確定 → 取消 → ...）。資料に無いブロックは後ろ | 資料を上から読む順と一致する |

## 3. 文言

文言は**日本語**で、**句点なし・改行なし**、**「何が拒まれたか／何ができなかったか」**を書く。包んだときに次のように読める形にする。

```
予約 R-0101 の確定: 仮押さえ期限以降は確定できない
予約 R-0101 の確定: 予約 R-0101 の取得: 対象が見つからない
予約 R-0102 の仮押さえの保存: 重なる利用枠には仮押さえできない
```

| 規則 | 書く | 書かない | 理由 |
|---|---|---|---|
| 主語と述語 | `仮押さえ期限以降は確定できない` | `期限切れ` / `Deadline passed` | 何が拒まれたかが読める。名詞 1 語は包んだときに意味が消える |
| 「失敗」だけの文言 | `対象が見つからない` / `トランザクションの外ではリポジトリを呼べない` | `失敗しました` / `エラーが発生しました` / `処理できません` | 何ができなかったかを書かない文言は、連鎖のどこにあっても情報を足さない |
| 句点・改行 | 末尾に何も付けない | `〜できない。` / 2 行の文言 | `: ` で連ねたときに文の途中に句点が現れる。1 行のログに収まらない |
| 敬体 | 常体（`できない`） | `できません` | 利用者への表示文はこの文言ではなく、境界が別に選ぶ（[translation.md](translation.md) §5） |
| 業務 ID | 包む側が文脈として足す（`予約 %s の確定: %w`） | sentinel の文言に ID を埋め込む | sentinel は値なので、ID を持てない。持たせると `errors.New` でなくなる |
| 個人情報 | 業務 ID（予約番号・顧客番号・会議室コード）だけ | 氏名・メール・電話・住所・外部サービスの利用者 ID・トークン | エラーはログに出る。ログに出してはいけないものはエラーにも入れない |
| 技術語 | 業務の語で書く | `nil` / `SQLSTATE` / 型名 | 読み手は運用者と利用者。技術的な原因は包まれた外部エラーが運ぶ |

リポジトリ層の sentinel も同じ規則で書く。`rdb.ErrNotFound = errors.New("対象が見つからない")`（`rdb` は複数の集約のリポジトリを持つので集約名を入れない）、`rdb.ErrConflict = errors.New("対象が別の操作で更新された")`（同じく集約名を入れない）。

## 4. 拒まないが何も変えない操作は error ではない

事前条件が成り立たないとき、資料が「拒む理由: なし（〜でなければ何も変えない）」と書く操作は、error ではなく `(Result, bool)` で返す。`Tentative.Expire` と `Confirmed.RecordNoShow` がこれにあたる。

```go
// 資料「期限到来を反映する」: 拒む理由なし（到来していなければ何も変えない）
func (t Tentative) Expire(at time.Time) (ExpireResult, bool) {
	if !t.deadline.HasArrived(at) {
		return ExpireResult{}, false
	}
	at = at.UTC()
	v := t.version.Next()
	return ExpireResult{
		Next:  Expired{core: t.core.withVersion(v)},
		Event: ExpiredEvent{base: base{reservationID: t.id, version: v, occurredAt: at}, slot: t.slot},
	}, true
}
```

| 資料の書き方 | 返す形 | 呼ぶ側の読み方 |
|---|---|---|
| 拒む理由: 〜 | `(Result, error)`。sentinel を返す | 「求めたことが拒まれた」。呼ぶ側は止まるか、境界へ返す |
| 拒む理由: なし（〜でなければ何も変えない） | `(Result, bool)`。`false` を返す | 「今は何も起きなかった」。呼ぶ側はそのまま先へ進む（期限を掃く worker が `false` の予約を飛ばす） |

`false` を sentinel にすると、期限が来ていない仮押さえを掃く worker が毎回 error を受け取り、境界がそれを「拒否」として記録してしまう。何も起きなかったことは失敗ではない。

## 5. 集約の外で守る不変条件

「同じ会議室の重なる利用枠へ現在有効な予約は一つ」は予約の内側では確かめられない（資料「集約の境界」）。`ErrOverlappingSlot` は集約と同じ package に置くが、集約の操作は返さない。返すのは 2 か所である。

| 返す場所 | いつ | 何を見て |
|---|---|---|
| 生成を呼ぶ側（usecase） | `reservation.Hold` を呼ぶ前 | 同じ会議室の現在有効な予約を読み取りポートから取り、`TimeSlot.Overlaps` が真なら `ErrOverlappingSlot` を返して `Hold` を呼ばない |
| DB 制約の翻訳（リポジトリ） | `ApplyHeld` で `room_booking_claims` に INSERT したとき | 排他制約違反（`23P01`）を `ErrOverlappingSlot` へ写す（[translation.md](translation.md) §3）。二人が同時に呼んで一方だけ通す保証はここが担う |

同じ sentinel を 2 か所が返すので、呼ぶ側と境界の対応表は `ErrOverlappingSlot` 1 つだけを見ればよい。「事前に確かめたときの拒否」と「同時に起きたときの拒否」を別の sentinel にすると、利用者から見て同じ結果に 2 つの名前が付く。

## 6. sentinel で足りないとき: 操作専用の型付きエラー

sentinel は「何が拒まれたか」だけを運ぶ。**呼ぶ側が次の判断に使う値**（いつまで停止か、どの予約が塞いでいるか）が要るときだけ、その操作専用の型付きエラーを 1 つ作る。作るのは例外で、作ったら次を守る。

```go
// SuspendedError は「仮押さえ停止中顧客による新しい申込み」を拒んだとき、停止の終了時刻を運ぶ。
// Hold 専用。他の操作で使い回さない。
type SuspendedError struct {
	Until time.Time
}

func (e *SuspendedError) Error() string { return ErrCustomerSuspended.Error() }

// Is により errors.Is(err, ErrCustomerSuspended) が真になる。翻訳表とテストは sentinel のまま。
func (e *SuspendedError) Is(target error) bool { return target == ErrCustomerSuspended }
```

| 規則 | 理由 |
|---|---|
| sentinel を置き換えない。`Is` メソッドで sentinel に答える | 対応表・テスト・usecase の判定が `errors.Is(err, ErrCustomerSuspended)` のまま変わらない。型を知るのは値を読む呼び手だけ |
| 1 操作専用。フィールドはその操作の呼び手が読む値だけ | 型の名前と中身が「どの操作で何を返すか」を語る |
| `RejectionError{Reason string}` / `DomainError{Kind, Message}` のような汎用型を作らない | 汎用型は「今回はどの Reason にするか」という分類の判断を毎回作り、文言や文字列定数で分岐する入口になる。sentinel は資料の行そのもので、判断が要らない |
| 値を読むのは `errors.AsType[*SuspendedError](err)` で、読む呼び手 1 か所 | 型付きエラーを読む場所が増えるなら、それは値ではなく sentinel で足りる拒否を型にしている |

## 7. テストとの関係

sentinel は `require.ErrorIs(t, err, reservation.ErrHoldDeadlinePassed)` で判定でき、文言では判定しない。テストの表の `wantErr error` にそのまま置ける形が、この規約の sentinel である。テストの書き方そのものはテストの形の共通規則が決める。
