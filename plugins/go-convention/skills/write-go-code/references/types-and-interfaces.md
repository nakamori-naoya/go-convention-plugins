# 型と interface

型は「不正な値を作れない」ように作り、interface は「使う側が要る分だけ」切る。抽象は要るところにだけ置き、具象は名前で読める形で返す。

# 業務の概念を型にする

## 値オブジェクト

業務や運用の意味を持つ値は、非公開フィールドの struct と、検証する `New*` で表す。値の形が条件を満たさなければ、`New*` が error を返す。構造体のフィールド、引数と戻り値、イベント、usecase の入出力、読み取りモデル、テストデータのどこでも、その概念を `string`、整数、浮動小数、`bool`、`time.Time` のまま持たない。

```go
// UserNo は、図書館が利用者に振る利用者番号である。例: "U-000123"。
type UserNo struct {
	v string
}

func NewUserNo(s string) (UserNo, error) {
	if !userNoPattern.MatchString(s) {
		return UserNo{}, ErrUserNoMalformed
	}
	return UserNo{v: s}, nil
}

func (n UserNo) Value() string {
	return n.v
}
```

向きで分けて考える。外から入ってくる値（要求、外部サービスの応答、設定）は、境界で値オブジェクトへ変換する。外部サービスの応答を写した型も例外にしない。外部の契約であることは、その値がサービスの中でどの概念かを型で言い表さない理由にならない。ポートの interface の引数と戻り値にも、プリミティブを置かない。

外へ出す写しは逆向きである。プリミティブへ戻すのは、外部の形式（DB の生成型、proto、ログの属性）へ写す変換の内側だけである。ログの属性へ何をどう渡すかは、write-logs が決める。

値オブジェクトを作る前に、同じ意味の型が既にないかを探す。複数の文脈で使う値オブジェクトの置き場は、apply-go-package-layout が決める。

## 取りうる値が有限なら、封じた型にする

状態、種別、方式のように取りうる値が有限なら、非公開フィールドを一つ持つ struct と、その package 変数で表す。package の外から新しい値を作れないので、列挙の外の値は存在しない。文字列との往復は `Parse<型>(s string) (<型>, error)` と `Value() string` で行い、`Parse` は知らない文字列を error で返す。

```go
type Status struct{ v string }

var (
	StatusOnLoan   = Status{"on_loan"}
	StatusOverdue  = Status{"overdue"}
	StatusReturned = Status{"returned"}
)

func ParseStatus(s string) (Status, error) {
	switch s {
	case StatusOnLoan.v:
		return StatusOnLoan, nil
	case StatusOverdue.v:
		return StatusOverdue, nil
	case StatusReturned.v:
		return StatusReturned, nil
	default:
		return Status{}, ErrUnknownStatus
	}
}
```

`type Status string` と `const` の組は使わない。型変換で列挙の外の値を作れ、`switch` の網羅を lint に頼ることになるからである。封じた型は、不正な値を作れないので、検査そのものが要らない。値は一か所で定義し、変換やテストの期待値でも同じ package 変数を使う。同じ文字列を別の場所で繰り返さない。

## 状態の和は、封じた interface にする

「A または B または C」は、非公開メソッドを一つ持つ interface と、それを実装する型で表す。非公開メソッドがあるので、package の外の型は実装できず、和が閉じる。`gochecksumtype` に網羅を検査させるため、interface の宣言に `//sumtype:decl` を付ける。どの型を和にし、和にどのメソッドを置くかは、implement-domain-model が決める。

`Kind` フィールドと全状態のフィールドを一つの struct に持つ形にはしない。どの状態でどのフィールドが有効かが、型で分からなくなる。

## ゼロ値

値オブジェクトと集約のゼロ値は無効で、作るのは `New*` と `Restore*` だけである。設定、バッファ、カウンタのような道具の型は、`strings.Builder` や `sync.Mutex` と同じく、ゼロ値のまま使える形にする。どちらの型かは、それが業務の概念か、それを支える道具かで決まる。

## 型エイリアス

別の型として区別したいなら、defined type（しかも非公開フィールドの struct）にする。`type UserNo = string` のようなエイリアスは、`string` と互換なので取り違えを検出できない。エイリアスは、型の移動の途中のように、同じ型に別の名前が要るときだけに使う。

# interface

## 使う側で小さく切り、実装側は struct を返す

