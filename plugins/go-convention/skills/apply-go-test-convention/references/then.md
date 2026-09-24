# Then の置き方

**期待は `want*` と `wantErr error` のフィールドに置き、検証はループ本体に1回書く。**
`verify` は「`got` の性質で、等値で書けないもの」にだけ、共通検証の**後に追加で**呼ぶ。

## 1. フィールド

| 期待 | フィールド | 規則 |
|---|---|---|
| `{pkg}_test` から期待値を構築できる | `want` | 型は戻り値そのまま |
| 構築できない（非公開フィールドを持つ・生成に資源が要る） | `want{何}`（`wantLo` / `wantHi` / `wantSize`） | 公開メソッドの射影と突き合わせる |
| 共同作業者への副作用 | `want{何}`（`wantFiles`） | `fixture` 経由で公開の手段で観測し、ループ本体で突き合わせる。無いことの期待はゼロ値（フィールドを書かない） |
| エラー | `wantErr error` | 対象が返す具体エラー（分類を土台にしたもの）を入れる。`nil` は成功の期待 |
| `got` の性質で、等値で書けないもの | `verify func(t *testing.T, got X)` | 表を書く時点で値が決まらない性質（絶対パスである・ソート済み・範囲内）。エラーと副作用には使わない（届かない） |

`wantErr bool` / `errContains` は使わない（理由は [table.md](table.md) §2）。

## 2. ループ本体の形

```go
			got, err := f.sut.Save(tt.key, tt.body)
			if tt.wantErr != nil {
				require.ErrorIs(t, err, tt.wantErr)
				assert.Zero(t, got)
			} else {
				require.NoError(t, err)
				assert.Equal(t, tt.wantSize, got.Size())
				if tt.verify != nil {
					tt.verify(t, got)
				}
			}

			// 副作用は共同作業者（保存先）を公開の手段で観測し、want{何} と突き合わせる。
			entries, err := os.ReadDir(f.dir)
			require.NoError(t, err)
			var gotFiles []string // ファイル無しはゼロ値。wantFiles を書かないケースと一致する
			for _, e := range entries {
				gotFiles = append(gotFiles, e.Name())
			}
			assert.Equal(t, tt.wantFiles, gotFiles)
```

- エラー時は結果がゼロ値であることも見る。「エラーと値の両方を返す」実装を検出する
- 最終状態の観測が無ければ、エラー分岐は `return` で抜ける（[examples.md](examples.md) §1）。あれば `else` で分け、観測は両方の分岐の後に置く
- 観測した値を集める変数はゼロ値から始める（`var gotFiles []string`）。空スライスで始めると、`want` を書かないケース（`nil`）と一致しない
- `verify` は `assert.Equal` を**置き換えない**。`want*` を空にして `verify` だけで検証するなら、それは表に収まっていない
- 順序不問の結果は `verify` にせず、ループ本体で正規化（ソート）してから `assert.Equal` する

`verify` を持つケースは、表を書く時点で決まらない値（`t.TempDir()` 配下の絶対パス）の性質だけを見る。[examples.md](examples.md) §3 の `6b0d4e`:

```go
			verify: func(t *testing.T, got filestore.Saved) {
				assert.True(t, filepath.IsAbs(got.Path()))
				assert.Equal(t, "a", filepath.Base(got.Path()))
			},
```

## 3. `require` と `assert`

| 使う | 条件 | 例 |
|---|---|---|
| `require` | **失敗したら後続の検証が無意味になる**か、panic を招く | `setup` の失敗、`NoError` / `ErrorIs`、`Len` の後の添字アクセス、`NotNil` の後の参照 |
| `assert` | 互いに独立した期待 | `Equal` の並び。1回の実行で不一致を全部報告する |

- 同じ値に `assert` の後で `require` を書かない。前提なら最初から `require`
- goroutine の中から `require` を呼ばない（`FailNow` は呼んだ goroutine しか止めない）。goroutine の中では `assert` を使い、`require` は `Wait` の後に置く
