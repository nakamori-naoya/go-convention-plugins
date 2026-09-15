# 行から読み取りモデルへの変換

**読み取りモデルはユースケース側が所有する契約である。Query実装はその型を再定義せず、DB行、SQLの関係計算、確認済みの値オブジェクトまたは純関数の結果を契約の型へ写す。** これにより依存は外側の実装から内側の契約へ向く。

## 型の境界

読み取りモデルは公開フィールドを持つ struct で、標準の型だけを持つ。集約、VO、sqlc の行、`pgtype`、proto を含めない。業務語で名付け、`DTO`、`Row`、`Response` の接尾辞を付けない。

```go
package query

import (
	"time"
	"github.com/jackc/pgx/v5/pgtype"
	querycontract "example.com/roomflow/reservation/usecase/query"
	"example.com/roomflow/rdb/sqlcgen"
)

func listRoomSlotsForDayRowToAvailableSlot(row sqlcgen.ListRoomSlotsForDayRow) querycontract.AvailableSlot {
	holdExpiresAt, hasHoldExpiresAt := timestamptzToTime(row.ExpiresAt)
	return querycontract.AvailableSlot{ReservationID: row.ReservationID, StartsAt: row.StartsAt.UTC(), EndsAt: row.EndsAt.UTC(), Status: row.Status, HoldExpiresAt: holdExpiresAt, HasHoldExpiresAt: hasHoldExpiresAt}
}

func timestamptzToTime(v pgtype.Timestamptz) (time.Time, bool) {
	if !v.Valid { return time.Time{}, false }
	return v.Time.UTC(), true
}
```

## 変換規則

| 項目 | 規則 |
|---|---|
| 名前 | `{Row}To{ReadModel}` |
| 引数 | DB行と、行に無いが出力に必要な解決済み値だけ |
| 返り値 | ユースケース側が所有する読み取りモデル |
| NULL | 値と `Has{X}` の対へ写し、既定値で存在を偽装しない |
| 時刻 | `.UTC()` を通す |
| 0件 | nil slice のまま返す |
| 処理 | 引数以外を読まない純粋関数。DBアクセス、集約・エンティティの復元や操作、ログ、新しい業務規則を持たない。SQLに不向きな確認済み業務計算は値オブジェクトまたは純関数を呼ぶ |

親子のJOIN結果は親の識別子で畳む。子の順序はSQLの `ORDER BY` が決め、Goで再ソートしない。子が0件の親を返すなら `LEFT JOIN` とNULLの有無で表す。

## 停止

- ユースケース側の読み取りポートまたは読み取りモデルが未確定
- 必要な値を保存列、SQLの関係計算、確認済みのドメイン値オブジェクトまたは純関数のどれからも導けず、新しい業務規則を発明しなければならない
- 型をQuery実装側へ置き、ユースケース側からimportするよう求められた
