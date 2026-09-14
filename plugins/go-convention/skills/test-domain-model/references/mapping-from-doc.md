# 資料からの割り振り

**domain-model 資料の「BDDとの対応」表（BDD → 要素 × 操作）が、その BDD をどのテスト関数に置くかを決める。** 表の要素が package と型を、操作がメソッドを指すので、テスト関数名は機械的に決まる。テストの書き手は置き場を選ばない。表に無い置き場を選んだら、それは表を直す話であってテストの話ではない。

## 1. 要素 × 操作 → テスト関数

| 表の行 | 実装での形 | テスト関数 | 題材 |
|---|---|---|---|
| 集約 × 生成の操作 | 生成関数 `Hold(...)` | `Test{生成関数}` | BDD-001 / 010 / 012 → `TestHold` |
| 集約 × 許される遷移（「状態と型の分割」の「できる操作」） | 状態型のメソッド `(Tentative) Confirm` | `Test{状態型}_{メソッド}` | BDD-002 → `TestTentative_Confirm` |
| 集約 × できない操作（「状態と型の分割」の「できない操作」。確定済みの再確定） | 絞り込み関数 `AsTentative` が sentinel を返す | `TestAs{状態}` | BDD-023 → `TestAsTentative` |
| 集約 × 拒まない操作（拒む理由が「なし」） | `(Result, bool)` を返すメソッド | `Test{状態型}_{メソッド}` | BDD-005 → `TestTentative_Expire` |
| VO × 判定・計算の操作 | VO のメソッド | `Test{VO}_{メソッド}` | BDD-013 / 014 → `TestTimeSlot_Overlaps`、BDD-015 → `TestHoldDeadline_HasArrived`、BDD-009 / 011 → `TestEligibility_CanApply` |
| VO × 生成の条件 | `New*`（表に BDD が無いことが多い） | `TestNew{VO}` | `TestNewTimeSlot`（生成した id だけ） |

同じ操作が状態型ごとにある（`Tentative.Cancel` と `Confirmed.Cancel`）なら、型が違うのでテスト関数も分かれる。表の「主な事前状態」が仮押さえ予約なら `TestTentative_Cancel`、確定予約なら `TestConfirmed_Cancel`。

## 2. 表の行がそのままテスト関数にならないとき

| 行の形 | する | 題材 |
|---|---|---|
| 1 BDD が 2 操作を挙げる（`BDD-021、BDD-022 / 繰り上げる／取り消す`） | 資料の並び順で 1 つずつ割る。1 番目の BDD に 1 番目の操作 | BDD-021 → 繰り上げる、BDD-022 → 取り消す |
| 要素が別の集約（この package に無い） | 書かない。末尾コメントに「別の集約 X の package が対象」 | 予約待ちの BDD-006 / 007 / 008 / 018 / 019 / 021 / 022 は `reservation` には無い |
| 成立を決める条件が集約の外の判断（繰上げ判断の並び順） | 操作自体の BDD はその集約の package に置き、判断の部分は末尾コメントで usecase へ | BDD-019 の「W-102 だけが繰り上がる」は繰上げ判断 |
| 資料が「同時に起きたとき」に置いた BDD | 書かない。末尾コメントに「メモリ上で再現できない。永続化層が対象」 | BDD-004 |
| 表が VO の判定に置いた BDD で、gherkin の `Then:` が集約の結果（確定予約は成立しない）まで書いている | `id` は表どおり VO のテストに置き、`When:` の時刻を判定の引数、`Then:` の結論を真偽に写す。集約側の結果は、同じ時刻を使った生成 id のケースを状態型のメソッドのテストに足す | BDD-015 → `TestHoldDeadline_HasArrived`（`at` = 09:15、`want: true`）。`TestTentative_Confirm` に「期限と同時刻の確定は拒まれる」を生成 id で |
| 表が生成に置いた BDD で、gherkin の `Given:` / `Then:` に永続化の観測（別の予約は成立しない、利用枠が空く）がある | `description` を削らず、その行は永続化層が観測すると報告に書く | BDD-001 の「別の予約は成立しない」 |

