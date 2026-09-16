---
name: apply-go-package-layout
description: 確定済みの論理責務、集約境界、Command・Query区分を、Go 1.27のpackage treeとimport方向へ写し、配置違反を修正する。「Goのpackageをどう切るか」「この責務をどこへ置くか」「import cycleを避けてCQRSを配置して」と言われ、論理的な所有者が既に決まっているときに使う。
---

# apply-go-package-layout

[工程順序の正本](playbook.yml)を最初に読み、同じagentが\`steps\`を宣言順に実行する。YAMLは工程順序を決め、各工程の判断内容と根拠はこの本文と参照資料を実読して評価する。失敗時は成功扱いせず停止して、完了工程、根拠、未決を残し、再開時は最初の未完了工程から続ける。

確定済みの論理責務と集約境界を受け取り、Goのdirectory、package、importが一意に対応する状態へ直す。

これはGo固有の物理配置を決める能力である。ドメイン、集約リポジトリ、ユースケース、外部境界、Query実装の責務自体は決めない。業務規則、集約境界、同期・結果整合、トランザクション境界が未決なら補完しない。

## 入力

- Go module rootの絶対パスと`go.mod`のmodule path。
- 業務文脈名と、確定済みの集約名。
- 各コード要素について確定済みの論理責務、所有する集約または業務文脈、Command・Query区分。
- 複数集約へ書くCommandがある場合、その横断調整責務。
- Queryについて、ユースケースが所有する読み取りポートと平らな読み取りモデル、ならびにそれを実装する責務。
- 既存のdirectory、package宣言、import、循環依存の検査方法。

## 開始条件

対象となる全コード要素に論理責務と所有者があり、集約境界が確定している場合だけ開始する。責務名が「サービス」「共通」だけで、ドメイン、集約リポジトリ、ユースケース、外部境界、Query実装のどれか判定できない場合は配置せず停止する。

## 作業手順

### 1. 論理入力を検査する

適用条件: 論理責務の一覧と集約境界が提示されている。

必須行動: 各要素に、業務文脈、集約または横断調整、論理責務、Command・Query区分、依存先があることを確認する。Queryの読み取りポートと読み取りモデルはユースケース所有、Query実装はその契約へ依存していることを確認する。

成功判定: 物理配置を推測せず、すべての要素を[Go package treeとimport規律](references/package-layout.md)の一行へ対応できる。

失敗時: 欠けた論理責務をGoのpackage名から逆算しない。未確定要素、答えによって配置が変わる一問、影響するimportを返して停止する。

### 2. Go package treeへ写す

適用条件: 業務文脈と集約のGo識別子を確定できる。

必須行動: module rootから対象アプリケーションrootまでの既存構成を保ち、その配下へ集約単位で次を写す。存在する責務のdirectoryだけを作り、空directoryは作らない。

```text
{context}/
├── {aggregate}/
│   ├── domain/
│   ├── repository/
│   ├── usecase/
│   │   ├── command/
│   │   └── query/
│   ├── query/
│   └── handler/
│       ├── command/
│       └── query/
└── orchestration/
    └── usecase/
        └── command/
