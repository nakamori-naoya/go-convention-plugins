# テーブルの形

**入力と期待値はデータとして並び、実行と検証はループ本体に1回だけ書く。** これが「テーブル駆動である」の定義である。

## 1. 形

無名 struct のスライスに、識別 → Given → When → Then の順でフィールドを置く（[examples.md](examples.md) §1）。

```go
	tests := []struct {
		id          string
		name        string
		description string
		values      []int // Given: 数列の中身
		target      int   // When:  対象関数の引数名そのまま
		wantLo      int   // Then
		wantHi      int   // Then
		wantErr     error // Then: nil なら成功を期待
	}{
```

```go
	for _, tt := range tests {
		t.Run(tt.id+" "+tt.name, func(t *testing.T) {
			t.Parallel()
```

表を縦に読めばケースの差分が分かり、ケースを足すのは行を足すだけになる。ケースごとに `func` を持たせる形はケースごとに検証が散り、`t.Run` を羅列したのと同じになる。`map` は実行順が不定で失敗の再現に `-run` が要る。

## 2. フィールド

| 順 | 区分 | フィールド名 | 正本 |
|---|---|---|---|
| 1 | 識別 | `id` / `name` / `description`。必ずこの3つ・この順。資料にあるケースは資料の ID・見出し・gherkin ブロックをそのまま写す | [case-identity.md](case-identity.md) |
| 2 | Given | 前提の名前（`values` / `given` / `seed`）と、値で書けない Given がケースごとに違うときだけ `setup` | [given.md](given.md) |
| 3 | When | 対象メソッドの引数名そのまま。操作列の型は `steps`。`context.Context` はフィールドにしない（ループ本体で `t.Context()` を渡す。キャンセルの持ち主をサブテストにする） | [given.md](given.md) |
| 4 | Then | `want` / `want{何}` / `wantErr error` / `verify` | [then.md](then.md) |

1ケースは複数行で書く。`id` / `name` / `description` は各1行で始め、この順に隣接させる。`check-cases.py` はこの形を前提に読む。

### 使わない名前

| 禁止 | 代わりに | 理由 |
|---|---|---|
| `expected` / `expect` / `actual` | `want` / `got` | 語彙を1つにする。混在すると同じ意味の名前を2つ覚える |
| `in` / `input` / `args` | 引数名そのまま | 袋に包むと `description` の `When:` と引数の対応が読めない。禁じるのは対象の引数を表の中で袋に包むことであり、対象の引数が入力 struct 1つでその名が `in`（`Execute(ctx, in ConfirmReservationInput)`）なら、引数名そのままの規則に従って `in` を使う |
| `ok` / `shouldFail` / `errMsg` / `errContains` | `wantErr error` | `bool` は別の原因のエラーでも緑になり、文言は変更で落ちる |
| `parallel` / `serial` / `skip` / `only` | 並列はテスト関数の属性。skip したいケースは消す | ケースごとの実行制御は、表を読んでも走るかどうかが分からない状態を作る |
| `teardown` / `before` / `after` | `setup` の中の `t.Cleanup` | 取得と解放が別の場所にあると、片方だけ直して漏れる |
| `map[string]any` のような型を失う袋 | `fixture` に型付きで置く | コンパイラが取り違えを検出できない |

## 3. ループ本体

- `t.Run` の名前は `tt.id+" "+tt.name`。サブテスト名は `BDD-001_名前` / `a3f9c1_名前` になり、`go test -run 'TestX/BDD-001_'` で1ケースだけ走る。`-run` には `id` の後の区切り `_` まで書く（`id` の桁は固定ではないので、区切りが無いと別の `id` の接頭辞に一致しうる）
- ケースを選り分ける分岐（`if i == 2` / `if tt.name == "..."` / `switch tt.id`）を書かない。ケース固有のことはフィールドに戻す
- `t.Parallel()` の置き方は [given.md](given.md) §3

## 4. ケースの並び

資料にあるケースを資料の順に、資料に無いケースをその後ろに置く（[case-identity.md](case-identity.md)）。並び順に意味を持たせない。どの順で走っても同じ結果になることが前提である。
