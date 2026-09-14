# 標準ライブラリ（Go 1.27）

**標準で書けるものは標準で書く。** 自前の補助関数とサードパーティは、標準ライブラリに同じものが無いときだけ足す。各項目に「どの版から使えるか」を付ける。Go 1.26 / 1.27 の項目は公式リリースノートで確認できたものだけを書いている。

## 1. 組み込み

| 書く | 書かない | 版 |
|---|---|---|
| `end := min(i+size, len(items))` | 自前の `minInt` / `if a < b { ... }` | 1.21 |
| `clear(m)` | `for k := range m { delete(m, k) }` | 1.21 |
| `for i := range n {` | `for i := 0; i < n; i++ {` | 1.22 |
| ループ変数をクロージャや goroutine でそのまま使う | `x := x`（反復ごとに新しい変数になった） | 1.22 |
| `p := new(yearsSince(born))`（式のアドレスを取る） | `v := yearsSince(born); p := &v` | 1.26 |
| 埋め込み型の昇格フィールドを struct リテラルのキーに書く | 埋め込み型のリテラルを入れ子で書く | 1.27 |

`new(expr)` は「ポインタで渡す必要のある一時的な値」（sqlc の nullable 引数、`omitzero` の対象にする任意項目）にだけ使う。ポインタを増やす理由にはしない（ポインタの規則は基本の規約）。

## 2. `slices` / `maps` / `iter`

**する:** 検索・整列・複製・比較は `slices` と `maps`。map のキーを整列して列挙するときは `slices.Sorted(maps.Keys(m))`。イテレータをスライスにするのは `slices.Collect`。渡されたスライスを変えずに返すときは `slices.Clone`。
**しない:** `sort.Slice` / `sort.Strings`（`slices.SortFunc` / `slices.Sort` に置き換わった）。自前のループ検索（`slices.Contains` / `slices.IndexFunc`）。`reflect.DeepEqual` での比較（`slices.Equal` / `maps.Equal` / `==`）。

```go
for _, room := range slices.Sorted(maps.Keys(byRoom)) { // 1.23（maps.Keys が iter.Seq を返す）
	// 出力順が安定する
}

sorted := slices.SortedFunc(slices.Values(slots), func(a, b TimeSlot) int { // 1.23
	return a.Start().Compare(b.Start())
})
```

| 関数 | 版 |
|---|---|
| `slices.Contains` / `Index` / `IndexFunc` / `Sort` / `SortFunc` / `Clone` / `Equal` / `Compact` / `Reverse` / `BinarySearch` | 1.21 |
| `maps.Clone` / `Equal` / `DeleteFunc` | 1.21 |
| `slices.Collect` / `Sorted` / `SortedFunc` / `Values` / `All` / `Chunk`、`maps.Keys` / `Values` / `All` / `Collect` | 1.23 |

理由: 自前のループは同じ処理を毎回違う形で書き、境界（空・1 件・重複）の扱いが場所ごとに変わる。標準関数は名前が意図を言う。

## 3. `iter.Seq` は列挙そのものに価値があるときだけ（1.23）

**する:** `iter.Seq[T]` / `iter.Seq2[K, V]` を返すのは、次のどれかが要るとき。
- 遅延（全件をメモリに載せられない。DB のカーソル、大きなファイルの行）
- 早期終了（呼び出し側が途中で `break` でき、残りを生成しない）
- 内部構造を晒さず列挙だけを公開したい（コレクションを持つ型の `All()`）

**しない:** 数十件で終わる結果を `iter.Seq` で返す。呼び出し側が結局 `slices.Collect` するものをイテレータにする。

```go
// する: 行数が多く、呼び出し側が途中で止めたい
func (q *RoomAvailabilityQuery) EachSlot(ctx context.Context, room string) iter.Seq2[AvailableSlot, error]

// しない: 1 日分の枠は数十件。スライスで返す
func (q *RoomAvailabilityQuery) ListForDay(ctx context.Context, room string, day time.Time) (RoomAvailability, error)
```

