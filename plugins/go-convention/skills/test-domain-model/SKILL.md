---
name: go-convention-internal-test-domain-model
description: 集約・エンティティ・値オブジェクトのテストを、domain-model 資料の「BDDとの対応」表から書く。資料の BDD をその表の要素×操作が指すテスト関数（生成関数・状態型のメソッド・絞り込み関数・値オブジェクトの操作）へ割り振り、Given を Restore* / New* の引数、Then を Next の値・発したイベントの値・sentinel で書き、テストしない BDD はファイル末尾に理由付きで列挙する。「この集約のテストを書いて」「domain-model 資料の BDD からドメインのテストを書いて」「この値オブジェクトの境界をテストして」と言われたときに使う。テストの形の共通規則そのもの、永続化（復元の往復・DB 制約・同時実行）、usecase の手順、RPC の入口は対象外として、それぞれの規約へ返す。
---

# test-domain-model

これは、**ドメインの package（集約・エンティティ・値オブジェクト・ドメインイベント）が資料どおりに判断するかを、メモリ上の値だけで確かめる規約**である。domain-model 資料の「BDDとの対応」表が、どの BDD をどのテスト関数に置くかを決め、テストは資料の gherkin を `id` / `name` / `description` に写し、Given を復元関数と `New*` の引数、Then を遷移の結果（`Next` の値・発したイベントの値・sentinel）で書く。

これは、**永続化された集約が正しく戻るか、usecase が正しい順で集約を呼ぶか、境界が正しいコードを返すか**を確かめるものではない。復元と保存の往復、DB 制約、同時実行、トランザクション、複数集約の協調、DTO の変換は、それぞれの層の規約が扱う。テストの形（テーブル駆動・`id` / `name` / `description`・`require` / `assert`・`{pkg}_test`）はテストの形の共通規則が決めていて、ここでは [table-shape.md](references/table-shape.md) に必要な分だけ要約して持つ。

前提: Go 1.27・testify（`github.com/stretchr/testify`）。DB・コンテナ・モック・スタブは使わない。

## 規約

| # | 柱 | 一言で | 正本 |
|---|---|---|---|
| 1 | 何をテストするか | VO の生成の条件・判定と計算・New 再生成、集約の生成関数と操作の事前条件・事後条件・拒む理由・発するイベント、`(Result, bool)` の両側、絞り込み関数の状態違い、不変条件。getter・永続化・他集約の判断・usecase の手順・資料に無い内部・同時実行・ログはテストしない | [what-to-test.md](references/what-to-test.md) |
| 2 | 資料からの割り振り | 「BDDとの対応」表の要素×操作がテスト関数を決める。生成 → `TestHold`、許される遷移 → `TestTentative_Confirm`、状態違いの拒否 → `TestAsTentative`、VO の操作 → `TestTimeSlot_Overlaps`。1 BDD 2 操作は資料の並び順。別の集約・同時実行・外の判断は末尾コメント | [mapping-from-doc.md](references/mapping-from-doc.md) |
| 3 | テーブルの形 | Given は `Restore*` / `New*` の引数名、When は操作の引数（`at` / `by`）、Then は `wantNext`（`Restore*` で組む）・`wantEvent`（getter の射影）・`wantErr`（sentinel）・`wantOK`。`t.Parallel()` あり。ケース間依存なし | [table-shape.md](references/table-shape.md) |
| 4 | 題材の完全な例 | 貸会議室予約の `reservation_test.go` 相当。`TestHold` / `TestTentative_Confirm` / `TestAsTentative` / `TestTimeSlot_Overlaps` と末尾コメント | [examples.md](references/examples.md) |

### 何をテストする／しない

