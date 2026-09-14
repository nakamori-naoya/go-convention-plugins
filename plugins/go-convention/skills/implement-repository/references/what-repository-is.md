# リポジトリロジックとは何か

**リポジトリロジックとは、ドメインの値とテーブルの行を往復させ、DB が拒んだ事実をドメインの言葉に翻訳するものである。** 集約を「復元」して usecase に渡し、usecase が集約を操作した結果（通常型なら次の状態、イベント型ならドメインイベント）を「永続化」する。それ以外のことをしない。

これは、**業務判断の置き場ではない**。何を許し何を拒むかは集約が決め、リポジトリはその結果を書くだけである。**トランザクションの持ち主でもない**。tx は usecase が張り、リポジトリはそれに乗る。**読み取りモデルの生成器でもない**。一覧・件数・検索は行を DTO へ写す関心で、集約を復元しない別物である（query service の規約が決める）。

## 1. する／しない

| する | しない |
|---|---|
| 復元: 行 → VO の `New*` と `Restore*` → 集約（和型で返す） | 業務判断・バリデーション（集約と VO の `New*` が担う。行が VO に拒まれたらそれはデータ破損であり、業務の拒否ではない） |
| 永続化: 通常型は次の状態を上書き、イベント型はドメインイベントを追記して current 行へ反映 | トランザクションの開始・コミット・ロールバック（usecase の規約が決める） |
| DB 制約違反 → ドメインの sentinel への翻訳（`reservation.ErrOverlappingSlot`） | ログ（`log/slog` を import しない。エラーを返せば境界が 1 回記録する） |
| 楽観ロック競合 → `rdb.ErrConflict`、見つからない → `rdb.ErrNotFound` | リトライ・キャッシュ・バックオフ |
| sqlc 生成コードの直接利用（`sqlcgen.New(tx)` を呼び、生成メソッドをそのまま使う） | 一覧・件数・検索・存在確認（Query 系。`:many` は非ルートエンティティの行を集めるときだけ） |
| 版の照合キー導出（`evt.Version().Value()-1` を `WHERE current_version =` に置く） | 版の採番（ドメインイベントが版を持って来る。リポジトリは足さない） |
| イベント表の `id` を決める（DB の identity 列に任せ、`RETURNING id` で受け取って詳細表へ渡す。ドメインにも usecase にも見せない） | ドメインイベントの生成（集約の操作が返す。リポジトリが組み立てない） |
| 時刻を行へ写す（すべてドメインの値から。`created_at` / `updated_at` もイベントの `OccurredAt()`） | `time.Now()`・ID の採番（時刻と識別子は usecase が用意して集約へ渡す） |
| 和型の型スイッチ（通常型の `Update` で状態ごとの marshaller を選ぶ） | 集約・VO のフィールドへの直接アクセス（別 package の非公開フィールドで、型が塞いでいる。getter だけを使う） |

「する」列に無いものは書かない。迷ったら「しない」に倒し、置き場が分からなければ停止条件で返す。

## 2. 依存の向き

```
usecase ──▶ reservation（domain: 集約・VO・Repository interface・sentinel）
   │                ▲
   │                │ import（復元と翻訳のため）
   ▼                │
  tx  ◀──── rdb ────┴──▶ rdb/sqlcgen（sqlc 生成）
```

- `rdb` は `reservation`・`sqlcgen`・`tx`・`pgx` を import する。`reservation` は `rdb` を知らない
- `Repository` interface はドメイン層（集約と同じ package）に集約ごとに 1 つ定義済みである。この skill は実装だけを書き、interface を切らない・変えない。メソッドを足したくなったら停止条件へ
- `ReservationRepository` は依存を持たない（`NewReservationRepository()` は引数なし）。`*pgxpool.Pool` を持たず、接続は ctx の tx から取る。ロガー・時計・ID 生成器も持たない

## 3. 例の置き場

ディレクトリ構成そのものは上位の開発規約が決める。この skill の例は import path を短くするため平らにしている（module `example.com/roomflow`）。

| path | 中身 |
|---|---|
| `reservation/` | 集約「予約」。`Repository` interface と sentinel もここ |
| `rdb/reservation_repository.go` | `ReservationRepository` と各メソッド |
| `rdb/reservation_marshaller.go` | `{元}To{先}` の純粋関数と、`status` / `event_type` の定数 |
| `rdb/errors.go` | `ErrNotFound` / `ErrConflict` / `ErrNoTransaction` と `translateConstraint` |
| `rdb/query/reservation.sql` | 集約「予約」が触る全テーブルの sqlc query |
| `rdb/schema/*.sql` | DDL（sqlc の `schema` が指す。名前付き制約はここ） |
| `rdb/sqlcgen/` | sqlc の生成物。手で編集しない |
| `tx/` | `Manager` と `From`。usecase が `Run` を呼び、リポジトリが `From` を呼ぶ |

## 4. 題材との対応

データモデル資料「RDB論理設計 — 貸会議室の予約」の 8 テーブルと、資料に無い仮定の 9 表目（`reservation_no_show_recorded_events`。ドメインの `ApplyNoShowRecorded` を写すために置く。資料は無断不利用を範囲外にしている）を、集約「予約」のリポジトリ 1 つが扱う。集約 1 つ = リポジトリ 1 つ = query ファイル 1 つで、テーブル数とは対応しない。

| 分類 | テーブル | リポジトリの操作 |
|---|---|---|
| リソース系 | `reservations` | `ApplyHeld` が INSERT、他の `Apply*` が楽観ロック付き UPDATE。`FindByID` の正本。全列 NOT NULL |
| リソース系 | `room_booking_claims` | `ApplyHeld` が INSERT、`ApplyCancelled` / `ApplyExpired` が DELETE。排他制約の置き場 |
| リソース系 | `tentative_hold_deadlines` | `ApplyHeld` が INSERT、`ApplyConfirmed` / `ApplyCancelled` / `ApplyExpired` が DELETE。`FindByID` が仮押さえのときだけ読む |
| イベント系 | `reservation_base_events` | 全 `Apply*` が INSERT（`version = evt.Version()`）。`RETURNING id`。`(reservation_id, version)` の一意制約が競合の最後の砦 |
| イベント系 | `reservation_{種別}_events` | 対応する `Apply*` が INSERT（`base_event_id` を持つ）。`no_show_recorded` は `FindByID` が確定済みのときだけ読み、`RestoreConfirmed` の無断不利用の時刻にする |

イベント系テーブルは追記だけで、UPDATE も DELETE も書かない。
