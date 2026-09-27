---
description: 電子チケットのチケットの業務知識とドメインモデルの資料だけを渡し、分配の集約を develop-domain-model でテストから書かせる。
tags: [electronic-ticket, domain-model, implementation]
plugins: ["../../../plugins/go-convention"]
max_turns: 200
timeout_seconds: 3600
allowed_tools: [Read, Glob, Grep, Skill, TodoWrite, Write, Edit, Bash]
---

電子チケットの販売サービスの「チケット」の業務のうち、「分配」の集約を、ドメイン層だけ、テスト駆動で実装してください。チケットの集約は今回の範囲の外です。永続化、usecase、入口は今回の範囲の外です。

## 作業場所

作業する repository は、この作業場所の `out/` です。Go の module（`example.com/service`）で、エラーの分類の package がすでにあります。資料は `out/docs/チケット/` にある業務知識（`business-knowledge.md`）とドメインモデル（`domain-model.md`）の二つだけで、これが根拠のすべてです。資料は書き換えないでください。

この環境は外のネットワークへ接続できません。Go の module は `go.mod` にあるものだけが使えます。Docker もありません。

## ほかの package のファイル

この環境には development-convention と testing-strategy の skill が入っていません。代わりに、その最新のファイルを `harness/` の下へ写してあります。skill が `develop-inside-out`、`apply-layer-convention`、`write-readable-code`、`apply-yagni` に従うよう求めたら `harness/<名前>/SKILL.md` を、testing-strategy の `design-test-strategy` の資料を求めたら `harness/design-test-strategy/` の下を読んでください。

## 問いと止まるとき

この実行には、問いに答える利用者がいません。skill が止まるよう定めた場面に当たったら、その部分は書かずに止まり、何が決まらず、どこが変わるかを報告してください。skill が仮置きして進めてよいとする場面は、仮置きして報告に挙げてください。

## 報告

最後に、日本語で、書いたファイル、資料の要素と型の対応、主に担う BDD の ID、仮置きしたもの、止めたものとその返し先、最後に通した検査のコマンドと結果を短く書いてください。
