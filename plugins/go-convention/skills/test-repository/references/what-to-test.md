# 何をテストするか

**永続化層のテストとは、実 DB の上で「データモデル資料の Before から After へ、資料どおりに行が変わる」ことを、資料に登場する全テーブルの全行で確かめるものである。** リポジトリは「復元 → 実物の集約の操作 → 保存」で駆動し、query service は「Before を投入 → 読み取り → DTO を突き合わせ」で駆動する。DB は dockertest で起動した実 PostgreSQL で、mock・stub・in-memory の代替を使わない。

これは、**業務ルールのテストではない**（集約と値オブジェクトが何を許し何を拒むかは、ドメインのテストが実 DB 無しで確かめる）。**SQL の文言のテストでもない**（query は sqlc が型で検査し、正しさは行の結果で観測する）。**usecase のテストでもない**（tx の境界・複数集約の協調・入力の解決は usecase のテストの関心）。

## 1. する／しない

| する | しない |
|---|---|
| データモデル資料の BDD ごとの状態変化を、**資料に登場する全テーブルの全行**で突き合わせる。0 件のテーブルも空であることを確かめる。1 テーブルでも欠けたら規約違反。これは絶対の規則で、例外を置かない | 集約が拒むシナリオ（`Confirm` が期限到来で拒む、`Cancel` が他人を拒む）。ドメインのテストの責務。ファイル末尾のコメントに BDD ID と理由を列挙する |
| 復元と保存の往復。保存する集約は `FindByID` で復元した実物から作るので、`Apply*` のケースが毎回 `FindByID` も通す。`FindByID` 単独は復元した集約の値と NotFound を見る | 業務ルール・境界値（期限の同時刻、隣接の判定、資格の停止期間）。値オブジェクトと集約のテストが担う |
| DB 制約違反がドメインの sentinel に翻訳されること（排他制約 → `reservation.ErrOverlappingSlot`）。集約の内側では確かめられない不変条件は、ここでしか検証できない | SQL の文言、query の名前、生成コードの形 |
| 楽観ロック競合（`rdb.ErrConflict`）。同じ Before から 2 本の tx を並走させ、後から保存した側が拒まれること | marshaller の単体（`{元}To{先}` は非公開。復元 → 保存の往復で観測する） |
| 同時実行。資料の「並行実行で必要な保証」を、同じ Before から 2 本を goroutine で並走させて一方だけ成立することで確かめる | ログ、リトライ、接続の再試行 |
| NotFound（`rdb.ErrNotFound`）と、ctx に tx が無いときの `rdb.ErrNoTransaction` | 通常型のテーブルに無い列、資料に無いテーブル |

「する」列に無いものは書かない。迷ったら「書かない」に倒し、末尾コメントに理由を残す。

「資料に登場する全テーブル」は資料の 8 表に、リポジトリの実装が置く資料に無いテーブルを足したものである。題材では無断不利用を残す仮定の 9 表目 `reservation_no_show_recorded_events`（資料は無断不利用を範囲外にしている）がそれで、実装にあるなら全ケースの `seed{Table}` / `want{Table}` に数え、`ApplyNoShowRecorded` のケースは 9 表全部を突き合わせる。

## 2. When の駆動: 復元 → 実物の操作 → 保存

リポジトリのテストの When は、usecase と同じ手順を同じ tx の中で行う。イベントを手で組み立てない（イベントの型は非公開フィールドで塞がれていて、組み立てられない）。

| 手順 | イベント型の集約（題材の予約） | 通常型の集約 |
|---|---|---|
| 1. Before を投入 | `rdbtest.Reset` → `rdbtest.Seed{Table}` × 資料の全テーブル | 同じ |
| 2. 復元 | `repo.FindByID(ctx, id)` → `reservation.AsTentative(found)` | `repo.FindByID` → `waitlist.AsWaiting` |
| 3. 実物の操作 | `tentative.Confirm(at, by)` → `(ConfirmResult, error)` | `waiting.Promote(at)` |
| 4. 保存 | `repo.ApplyConfirmed(ctx, res.Event)` | `repo.Update(ctx, res.Next)` |
| 5. After を突き合わせ | `rdbtest.Read{Table}` × 全テーブルを `assert.Equal` | 同じ |

- 生成のシナリオ（資料 BDD-001 仮押さえ）は復元の代わりに実物の生成 `reservation.Hold(...)` から始め、`ApplyHeld(ctx, res.Event)`（通常型は `Create(ctx, res.Next)`）で保存する
- 2 〜 4 は `rdbtest.Run(ctx, t, pool, fn)` の中で行う。usecase が張る tx の代わりで、`fn` が error を返せば rollback される。拒まれたケースの After が Before と同じであることは、この rollback を含めて観測する
- 時刻と ID は表の値をそのまま操作に渡す。`time.Now()` を呼ばない。After の `created_at` / `updated_at` / `occurred_at` は資料の値と一致する
- `Restore*` を直接呼んで保存対象を作らない。復元経路が `FindByID` だけなら、往復が毎ケースで検証される

## 3. 同時実行と楽観ロック競合

資料の「並行実行で必要な保証」と「同時仮押さえ」は、**同じ Before から 2 本の tx を並走させる**ことで写す。どちらも表の When を 2 件にし、ループ本体で goroutine 2 本を `sync.WaitGroup.Go` で走らせる。書き方は [table-shape.md](table-shape.md) §4。

