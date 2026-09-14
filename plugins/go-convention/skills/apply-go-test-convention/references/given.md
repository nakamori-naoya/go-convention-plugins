# Given の置き方

**既定は宣言的なデータ。** `setup func` は「値として表に書けない Given」だけの逃げ道である。ケース間の依存は作らない。入力が引数ではなく、それまでの操作である型は、操作列で表す。

## 1. 既定: データ

```go
		values      []int // Given: 数列の中身
```

- Given のフィールドは `description` の `Given:` 行と1対1で対応させる
- データから SUT を組み立てるコードはループ本体に1回（`seq := numseq.NewNumberSequence(tt.values)`）
- Given の struct が肥大化するなら SUT の引数が多すぎるサイン。テストではなく型設計で直す

表を縦に読んでケースの差分が分かるのは、Given がデータのときだけである。

## 2. 逃げ道: `setup func(t *testing.T) fixture`

**使う条件: Given に `t` が要る（`t.TempDir` / `t.Cleanup` / トランザクション）か、直列化できない依存（DB ハンドル・チャネル）が要る。** それ以外はデータで書く。

```go
	// fixture は SUT と、Then で覗く共同作業者（保存先ディレクトリ）を持つ。
	type fixture struct {
		sut *filestore.Store
		dir string
	}

	tests := []struct {
		id          string
		name        string
		description string
		setup       func(t *testing.T) fixture              // Given: 資源の取得だけ
		seed        []string                                // Given: 保存済みのキー。投入はループ本体
		key         string                                  // When:  対象メソッドの引数名そのまま
		body        []byte                                  // When
		wantSize    int                                     // Then
		wantErr     error                                   // Then: nil なら成功を期待
		wantFiles   []string                                // Then: 保存先に在るファイル名。無ければ書かない
		verify      func(t *testing.T, got filestore.Saved) // Then: got の性質で、等値で書けないもの
	}{
		{
			id:   "6b0d4e",
			name: "本文をキー名のファイルとして保存する",
			description: `Given: 空の保存先がある
When: キー a に 5 バイトの本文を保存する
Then: 5 バイト保存され、保存先はキー a を名前にした絶対パスである
  And: 保存先にはファイル a だけが在る`,
			setup: func(t *testing.T) fixture {
				dir := t.TempDir()
				sut, err := filestore.Open(dir)
				require.NoError(t, err)
				return fixture{sut: sut, dir: dir}
			},
```

```go
			f := tt.setup(t) // サブテストの t を渡す。t.Cleanup がこのケースの終わりに走る
			for _, key := range tt.seed {
				_, err := f.sut.Save(key, []byte("seeded"))
				require.NoError(t, err)
			}
```

| 規則 | 理由 |
|---|---|
| 戻り型はテスト関数の中で宣言した `fixture` struct。SUT と、Then で覗く共同作業者を持つ | SUT だけ返すと Then で副作用を観測できない。`any` や `map` は型を失う |
| `setup` フィールドを置くのは、ケースごとに `setup` が違うときだけ。置いたら全ケースが持つ | 全ケースで同じ `setup` は、フィールドではなくループ本体の Given 構築コードである。有無がケースで変わると Given の読み方が変わり、表を縦に読めなくなる |
| `setup` は資源の取得だけ。資源に何を入れたかは `seed` 等のデータ欄に出し、投入はループ本体で行う | 前提の中身が表に出る。`setup` に入れると閉じた関数の中に隠れる |
| `setup` に When と Then を入れない | 操作が入った時点で、ケースごとに検証が散る形に戻る |
| サブテストの `t` を渡す | `t.Cleanup` がサブテスト終了時に走る。親の `t` だと全ケース終了まで資源が残る |

## 3. ケース間の依存と順序

**ケース間の依存は作らない。** 各ケースが自分の世界を組み立てる。

