package domain_test

// BDD の資料: docs/フォロー/business-knowledge.md

import (
	"testing"
	"uuid"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"example.com/service/follow/follow/domain"
	"example.com/service/internal/shared/vo/id"
)

func TestPendingFollow_FollowUser(t *testing.T) {
	t.Parallel()

	// U-0001 はフォロワー、U-0002 から U-0004 はフォロー相手になる登録済みの利用者である。
	u0001, err := id.NewUserID("0193a3c1-7a4e-7c2e-9f10-000000000001")
	require.NoError(t, err)
	u0002, err := id.NewUserID("0193a3c1-7a4e-7c2e-9f10-000000000002")
	require.NoError(t, err)
	u0003, err := id.NewUserID("0193a3c1-7a4e-7c2e-9f10-000000000003")
	require.NoError(t, err)
	u0004, err := id.NewUserID("0193a3c1-7a4e-7c2e-9f10-000000000004")
	require.NoError(t, err)
	follower := domain.NewFollower(u0001)
	followID := domain.NewFollowIDFromUUID(uuid.MustParse("0193a3c1-7a4e-7c2e-9f10-0000000f0001"))

	// 表で使う人数。生成の条件は FollowingCount のテストが確かめる。
	ten, err := domain.NewFollowingCount(10)
	require.NoError(t, err)
	justBelowLimit, err := domain.NewFollowingCount(4999)
	require.NoError(t, err)
	atLimit, err := domain.NewFollowingCount(5000)
	require.NoError(t, err)

	type followed struct {
		followID domain.FollowID
		version  domain.Version
		follower domain.Follower
		followee domain.Followee
	}

	tests := []struct {
		id             string
		name           string
		description    string
		followingCount domain.FollowingCount // Given: フォロワーのフォロー中の人数
		followee       domain.Followee       // Given: フォロー相手
		wantNext       domain.Following      // Then
		wantEvent      followed              // Then
		wantErr        error                 // Then: nil なら受ける
	}{
		{
			id:   "BDD-001",
			name: "フォローしていない相手をフォローするとフォロー中になる",
			description: `Given: 利用者 U-0001 のフォロー中の人数は10人である
  And: 利用者 U-0002 は登録済みの利用者で、利用者 U-0001 は U-0002 をフォローしていない
When: 利用者 U-0001 が本人として利用者 U-0002 をフォローする
Then: フォロワー U-0001、フォロー相手 U-0002 のフォローがフォロー中で生まれ、「フォローした」が起きる
  And: 利用者 U-0001 のフォロー中の人数は11人になる`,
			followingCount: ten,
			followee:       domain.NewFollowee(u0002),
			wantNext:       domain.RestoreFollowing(followID, follower, domain.NewFollowee(u0002), domain.FirstVersion),
			wantEvent:      followed{followID: followID, version: domain.FirstVersion, follower: follower, followee: domain.NewFollowee(u0002)},
		},
		{
			id:   "BDD-002",
			name: "4,999人をフォロー中の利用者は5,000人目をフォローできる",
			description: `Given: 利用者 U-0001 のフォロー中の人数は4,999人である
  And: 利用者 U-0003 は登録済みの利用者で、利用者 U-0001 は U-0003 をフォローしていない
When: 利用者 U-0001 が本人として利用者 U-0003 をフォローする
Then: フォロワー U-0001、フォロー相手 U-0003 のフォローがフォロー中で生まれ、「フォローした」が起きる
  And: 利用者 U-0001 のフォロー中の人数は5,000人になる`,
			followingCount: justBelowLimit,
			followee:       domain.NewFollowee(u0003),
			wantNext:       domain.RestoreFollowing(followID, follower, domain.NewFollowee(u0003), domain.FirstVersion),
			wantEvent:      followed{followID: followID, version: domain.FirstVersion, follower: follower, followee: domain.NewFollowee(u0003)},
		},
		{
			id:   "BDD-003",
			name: "5,000人をフォロー中の利用者は次の一人をフォローできない",
			description: `Given: 利用者 U-0001 のフォロー中の人数は5,000人である
  And: 利用者 U-0004 は登録済みの利用者で、利用者 U-0001 は U-0004 をフォローしていない
When: 利用者 U-0001 が本人として利用者 U-0004 をフォローする
Then: フォローは生まれず、「フォローした」は起きない
  And: 利用者 U-0001 のフォロー中の人数は5,000人のままである
  NOTE: Rule: フォロー上限に達している利用者がフォローする
    Reason: 一人の利用者のフォロー中の人数は5,000人を超えない`,
			followingCount: atLimit,
			followee:       domain.NewFollowee(u0004),
			wantErr:        domain.ErrFollowLimitReached,
		},
		{
			id:   "BDD-004",
			name: "自分自身はフォローできない",
			description: `Given: 利用者 U-0001 のフォロー中の人数は10人である
When: 利用者 U-0001 が本人として利用者 U-0001 をフォローする
Then: フォローは生まれず、「フォローした」は起きない
  NOTE: Rule: 自分自身をフォローする
    Reason: 利用者は自分自身をフォローしない`,
			followingCount: ten,
			followee:       domain.NewFollowee(u0001),
			wantErr:        domain.ErrFollowSelf,
		},
		{
			id:   "e4b7a2",
			name: "フォロー上限に達している利用者が自分自身をフォローすると自分自身の理由で拒まれる",
			description: `Given: 利用者 U-0001 のフォロー中の人数は5,000人である
When: 利用者 U-0001 が本人として利用者 U-0001 をフォローする
Then: 自分自身をフォローするとして拒まれる`,
			followingCount: atLimit,
			followee:       domain.NewFollowee(u0001),
			wantErr:        domain.ErrFollowSelf,
		},
	}
	for _, tt := range tests {
		t.Run(tt.id+" "+tt.name, func(t *testing.T) {
			t.Parallel()

			got, err := domain.NewPendingFollow(follower, tt.followee, tt.followingCount).FollowUser(followID)
			if tt.wantErr != nil {
				require.ErrorIs(t, err, tt.wantErr)
				assert.Zero(t, got)
				return
			}
			require.NoError(t, err)
			assert.Equal(t, tt.wantNext, got.Next)
			assert.Equal(t, tt.wantEvent, followed{
				followID: got.Event.FollowID(),
				version:  got.Event.Version(),
				follower: got.Event.Follower(),
				followee: got.Event.Followee(),
			})
		})
	}
}
