---
name: implement-usecase
description: Go の usecase 層を、command（入力の解決 → tx を張る → 復元または生成 → 絞り込み → 操作 → 保存）と query（読み取りポートを呼んで DTO を返す）の 2 つの形で書く。tx は command の usecase が `tx.Manager.Run` で張り（query は張らない）、ポートはドメインの `Repository` interface と usecase 側の読み取りポートに依存し、ID は usecase が `IDGenerator` で用意し時刻は Input の `At` で受けて集約へ渡し、複数集約の協調（同じ tx か、ドメインイベントを受けた別 usecase か）を資料に従って決める。「この usecase を書いて」「業務イベントをアプリケーション層に落として」「tx の張り方を直して」「集約を 2 つ触る手順を書いて」と言われたときに使う。業務ルールの実装（集約・VO）、SQL とリポジトリの中身、読み取りモデルの SQL、RPC の入口と DTO 変換、エラーの翻訳表、ログの出力、テストは対象外として、それぞれの規約へ返す。
---

# implement-usecase

[工程順序の正本](playbook.yml)を最初に読み、同じagentが\`steps\`を宣言順に実行する。YAMLは工程順序を決め、各工程の判断内容と根拠はこの本文と参照資料を実読して評価する。失敗時は成功扱いせず停止して、完了工程、根拠、未決を残し、再開時は最初の未完了工程から続ける。

これは、**1 つの業務イベントを、ドメインの操作とポートの呼び出しの並びとして書く規約**である。usecase は「集めて、呼んで、保存する」だけの薄い層で、判断はすべてドメインが持つ。

これは、**業務ルールの置き場ではない**（何を許し何を拒むかは集約と VO が決め、usecase は状態を見て分岐しない）。**SQL の置き場でもない**（復元と保存はドメインの永続化ポート、一覧と件数は読み取りポートの実装が担う）。**transport を知らない**（proto も `connect` も HTTP も import せず、Input と Output は primitive の struct）。**ドメインの判断を代行しない**（型スイッチ、`Status()` の比較、件数の解釈、時刻の比較を書かず、材料を集めて集約に渡す）。エラーの分類と翻訳（エラーの規約）、ログ（ログの規約）、テスト（テストの規約）も扱わない。

前提: Go 1.27、`github.com/jackc/pgx/v5`（`tx.Manager` の実装が使う。usecase は import しない）。入力はドメインの実装、domain-model 資料、domain-rule 資料、確定済みの論理責務・集約境界を Go package へ写した配置である。例の題材は貸会議室予約 RoomFlow（module `example.com/roomflow`）である。

## 入力

- ドメインの実装、domain-model資料とdomain-rule資料の絶対path、確定済みの論理責務・集約境界を写したGo package配置。
- `references`: 追加で従う資料の絶対path配列。任意。手順の最初に読み、以降の判断でこの規約と併せて従う。

プロジェクト固有の規約（置き場、命名、追加で従う資料）は、対象repositoryのAGENTS.md / CLAUDE.mdと`references`で渡される。この入口は既定値を持たず、指示文へ展開もしない。

先に赤いテスト（資料の業務イベントと集約の操作から書かれ、usecase が無いために失敗している）がある場面も通常である。そのテストが前提にする型名・`Input` / `Output`・コンストラクタに合わせ、テストを変えずに緑にする実装を書く。テストが資料に無い協調や、ドメインが持つべき判断を usecase に要求していれば、実装で補わずテストと資料へ返す。

## 規約

| # | 柱 | 一言で | 正本 |
|---|---|---|---|
| 1 | command の形 | 1 業務イベントに 1 型 1 `Execute(ctx, in) error`（返すものがあれば `(Output, error)`）。入力の解決 → `Run` → 復元（`FindByID`）または生成（`Hold`）→ 絞り込み（`AsTentative`）→ 操作 → 保存（イベント型は `Apply{Event}(ctx, res.Event)`、通常型は `Create` / `Update`）。ID は usecase が `IDGenerator` で用意し、時刻は Input の `At`（usecase は `Clock` を持たない）。`(Result, bool)` の false は「何もしない」 | [command.md](references/command.md) |
| 2 | query の形 | DTO を返す読み取りポートを usecase 側に定義し、実装を注入する。入力の解決とソース選択（進行中 → 現行、終了 → 履歴）は usecase、SQL・並び順・集計は実装の関心。集約を復元しない、書かない、`Run` を張らない | [query.md](references/query.md) |
| 3 | tx | command の usecase だけが `tx.Manager.Run(ctx, func(ctx context.Context) error)` で張る。単位は 1 業務イベント。`Run` の中に復元・読み取り（同じ tx）・操作・保存、外に VO の解決・採番。error を返せば rollback、nil なら commit。query は張らない | [transaction.md](references/transaction.md) |
| 4 | 複数集約の協調 | 資料「集約どうしの協働」の「一貫性」が「同じ操作」なら同じ tx で 2 集約、「結果整合」ならドメインイベントを受けた別 usecase。集約の外で守る不変条件は読み取りポートで材料を読み、ドメインの判定を呼んで sentinel を返す。DB 制約が最後の砦 | [cross-aggregate.md](references/cross-aggregate.md) |
| 5 | エラー | package を出る `return` ごとに `fmt.Errorf("予約 %s の確定: %w", in.ReservationID, err)` で文脈を 1 回。分類しない、ログしない、既定値に丸めない、フォールバックしない、ガード節で早期リターン | [command.md](references/command.md) §6 |

### する／しない

| する | しない |
|---|---|
| 入力の primitive を VO の `New*` で解決する。入力不正の sentinel はここで出る | `if in.RoomCode == ""` のような検証を自前で書く（VO の `New*` が拒む） |
| `tx.Manager.Run` で tx を張り、`Run` の中で復元・操作・保存する | リポジトリや読み取りポートの実装に tx を張らせる。`pgx` を import する |
| 復元（`FindByID`）または生成（`Hold`）→ 絞り込み（`AsTentative`）→ 操作 → 保存 | 型スイッチ、`Status()` の比較、`len(x) > 0` で業務の拒否を返す、時刻を比べる |
| ID を `IDGenerator` で用意し、時刻を Input の `At` で受け、集約の引数で渡す | ドメインに `time.Now()` や採番をさせる。usecase に `Clock` を持たせる。同じ `Execute` で 2 つの時刻を使う |
| ドメインの `Repository` interface に依存する | 永続化ポートを usecase 側で切り直す。状態指定取得（`FindTentativeByID`）を求める |
| 一覧・件数・材料の読み取りは、usecase 側に定義した DTO を返す読み取りポートで行う | 読み取りポートに集約や VO を返させる。読み取りポートで書き込む |
| 集約の外で守る不変条件（`ErrOverlappingSlot`）は、材料を読み、ドメインの判定（`TimeSlot.Overlaps`）を呼び、資料の sentinel を返す | 不変条件を DB 制約だけに任せる。DB 制約違反の翻訳を usecase で行う |
| 複数集約は資料の「一貫性」に従い、同じ tx か、イベントを受けた別 usecase かを決める | usecase が usecase を呼ぶ。2 つの tx に分けて「後で直す」 |
| ソース選択（現行か履歴か）を入力と時刻で決める | error を見て別の経路へ倒す（フォールバック）。再試行を `for` で囲む |
| `(Result, bool)` の false を「何も起きなかった」として nil で返す | false を error にする。sentinel を nil に読み替える |
| 文脈を 1 回足して返す | 分類する、`connect` を import する、`log/slog` を import する、既定値に丸める |
| 資料の業務語で名付ける（`HoldReservation` / `ConfirmReservation` / `PromoteWaitlist`） | `Create` / `Update` / `Process` / `Handle` / `Sync` の機械語。`Usecase` 接尾辞 |
| 公開メソッドは `Execute` 1 つ | 業務の差分・計画・同期を計算する非公開関数（`diff*` / `plan*` / `sync*`） |

## 手順

1. **usecase を切る。** `references` があれば先に読む。domain-rule 資料の「業務イベント」1 つ、または「状態と、その移り変わり」の引き金 1 つに command を 1 つ、画面や API が求める一覧・表示 1 つに query を 1 つ置く。名前は資料の業務語。完了条件: usecase 名が資料の業務イベントまたは一覧と 1:1 で、`Create` / `Update` の機械語と `Usecase` 接尾辞が無い
2. **Input / Output と、ID・時刻の持ち主を決める。** Input は境界が受け取った primitive（`string` / `time.Time` / `int`）の struct。ID は生成（`Hold`）のときだけ usecase が `IDGenerator` で用意し、時刻は生成も遷移（`Confirm` / `Cancel` / `Expire`）も Input の `At` で受ける（RPC の入口がサーバーの時計で、worker が判定時刻で埋める）。完了条件: Input の各フィールドが VO の `New*` の引数か、操作の引数のどれかに写り、usecase が時計を持たない
3. **依存を並べる。** command は `*tx.Manager`、ドメインの `Repository`、読み取りポート（usecase 側で定義。DTO を返す）、生成なら `IDGenerator`。query は読み取りポートだけ。コンストラクタは全部を引数で受けて `*T` を返す。完了条件: usecase が自前で切った interface が、読み取りポートと `IDGenerator` だけ
4. **集約の協調を決める。** 触る集約が 2 つ以上なら domain-model 資料「集約どうしの協働」の「一貫性」を読み、「同じ操作」なら同じ `Run`、「結果整合」ならイベントを受けた別 usecase にする。「集約をまたぐ不変条件」の「守る場所」が「生成を呼ぶ側」なら、その材料を読む読み取りポートを 3 に足す。完了条件: 集約ごとに「同じ tx」か「別 usecase」かが決まり、不変条件ごとに読む材料と返す sentinel が決まっている
5. **`Execute` を書く。** command は入力の解決 → 採番 → `Run` → 復元または生成 → 絞り込み → 操作 → 保存。query は入力の解決 → 読み取りポート → 返す。error は `return` ごとに文脈を 1 回。完了条件: `Run` の中に型スイッチ・状態の比較・時刻の比較・SQL・`log/slog`・`connect` が無く、`time.Now()` が usecase に無い
6. **コンパイルを通す。** `go build ./... && go vet ./...`。完了条件: 両方が通り、`usecase` package の import に `pgx` / `sqlcgen` / `connect` / proto が無い
7. **報告する。** 「報告」の項目を返す

## 停止条件

止まるのは、資料または規約の契約に反する要求、正本に無い決定が要る、利用者の許可が要る、toolが失敗した、のどれかに当たるときで、それ以外の判断の揺れでは止まらない。欠けているのが業務事実（操作・状態・拒む理由・資料が未決と明示した値）なら止まり、命名・分割・定義場所・並び・テストの置き場のような設計判断の揺れなら仮説を明示して進む。

- 資料に無い操作が要る（usecase で状態を見て分岐したくなる、集約に無いメソッドを呼びたくなる） → 書かず、ドメインの規約と資料へ返す
- 触る集約が 2 つ以上で、資料「集約どうしの協働」にその組が無い、または「片方だけ成立したときの扱い」が未決 → 書かず、資料へ返す
- 読み取りポートで確かめる不変条件（重なり・一意）に対応する DB 制約がデータモデル資料に無い → 書かず、データモデル資料へ返す。usecase の読み取り検査だけでは同時に起きたときを守れない
- ドメインの `Repository` interface に無いメソッド（状態指定取得・一覧・件数・`Exists`）が要る → 読み取りポートで足りるならそちらへ。足りなければドメインの規約へ返す
- Input に proto・`connect.Request`・HTTP の型を求められた → 従わず、入口の規約へ返す
- フォールバック（失敗したら別経路で続ける）が要ると判断した → 書く前に利用者の許可を求める

止まるときは、書いた範囲と書かなかった範囲を分け、返す先（資料、実装の規約、利用者）と必要な決定を報告に示す。

判断の揺れでは、その時点の根拠から最も筋の良い形を仮説として採り、仮説であることと採らなかった形を報告に明示して進む。

- 入力の解決順や材料の取得順が資料に無い: 集約操作の事前条件が要る順に決め、報告に示す。

## チェックリスト

- [ ] 1 型 1 `Execute`。公開メソッドが他に無く、非公開関数に業務の判断が無い
- [ ] Input / Output が primitive の struct で、VO・集約・proto を持たない
- [ ] 入力の解決が `Run` の前にあり、VO の `New*` の error を文脈付きで返している
- [ ] `Run` の中が復元（または生成）→ 絞り込み → 操作 → 保存の順で、型スイッチ・`Status()`・`len(...) > 0`・時刻の比較が無い
- [ ] ID は `IDGenerator`、時刻は Input の `At` から来て、`time.Now()` も `Clock` も usecase に無い
- [ ] 保存がイベント型なら `Apply{Event}(ctx, res.Event)`、通常型なら `Create(ctx, res.Next)` / `Update(ctx, res.Next)` で、集約とイベントを取り違えていない
- [ ] `(Result, bool)` の false で nil を返し、sentinel を `errors.Is` で nil に読み替えていない
- [ ] 集約が 2 つ以上なら、資料の「一貫性」どおりに同じ `Run` か別 usecase になっている
- [ ] 集約の外で守る不変条件は、材料を読み取りポートで読み、判定はドメインのメソッドで、返すのは資料の sentinel
- [ ] `fmt.Errorf` が `return` ごとに 1 回で、`%w` が 1 つ。`errors.AsType` / `connect` / `log/slog` が無い
- [ ] 読み取りポートの interface が usecase 側にあり、DTO を返し、実装は注入されている

## 報告

- usecase の一覧（名前、command / query、対応する資料の業務イベントまたは一覧）
- 各 usecase の Input / Output と、Input の `At` を誰が埋めるか（RPC の入口 / worker）
- 依存の一覧（`Repository`、読み取りポートとその DTO、`IDGenerator`）
- 集約が 2 つ以上の usecase について、選んだ形（同じ tx / 別 usecase）と根拠になった資料の行
- 集約の外で守る不変条件と、読む材料・呼ぶ判定・返す sentinel
- 仮定したこと（資料に無い読み取りポート、DTO の列）と、資料またはドメインの実装と食い違った点
- 停止条件で返した論点
