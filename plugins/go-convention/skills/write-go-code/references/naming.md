# 命名

名前は、定義した場所ではなく呼び出し側で読まれる。`package.Name` の形で読んだときに、一回で意味が通ることを基準に決める。業務の概念の名前は、資料（業務知識、ドメインモデル）の語と、そのクラス図の英名を使う。資料に語の無い概念に名前を付けたくなったら、その名前を資料への提案に含める。

# package とファイル

## package 名は、中身が何であるかを一語で言う

package 名は、短い一語の小文字の単数形で、ディレクトリ名と一致させる。中身が何であるか（`domain`、`repository`、`command`、`clock`、`tx`）を言う。

`util`、`common`、`helpers`、`misc`、`types`、`models` のように、何でも入る名前は付けない。こうした名前が要ると感じたら、置きたい関数の呼び出し側を見る。呼び出し側が一つの package なら、その package に置く。複数なら、その関数が属する概念の名前が package 名になる。責務を定めた共有の置き場（文脈共有の値オブジェクトなど）は、apply-go-package-layout が決める。

## ファイル名は中身を言う

ファイル名は小文字の snake_case で、中身を言う（`loan.go`、`loan_repository.go`、`errors.go`）。`impl.go`、`helpers.go`、`types.go`、`interfaces.go` のように、何が入っているか分からない名前は付けない。interface は自分の名前のファイルに置く（[型と interface](types-and-interfaces.md)）。

# 型、関数、変数

## 型名に package 名を繰り返さない

呼び出し側は常に `package.Name` と読む。`domain.LoanDomain` や `clock.ClockInterface` のように、同じ語を二回並べない。

## 頭字語は全部大文字か全部小文字にする

`ID`、`URL`、`HTTP`、`JSON`、`DB`、`SQL`、`API` と綴る。公開なら `LoanID`、非公開なら `loanID` である。`Id` や `Url` と混ぜると、同じ概念が二つの綴りを持ち、検索で片方を落とす。

## 値を返すメソッドに `Get` を付けない

`func (l OnLoan) Due() Due` のように、名詞で名付ける。bool を返す問い合わせは `Is`、`Has`、`Can` で始める。状態を変えるメソッドは、資料のコマンドの動詞（`Borrow`、`Return`、`MarkOverdue`）にする。不変の型に `SetX` を書かない。

## 等値は `Equal` にする

`==` で比べられる型（非公開フィールドがすべて比較可能で、正規化済み）には、`Equal` を書かずに `==` を使う。比べられない型だけに `Equal` を書く。`Equals` や `IsEqual` とは綴らない。

## レシーバ名は一、二文字で、型の中で揃える

型名の頭文字（`OnLoan` なら `l`、`LoanRepository` なら `r`）を使い、同じ型の全メソッドで同じ名前にする。`this`、`self` は使わない。

## interface 名は役割で付ける

一メソッドの interface は、動詞と `er`、または慣習の名詞（`Clock`）にする。複数メソッドなら役割の名詞（`LoanRepository`）にする。`I` の接頭辞や、実装側の `Impl` の接尾辞は付けない。実装は、何で実装したかを package 名と型名で言う。

## 生成は `New`、復元は `Restore`

生成は `New<型名>` と名付ける。生成の条件で拒む値があるときだけ `(T, error)` を返す。永続化から組み立て直すのは `Restore<型名>` で、生成と復元を同じ関数にしない。`New` の接頭辞は生成関数だけに使い、型の名前には使わない（まだ保存されていない状態の型を `NewLoan` と名付けると、生成関数と取り違える）。`Create`、`Make`、`Build` は使わない。`Must<型名>` は、失敗すればプログラムの誤りであるもの（`regexp.MustCompile`）だけに使う。

## エラーは `Err<何が拒まれたか>`

エラーの定義は `ErrLoanLimitReached` のように、`Err` の接頭辞と、何が拒まれたかで名付ける。文言と分類は handle-errors が決める。

## 結果と入力の struct

集約のコマンドの結果は `<コマンド名>Result`、usecase の入力は `<usecase名>Input`、出力は `<usecase名>Output` にする。`Response`、`DTO`、`Req` を混ぜない。

## 変換関数は `<元>To<先>`

変換は同じ package に何本も並ぶので、何を何にするかを名前で言う（`loanRowToLoan`、`lentToInsertParams`）。`convert`、`toDomain`、`fromRow` のように、元か先の片方が名前に無いものは付けない。

## 変数と定数

変数の名前は、スコープが短いほど短く、長いほど説明的にする。エラーは常に `err`、`context.Context` は常に `ctx` である。`data`、`info`、`tmp`、`result` のように、何のデータかが無い名前は付けない。同じ意味の変数に二つの名前を付けない。

定数は MixedCaps（`loanPeriodDays`）で、値の意味を名前にする。`ALL_CAPS` にしない。マジックナンバーを本文に埋めない。
