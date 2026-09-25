# package の木と import の向き

確定した業務文脈を `{context}`、集約を `{aggregate}`、単純なパターンの手順を `{procedure}` として、次の木へ写す。directory は責務が実在するときだけ作る。

```text
internal/
├── crosscutting/          横断的関心事（errors、log、clock、idgen、tx、rdb、config、dockertest、integrationtest）
├── shared/vo/             文脈共有の値オブジェクト（識別子が多ければ shared/vo/id）
└── contracts/{message}/   プロセス間のメッセージの契約（Outbox の要求、配信のメッセージ）
{context}/
├── {aggregate}/
│   ├── domain/            集約、状態の型、値オブジェクト、イベント、永続化ポート、エラー
│   ├── repository/        永続化ポートの実装
│   ├── usecase/command/   command の usecase
│   ├── usecase/query/     読み取りのポート、読み取りモデル、query の usecase
│   ├── query/             読み取りのポートの実装
│   └── handler/           入口（RPC、受信境界、巡回）
├── {procedure}/
│   ├── usecase/           手順と、手順が所有するポート
│   ├── repository/        手順の口の実装
│   └── handler/           入口
└── orchestration/usecase/command/  資料が同じ時点で二つ以上の集約へ書くと定めた command
```

## 共有の置き場は、責務を定めたものだけにする

ドメインモデルのクラス図で `<<値オブジェクト・文脈共有>>` の印が付いた値は `internal/shared/vo` に、印の無い値オブジェクトはその集約の `domain` に置く。印の付いた値を一つの集約の `domain` に置くと、別の集約や別のプロセスがその `domain` を import することになるからである。送る側と受ける側のプロセスが同じ型を使うメッセージは `internal/contracts` に置く。禁じるのは `shared` という名前ではなく、`common` や `util` のように責務を定めない置き場である。

テストの前提を組み立てる Builder は、組み立てる対象の実装の直下の `builders/` に、mock は interface を所有する package の直下の `mock/` に置く。本番のコードは `builders` と `mock` を import しない。

## import は外側から内側へだけ向かう

`domain` は、標準ライブラリ、`crosscutting/errors`、`shared/vo` だけを import する。

`repository` は、`domain`、`shared/vo`、`crosscutting`、DB の生成型を import し、usecase、query、handler を import しない。

`usecase/command` は、`domain`、`shared/vo`、`crosscutting`（tx、errors、idgen）、自分が所有する外部の境界のポートを import する。`usecase/query` と `query` は import しない。コマンドの判断に要る材料は、`domain` の永続化ポートの Find が集めるからである。

`usecase/query` は、読み取りのポートと読み取りモデルを所有し、`query` の実装を import しない。`query` は `usecase/query` の契約、値オブジェクト、`crosscutting`（rdb、errors）、DB の生成型を import し、集約を復元しない。

`handler` は、usecase と proto の生成型だけを import する。リポジトリと Query の実装を usecase へ渡すのは、組み立ての関数だけである。巡回の入口が query の usecase で候補を選び、一件ずつ command の usecase を呼ぶのはよい。

`{procedure}/usecase` は、自分が所有するポート、`contracts`、`shared/vo`、`crosscutting`（tx、errors、log）を import し、DB の生成型と pgx を import しない。

循環を、interface の複製や、別の package の型を名前だけ出し直す中継の package で隠さない。package の名前は directory の末尾と一致させ、一つのファイルで衝突したら呼び手の import の別名（`loandomain`）で解く。