| 検証すること | 並走させる 2 本 | 後から保存する側が受ける error | After |
|---|---|---|---|
| 同じ空き枠への同時仮押さえ（資料 BDD-005） | `Hold` → `ApplyHeld` × 2（予約者が違う） | `reservation.ErrOverlappingSlot`（排他制約の翻訳） | 先に成立した 1 件のリソース系 3 行とイベント系 2 行だけ |
| 同じ集約への同時更新（楽観ロック競合） | `FindByID` → `Confirm` → `ApplyConfirmed` × 2 | `rdb.ErrConflict`（楽観ロック付き UPDATE の 0 行） | 先に成立した 1 本の After |

先に成立する側を先頭に固定する（先頭が保存まで進んで tx を開いたまま待ち、残りが保存に入る直前で揃ってから commit する）。成立する側が実行のたびに変わると After が決まらず、表に書けない。

## 4. DB 制約違反と NotFound

| ケース | Before | When | `wantErr` | After |
|---|---|---|---|---|
| 確定予約と重なる仮押さえ（資料 BDD-010） | 確定予約の占有 | 重なる利用枠の `Hold` → `ApplyHeld` | `reservation.ErrOverlappingSlot` | Before と同じ（`want{Table}` に `seed{Table}` と同じ行を書く） |
| 隣接する仮押さえ（資料 BDD-008） | 確定予約の占有 | 境界で接する利用枠の `Hold` → `ApplyHeld` | nil | 2 件目の占有が足される |
| 無い予約の取得 | 空 | `FindByID` | `rdb.ErrNotFound` | 空 |
| tx の外で呼ぶ | 任意 | `rdbtest.Run` を通さず `repo.FindByID(ctx, id)` | `rdb.ErrNoTransaction` | Before と同じ |

集約は「重なる利用枠に有効な予約が無いこと」を内側で確かめられない（資料「集約の境界」）。だから重なりは DB の排他制約が守り、その翻訳を確かめるのはこの層である。集約が拒む条件（資格・期限・本人）はこの層に届かないので、書かない。

## 5. 資料の BDD の割り振り

データモデル資料の「シナリオと記録の対応」の表が、そのまま割り振り表になる。

| 資料の行 | 割り振り |
|---|---|
| どれかのテーブルに「追加」「更新」「削除」がある | その変化を書くメソッドのテスト関数（`ApplyHeld` / `ApplyConfirmed` / `ApplyCancelled` / `ApplyExpired`）に、資料の ID をそのまま `id` にして置く |
| 全テーブル「変更なし」で、拒む主体が集約（事前条件・本人・資格） | 書かない。ファイル末尾の `// テストしない BDD:` に ID と理由を列挙する |
| 全テーブル「変更なし」で、拒む主体が DB 制約（一意・排他） | 書く。`wantErr` にドメインの sentinel、`want{Table}` に Before と同じ行 |
| 「成立した一件だけ」（同時実行） | 書く。When を 2 件にして並走させる |

題材の 10 件は次のように割り振られる。

| ID | 見出し | 置き場 | 理由 |
|---|---|---|---|
| BDD-001 | 空き枠を仮押さえする | `TestReservationRepository_ApplyHeld` | 生成 → `ApplyHeld` |
| BDD-002 | 仮押さえ期限と同時刻の確定を期限切れとして記録する | 末尾コメント | 確定は `Confirm` が期限到来で拒み、リポジトリに届かない。期限切れの記録は BDD-009 で検証する |
| BDD-003 | 仮押さえ予約を確定する | `TestReservationRepository_ApplyConfirmed` | 復元 → `Confirm` → `ApplyConfirmed` |
| BDD-004 | 確定予約を取り消す | `TestReservationRepository_ApplyCancelled` | 復元 → `AsActive` → `Cancel` → `ApplyCancelled` |
| BDD-005 | 同じ空き時間への同時仮押さえは一方だけ成立する | `TestReservationRepository_ApplyHeld` | 2 本並走。排他制約の翻訳 |
| BDD-006 | 仮押さえ予約を取り消す | `TestReservationRepository_ApplyCancelled` | 復元 → `AsActive` → `Cancel` → `ApplyCancelled` |
| BDD-007 | 第三者による確定予約の取消を拒む | 末尾コメント | `Cancel` が本人でない呼び手を拒み、リポジトリに届かない |
| BDD-008 | 確定予約に隣接する利用枠を仮押さえする | `TestReservationRepository_ApplyHeld` | 排他制約が隣接を許すことは DB でしか確かめられない |
| BDD-009 | 未確定のまま仮押さえ期限が到来する | `TestReservationRepository_ApplyExpired` | 復元 → `Expire` → `ApplyExpired` |
| BDD-010 | 確定予約と重なる利用枠の仮押さえを拒む | `TestReservationRepository_ApplyHeld` | 排他制約の翻訳。After は Before と同じ |

資料に無いケース（楽観ロック競合、`FindByID` の各状態の復元、NotFound、tx の外、無断不利用の記録 `ApplyNoShowRecorded`）は生成した id で足す。同じ BDD 番号がドメインのテストのディレクトリにもある。`id` の一意はディレクトリの中で見る。

## 6. query service

query service は書き込みが無いので、全テーブルの突き合わせは要らない。Before を投入し、読み取りメソッドを呼び、返った DTO を `assert.Equal` で突き合わせる。観点は [query-service-test.md](query-service-test.md)。