| 規則 | 内容 |
|---|---|
| 独立 | どのケースも単独で `-run 'TestX/BDD-001_'` で通る |
| 順序 | どの順で走っても同じ結果。`go test -shuffle=on` はテスト関数間の順序だけを入れ替える（落ちればテスト関数間の依存が確定する。サブテストの順序は変えない） |
| 「作成→取得」の連続 | 2ケースではなく1ケースの `steps`（§4） |
| 並列 | 並列可否はケースの属性ではなく、テスト関数（SUT と資源）の属性 |

`t.Parallel()` はテスト関数の先頭とサブテストの先頭の両方に書くか、両方に書かないか。片方だけは無い。

```go
func TestFindPairSummingTo(t *testing.T) {
	t.Parallel()
```

```go
		t.Run(tt.id+" "+tt.name, func(t *testing.T) {
			t.Parallel()
```

書かないときは、ループ直前のコメントで共有資源を名指しする（`// 同一スキーマの users テーブルを共有するため直列で走らせる。`）。「並列にすると不安定」は隔離が壊れている証拠であり、並列を諦める理由ではなく隔離を直す理由である。

## 4. 操作列: 入力が引数ではなく、それまでの操作である型

スタック・キュー・集約のように、入力が引数ではなく**それまでの操作**である型は、操作列で表す。表を支える型（`opKind` / `op` / `step`）はテスト関数の中で宣言する（[examples.md](examples.md) §2）。資源が要る型は §2 の `setup` で `fixture` を取得し、`given` / `steps` は `f.sut` を操作する。

```go
		given       []op   // Given: 準備の操作。期待を持たない
		steps       []step // When + Then: 操作と、その直後の期待
		wantLen     int    // Then: 最終状態を公開クエリで観測した値
```

| 規則 | 理由 |
|---|---|
| `given []op` と `steps []step` を分ける | `given` は前提で期待を持たない。`steps` は観測値に期待を持つ |
| 操作の実行は `switch` を持つ局所クロージャ1つ。`given` も `steps` もそこを通る | `given` は `require.NoError` だけ、`steps` は `want` / `wantErr` で検証する。実行が1か所なら検証も1か所に留まる |
| 操作ごとに観測値を1つ決め、`step.want` はその値。観測値の型は全操作で1つ | 期待の無い `step` を作らない。積む操作なら積んだ後の個数、取り出す操作なら取り出した値。型が揃わないなら `steps` に入れる操作を対象メソッドだけにし、他の操作は `given` に置く |
| 最終状態は `want{何}` | 公開クエリで観測できる射影（`wantLen` / `wantTop` / `wantIsEmpty`）。観測できない内部状態を見たくなったら、型に問い合わせが足りない |
| 不変な SUT は受け直す | `s = s.Push(v)`。可変なら `s.Push(v)`。形は同じ |
| `steps` は10以下 | 10を超えると `description` の `When:` 1行に列挙できず、ケースではなくシナリオになる。別ケースに割る |

## 5. 後始末

**資源を取得した `setup` の中で、取得の直後に `t.Cleanup`。** `teardown` / `before` / `after` フィールドは使わない。後始末は「何を作ったか」に従属し、ケースには従属しない。

| 資源 | 書き方 |
|---|---|
| `t` を受け取る取得（`t.TempDir()`） | 取得側が `t.Cleanup` を登録済み。何も書かない |
| 自前で変えた状態（権限・接続・トランザクション） | 変えた直後に `t.Cleanup` で戻す |

[examples.md](examples.md) §3 の `1fa5c9`。読み取り専用にした権限を戻してから、`t.TempDir()` の削除が走る:

```go
			setup: func(t *testing.T) fixture {
				dir := t.TempDir()
				sut, err := filestore.Open(dir)
				require.NoError(t, err)
				require.NoError(t, os.Chmod(dir, 0o500))
				t.Cleanup(func() { _ = os.Chmod(dir, 0o700) }) // 権限を戻してから t.TempDir の削除が走る（LIFO）
				return fixture{sut: sut, dir: dir}
			},
```

`t.Cleanup` は `require` の `FailNow` でも LIFO で走り、サブテストの `t` に紐づくので並列とも整合する。
