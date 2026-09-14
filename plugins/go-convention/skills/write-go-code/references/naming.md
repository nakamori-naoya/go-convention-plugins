# 命名

**名前は呼び出し側で読まれる。** 定義側で「説明的」に見える名前（`GetID` / `ReservationRepositoryImpl` / `reservationutil`）は、呼び出し側では冗長か、何も言っていない。名前は `package.Name` の形で読んだときに 1 回で意味が通ることを基準に決める。

## 1. package 名

**する:** 短い 1 語の小文字。単数形。ディレクトリ名と一致。中身が何であるか（`reservation` / `rdb` / `query` / `usecase` / `handler` / `tx`）。テスト支援 package は Go 慣習の `{pkg}test`（`rdbtest`）。
**しない:** `util` / `utils` / `common` / `base` / `helpers` / `misc` / `shared` / `types` / `models`。アンダースコアや MixedCaps（`room_flow` / `roomFlow`）。複数形（`reservations`）。

```go
// しない: 何も言っていない。何でも入る
package util

// する
package reservation
```

`util` / `common` が要ると感じたら、置きたい関数の**呼び出し側**を見る。呼び出し側が 1 package なら、その package に置く。複数なら、その関数が属する概念の名前が package 名になる。

理由: package 名は呼び出し側の全行に現れる。`util.Clamp` は何の util か毎回考えさせ、`common` は「どこにも属さない」の言い換えで、依存の向きを壊す入口になる。

## 2. 型名に package 名を繰り返さない

**する:** `reservation.ID` / `reservation.Tentative` / `rdb.ReservationRepository`（`rdb` は複数集約のリポジトリを持つので集約名が要る）。
**しない:** `reservation.ReservationID` / `reservation.ReservationTentative`。

理由: 呼び出し側は常に `reservation.ReservationID` と読む。同じ語が 2 回並ぶ。

## 3. 頭字語は全部大文字か全部小文字

**する:** `ID` / `URL` / `HTTP` / `JSON` / `DB` / `RDB` / `SQL` / `API`。公開なら `ReservationID` / `ParseURL`、非公開なら `reservationID` / `parseURL`。
**しない:** `Id` / `Url` / `Http` / `Json` / `Db`。

理由: Go の標準ライブラリ（`http.StatusOK` / `url.URL` / `json.Marshal`）と揃う。`Id` と `ID` が混ざると同じ概念が 2 つの綴りを持ち、検索で片方を落とす。

## 4. getter に `Get` を付けない

**する:** `func (r Tentative) ID() ID`、`func (v Version) Value() int`、`func (c Confirmed) NoShowAt() (time.Time, bool)`。bool を返す問い合わせは `Is` / `Has` / `Can` で始める（`HasArrived` / `CanApply` / `IsZero`）。
**しない:** `GetID()` / `GetValue()`。setter（`SetX`）を不変の型に書く。

```go
// しない
func (r Tentative) GetID() ID

// する
func (r Tentative) ID() ID
```

状態を変えるメソッドは業務の動詞（`Confirm` / `Cancel` / `Expire` / `RecordNoShow`）。`SetX` は設定用の可変な型（オプション・ビルダー）にだけ許す。ドメインの型は不変なので `SetX` は現れない。

理由: `Get` は情報を足さない。`r.ID()` と `r.GetID()` は同じ意味で、前者が短い。Go の標準ライブラリに `Get` 接頭辞の getter は無い。

## 5. 等値は `Equal`

**する:** `func (t TimeSlot) Equal(o TimeSlot) bool`（`time.Time.Equal` / `bytes.Equal` / `reflect.DeepEqual` と同じ）。ただし `==` で比べられる型（非公開フィールドが全部 comparable で正規化済み）には `Equal` を書かず `==` を使う。
**しない:** `Equals` / `IsEqual` / `Same`。

理由: 標準ライブラリの語彙と揃える。`==` が使える型に `Equal` を足すと、呼び出し側で `==` と `Equal` のどちらが正しいか分からなくなる。

## 6. レシーバ名は 1〜2 文字、型内で一貫

**する:** 型名の頭文字（`Tentative` は `t`、`Confirmed` は `c`、`ReservationRepository` は `r`、`Manager` は `m`）。同じ型の全メソッドで同じ名前。
**しない:** `this` / `self` / `me`。メソッドごとに違う名前。長い名前（`reservation` / `repo`）。

```go
func (t Tentative) Confirm(at time.Time, by CustomerID) (ConfirmResult, error)
func (t Tentative) Cancel(at time.Time, by CustomerID) (CancelResult, error)
func (t Tentative) Expire(at time.Time) (ExpireResult, bool)
```

理由: レシーバはメソッド本文で最も頻繁に現れる。短いほど本文が読める。型内で揃えると、メソッドを移動・コピーしたときに名前を直す作業が消える。

## 7. interface 名

