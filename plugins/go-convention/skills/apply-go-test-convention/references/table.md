# テーブルの形

入力と期待はデータとして並べ、実行と検証はループ本体に一回だけ書く。これが「テーブル駆動である」の定義である。

# 形

無名 struct のスライスに、識別、Given、When、Then の順でフィールドを置く。

```go
	tests := []struct {
		id          string
		name        string
		description string
		lent        lending.Count  // Given: 借りている冊数
		overdue     lending.Count  // Given: 延滞の貸出の冊数
		lentAt      lending.LentAt // When:  貸出の時点
		wantDueDay  time.Time      // Then:  返却期限の日（取り出した値）
		wantErr     error          // Then:  nil なら借りられる
	}{
```

表を縦に読めばケースの差分が分かり、ケースを足すのは行を足すだけになる。ケースごとに `func` を持たせる形は、ケースごとに検証が散り、`t.Run` を羅列したのと同じになる。`map` は実行の順が決まらず、失敗の再現に手間がかかる。

一つのケースは、複数の行で書く。`id`、`name`、`description` は、それぞれ一行で始め、この順に隣接させる。`check-cases.py` は、この形を前提に読む。

# フィールドの名前

識別のフィールドは、`id`、`name`、`description` の三つで、必ずこの順に置く（[ケースの識別](case-identity.md)）。

Given のフィールドは、前提の名前（`lent`、`overdue`）にする。値で書けない Given がケースごとに違うときだけ、`setup` を置く（[Given](given.md)）。

When のフィールドは、対象のメソッドの引数名そのままにする。入力を `in`、`input`、`args` のような袋に包まない。包むと、`description` の `When:` と引数の対応が読めなくなる。対象の引数が入力の struct 一つで、その名前が `in` なら、引数名そのままの規則どおり `in` を使う。`context.Context` はフィールドにせず、ループ本体で `t.Context()` を渡す。

Then のフィールドは、`want`、`want<何>`、`wantErr error` にする（[Then](then.md)）。`expected` や `actual` は使わず、語を `want` と `got` に揃える。`ok`、`shouldFail`、`errMsg` は使わない。`bool` は別の原因のエラーでも緑になり、文言は変更で落ちる。

ケースごとの実行の制御（`parallel`、`skip`、`only`）はフィールドにしない。表を読んでも走るかどうかが分からなくなる。並列はテスト関数の属性で、走らせたくないケースは消す。後始末（`teardown`、`before`、`after`）もフィールドにせず、`setup` の中の `t.Cleanup` に置く。型を失う袋（`map[string]any`）も使わない。

# ループ本体

```go
	for _, tt := range tests {
		t.Run(tt.id+" "+tt.name, func(t *testing.T) {
			t.Parallel()
```

`t.Run` の名前は `tt.id+" "+tt.name` にする。サブテストの名前は `BDD-001_名前` や `7c2e19_名前` になり、`go test -run 'TestX/BDD-001_'` で一つのケースだけを走らせられる。`-run` には `id` の後の区切りの `_` まで書く。`id` の桁は決まっていないので、区切りが無いと別の `id` の頭に一致しうる。

ケースを選り分ける分岐（`if tt.id == ...`）を書かない。ケースに固有のことは、フィールドに戻す。

# ケースの並び

資料にあるケースを資料の順に、資料に無いケースをその後ろに置く。並びに意味を持たせない。どの順で走っても、同じ結果になることが前提である。
