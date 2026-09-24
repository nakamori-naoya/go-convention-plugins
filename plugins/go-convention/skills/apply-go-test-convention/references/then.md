# Then の置き方

期待は `want*` と `wantErr error` のフィールドに置き、検証はループ本体に一回だけ書く。`verify` は、`got` の性質で等値では書けないものにだけ、共通の検証の後に追加で呼ぶ。

# フィールド

`{pkg}_test` から期待値を組み立てられるなら、戻り値と同じ型の `want` に置く。組み立てられない（非公開のフィールドを持つ、生成に資源が要る）なら、公開メソッドの射影を `want{何}` に置く。次の例では、貸出は `{pkg}_test` から組み立てられないので、返却期限の日を取り出して `wantDueDay` と突き合わせる。

```go
		wantDueDay  time.Time      // Then:  返却期限の日（取り出した値）
		wantErr     error          // Then:  nil なら借りられる
```

共同作業者への副作用は、`fixture` を通じて公開の手段で観測し、`want{何}`（`wantFiles`）とループ本体で突き合わせる。無いことの期待はゼロ値で、フィールドを書かない。

エラーは `wantErr error` に、対象が返す具体エラー（分類を土台にしたもの）を入れる。`nil` は成功の期待である。`wantErr bool` や `errContains` は使わない。理由は [テーブルの形](table.md) にある。

`verify func(t *testing.T, got X)` は、表を書く時点で値が決まらない `got` の性質（絶対パスである、整列済みである、範囲内にある）にだけ使う。エラーと副作用には使わない。`verify` には届かないからである。

# ループ本体の形

```go
			got, err := pending.Borrow(tt.lentAt)
			if tt.wantErr != nil {
				require.ErrorIs(t, err, tt.wantErr)
				assert.Zero(t, got)
				return
			}
			require.NoError(t, err)
			assert.Equal(t, tt.wantDueDay, got.Due().Day())
```

エラーのときは、結果がゼロ値であることも見る。「エラーと値の両方を返す」実装を見つけるためである。最終状態の観測が無ければ、上の例のように、エラーの分岐は `return` で抜ける。副作用の観測があるなら、`else` で分け、観測は両方の分岐の後に置く。観測した値を集める変数はゼロ値から始める（`var gotFiles []string`）。空のスライスで始めると、`want` を書かないケース（`nil`）と一致しない。

`verify` は `assert.Equal` を置き換えない。`want*` を空にして `verify` だけで検証するなら、それは表に収まっていない。順序を問わない結果は、`verify` にせず、ループ本体で整列してから `assert.Equal` する。

# require と assert

`require` は、失敗したら後の検証が無意味になるか、panic を招くときに使う。`setup` の失敗、`NoError` と `ErrorIs`、`Len` の後の添字アクセス、`NotNil` の後の参照がそれにあたる。`assert` は、互いに独立した期待に使う。`Equal` を並べれば、一回の実行で不一致を全部報告できる。

同じ値に、`assert` の後で `require` を書かない。前提なら最初から `require` にする。goroutine の中から `require` を呼ばない。`FailNow` は呼んだ goroutine しか止めないからである。goroutine の中では `assert` を使い、`require` は `Wait` の後に置く。
