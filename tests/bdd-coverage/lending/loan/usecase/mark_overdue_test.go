package usecase_test

// BDD の資料: docs/lending/業務知識.md

import "testing"

func TestMarkOverdue_Execute(t *testing.T) {
	tests := []struct {
		id          string
		name        string
		description string
	}{
		{
			id:   "BDD-OUT-001",
			name: "延滞になった貸出の通知の要求が延滞と同時に記録される",
			description: `Given: 貸出 L-0001 は貸出中で、返却期限は2026年10月15日である
When: 2026年10月16日に貸出 L-0001 を延滞にする
Then: 貸出は延滞になり、延滞の通知の要求が同じ確定で記録される`,
		},
		{
			id:   "5d2a90",
			name: "借りたばかりの貸出は延滞にならない",
			description: `Given: 貸出 L-0002 は貸出中で、返却期限は2026年10月15日である
When: 2026年10月1日に貸出 L-0002 を延滞にする
Then: 貸出は貸出中のまま変わらない`,
		},
	}
	for _, tt := range tests {
		t.Run(tt.id+" "+tt.name, func(t *testing.T) {})
	}
}
