# write-go-code — 2026-09-16 実行記録の所見

記録: [write-go-code.json](write-go-code.json)（case `write-go-code-signature-and-fallback`、stage `after-required-reference-read`、resources `references/basics.md`（sha256 `95dbfae08b3a…` ＝ §7追補後の確定版）/ `references/naming.md`、生成 `claude-opus-5` effort high、独立judge `claude-sonnet-5`、SKILL sha256 `ded7d1bb2623…`）。[attempt-1](write-go-code.attempt-1.json) は §7追補前の basics.md と旧criterion `signature`（『ctxを第一引数にし、…』）に対する記録で、judgeは `signature` をfailにした。E-3でcriterionを現行§7から導ける文へ直し、本記録はその新しいcriteriaで実行した。

## 実行

```bash
cd go-convention-plugins && python3 ../product-planning-plugins/shared/runtime-source/evaluate-skills.py --fixtures evals/scenarios.json \
  --model-command '["python3","../product-planning-plugins/shared/runtime-source/claude-eval-adapter.py"]' \
  --judge-command '["python3","../product-planning-plugins/shared/runtime-source/claude-eval-adapter.py"]' \
  --model claude-opus-5 --judge-model claude-sonnet-5 --settings '{"effort":"high"}' --output evals/runs/2026-09-16/write-go-code.json
```

このrepositoryは評価runtimeの複製を持たないので、正式な定義を直接使った。fixtureはこのevalのために新規作成した（`util` package・`Get` 接頭辞・返り値3つ・naked return・`ctx` 第二引数・既定値10への丸め、を1関数に入れた題材）。

## agentの所見（「」は応答の逐語。『』はreference等の出典付き引用）

| criterion | 所見 | 根拠 |
|---|---|---|
| no-fallback | 満たす。丸めを消してerrorを `%w` で包み、資料に仕様として書かれていれば停止条件に当たる分岐も述べる | 「「不正なら既定値 10」はコードのコメントにしかなく、資料（仕様）にあるとは示されていないので停止条件には当たらないと判断して消した。」 |
| signature | 満たす。返り値2つ・naked return除去・`else` 除去・`util` と `Get` の修正に加え、使われない `ctx` は現行 basics.md §7（『使われない ctx は第一引数へ移さず引数ごと外す』）どおり引数ごと外している | 「`basics.md §7`（ctx は第一引数。ただし I/O をしない純粋な変換は ctx を受け取らず、使われない ctx は引数ごと外す）」 |
| truthful | 満たす。6 commandを列挙し未実行と明示。linterの警告についても未実行なので言えないと述べる | 「### 機械検査（実行するコマンドのみ。結果は未実行）」「未実行なので言えない」 |

judge（3件pass）と一致。attempt-1では §7 の未定義領域で judge と私の読みが分かれたが、§7追補（M-11）と criterion の書き直し（E-3）で揺れは消えた。

## 気づき

- 関数名を `parseLimit`（非公開）にしており、attempt-1の `ParseLimit` と違う。「usecase 内だけで使う補助関数として非公開にした仮説で、他 package から呼ぶなら `ParseLimit`」と採らなかった形を示している。公開/非公開は入力から一意に決まらないので仮説扱いは妥当。
- 未読の3 reference（types-and-interfaces / stdlib-1.27 / tooling）に依存する判断が発生していないと述べており、resourcesを2本に絞ったfixtureの限界を応答自身が明示している。

## 未確認

- gofmt / vet / lint / testは実行していない。直したコードのコンパイルも未確認。