| テストする | テストしない |
|---|---|
| VO の生成の条件: 拒む組は sentinel、境界（`start == end`）はどちら側か、通る組は `==` で比べられる値になる | getter だけの検証（`Restore*` して `ID()` を読む） |
| VO の判定と計算の操作: 真偽・計算結果と、その境界（隣接・同時刻） | 永続化と復元の往復（保存 → `FindByID` → 同じ値） |
| VO を返す操作の New 再生成: 返る値が `New*` の結果と等しい | 他の集約の判断（繰上げ判断が先頭を選ぶ、予約待ちの並び順） |
| 集約の生成関数: 事前条件ごとの sentinel、`Next` の値、発するイベントの値 | usecase の手順（復元 → 絞り込み → 操作 → 保存の並び、tx） |
| 集約の操作: 事前条件を資料の順に破ったときの sentinel、`Next` の値、発するイベントの値、版が 1 進む | 資料に無い内部（非公開フィールド、共通の埋め込み struct、定数の値そのもの） |
| 拒まない操作 `(Result, bool)`: 条件を満たさなければ `false` とゼロ値、満たせば `true` と `Next` / `Event` | 資料の「同時に起きたとき」（メモリ上の値に同時実行は無い。永続化層が対象） |
| 絞り込み関数: 状態ごとの sentinel、`nil` の sentinel、同じ状態なら同じ値 | 集約の内側で確かめられない生成の条件（重なる利用枠。呼ぶ側と DB 制約が守る） |
| 不変条件: 終端状態に操作が無いこと（絞り込みで観測）、`Next` が元の値を引き継ぎ版だけ進むこと、イベントの版が `Next` の版と一致すること | ログ（ドメインは出さない）、`String()`、JSON |

## 手順

1. **資料と実装を突き合わせる。** domain-model 資料の「BDDとの対応」表（BDD → 要素 × 操作）と、対象 package の公開 API（生成関数・状態型のメソッド・`As*`・`Restore*`・VO の `New*` と操作・sentinel）を読む。完了条件: 表の全行に、この package のテスト関数名か「末尾コメント行き」の印が付いている（[mapping-from-doc.md](references/mapping-from-doc.md) の表の形）
2. **テスト関数の一覧を作る。** 公開の生成関数・状態型のメソッド・絞り込み関数・VO の `New*`（拒む組があるもの）と操作ごとに 1 本。完了条件: 対象 1 つにテスト関数 1 つで、名前が `Test{型}_{メソッド}` / `Test{関数}` に決まっている
3. **資料のケースを写す。** 割り振った BDD を資料の順に `id`（資料の ID）/ `name`（見出し文）/ `description`（gherkin ブロックを字下げと `NOTE:` 込みで転記）へ写し、Given を `Restore*` / `New*` の引数、When を操作の引数、Then を `wantNext` / `wantEvent` / `wantErr` / `wantOK` / `want` に置く。完了条件: `description` の各行が、フィールドか「別の id が担う行」か「別の層が観測する行」のどれかに振り分けられ、`description` を削っていない
4. **資料に無いケースを足す。** package の sentinel ごとに 1 つ以上（集約が返さない sentinel を除く）、事前条件の順（複数を同時に破ったとき資料の順で最初の理由が返る）、`(Result, bool)` の `false` 側、VO の拒む組と境界。`id` は生成した id。完了条件: 集約と VO が返しうる sentinel が全部どこかの `wantErr` に現れる
5. **末尾コメントを書く。** 集約ルートのテストファイル（`reservation_test.go`）の末尾に `// テストしない BDD:` と、`id:` に現れない資料の ID を理由付きで 1 行ずつ。完了条件: 資料の全 ID が `id:` か末尾コメントに現れる
6. **機械検査を通す。** `CLAUDE_PLUGIN_ROOT` は Claude Code が展開する。Codex では、この `SKILL.md` があるディレクトリの 2 つ上（plugin root）の絶対パスを入れる。完了条件: 全部通る
   ```bash
   go vet ./<domain package>/...
   go test -shuffle=on -count=1 ./<domain package>/...
   go test -count=1 -run 'TestHold/BDD-001_' ./<domain package>/...   # 足したケースを 1 つずつ単独で
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/test-domain-model/scripts/check-bdd-coverage.py" <domain-rule 資料.md（### [BDD-NNN] 見出しを持つ資料）> <テストのディレクトリ>
   ```
   テストの形（`id` の一意・順序・`description` の形）の検査は、テストの形の共通規則の検査を別途通す
7. **報告する。** 下の「報告」の項目

## 停止条件