理由: イテレータは呼び出し側に `for range` を強制し、`len` も添字も使えない。小さな結果はスライスの方が呼び出し側の選択肢が多い。

## 4. `strings` / `bytes`

| 書く | 書かない | 版 |
|---|---|---|
| `before, after, found := strings.Cut(s, ":")` | `strings.SplitN(s, ":", 2)` ＋ 長さ検査 | 1.18 |
| `for line := range strings.Lines(text) {` | `strings.Split(text, "\n")` で全行を一度に作る | 1.24 |
| `for part := range strings.SplitSeq(s, ",") {`（ループで消費するとき） | `for _, part := range strings.Split(s, ",")` | 1.24 |
| `for f := range strings.FieldsSeq(s) {` | `strings.Fields(s)` をループで消費 | 1.24 |
| `dir, base, found := strings.CutLast(path, "/")` | `i := strings.LastIndex(path, "/")` ＋ 添字計算 | 1.27 |
| `bytes.CutLast` | `bytes.LastIndex` ＋ 添字計算 | 1.27 |

`strings.Lines` の各行は末尾の改行を含む。取るなら `strings.TrimSuffix(line, "\n")`。結果をスライスとして持ち回るなら従来の `Split` のままにする（イテレータにする理由は §3）。

理由: `Cut` 系は「見つかったか」を bool で返し、添字の計算を消す。`Seq` 系は中間スライスを作らない。

## 5. `time`

**する:**
- 時刻は UTC で保持する。値オブジェクトの `New*` で `t.UTC()` に正規化する。`UTC()` は `Location` を UTC にし、monotonic clock reading も落とす（`In` / `Local` / `UTC` はどれも落とす）ので、これだけで `==` で比べられる値になる。`Round(0)` は要らない（`Location` と monotonic が残ると同じ瞬間でも `==` が偽になる）。表示用の時差変換は境界（handler）でだけ行う
- `time.Now()` を呼ぶのは境界（handler が `Clock` から取って usecase の入力の `At` に入れる、worker）で **1 回**。同じ処理の中で 2 回呼ばない。usecase は `Clock` を持たず入力の `At` を使い、ドメインは `at time.Time` を引数で受ける
- 比較は `Equal` / `Before` / `After` / `Compare`。区間は半開（`start <= t < end`）で、含むかどうかは `!t.Before(start) && t.Before(end)` と書く（隣接する区間が重ならない）
- 期間は `time.Duration`。`int` の秒・ミリ秒を持ち回らない

**しない:** `time.Local` に依存する（コンテナの TZ 設定で結果が変わる）。ドメインで `time.Now()` を呼ぶ。`time.Time` の `==`（正規化していない型）。

```go
func NewTimeSlot(room RoomCode, start, end time.Time) (TimeSlot, error) {
	start, end = start.UTC(), end.UTC()
	if !start.Before(end) {
		return TimeSlot{}, ErrTimeSlotNotOrdered
	}
	return TimeSlot{room: room, start: start, end: end}, nil
}
```

Go 1.27 から `time` のタイマーチャネルは常に同期（バッファ無し）で、GODEBUG `asynctimerchan` は消えた。`time.After` の結果を受け取らずに捨てても、タイマーは GC される。

理由: 「同じ時刻」の判定が Location と monotonic に依存すると、DB から復元した値と生成した値が一致せず、テストが環境で揺れる。`time.Now()` が散ると 1 つの操作の中で「今」が複数になる。

## 6. 乱数と識別子

**する:** 乱数は `math/rand/v2`（1.22）。`rand.IntN(n)` / `rand.N(d)`（generic。`time.Duration` にも使える）。秘密（トークン・鍵）は `crypto/rand`。識別子の採番は標準の `uuid` package（1.27 で追加）を使い、サードパーティの uuid を足さない（API は pkg.go.dev で確認する）。採番は境界（usecase の `IDGenerator`）が行い、ドメインは `id ID` を引数で受ける。
**しない:** `math/rand`（v1）。`rand.Seed`。`time.Now().UnixNano()` を乱数や識別子の代わりにする。