interface は、それを引数に取る package が、そこで呼ぶメソッドだけを持つ形で定義する。実装の package は具象の struct（のポインタ）を返し、呼び出し側で interface に代入する。実装側で「この型ができること全部」の interface を公開しない。同じ package の具象型や、内向きに依存して済む相手を、理由無く interface で包まない。

interface が要る理由は二つしかない。依存の向きを内向きに保つため（実装の package を import しない）と、テストで差し替えるため（差し替えてよい境界だけ。apply-go-test-convention が決める）である。どちらも無い interface は、型を一つ増やすだけで、検査できることが増えない。

実装しているかは、実装側で一行、コンパイル時に確かめる。

```go
var _ domain.LoanRepository = (*LoanRepository)(nil)
```

## 例外は三つ

**集約の永続化ポート**は、集約と同じ package（ドメイン）が定義する。偽物を作らないテスト方針では、使う側で切る利点が消え、契約を集約ごとに一か所へ置く利点が勝つからである。

**状態の和**は、状態の型を定義する package が定義する。和を閉じるのは、型を定義する package の仕事だからである。

**差し替えるためだけにある技術境界**（時計、採番器）の interface は、それを所有する横断的関心事の package に一つだけ置く。使う側の数だけ interface や mock を増やしても、守られるものが無いからである。

```go
// clock は、現在時刻の取得を差し替えられるようにする。
package clock

//go:generate go run go.uber.org/mock/mockgen -source=clock.go -destination=mock/clock.go -package=mock_clock

type Clock interface {
	Now() time.Time
}
```

採番器は、業務の概念をまだ持たない UUID だけを返し、使う側がその場で識別子の値オブジェクトへ変換する。識別子の種類ごとに採番器やメソッドを増やさない。

外部サービスの照会のように、制御できない外部の境界のポートは、使う側が所有する（原則どおり）。

横断的関心事の型（時計、採番器、トランザクションの管理）は、一つの目的だけを持たせ、公開するメソッドは外から実際に呼ばれるものだけにする。便利そうな操作を足していくと、どの層からでも何でもできる置き場になり、層の線が消えるからである。

## interface と実装は、ファイルを分ける

interface は、自分の名前のファイル（`Clock` なら `clock.go`、`NoticePublisher` なら `notice_publisher.go`）に単独で置く。そのファイルに置くのは、`go:generate`（mock の生成元）と、その契約に固有のエラーだけである。実装する型は、その型の名前のファイル（`System` なら `system.go`）に置く。生成コードは対象外である。

こうすると、契約と実装を別々に読め、契約だけを変える差分と実装だけを変える差分が混ざらない。

## 関数型で足りるなら interface にしない

呼び出し側が振る舞いを一つだけ要し、状態を持たないなら、関数型（`func(ctx context.Context) error`）にする。状態を持つか、複数の実装を名前で区別したいときだけ interface にする。

# any、generics、埋め込み

## `any` は、値の型が実行時まで決まらない境界だけ

`any` を使うのは、JSON の decode、`slog` の属性値、`sql.Scanner` のように、値の型が実行時まで決まらない境界だけである。受け取ったら、すぐに具象型か generics に戻す。`map[string]any` を業務のデータ構造に使わない。`any` を使うと、型の検査が実行時まで先送りになる。

## generics は、同じアルゴリズムを複数の型に使うときだけ

型パラメータを使うのは、同じアルゴリズムを複数の型に適用するとき（`slices.SortFunc` のような操作）だけである。使う型が一つしか無いのに型パラメータを付けない。メソッドを持たない入れ物を generics で作らない（集約のコマンドの結果は、コマンドごとの具体の struct にする）。振る舞いの違いは interface で、型の違いは generics で表す。

Go 1.27 からメソッドが自分の型パラメータを持てる（ジェネリックメソッド）が、既定では使わない。package 関数で書けるものは、package 関数で書く。ツールの対応が追いついておらず、package 関数なら従来の知識で読めるからである。

## struct を埋め込んで実装を共有しない

struct を埋め込むと、埋め込んだ型の公開メソッドが外側の型の API に昇格し、意図しないメソッドが公開される。共有したい実装は、非公開の関数に切り出して呼ぶ。`sync.Mutex` はフィールドに持ち、埋め込まない。interface の埋め込みで役割を合成するのはよい。
