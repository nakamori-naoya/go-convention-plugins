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

func TestFollowing_UnfollowUser(t *testing.T) {
	t.Parallel()

	u0001, err := id.NewUserID("0193a3c1-7a4e-7c2e-9f10-000000000001")
	require.NoError(t, err)
	u0002, err := id.NewUserID("0193a3c1-7a4e-7c2e-9f10-000000000002")
	require.NoError(t, err)
	followID := domain.NewFollowIDFromUUID(uuid.MustParse("0193a3c1-7a4e-7c2e-9f10-0000000f0001"))

	type unfollowed struct {
		followID domain.FollowID
		version  domain.Version
	}

	tests := []struct {
		id          string
		name        string
		description string
		following   domain.Following // Given: フォロー中のフォロー。フォロー中の人数はフォローの中に無いので受け取らない
		wantEvent   unfollowed       // Then
	}{
		{
			id:   "BDD-010",
			name: "フォロー中の相手を外すとフォローが終わる",
			description: `Given: フォロワー U-0001、フォロー相手 U-0002 のフォローがフォロー中である
  And: 利用者 U-0001 のフォロー中の人数は11人である
When: 利用者 U-0001 が本人として利用者 U-0002 のフォローを外す
Then: そのフォローは終わり、「フォローを外した」が起きる
  And: 利用者 U-0001 のフォロー中の人数は10人になり、U-0002 は U-0001 から見てフォローしていない相手になる`,
			following: domain.RestoreFollowing(followID, domain.NewFollower(u0001), domain.NewFollowee(u0002), domain.FirstVersion),
			wantEvent: unfollowed{followID: followID, version: domain.FirstVersion.Next()},
		},
	}
	for _, tt := range tests {
		t.Run(tt.id+" "+tt.name, func(t *testing.T) {
			t.Parallel()

			got := tt.following.UnfollowUser()
			assert.Equal(t, tt.wantEvent, unfollowed{followID: got.Event.FollowID(), version: got.Event.Version()})
		})
	}
}