Go 1.27 から `*rand.Rand` にも generic な `N` メソッドがある（トップレベルの `rand.N` と同じ振る舞い）。

理由: v1 はグローバルな seed と `Seed` の呼び忘れで再現性が壊れる。v2 は初期化が要らず、generic な `N` が型ごとの関数を消す。

## 7. ファイルとプロセス

**する:** 利用者が指定したディレクトリの下だけを開くときは `os.Root`（1.24）。`root.Open(name)` は `root` の外へ出るパス（`..` / シンボリックリンク）を拒む。シグナルは `signal.NotifyContext`（1.16。1.26 から `context.Cause(ctx)` で受けたシグナルが読める）。
**しない:** `filepath.Clean` ＋ `strings.HasPrefix` で自前のパス検査。`signal.Notify` ＋ 自前のチャネルとゴルーチン。

```go
root, err := os.OpenRoot(dir)
if err != nil {
	return fmt.Errorf("成果物ディレクトリ %s を開く: %w", dir, err)
}
defer root.Close()
f, err := root.Open("report.csv") // dir の外へは出られない
```

理由: パスの正規化と検査を自前で書くと、OS ごとの差（大文字小文字・シンボリックリンク・UNC パス）で穴が残る。

## 8. 並行

**する:**
- 複数の goroutine を待つだけなら `sync.WaitGroup.Go`（1.25）
- goroutine が `error` を返すなら `golang.org/x/sync/errgroup`。`errgroup.WithContext(ctx)` で最初の失敗が他をキャンセルする。同時数を絞るなら `g.SetLimit(n)`
- 裸の `go` は必ず寿命を持つ。「誰が終わりを待つか」（`WaitGroup` / `errgroup`）と「いつ止まるか」（`ctx.Done()`）の両方が読めない `go` は書かない
- 共有状態は `sync.Mutex` を struct のフィールドに持ち（埋め込まない）、ロックの範囲を関数の先頭 `mu.Lock(); defer mu.Unlock()` で示す。単純なカウンタは `atomic.Int64`（1.19）

**しない:** `wg.Add(1)` ＋ `go func() { defer wg.Done() ... }()` の手書き（`go fix` の `waitgroupgo` が書き換える）。結果をチャネルで集めるために goroutine ごとにチャネルを作る（`errgroup` ＋ 添字で書く）。

```go
g, ctx := errgroup.WithContext(ctx)
results := make([]RoomAvailability, len(rooms))
for i, room := range rooms { // 1.22: i, room は反復ごとに新しい
	g.Go(func() error {
		r, err := q.ListForDay(ctx, room, day)
		if err != nil {
			return fmt.Errorf("会議室 %s の空き取得: %w", room, err)
		}
		results[i] = r
		return nil
	})
}
if err := g.Wait(); err != nil {
	return nil, err
}
```

Go 1.27 から `runtime/pprof` の `goroutineleak` プロファイル（`net/http/pprof` では `/debug/pprof/goroutineleak`）が正式になった。「二度と起きない goroutine」を GC の到達性で検出する。寿命の無い `go` を探すときに使う。

理由: 寿命の無い goroutine は、失敗しても誰にも報告されず、リークしても数が増えるまで気付かれない。`errgroup` は失敗の伝播とキャンセルを 1 つの形にする。

## 9. `context`

**する:** 期限は `context.WithTimeout` / `WithDeadline`。キャンセルの理由を伝えたいなら `context.WithCancelCause`（1.21）と `context.Cause(ctx)`。後片付けを親のキャンセル後も走らせるなら `context.WithoutCancel`（1.21）。キャンセル時の処理は `context.AfterFunc`（1.21）。
**しない:** `ctx` に業務の値を載せる（`ctx.Value` は横断的関心 — リクエスト ID・認可主体・トランザクション — だけ）。文字列をキーにする（非公開の型をキーにする）。

## 10. `testing`

テストの形（表・命名・検証）はテストの形の共通規則が決める。ここでは標準ライブラリの何を使うかだけ。