```

`domain`をCommand・Queryへ分けない。`repository`と`query`は並列に置く。`usecase/query`は読み取りポート、読み取りモデル、Queryユースケースを所有する。`query`はそのポートの実装だけを持つ。二つ以上の集約リポジトリへ書くCommandだけを`orchestration/usecase/command`へ置き、他集約を読むだけのCommandは引き金となる集約の`usecase/command`へ置く。`orchestration`に`domain`、`repository`、`query`を作らない。

成功判定: 各コード要素が一つのdirectoryへ対応し、空directory、同じ責務の二重配置、集約間の相互importがない。

失敗時: 既存packageを残す互換shimや転送packageを作らない。移動範囲が利用者の依頼を越える場合は、必要な移動単位を返して停止する。

### 3. package名と公開面を決める

適用条件: directoryへの対応が確定した。

必須行動: 各directoryは一つのGo packageにする。package名はdirectory末尾の短い小文字名を既定とし、予約語または同一ファイル内のimport名と衝突するときだけ、業務語を接頭辞にした名前へ一意に変える。呼び手側のimport aliasで曖昧さを解消できる場合はdirectory名を増やさない。

成功判定: 同じdirectoryに複数package宣言がなく、公開シンボルはその論理責務が外部へ提供する契約だけである。

失敗時: `common`、`shared`、`util`という新しい逃げ場を作らない。複数責務が必要なら入力の論理所有者へ戻して停止する。

### 4. import方向を適用する

適用条件: package対応が確定している。

必須行動: 参照資料の許可表どおりにimportを直す。特に次を守る。

- `domain`は外側のpackageをimportしない。
- `usecase/query`は読み取り契約を所有し、`query`実装をimportしない。
- `query`実装は`usecase/query`をimportし、そのinterfaceを満たす。集約を復元・操作しない。
- `usecase/command`と横断調整Commandは、実装packageでなく内側のポートへ依存する。
- `handler`はusecaseへ依存し、DB実装を直接呼ばない。組み立てだけが実装を結ぶ。
- `repository`は集約永続化だけを実装し、一覧・件数・検索・存在確認を持たない。

成功判定: `go list -deps ./...`と対象repositoryのimport cycle検査が成功し、禁止方向のimportがない。

失敗時: cycleをinterface複製、転送型、shimで隠さない。cycleを作る二つの責務と未確定の所有者を返して停止する。

### 5. 移動後の参照を直して検証する

適用条件: directory、package、importの変更が完了した。

必須行動: import path、生成設定、テストpackage、composition rootの参照を新しい配置へ直す。`gofmt -w`を変更したGo fileだけに実行し、`go build ./...`、`go vet ./...`、対象テストを実行する。

成功判定: すべての検査が成功し、古いpackageへのimport、転送package、空directoryが残っていない。

失敗時: 旧pathを残す互換packageを追加しない。最初の失敗、残る旧import、変更済み範囲を返す。

## 出力

- 論理責務からGo directory、package、importへの対応表。
- 規約を反映したGo fileと、更新した生成・テスト・組み立ての参照。
- 実行した`gofmt`、`go list`、`go build`、`go vet`、対象テストの結果。

## 非責務

- 論理責務、集約境界、業務規則、整合方式を発見・変更しない。
- SQL、集約、ユースケース、ハンドラーの実装内容を作らない。
- Go以外の言語へ同じdirectory treeを適用しない。
- 後方互換のpackage、alias、shimを作らない。

## 停止条件

- 論理責務または集約境界が未確定である。
- Queryの読み取りポート・読み取りモデルの所有者が未確定である。
- 複数集約へ書くか、他集約を読むだけかが未確定である。
- 既存公開packageの移動に利用者の権限または対象範囲が足りない。
- Go module root、module path、検証方法を確認できない。

停止時は、確定済みの対応を破棄せず、未配置要素、必要な論理判断、影響するimport、再開条件を返す。

## 完了条件

- 全コード要素が確定済み論理責務どおりのGo packageへ一度だけ配置されている。
- Query契約は`usecase/query`、実装は`query`にあり、importが実装から契約へ向いている。
- 複数集約書き込みだけが横断調整Commandにあり、集約間の循環importがない。
- 古いpackage、互換shim、空directoryが残っていない。
- Goの構文、依存、ビルド、対象テストを検証している。

## 使用例

典型例: 予約一覧の読み取りポートと`ReservationSummary`を`reservation/usecase/query`へ、sqlcを呼ぶ実装を`reservation/query`へ置き、後者から前者をimportする。

似て非なる例: 予約確定が会議室の状態を読むだけで予約集約だけを保存するなら、`reservation/usecase/command`に置く。二集約の調整directoryへ移さない。

反例: 読み取りモデルを`reservation/query`へ置き、`reservation/usecase/query`から実装packageをimportする。依存が外向きになるため拒否する。

境界例: 予約確定と予約待ち登録の両方へ書くと確定した場合だけ、Commandを`orchestration/usecase/command`へ移す。片方を読むだけへ変われば予約集約側へ戻す。
