# 何をテストするか

**handler のテストは、公開 API の契約を確かめる。** 利用者が見るのは proto の入出力・`connect.Code`・公開文言・「操作が本当に起きたか」だけであり、テストもそれだけを見る。経路は本番と同じ（proto → 入力 → usecase → リポジトリ → 実 DB → 応答）で、経路の途中に偽物を挟まない。

## 1. handler のテストとは何か・何でないか

| | 内容 |
|---|---|
| である | API テスト。`httptest.NewServer` に本番同等の組み立てで起動した server を、生成クライアントで叩く。interceptor（翻訳・ログ・認可）を通る |
| でない | handler 単体テスト。`ReservationServer` のメソッドを直接呼ぶと interceptor を通らず、Code への翻訳と認可が検証できない。proto 変換しか見えないテストになる |
| でない | 依存の差し替え。偽の usecase・偽のリポジトリ・in-memory DB を挿すと「変換は正しいが保存されない」を見逃す。唯一の差し替えは認可 interceptor（[server-setup.md](server-setup.md) §3） |
| でない | interceptor の単体テスト。翻訳表と認可は RPC を叩いた結果（Code・文言）で確かめる。interceptor を単独で呼ばない |
| でない | 下の層の再演。ドメイン・永続化層・usecase のテストが確定したことを、公開 API から二度確かめない |

## 2. する / しない

| する | 何で確かめるか | 理由 |
|---|---|---|
| proto ↔ 入力の変換 | 欠けた・空のフィールド → `InvalidArgument`。欠けは handler の公開 sentinel（`handler.ErrStartsAtRequired`）、空は値オブジェクトの生成の条件の sentinel（`reservation.ErrIDRequired`）が文言になる | 変換は handler にしか無いコード。ここで見なければどこでも見ない |
| `connect.Code` の翻訳 | その RPC が返しうる sentinel ごとに 1 ケース。`connect.CodeOf(err)` を Code と、`(*connect.Error).Message()` を sentinel の文言と突き合わせる | 対応表は境界 1 か所にあり、公開 API の契約そのもの。表の行が RPC の結果として現れることを確かめる |
| 認可 | 主体無し → `Unauthenticated`。他人の予約 → `PermissionDenied` | 主体は interceptor が ctx に載せ、本人性はドメインが判定する。両方を通した結果が Code になるのは公開 API だけ |
| 永続化の反映 | 成功ケースで、反映が起きるテーブルを読み取り関数で読み、射影（識別子・状態・版）を 1 行突き合わせる | 「変換は正しいが保存されない」（tx を張り忘れた・usecase を呼んでいない）を検出する |
| レスポンスの内容 | 成功ケースで、値が入るフィールドを射影で突き合わせる | 採番した識別子・期限を返す RPC では、これが利用者との契約 |

| しない | 誰が確かめるか | 理由 |
|---|---|---|
| 業務の境界値（隣接する利用枠・期限と同時刻・利用開始と同時刻） | ドメインのテスト | 集約の事前条件の話。公開 API から見ると Code が同じで、ケースが増えるだけ |
| SQL・DB 制約違反の翻訳・同時実行・楽観ロック競合 | 永続化層のテスト | リポジトリの契約。HTTP を通す必要が無い |
| 全テーブル・全カラムの突き合わせ | 永続化層のテスト | 反映の「有無」が分かれば足りる。全行の突き合わせは永続化層の絶対規則で済んでいる |
| usecase の観点（入力解決・複数集約の協調・ソース選択・tx 境界の commit / rollback・コマンドの呼び分け） | usecase のテスト | 拒否で何も変わらないこと（rollback）は usecase のテストが DB 状態で確定済み。ここでは拒否ケースの DB を読まない |
| ログの有無・内容 | 書かない | logger は `slog.DiscardHandler`。ログは運用者向けの出力で、公開 API の契約ではない |
| `Internal` になる経路 | 書かない | 対応表に無い sentinel・tx 無し・取り違えは実装の誤り。テストで期待する Code ではない（SKILL.md の停止条件） |