## 3. 題材の割り振り表

資料「ドメインモデル — 貸会議室の予約」の「BDDとの対応」表を、package `reservation` のテストへ割り振った結果。この表を作ってからケースを書く。

| BDD | 要素 × 操作（資料） | `reservation` のテスト関数 | 末尾コメント（テストしない理由） |
|---|---|---|---|
| BDD-001 | 予約 × 仮押さえ予約を成立させる | `TestHold` | — |
| BDD-002 | 予約 × 確定する | `TestTentative_Confirm` | — |
| BDD-003 | 予約 × 取り消す（確定予約） | `TestConfirmed_Cancel` | — |
| BDD-004 | 予約 × 仮押さえ予約を成立させる（同時） | — | 二人の同時仮押さえは集約をまたぐ排他で、メモリ上の値では再現できない。永続化層が対象 |
| BDD-005 | 予約 × 期限到来を反映する | `TestTentative_Expire` | — |
| BDD-006 | 予約待ち × 登録する | — | 別の集約（予約待ち）の package が対象 |
| BDD-007 | 予約待ち × 繰り上げる | — | 別の集約（予約待ち）の package が対象。後半の仮押さえ成立は繰上げ判断（usecase）の責務 |
| BDD-008 | 予約待ち × 取り消す | — | 別の集約（予約待ち）の package が対象 |
| BDD-009 | 顧客の予約資格 × 新しい申込みができるか | `TestEligibility_CanApply` | — |
| BDD-010 | 予約 × 仮押さえ予約を成立させる | `TestHold` | — |
| BDD-011 | 顧客の予約資格 × 新しい申込みができるか | `TestEligibility_CanApply` | — |
| BDD-012 | 予約 × 仮押さえ予約を成立させる | `TestHold` | — |
| BDD-013 | 利用枠 × 重なるか | `TestTimeSlot_Overlaps` | — |
| BDD-014 | 利用枠 × 重なるか | `TestTimeSlot_Overlaps` | — |
| BDD-015 | 仮押さえ期限 × 到来したか | `TestHoldDeadline_HasArrived` | — |
| BDD-016 | 予約 × 取り消す（確定予約、別の予約者） | `TestConfirmed_Cancel` | — |
| BDD-017 | 予約 × 取り消す（確定予約、利用開始と同時刻） | `TestConfirmed_Cancel` | — |
| BDD-018 | 予約待ち × 登録する | — | 別の集約（予約待ち）の package が対象 |
| BDD-019 | 予約待ち × 繰り上げる | — | 繰上げ順は繰上げ判断（usecase）の責務。繰り上げる操作は別の集約（予約待ち）の package が対象 |
| BDD-020 | 予約 × 取り消す（仮押さえ停止中の確定予約） | `TestConfirmed_Cancel` | — |
| BDD-021 | 予約待ち × 繰り上げる（取消が先） | — | 別の集約（予約待ち）の package が対象 |
| BDD-022 | 予約待ち × 取り消す（繰上げが先） | — | 別の集約（予約待ち）の package が対象 |
| BDD-023 | 予約 × 確定する（確定予約は確定を呼べない） | `TestAsTentative` | — |
| BDD-024 | 予約 × 取り消す（仮押さえ予約） | `TestTentative_Cancel` | — |

この表から、`reservation` のテスト関数と各関数が持つ資料の ID は次のとおり。