| 使う | 代わりに使わない | 版 |
|---|---|---|
| `t.Context()` — サブテスト終了でキャンセルされる ctx | `context.Background()` をテストに書く | 1.24 |
| `for b.Loop() {` | `for i := 0; i < b.N; i++ {` | 1.24（1.26 でループ本体のインライン化を妨げなくなった） |
| `t.TempDir()` | `os.MkdirTemp` ＋ 手動削除 | 1.15 |
| `t.Chdir(dir)` — 終了時に戻る | `os.Chdir` ＋ `t.Cleanup` | 1.24 |
| `t.Output()` — テストログに繋がる `io.Writer`。`slog.New(slog.NewTextHandler(t.Output(), nil))` でテスト中のログを紐付ける | `os.Stderr` に直接書く | 1.25 |
| `t.Attr(key, value)` — テスト結果に属性を付ける（`-json` の出力に載る） | ログに `key=value` を書く | 1.25 |
| `t.ArtifactDir()` — 成果物（スクリーンショット・ダンプ）を置くディレクトリ。`go test -artifacts` のときだけ `-outputdir` 下に残る | `t.TempDir()` に置いて失敗時に消える | 1.26 |
| `slog.DiscardHandler` — ログを捨てる handler | 自前の no-op handler | 1.24 |
| `httptest.NewTestServer` — `synctest` と組み合わせられる in-memory ネットワークのサーバ | — | 1.27 |

### `testing/synctest`（1.25 で正式）

**する:** 時間に依存する並行コード（タイムアウト・リトライ間隔・期限切れ監視）のテストだけ `synctest.Test(t, func(t *testing.T) { ... })` で仮想時計の中で走らせる。`synctest.Wait()` で全 goroutine が停止するまで待つ。1.27 から `synctest.Sleep(d)` が `time.Sleep` ＋ `Wait` を 1 回で行う。
**しない:** 時間に依存しないコードを `synctest` で包む。本物の `time.Sleep` でタイミングを合わせる。

理由: 仮想時計は「15 分後」を実時間で待たずに進め、`Wait` は「全部止まった」を保証するので、時間依存のテストがフレーキーにならない。

## 11. `encoding/json/v2` と `jsontext`（1.27 で正式）

Go 1.27 から `encoding/json` は v2 実装の上で動き（振る舞いは v1 互換、エラー文言は変わる）、`encoding/json/v2` と `encoding/json/jsontext` が正式になった。**新しく書くコードは v2 を使う。**

**する:**
- `json.Marshal(v, opts...)` / `json.Unmarshal(b, &v, opts...)`。ストリームは `json.MarshalWrite(w, v)` / `json.UnmarshalRead(r, &v)`
- 未知のフィールドを拒みたい境界では `json.RejectUnknownMembers(true)` を渡す
- 「ゼロ値なら出さない」は `omitzero`（1.24）。`omitempty` は JSON として空（`[]` / `{}` / `""`）のときだけ省く別の意味なので、意図が「ゼロ値」なら `omitzero`
- v2 の既定を前提に書く: フィールド名の照合は大文字小文字を区別する、`nil` スライスは `[]`、`nil` map は `{}`、`time.Time` は RFC 3339
- JSON を「値に写さず」構文として読む（大きな配列を 1 要素ずつ、フィールドの順序を保つ）ときだけ `jsontext.Decoder` の `ReadToken` / `ReadValue`
- json タグを書くのは境界の DTO（handler の入出力・設定ファイル・外部 API の型）だけ。**ドメインの型（値オブジェクト・集約・イベント）に json タグを書かない**（ドメインは非公開フィールドで、境界の型へ写してから encode する）

**しない:** `encoding/json`（v1）を新規コードで import する。`GOEXPERIMENT=nojsonv2` に頼る（将来消える）。`map[string]any` に decode して型アサーションで取り出す。

