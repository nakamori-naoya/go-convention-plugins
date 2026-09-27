package id_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"example.com/service/internal/shared/vo/id"
)

func TestNewUserID(t *testing.T) {
	t.Parallel()
	tests := []struct {
		id      string
		name    string
		s       string
		wantErr error
	}{
		{id: "a41c07", name: "UUID の形の値は読める", s: "0193a3c1-7a4e-7c2e-9f10-5b8d2e6a4f01"},
		{id: "5d2e90", name: "空の値は拒む", s: "", wantErr: id.ErrInvalidUserID},
		{id: "c83f11", name: "UUID でない値は拒む", s: "user-1", wantErr: id.ErrInvalidUserID},
	}
	for _, tt := range tests {
		t.Run(tt.id+" "+tt.name, func(t *testing.T) {
			t.Parallel()
			got, err := id.NewUserID(tt.s)
			if tt.wantErr != nil {
				require.ErrorIs(t, err, tt.wantErr)
				assert.Zero(t, got)
				return
			}
			require.NoError(t, err)
			assert.Equal(t, tt.s, got.Value().String())
		})
	}
}