- domain-model 資料に「BDDとの対応」表が無い、または表の行に要素・操作が無い → 置き場を決められない。書かずに資料の作成へ返す
- 表の要素×操作に対応する公開の型・メソッド・関数が package に無い → テストで補わない。実装の規約へ、資料のどの行に対応する API が無いかを返す
- 対象の操作が sentinel ではなく `fmt.Errorf` で作ったエラーや文言だけの `error` を返す → `wantErr` に書けない。エラーの規約へ返す
- 対象が `time.Now()` や採番を内側で呼び、時刻・ID を引数で受けない → 期待値が決まらない。実装の規約へ返す
- 資料の gherkin の `Then:` に、この package のどの公開 API でも観測できず、別の id も担わない行がある → `description` を削らない。その行をどの層が観測するかを報告に書き、それが決まらなければ止まる
- 資料の BDD を写すのに `setup func` や操作列が要る → ドメインのテストの Given は `Restore*` のデータで書ける。要ると思ったら対象が集約の外の手順（usecase）である。書かずに返す

## 機械検査で言えること

| 検査 | 通ったら言えること |
|---|---|
| `go vet` / コンパイル | 形の違反は見つからなかった。イベントと `Next` の型は遷移結果型の型引数で決まっている |
| `go test -shuffle=on` | テスト関数間の順序依存は見つからなかった |
| `go test -run 'TestHold/BDD-001_'` が通る | そのケースは単独で通る |
| `check-bdd-coverage.py` | 次の 4 つの述語が成り立った。1. 資料に `### [BDD-NNN] 見出し` の形の見出しが 1 つ以上ある 2. 資料の各 BDD ID が、ディレクトリの `*_test.go` の `id:` の値か、`// テストしない BDD:` に続く `// BDD-NNN 理由` のどちらか一方に現れる（両方には現れない） 3. `id:` の値のうち `BDD-` で始まるものは、資料の見出しにある 4. `// テストしない BDD:` の列挙は 1 ファイルに 1 つで、ファイルの最後にあり、各行は `// BDD-NNN 理由` の形で理由が空でない。書かない理由が正しいとは言えない |

「割り振りが表と一致する」「`description` の行がフィールドに写っている」「末尾コメントの理由が正しい」は、この検査では言えない。下のチェックリストを人が読む。

## チェックリスト（機械で言えないことだけ）

- [ ] 各 BDD の `id:` が置かれたテスト関数が、資料の「BDDとの対応」表の要素×操作と一致する。許される遷移が絞り込み関数に、状態違いの拒否が状態型のメソッドに置かれていない
- [ ] 1 BDD が 2 操作を挙げる行は、資料の並び順で 1 つずつ割られている
- [ ] Given のフィールド名が `Restore*` / `New*` の引数名（`id` だけは `reservationID` のように集約名を添える）で、When が操作の引数名、Then が `wantNext` / `wantEvent` / `wantErr` / `wantOK` / `want`
- [ ] `wantNext` は `Restore*` で元の値から組み、版だけ進んでいる。`wantEvent` は getter の射影で、版が `wantNext` の版と同じ
- [ ] 拒むケースは `wantErr` が sentinel で、`assert.Zero(t, got)` がある。`(Result, bool)` の `false` 側にも `assert.Zero` がある
- [ ] 資料に無いケースが、sentinel ごと・事前条件の順・境界・`false` 側を埋めている。生成した id で、`name` が業務語の 1 文
- [ ] getter だけのケース、`Restore*` の往復、他集約の判断、usecase の手順、同時実行のケースが無い
- [ ] 末尾コメントの理由が「どの層・どの package が担うか」か「メモリ上で再現できない」のどちらかで、書き忘れと区別できる
- [ ] 表の前に置いたのは VO の生成（`New*` ＋ `require.NoError`）と射影 struct の宣言だけで、関数が無い
- [ ] `t.Parallel()` がテスト関数の先頭とサブテストの先頭の両方にある

## 報告

- テスト関数の一覧と、各関数が持つ資料の ID（割り振りの表）
- ケース数と内訳: 資料にあるケース / 資料に無いケース（sentinel・境界・順序・`false` 側のどれを埋めたか）/ テストしない BDD（ID と理由）
- `description` の行のうちフィールドに写せず、別の id または別の層が観測する行
- 機械検査の結果（`go vet` / `go test -shuffle=on` / 単独実行 / `check-bdd-coverage.py`）
- 停止条件に当たって返した論点（資料へ、実装へ、エラーの規約へ）