```go
import (
	"encoding/json/v2"
	"encoding/json/jsontext"
)

type config struct {
	DSN     string        `json:"dsn"`
	Timeout time.Duration `json:"timeout,omitzero"`
}

func loadConfig(r io.Reader) (config, error) {
	var c config
	if err := json.UnmarshalRead(r, &c, json.RejectUnknownMembers(true)); err != nil {
		return config{}, fmt.Errorf("設定の読み取り: %w", err)
	}
	return c, nil
}

func countTopLevel(r io.Reader) (int, error) {
	dec := jsontext.NewDecoder(r)
	if _, err := dec.ReadToken(); err != nil { // '['
		return 0, err
	}
	n := 0
	for dec.PeekKind() != ']' {
		if _, err := dec.ReadValue(); err != nil {
			return 0, err
		}
		n++
	}
	return n, nil
}
```

v2 で消えたもの（1.27 の正式版で GOEXPERIMENT 期から変わった点）: `format` タグオプション、`unknown` タグオプション、`DiscardUnknownMembers`、`SkipFunc`。`inline` タグは `embed` に改名。`jsontext` の数値 `Token` アクセサはエラーも返す。実験版で書いたコードはここを直す。

理由: v1 は大文字小文字を無視した照合と `omitempty` の曖昧さで「意図しない一致」を起こす。v2 は既定が厳密で、`Options` で緩める方向にしか動かない。ドメインの型に json タグを書くと、DTO の都合（フィールド名・省略）がドメインに漏れる。

## 12. `errors.AsType[T]`（1.26）

**する:** 外部型のエラーを判定するときは `errors.AsType[T]`。変数の事前宣言とポインタ渡しが要らない。
**しない:** `var pgErr *pgconn.PgError; if errors.As(err, &pgErr) {`。

```go
if pgErr, ok := errors.AsType[*pgconn.PgError](err); ok && pgErr.Code == "23505" {
	return reservation.ErrOverlappingSlot
}
```

どこで何を翻訳するかはエラーの規約が決める（外部型の翻訳はリポジトリの中）。`errors.Is` / `%w` / `errors.Join` の使い分けも同じ。

理由: `errors.As` は `&target` の型を実行時に検査し、`*T` と `T` の取り違えが `panic` になる。`AsType` はコンパイル時に決まる。

## 13. `log/slog`

**する:** 常に `*Context` 版（`InfoContext` / `ErrorContext`）。複数の出力先は `slog.NewMultiHandler(h1, h2)`（1.26）。テストでは `slog.DiscardHandler`（1.24）か `t.Output()` に繋いだ handler。
**しない:** `fmt.Println` / `log.Printf` をアプリケーションコードで使う。`slog.Info`（ctx 無し）。

どの層が出すか、属性名、秘匿はログの規約が決める。ドメイン package は `log/slog` を import しない。

## 14. その他、置き換えの表

| 書く | 書かない | 版 |
|---|---|---|
| `http.NewServeMux()` ＋ `mux.HandleFunc("POST /reservations/{id}/confirm", h)` | メソッドとパスを handler 内で分岐 | 1.22 |
| `u.Clone()` / `values.Clone()` | `*u` のコピー（内部の `User` がポインタで共有される） | 1.27 |
| `atomic.Int64` / `atomic.Bool` | `int64` ＋ `atomic.AddInt64` | 1.19 |
| `os.ReadFile` / `os.WriteFile` | `io/ioutil` | 1.16 |
| `errors.Is(err, fs.ErrNotExist)` | `os.IsNotExist(err)` | 1.16 |
| `strconv.Itoa` | `fmt.Sprintf("%d", n)` | — |
| `fmt.Appendf(buf, ...)` | `append(buf, fmt.Sprintf(...)...)` | 1.19 |
| `cmp.Compare` / `cmp.Or` | 自前の三値比較、`if v == "" { v = def }`（ただし既定値の補完そのものは基本の規約が禁じる。`cmp.Or` は「複数の候補から最初の非ゼロ」を選ぶ明示的な場面だけ） | 1.21 / 1.22 |

`go fix ./...` がこれらの多くを自動で書き換える（ツールの規約）。