## 3. ケースの選び方（1 RPC あたり 4〜8）

| 順 | ケース | 期待 | 数 |
|---|---|---|---|
| 1 | 成功 | `wantCode` 0、`wantResp`、`want{Table}` | 1 |
| 2 | その RPC が返しうる sentinel ごと | sentinel に対応する Code と文言 | sentinel の数（確定なら `ErrHoldDeadlinePassed` / `rdb.ErrNotFound`。`ErrAlreadyConfirmed` 等の状態違いは 1 つ代表で足りる） |
| 3 | 主体無し | `Unauthenticated`。文言は見ない | 1 |
| 4 | 他人 | `PermissionDenied`、`ErrNotOwner` の文言 | 1 |
| 5 | 入力不正 | `InvalidArgument`、値オブジェクトの生成の条件か handler の欠け sentinel の文言 | 1（必須フィールドが複数なら代表 1。確定なら空の予約番号、仮押さえなら `starts_at` の欠け） |

| 規則 | 理由 |
|---|---|
| 4 未満なら、認可か入力不正が抜けている | どの RPC も主体を要し、入力を持つ。無いなら書き忘れ |
| 8 を超えるなら、業務の境界値か usecase の観点を持ち込んでいる | 公開 API の契約は Code の種類の数で決まり、境界値の数では増えない |
| 同じ Code のケースは sentinel が違うときだけ足す | 同じ sentinel を別の前提で 2 回見ても、対応表の同じ行を 2 回見るだけ |
| 状態違いの sentinel（確定済み・取消済み・期限切れ）は代表 1 つ | 絞り込み関数の分岐はドメインのテストが全状態を見ている。ここでは「状態違いが `FailedPrecondition` になる」ことが分かれば足りる |

題材 `ConfirmReservation` の 6 ケース（[table-shape.md](table-shape.md) §2）:

| id | 前提 | Code | 文言 |
|---|---|---|---|
| `c4e1a8` | 期限前の仮押さえ予約、本人 | 成功 | — |
| `7d0f2b` | 仮押さえ予約、本人、仮押さえ期限が `now` より前 | `FailedPrecondition` | `reservation.ErrHoldDeadlinePassed` |
| `e93a61` | 仮押さえ予約、他人 | `PermissionDenied` | `reservation.ErrNotOwner` |
| `52b7c0` | 予約が無い | `NotFound` | `rdb.ErrNotFound` |
| `a1d48e` | 空の予約番号 | `InvalidArgument` | `reservation.ErrIDRequired` |
| `f06c93` | 主体無し | `Unauthenticated` | 見ない（主体注入 interceptor の文言で、公開 API の契約ではない） |

`ErrAlreadyConfirmed`（確定済みの再確定）は、この RPC では `FailedPrecondition` の 2 つ目になるので足していない。足すなら状態違いの代表として 1 つで、7 ケースになる。

## 4. `id` / `name` / `description`

| 資料 | `id` | `name` | `description` |
|---|---|---|---|
| RPC ごとの BDD を持つ API 仕様の資料がある | 資料の ID そのまま | 資料の見出し文 | 資料の gherkin ブロックを改変せず転記。書かない ID はファイル末尾の `// テストしない BDD:` に理由付きで列挙 |
| 無い | 生成した id（ディレクトリ内で一意・不変） | 業務語で 1 文（「期限を過ぎた仮押さえは確定できない」） | `Given:` 前提の行と主体 / `When:` 誰がどの RPC を何で呼ぶ / `Then:` Code と文言、成功なら応答と反映 |

業務知識・ドメインモデル・データモデルの資料の BDD は、それぞれドメイン・永続化層のテストの対象であり、この層の `id` には使わない。同じ場面を公開 API から見るケースでも、id は生成する。
