# package の木と import の向き

# 木

確定した業務文脈を `{context}`、集約を `{aggregate}`、単純なパターンの手順を `{procedure}` として、次の木へ写す。directory は、責務が実在する場合だけ作る。空の directory を作らない。

```text
internal/
├── crosscutting/          横断的関心事（errors、log、clock、idgen、tx、rdb、config、dockertest、integrationtest）
├── shared/vo/             文脈共有の値オブジェクト
└── contracts/{message}/   プロセス間のメッセージの契約
{context}/
├── {aggregate}/           戦術的 DDD の集約
│   ├── domain/            集約、状態の型、値オブジェクト、イベント、永続化ポート、エラー
│   ├── repository/        永続化ポートの実装
│   ├── usecase/command/   command の usecase
│   ├── usecase/query/     読み取りのポートと読み取りモデルと query の usecase
│   ├── query/             読み取りのポートの実装
│   └── handler/           入口（RPC、受信境界、巡回）
├── {procedure}/           単純なパターンの手順
│   ├── usecase/           手順と、手順が所有するポート
│   ├── repository/        リポジトリ相当の口の実装
│   └── handler/           入口
└── orchestration/usecase/command/  資料が同じ時点で二つ以上の集約へ書くと定めた command
```

## 共有の置き場

**文脈共有の値オブジェクト**は、`internal/shared/vo` に置く。どの値が文脈共有かは、ドメインモデルの資料がクラス図の `<<値オブジェクト・文脈共有>>` の印で示す。印の付いた値を一つの集約の `domain` に置くと、別の集約や別のプロセスが、その集約の `domain` を import することになるからである。印の無い値オブジェクトは、その集約の `domain` に置く。識別子が多いなら、`shared/vo/id` のように分けてよい。

**プロセス間のメッセージの契約**（Outbox の要求、配信のメッセージ）は、`internal/contracts/{message}` に置く。送る側のプロセスと受ける側のプロセスが、同じ契約の型を import する。

**横断的関心事**は、`internal/crosscutting` に置く。業務の概念を import しない。

禁じるのは、責務を定めない置き場である。`shared/vo` は文脈共有の値オブジェクトだけを、`contracts` はプロセス間のメッセージだけを持つ。`common`、`util`、`helpers` のように、何でも入る置き場は作らない。新しい値オブジェクトを作る前に、`shared/vo` と集約の `domain` に同じ意味の型が無いかを探す。

## テスト支援

Builder は、それが組み立てる実装の直下の `builders/` に置く（`shared/vo/builders`、`{aggregate}/domain/builders`、`{aggregate}/repository/builders`）。mock は、interface を所有する package の直下の `mock/` に置く。本番のコードは、`builders` と `mock` を import しない。

# import の向き

import は、外側から内側へだけ向かう。

`domain` は、Go の標準ライブラリ、`crosscutting/errors`、`shared/vo` だけを import する。

`repository` は、`domain`、`shared/vo`、`crosscutting`（rdb、tx、errors、clock、idgen）、DB の生成型を import する。usecase、query、handler を import しない。

`usecase/command` は、`domain`（ポートと型）、`shared/vo`、`crosscutting`（tx、errors、idgen）、外部の境界のポート（usecase/command が所有する）を import する。**`usecase/query` と `query` を import しない。** command は読み取りの口を呼ばないからである。判断の材料は、`domain` の Find が集める。

`usecase/query` は、読み取りのポートと読み取りモデルを所有し、`shared/vo` と `domain` の値オブジェクトだけを使う。`query` の実装を import しない。

`query` は、`usecase/query` の契約、`shared/vo`、`domain` の値オブジェクト、`crosscutting`（rdb、errors）、DB の生成型を import する。集約を復元せず、操作しない。

`handler` は、`usecase/command` と `usecase/query`、転送の型を import する。リポジトリと query の実装は、組み立ての場所（`run`）だけが import する。巡回のように、一つの入口が query の usecase で候補を選び、一件ごとに command の usecase を呼ぶのはよい。ループと失敗の閉じ込めは、入口が持つ。

`{procedure}/usecase` は、自分が所有するポート（リポジトリ相当の口、外部の副作用の口）と、`contracts`、`shared/vo`、`crosscutting`（tx、errors）を import する。DB の生成型と pgx を import しない。`{procedure}/repository` がポートを実装する。

# package の名前

directory の末尾と package の名前を一致させる。`domain`、`repository`、`command`、`query` が一つのファイルで衝突したら、呼び手の import の別名で解く（`loandomain`、`loanquery`）。別名は曖昧さを解くだけで、依存の向きを変えない。

# 判断の例

典型例：利用者番号と資料番号は、クラス図で文脈共有の印が付いているので `internal/shared/vo` に、返却期限と貸出状況は印が無いので `lending/loan/domain` に置く。

似て非なる例：延滞の通知の要求は、貸出の集約の `domain` の値ではなく、延滞にするプロセスと通知を発行するプロセスの間のメッセージなので、`internal/contracts/overduenotice` に置く。

反例：command の usecase が、候補の一覧を読むために `usecase/query` を import する。材料は Find が集め、一覧を選んで一件ずつ呼ぶのは入口の仕事なので、拒否する。

境界例：資料が「貸出と在庫を同じ時点で更新する」と定めたときだけ、その command を `orchestration/usecase/command` に置く。資料が時間差を許すなら、発生元の集約の command が Outbox の要求を同じトランザクションで記録し、別の手順が処理する。
