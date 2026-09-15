# Go package treeとimport規律

## 論理責務からdirectoryへの対応

確定済みの業務文脈を`{context}`、集約を`{aggregate}`として次へ写す。

| 論理責務 | Go directory | 所有するもの |
|---|---|---|
| ドメイン | `{context}/{aggregate}/domain` | 集約、エンティティ、値オブジェクト、純関数、業務イベント、集約リポジトリinterface |
| 集約リポジトリ実装 | `{context}/{aggregate}/repository` | 集約の復元・保存、永続化変換、DB制約違反の翻訳 |
| Commandユースケース | `{context}/{aggregate}/usecase/command` | 入力、時刻・ID供給、集約操作、トランザクション |
| Query契約とユースケース | `{context}/{aggregate}/usecase/query` | 読み取りポートinterface、平らな読み取りモデル、Queryユースケース |
| Query実装 | `{context}/{aggregate}/query` | SQL・読み取り・集計、行から読み取りモデルへの変換 |
| Command外部境界 | `{context}/{aggregate}/handler/command` | 転送入力からCommand入力への変換、Command結果の転送 |
| Query外部境界 | `{context}/{aggregate}/handler/query` | Query入力の変換、読み取りモデルから転送型への項目コピー |
| 複数集約書き込みの調整 | `{context}/orchestration/usecase/command` | 複数の集約リポジトリポートを使う一つのCommandとトランザクション |

directoryは責務が実在する場合だけ作る。`domain/query`は作らない。`orchestration`は`domain`、`repository`、`query`を持たない。

## import許可表

| 呼び元 | importしてよい内側の責務 | 禁止する責務 |
|---|---|---|
| `domain` | Go標準・値の実装に必要な純粋ライブラリ | repository、usecase、query、handler、転送型、DB生成型 |
| `repository` | domain、DB接続・生成型 | usecase、query実装、handler |
| `usecase/command` | domainのポートと型、`usecase/query`の読み取り契約、トランザクション抽象 | repository実装、query実装、handler、転送型 |
| `usecase/query` | domainの値オブジェクト・純関数を入力解決に使う場合だけ | repository実装、query実装、handler、DB生成型 |
| `query` | `usecase/query`の契約、DB接続・生成型、domainの値オブジェクト・純関数を計算に使う場合だけ | 集約の復元・操作、repository実装、handler |
| `handler/command` | `usecase/command`、転送型 | repository実装、query実装、DB生成型 |
| `handler/query` | `usecase/query`、転送型 | repository実装、query実装、DB生成型 |
| 横断調整Command | 複数集約のdomainポートと型、`usecase/query`の読み取り契約、トランザクション抽象 | repository実装、query実装、handler |

Query実装は`usecase/query`にあるinterfaceを構造的に満たす。`usecase/query`がQuery実装の型をimportしてはならない。読み取りモデルも`usecase/query`が定義し、Query実装はその型を返す。

## package名

directory末尾とpackage名を一致させると、`domain`、`repository`、`command`、`query`が複数importで衝突する場合がある。衝突は呼び手のimport aliasで解消する。

```go
import (
    reservationdomain "example.com/roomflow/booking/reservation/domain"
    querycontract "example.com/roomflow/booking/reservation/usecase/query"
)
```

aliasは呼び手の曖昧さを解消するだけで、依存方向を変えない。package名を`common`や`shared`へ変えて責務を隠さない。

## 判断例

典型例: 空き枠一覧の型とinterfaceは`usecase/query`、DBから組み立てる型は`query`へ置く。実装から契約へimportする。

似て非なる例: Commandのために重複予約を読むinterfaceも読み取り契約なので`usecase/query`に置ける。Commandは契約をimportし、実装をimportしない。

反例: 循環を避けるため同じinterfaceをCommand側とQuery実装側へ二重定義する。契約の所有者が二つになるため拒否する。

境界例: 一つのCommandが二集約のリポジトリへ書くなら横断調整へ置く。片方を読むだけなら引き金となる集約のCommandに留める。
