package domain_test

// BDD の資料: docs/lending/業務知識.md

import "testing"

func TestPendingLoan_Borrow(t *testing.T) {
	tests := []struct {
		id          string
		name        string
		description string
	}{
		{
			id:   "BDD-001",
			name: "延滞の無い利用者が本を借りると貸出中の貸出が生まれる",
			description: `Given: 利用者 U-0001 は本を1冊も借りておらず、延滞の貸出も無い
When: 利用者 U-0001 が2026年10月1日に本 B-1001 を借りる
Then: 利用者 U-0001 と本 B-1001 の貸出が貸出中で生まれる`,
		},
		{
			id:   "BDD-003",
			name: "5冊借りている利用者は6冊目を借りられない",
			description: `Given: 利用者 U-0001 は貸出中の本を5冊借りている
When: 利用者 U-0001 が2026年10月1日に本 B-1006 を借りる
Then: 貸出は生まれない`,
		},
	}
	for _, tt := range tests {
		t.Run(tt.id+" "+tt.name, func(t *testing.T) {})
	}
}