| テスト関数 | 資料の ID | 資料に無いケースで埋めるもの |
|---|---|---|
| `TestHold` | BDD-001 / 010 / 012 | 資格の顧客が予約者と違う（`ErrEligibilityMismatch`） |
| `TestTentative_Confirm` | BDD-002 | 期限と同時刻（`ErrHoldDeadlinePassed`）、他人（`ErrNotOwner`）、期限以降かつ他人は期限の理由が先 |
| `TestTentative_Cancel` | BDD-024 | 利用開始と同時刻（`ErrSlotAlreadyStarted`）、他人（`ErrNotOwner`） |
| `TestConfirmed_Cancel` | BDD-003 / 016 / 017 / 020 | — |
| `TestTentative_Expire` | BDD-005 | 期限前は `false` |
| `TestConfirmed_RecordNoShow` | —（資料の BDD-009 は資格の側に置かれている） | 利用開始 15 分後ちょうどは `false`、16 分後は `true`、記録済みは `false` |
| `TestAsTentative` | BDD-023 | 仮押さえ予約はそのまま、取消済み（`ErrAlreadyCancelled`）、期限切れ（`ErrAlreadyExpired`）、`nil`（`ErrNoReservation`） |
| `TestAsActive` | — | 仮押さえ・確定はそのまま、取消済み、期限切れ、`nil` |
| `TestTimeSlot_Overlaps` | BDD-013 / 014 | 別の会議室、相手が先に始まる、同じ利用枠 |
| `TestNewTimeSlot` | — | 同時刻（`ErrTimeSlotNotOrdered`）、逆順、通る組の `==` |
| `TestHoldDeadline_HasArrived` | BDD-015 | 1 秒前は偽 |
| `TestEligibility_CanApply` | BDD-009 / 011 | 2 回では予約可能、30 日より前の記録は数えない |
| `TestVersion_Next` / `TestNewVersion` | — | `Next` は `NewVersion(n+1)` と等しい、0 は拒む |

`ErrOverlappingSlot` はどのテスト関数の `wantErr` にも現れない。`Hold` が返さない（資料「集約の境界」）ので、永続化層のテストが DB 制約の翻訳として確かめる。

## 4. `id` / `name` / `description`

| | 資料にあるケース | 資料に無いケース |
|---|---|---|
| `id` | 資料の ID そのもの（`BDD-014`） | 生成した id（例: `1fbea5`。生成方法は決めない） |
| `name` | `### [BDD-014] 一部でも重なる利用枠の仮押さえは成立しない` の ID を除いた見出し文 | 業務の言葉で 1 文 |
| `description` | 資料の gherkin ブロックを、字下げと `NOTE:` を含めて改変せず転記 | 同じ形で自分で書く |

- `id` は同じディレクトリ（package）の `*_test.go` 全体で一意。資料の 1 BDD は 1 つのテスト関数の 1 ケースにしか置かない。2 か所に置きたくなったら、表がどちらかに決めている
- 同じ資料の ID が別のディレクトリ（永続化層の package）の `id:` にも現れることはある。一意はディレクトリ内の話で、層をまたいで同じ BDD を検証することは妨げない。データモデル資料が自分の番号体系（同じ `BDD-001` が別のシナリオ）を持つこともあり、永続化層はそちらの資料を照合する
- `name` と `description` は言い換えない。`description` の `Then:` に写せない行があっても削らない（§2）

## 5. テストしない BDD の末尾コメント

資料にあるが `id:` に使わない ID は、集約ルートのテストファイル（`reservation_test.go`）の末尾に、`// テストしない BDD:` に続けて 1 行ずつ列挙する。

```go
// テストしない BDD:
// BDD-004 二人の同時仮押さえは集約をまたぐ排他で、メモリ上の値では再現できない。永続化層が対象
// BDD-006 予約待ちの登録は別の集約（予約待ち）の package が対象
```

| 規則 | 理由 |
|---|---|
| 理由は「どの層・どの package が担うか」か「メモリ上で再現できない」のどちらか | 書き忘れと判断の結果を区別する |
| 資料の全 ID が `id:` か末尾コメントのどちらかに現れる | `check-bdd-coverage.py` が判定する。どちらにも無い ID は書き忘れ |
| 置き場はディレクトリに 1 つ、集約ルートのテストファイルの末尾 | VO のテストファイルが複数あっても探す場所は 1 つ |

資料が 2 つの集約を持つとき、それぞれの package が「もう一方の集約の BDD」を末尾コメントに持つ。行数は増えるが、照合したことが機械で言える。