**する:** 1 メソッドは動詞 + `er`（`Reader` / `Clock` は例外的に名詞で慣習）。複数メソッドは役割の名詞（`Repository` / `Event` / `Reservation`）。
**しない:** `I` 接頭辞（`IRepository`）。実装側に `Impl` 接尾辞（`RepositoryImpl`）。

```go
// しない
type IReservationRepository interface{ ... }
type ReservationRepositoryImpl struct{ ... }

// する: interface は役割、実装は「何で実装したか」
type Repository interface{ ... }        // package reservation
type ReservationRepository struct{ ... } // package rdb
```

理由: interface が主役で、実装は差し替え可能な側である。`Impl` は「実装であること」しか言わず、`rdb.` の package 名が既に「RDB で実装した」と言っている。

## 8. コンストラクタと復元

**する:** 生成は `New{型}`（1 package に 1 型なら `New`）。生成の条件で拒む組があるときだけ `(T, error)`、無いなら `T`。永続化からの復元は `Restore{型}`（検証しない。どの操作に復元を使うかはドメインモデルの規約が決める）。生成と復元を同じ関数にしない。
**しない:** `Create` / `Make` / `Build`。`Must{型}` を本番コードで使う（`regexp.MustCompile` のような「失敗すればプログラムの誤り」だけに限る）。

```go
func NewTimeSlot(room RoomCode, start, end time.Time) (TimeSlot, error) // 拒む組がある
func NewHoldDeadline(heldAt time.Time) HoldDeadline                     // 拒む組が無い
func RestoreTentative(id ID, customer CustomerID, slot TimeSlot, deadline HoldDeadline, v Version) Tentative
```

理由: `New` は「検証して作る」、`Restore` は「検証済みの値を組み立て直す」で、呼び出し側が何を期待できるかが名前で決まる。

## 9. sentinel と error 型

**する:** sentinel は `Err{何が拒まれたか}`（`ErrNotOwner` / `ErrHoldDeadlinePassed`）。error を実装する型は `{何}Error`（`*pgconn.PgError` のように外部型を翻訳するときに参照する）。文言・包み方・翻訳はエラーの規約が決める。
**しない:** `Error` 接頭辞（`ErrorNotOwner`）。`Err` 接尾辞（`NotOwnerErr`）。

理由: `errors.Is(err, reservation.ErrNotOwner)` と読んだときに、それが sentinel だと綴りで分かる。

## 10. 結果と入力の struct

**する:** 操作の結果は `{操作}Result`（`ConfirmResult` / `HoldResult`）。usecase の入力は `{usecase}Input`（`ConfirmReservationInput`）。変換の引数は `{先}Params`（sqlc の `InsertReservationParams` に揃える）。
**しない:** `Response` / `Output` / `DTO` / `Req` / `Res` の混在。

理由: 結果型の綴りが揃うと、`XResult` を見た瞬間に「操作 X の返り値」だと分かる。

## 11. 変換関数

**する:** `{元}To{先}`（`heldToInsertReservationParams` / `reservationRowToReservation`）。何を何にするかを名前だけで言う。
**しない:** `convert` / `map` / `transform` / `toDomain` / `fromRow`（元か先のどちらかが名前に無い）。

理由: 変換は同じ package に何本も並ぶ。元と先が名前に無いと、呼び出し側でシグネチャを見に行く。

## 12. 変数

**する:** スコープが短いほど短く（`i` / `tt` / `err` / `ctx` / `tx` / `evt` / `res`）。スコープが長いほど説明的に。エラーは常に `err`。`context.Context` は常に `ctx`。
**しない:** `data` / `info` / `obj` / `tmp` / `result`（何のデータかが無い）。1 文字の名前を関数の先頭から末尾まで生かす。同じ意味の変数に 2 つの名前（`reservation` と `rsv`）。

理由: 短い名前は近くに定義があるから読める。遠くに定義がある名前は、定義を見ずに意味が要る。

## 13. 定数

**する:** MixedCaps（`holdTTL` / `MaxPageSize`）。値の意味を名前にする。
**しない:** `ALL_CAPS`（`HOLD_TTL`）。マジックナンバーを本文に埋める。

理由: Go の定数は識別子であって前処理マクロではない。`ALL_CAPS` は他の識別子と綴りの規則が変わり、頭字語の規則（§3）とも衝突する。

## 14. ファイル名

**する:** 小文字 snake_case（`reservation.go` / `reservation_repository.go` / `errors.go`）。テストは `{本体}_test.go`。型ごと・関心ごとに分け、1 ファイルに 1 集約の状態型と操作をまとめる。
**しない:** MixedCaps（`ReservationRepository.go`）。`impl.go` / `helpers.go` / `misc.go` / `types.go` / `interfaces.go`（何が入っているか分からない名前）。

理由: ファイル名は `go test -run` の結果やスタックトレースで最初に目に入る。中身を言う名前なら開かずに当たりが付く。
