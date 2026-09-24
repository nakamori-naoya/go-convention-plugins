# 標準ライブラリ（Go 1.27）

この reference は、`go fix ./...` を走らせた後に残ったものを直すときに読む。`min` / `max`、`clear`、`for range n`、ループ変数の複製の削除、`slices` と `maps` への置き換え、`strings.Cut` と `SplitSeq`、`sync.WaitGroup.Go`、`fmt.Appendf` のような書き換えは、`go fix` の modernizer が機械で行う。ここに置くのは、機械では決まらない判断だけである。

標準ライブラリで書けるものは、標準ライブラリで書く。自前の補助関数とサードパーティは、標準ライブラリに同じものが無いときだけ足す。

# 値と列挙

## `new(expr)` はポインタで渡す必要のある一時的な値だけ

Go 1.26 から、`new(expr)` で式のアドレスを取れる。使うのは、sqlc の nullable な引数や `omitzero` の任意の項目のように、ポインタで渡す必要のある一時的な値だけにする。ポインタを増やす理由にはしない。

## `iter.Seq` は、列挙そのものに価値があるときだけ

`iter.Seq[T]` と `iter.Seq2[K, V]` を返すのは、全件をメモリに載せられない（DB のカーソル、大きなファイル）か、呼び出し側が途中で止めたい（残りを作らない）か、内部の構造を隠して列挙だけを公開したいときだけである。数十件で終わる結果や、呼び出し側が結局 `slices.Collect` するものは、スライスで返す。イテレータは呼び出し側に `for range` を強い、`len` も添字も使えなくする。

# 時刻、乱数、識別子

## 時刻は UTC で持ち、`Clock` から取る

時刻は UTC で保持する。値オブジェクトの `New*` で `t.UTC()` に正規化すると、Location と monotonic clock の読みが揃い、`==` で比べられる値になる。表示のための時差の変換は、境界でだけ行う。`time.Local` に依存しない。業務の日付へ変えるときのタイムゾーンは、設定値として入口が受ける。

`time.Now()` を、ドメイン、usecase、リポジトリの本文で直接呼ばない。時刻は横断的関心事の `Clock` から取る。業務の判断に使う時刻は入口が、記録だけの時刻はリポジトリが、それぞれ一度だけ取る（apply-layer-convention が決める）。区間は半開（`start <= t < end`）にし、期間は `time.Duration` で持つ。

## 乱数と識別子

乱数は `math/rand/v2` を使い、秘密（トークン、鍵）は `crypto/rand` で作る。識別子の元になる UUID は、標準の `uuid` package（1.27）で採番し、サードパーティの uuid を足さない。採番は横断的関心事の採番器が一か所で行い、使う側がその場で識別子の値オブジェクトへ変換する。`time.Now().UnixNano()` を乱数や識別子の代わりにしない。

# 並行と寿命

## 裸の `go` には寿命を持たせる

goroutine を起動するときは、誰が終わりを待つか（`sync.WaitGroup` か `errgroup`）と、いつ止まるか（`ctx.Done()`）の両方が読めるようにする。どちらかが読めない `go` は書かない。goroutine が error を返すなら `golang.org/x/sync/errgroup` を使い、`errgroup.WithContext` で最初の失敗が残りを取り消すようにする。常駐するワーカーは、見張りの関数で起動する（write-logs が定める）。

共有する状態は、`sync.Mutex` を struct のフィールドに持ち（埋め込まない）、ロックの範囲を関数の先頭の `mu.Lock(); defer mu.Unlock()` で示す。

## ctx で運ぶのは、横断的な値だけ

期限は `context.WithTimeout` で付ける。取り消しの理由を伝えるなら `context.WithCancelCause` と `context.Cause`、親の取り消しの後にも後片付けを走らせるなら `context.WithoutCancel` を使う。`ctx.Value` で運ぶのは、リクエストの識別子、認可の主体、トランザクションのような横断的な値だけで、業務の値を載せない。キーは非公開の型にする。

# 入出力

## ファイルは `os.Root` で閉じ込める

利用者が指定したディレクトリの下だけを開くときは、`os.Root`（1.24）を使う。`..` やシンボリックリンクで外へ出るパスを拒む。`filepath.Clean` と `strings.HasPrefix` の自前の検査は書かない。シグナルは `signal.NotifyContext` で ctx に変える。

## JSON は `encoding/json/v2`

新しく書くコードは、`encoding/json/v2`（1.27 で正式）を使う。v2 は、フィールド名の照合で大文字と小文字を区別し、`nil` のスライスを `[]` に、`nil` の map を `{}` にする。「ゼロ値なら出さない」は `omitzero` で書く（`omitempty` は JSON として空のときだけ省く別の意味である）。未知のフィールドを拒みたい境界では、`json.RejectUnknownMembers(true)` を渡す。

json のタグを書くのは、境界の型（handler の入出力、設定のファイル、外部 API の型）だけで、ドメインの型には書かない。`map[string]any` に decode して型アサーションで取り出さない。JSON を値に写さず、構文として読む（大きな配列を一要素ずつ読む）ときだけ、`encoding/json/jsontext` を使う。

実験版で書いたコードは、1.27 の正式版で消えたもの（`format` と `unknown` のタグの option、`DiscardUnknownMembers`、`SkipFunc`）と、`inline` から `embed` への改名を直す。

# エラーと記録

外部の型のエラーは `errors.AsType[T]`（1.26）で判定する。アプリケーションのコードは標準の `errors` を直接 import せず、エラーの分類を持つ package が同じ名前で提供する `Is` と `AsType` を使う（handle-errors が決める）。

ログは、注入された logger で、ctx を取る形（`LogAttrs`、`InfoContext`）で出す。`slog.Default()` と `slog.SetDefault` に頼らない。複数の出力先は `slog.NewMultiHandler`（1.26）で束ねる（write-logs が決める）。

# テスト

テストの形は apply-go-test-convention が決める。標準ライブラリでは、ctx に `t.Context()`（1.24）、ベンチマークのループに `b.Loop()`（1.24）、テストの中のログに `t.Output()`（1.25）と `slog.DiscardHandler`（1.24）、成果物の置き場に `t.ArtifactDir()`（1.26）を使う。

時間に依存する並行のコード（期限、再試行の間隔）のテストだけ、`testing/synctest`（1.25）の仮想時計の中で走らせる。本物の `time.Sleep` でタイミングを合わせない。
