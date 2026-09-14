# 型と interface

**型は「不正な値を作れない」ように設計し、interface は「使う側が要る分だけ」定義する。** 抽象は要るところにだけ置き、具象は名前で読める形で返す。

## 1. interface は使う側で小さく定義し、実装側は struct を返す

**する:** interface は、それを引数に取る package が、そこで呼ぶメソッドだけを持つ形で定義する。実装側の package は具象の struct（ポインタ）を返す。呼び出し側で interface に代入する。
**しない:** 実装側で「この型ができること全部」の interface を export する。1 メソッドしか呼ばないのに 6 メソッドの interface に依存する。

```go
// package usecase（使う側）。ID の採番と読み取りは usecase が要る分だけ定義する
type IDGenerator interface {
	NewReservationID() (reservation.ID, error)
}

type HoldReservation struct {
	tx      *tx.Manager
	repo    reservation.Repository
	active  ActiveReservationReader
	noShows NoShowReader
	ids     IDGenerator
}

// package handler（使う側）。時刻の取得は handler が要る分だけ定義し、usecase の入力の At に入れる
type Clock interface {
	Now() time.Time
}

// package rdb（実装側）。struct のポインタを返す。interface を返さない
func NewReservationRepository() *ReservationRepository {
	return &ReservationRepository{}
}
```

**例外を 2 つだけ置く。集約の永続化ポート（リポジトリの interface）と、状態の和型（sealed interface）はドメイン（集約と同じ package）が定義する。**

```go
// package reservation（ドメイン）が定義する。usecase はこれに依存し、rdb がこれを実装する
type Repository interface {
	FindByID(ctx context.Context, id ID) (Reservation, error)
	ApplyHeld(ctx context.Context, evt Held) error
	ApplyConfirmed(ctx context.Context, evt ConfirmedEvent) error
	ApplyCancelled(ctx context.Context, evt CancelledEvent) error
	ApplyExpired(ctx context.Context, evt ExpiredEvent) error
	ApplyNoShowRecorded(ctx context.Context, evt NoShowRecorded) error
}
```

理由: 使う側で定義すれば、interface は呼ぶメソッドだけを持ち、テストや差し替えの単位が「この関数が要るもの」に一致する。永続化ポートが例外なのは、偽物を作らないテスト方針では「使う側で切る利点」が消え、契約を集約ごとに 1 か所へ置く利点が勝つからである。和型が例外なのは、和を閉じるのが型を定義する package の仕事だからである（§6）。ポートと和型の中身はドメインモデルの規約が決める。

### 実装しているかをコンパイル時に確かめる

```go
// package rdb
var _ reservation.Repository = (*ReservationRepository)(nil)
```

理由: メソッドの綴りを間違えても、interface に代入する行が遠い package にあると、そこまでコンパイルが通ってしまう。実装側の 1 行で止める。

## 2. `any` は真に多相な境界だけ

**する:** `any` を使うのは、値の型が実行時まで決まらない境界（JSON の decode、`slog` の属性値、`sql.Scanner`）だけ。受け取ったら直ちに具象型か generics に戻す。
**しない:** 引数や戻り値を `any` にして「何でも受ける」関数を書く。`map[string]any` を業務のデータ構造に使う。`interface{}` と綴る。

理由: `any` は型検査を実行時へ先送りする。呼び出し側は何を渡せるか分からず、受け取り側は型アサーションを書き、どちらの誤りもコンパイルで止まらない。

## 3. generics は「同じアルゴリズムを複数の型に」だけ

**する:** 型パラメータを使うのは次の 2 つのどちらかのとき。
1. 同じアルゴリズムを複数の型に適用する（`slices.SortFunc` のような操作）
2. 型ごとに同じ補助型を量産しないため（題材の遷移結果型）

```go
// 2 の例。状態ごとに ConfirmResult / CancelResult ... の struct を 5 つ書く代わりに 1 つの generic 型
type Transition[S Reservation, E Event] struct {
	Next  S
	Event E
}

type ConfirmResult = Transition[Confirmed, ConfirmedEvent]
type CancelResult = Transition[Cancelled, CancelledEvent]
```

**しない:** 使う型が 1 つしか無いのに型パラメータを付ける。interface で足りる場面に generics を使う（振る舞いの差は interface、型の差は generics）。制約 interface を実装側 package に export して依存を作る。

理由: generics は読み手に型の代入を頭の中でさせる。具象型で書けるなら具象型が最も読める。

### ジェネリックメソッド（Go 1.27）

Go 1.27 からメソッドが自分の型パラメータを持てる。**既定では使わない。** 使うのは、型パラメータがレシーバの型ではなく引数だけで決まり、package 関数にすると名前が `{型}{動詞}` になって型名を繰り返す 1 行の変換に限る。それ以外は従来どおり package 関数（`func Map[T, U any](s []T, f func(T) U) []U`）に置く。

理由: 1.27 で入ったばかりの機能で、ツール（lint・IDE）の対応が追いついていない。package 関数で書けるものを package 関数で書けば、移行も検索も従来の知識で足りる。

## 4. 型パラメータの自己参照制約（Go 1.26）

Go 1.26 から `type Adder[A Adder[A]] interface{ Add(A) A }` のように制約が自分を参照できる。使うのは「同じ型同士の演算」を generic に書くときだけ。題材には現れない。

## 5. 列挙は封じた struct ＋ package 変数

**する:** 列挙は非公開フィールドを 1 つ持つ struct と、その package 変数で表す。文字列との往復は `Parse{型}(s string) ({型}, error)` と `{型}.Value() string`。`switch` の `default` は `error` を返す。
**しない:** `type Kind int` / `type Kind string` の defined basic type ＋ `const ( ... iota )`。`default` で既定値に丸める。`default` で `panic` する。

```go
// しない: Kind(42) や Kind("unknown") で列挙の外の値を作れる
type Kind string

const (
	KindTentative Kind = "tentative"
	KindConfirmed Kind = "confirmed"
)

// する: package 外から Kind{"x"} は書けない（フィールドが非公開）。値は package 変数だけ
type Kind struct{ v string }

var (
	KindTentative = Kind{"tentative"}
	KindConfirmed = Kind{"confirmed"}
	KindCancelled = Kind{"cancelled"}
	KindExpired   = Kind{"expired"}
)

var ErrUnknownKind = errors.New("予約の種別が不明")

func ParseKind(s string) (Kind, error) {
	switch s {
	case KindTentative.v:
		return KindTentative, nil
	case KindConfirmed.v:
		return KindConfirmed, nil
	case KindCancelled.v:
		return KindCancelled, nil
	case KindExpired.v:
		return KindExpired, nil
	default:
		return Kind{}, ErrUnknownKind
	}
}

func (k Kind) Value() string { return k.v }
func (k Kind) IsZero() bool  { return k == Kind{} }
```

理由: defined basic type は型変換で列挙の外の値を作れ、`switch` の網羅を lint（`exhaustive`）に頼ることになる。封じた struct は不正な値を**作れない**ので、検査そのものが要らない。`default` で丸めると DB の壊れた行が正常な種別として通る。`panic` すると境界でエラーに翻訳できない。

## 6. 型の和は sealed interface

**する:** 「A または B または C」は、非公開メソッドを 1 つ持つ interface と、それを実装する型で表す。非公開メソッドがあるので package 外の型は実装できない（和が閉じる）。型スイッチは実装する型を全部列挙し、`default` に来るのは nil だけなので sentinel（`ErrNoReservation`）を返す。`gochecksumtype` に網羅を検査させるため interface 宣言に `//sumtype:decl` を付ける。
**しない:** `Kind` フィールド ＋ 全状態のフィールドを 1 struct に持つ（どの状態でどのフィールドが有効かが型で分からない）。公開メソッドだけの interface（package 外で勝手に実装される）。

```go
//sumtype:decl
type Reservation interface {
	ID() ID
	Customer() CustomerID
	Slot() TimeSlot
	Version() Version
	isReservation()
}

func AsTentative(r Reservation) (Tentative, error) {
	switch v := r.(type) {
	case Tentative:
		return v, nil
	case Confirmed:
		return Tentative{}, ErrAlreadyConfirmed
	case Cancelled:
		return Tentative{}, ErrAlreadyCancelled
	case Expired:
		return Tentative{}, ErrAlreadyExpired
	default:
		return Tentative{}, ErrNoReservation
	}
}
```

どの型を和にし、どの操作をどの型に置くかはドメインモデルの規約が決める。ここでは Go での表し方だけを決める。

理由: 型で状態を分けると、「確定済みに確定を呼ぶ」はメソッドが無いのでコンパイルで止まる。`Kind` フィールド方式は全操作が全状態で呼べてしまい、状態違いの検査を全メソッドに書くことになる。

## 7. ゼロ値が有効な基盤型は、ゼロ値のまま使える設計にする

**する:** 設定・バッファ・カウンタ・オプションのような基盤型は、`var b strings.Builder` / `var mu sync.Mutex` と同じく、ゼロ値で使えるようにする（フィールドのゼロ値が「既定の振る舞い」になる形にする。ただし §基本 の「暗黙の既定」とは違い、ゼロ値が意味を持つ型として文書化する）。
**しない:** コンストラクタを呼ばないと `nil` map に書き込んで panic する基盤型。

ドメインの値オブジェクトと集約はこの規則の対象外で、ゼロ値は無効（生成は `New*` / `Restore*` だけ）。どちらの型なのかは、その型が業務の概念か、それを支える道具かで決まる。

理由: Go はゼロ値を避けられない（`var x T`、struct のフィールド、map の欠損）。道具の型がゼロ値で使えれば、呼び忘れの `New` が無くなる。業務の型はゼロ値を無効にしなければ「空の予約」が生まれる。

## 8. 埋め込み

**する:** interface の埋め込みで役割を合成する（`type Active interface { Reservation; Cancel(...) }`）。
**しない:** struct の埋め込みで実装を共有する。埋め込んだ型の公開メソッドが外側の型の API に昇格し、意図しないメソッドが公開される。`sync.Mutex` を埋め込む（`Lock` / `Unlock` が公開される）。

理由: struct 埋め込みは「is-a」に見えて継承ではなく、API の漏れを作る。共有したい実装は非公開の関数に切り出して呼ぶ。

## 9. 型エイリアスと defined type

**する:** `type HoldResult = Transition[Tentative, Held]` のように、generic 型の具体化に名前を付けるときだけ型エイリアス（`=`）を使う。別の型として区別したいなら defined type（`type ID struct{ v string }`）。
**しない:** `type UserID = string` のようなエイリアスで型を「名付けただけ」にする（`string` と互換なので取り違えを検出できない）。

理由: エイリアスは同じ型の別名で、型検査上は何も足さない。区別が要るなら defined type、しかも defined basic type ではなく非公開フィールドの struct（§5 と同じ理由）。

## 10. 関数型と 1 メソッド interface

**する:** 呼び出し側が「振る舞い 1 つ」しか要らず、状態を持たないなら関数型（`func(ctx context.Context) error`）。状態を持つか、複数の実装を名前で区別したいなら interface。
**しない:** 関数型で足りるところに 1 メソッド interface と実装 struct を作る。

理由: `tx.Manager.Run(ctx, func(ctx context.Context) error)` のような 1 回きりの処理に interface と struct を作ると、型が 2 つ増えて呼び出し側の行数が増えるだけで、検査できることは増えない。
