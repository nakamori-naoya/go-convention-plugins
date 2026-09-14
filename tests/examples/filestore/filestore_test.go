package filestore_test

import (
	"io/fs"
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"example.com/go-test-convention/examples/filestore"
)

func TestStore_Save(t *testing.T) {
	t.Parallel()

	// fixture は SUT と、Then で覗く共同作業者（保存先ディレクトリ）を持つ。
	type fixture struct {
		sut *filestore.Store
		dir string
	}

	tests := []struct {
		id          string
		name        string
		description string
		setup       func(t *testing.T) fixture              // Given: 資源の取得だけ
		seed        []string                                // Given: 保存済みのキー。投入はループ本体
		key         string                                  // When:  対象メソッドの引数名そのまま
		body        []byte                                  // When
		wantSize    int                                     // Then
		wantErr     error                                   // Then: nil なら成功を期待
		wantFiles   []string                                // Then: 保存先に在るファイル名。無ければ書かない
		verify      func(t *testing.T, got filestore.Saved) // Then: got の性質で、等値で書けないもの
	}{
		{
			id:   "6b0d4e",
			name: "本文をキー名のファイルとして保存する",
			description: `Given: 空の保存先がある
When: キー a に 5 バイトの本文を保存する
Then: 5 バイト保存され、保存先はキー a を名前にした絶対パスである
  And: 保存先にはファイル a だけが在る`,
			setup: func(t *testing.T) fixture {
				dir := t.TempDir()
				sut, err := filestore.Open(dir)
				require.NoError(t, err)
				return fixture{sut: sut, dir: dir}
			},
			key:       "a",
			body:      []byte("hello"),
			wantSize:  5,
			wantFiles: []string{"a"},
			verify: func(t *testing.T, got filestore.Saved) {
				assert.True(t, filepath.IsAbs(got.Path()))
				assert.Equal(t, "a", filepath.Base(got.Path()))
			},
		},
		{
			id:   "f18c72",
			name: "別のキーなら保存済みの隣に足される",
			description: `Given: キー a が保存済みである
When: キー b に 5 バイトの本文を保存する
Then: 5 バイト保存される
  And: 保存先にはファイル a と b が在る`,
			setup: func(t *testing.T) fixture {
				dir := t.TempDir()
				sut, err := filestore.Open(dir)
				require.NoError(t, err)
				return fixture{sut: sut, dir: dir}
			},
			seed:      []string{"a"},
			key:       "b",
			body:      []byte("world"),
			wantSize:  5,
			wantFiles: []string{"a", "b"},
		},
		{
			id:   "4d9a35",
			name: "空の本文でもファイルは作られる",
			description: `Given: 空の保存先がある
When: キー a に空の本文を保存する
Then: 0 バイト保存される
  And: 保存先にはファイル a だけが在る`,
			setup: func(t *testing.T) fixture {
				dir := t.TempDir()
				sut, err := filestore.Open(dir)
				require.NoError(t, err)
				return fixture{sut: sut, dir: dir}
			},
			key:       "a",
			body:      []byte{},
			wantSize:  0,
			wantFiles: []string{"a"},
		},
		{
			id:   "c72e60",
			name: "空のキーには保存できない",
			description: `Given: 空の保存先がある
When: 空のキーに本文を保存する
Then: キーが空のため拒まれる
  And: 保存先にファイルは無い`,
			setup: func(t *testing.T) fixture {
				dir := t.TempDir()
				sut, err := filestore.Open(dir)
				require.NoError(t, err)
				return fixture{sut: sut, dir: dir}
			},
			key:     "",
			body:    []byte("hello"),
			wantErr: filestore.ErrEmptyKey,
		},
		{
			id:   "09e7b4",
			name: "保存済みのキーには上書きしない",
			description: `Given: キー a が保存済みである
When: キー a に本文を保存する
Then: 保存済みのため拒まれる
  And: 保存先にはファイル a だけが在る
  NOTE: Rule: 同じキーには一度しか保存できない
    Reason: キー a が保存済みで、二件目の保存になるため`,
			setup: func(t *testing.T) fixture {
				dir := t.TempDir()
				sut, err := filestore.Open(dir)
				require.NoError(t, err)
				return fixture{sut: sut, dir: dir}
			},
			seed:      []string{"a"},
			key:       "a",
			body:      []byte("again"),
			wantErr:   filestore.ErrExists,
			wantFiles: []string{"a"},
		},
		{
			id:   "1fa5c9",
			name: "保存先が読み取り専用なら保存できない",
			description: `Given: 読み取り専用の保存先がある
When: キー a に本文を保存する
Then: 書き込めないため拒まれる
  And: 保存先にファイルは無い`,
			setup: func(t *testing.T) fixture {
				dir := t.TempDir()
				sut, err := filestore.Open(dir)
				require.NoError(t, err)
				require.NoError(t, os.Chmod(dir, 0o500))
				t.Cleanup(func() { _ = os.Chmod(dir, 0o700) }) // 権限を戻してから t.TempDir の削除が走る（LIFO）
				return fixture{sut: sut, dir: dir}
			},
			key:     "a",
			body:    []byte("hello"),
			wantErr: fs.ErrPermission,
		},
	}

	for _, tt := range tests {
		t.Run(tt.id+" "+tt.name, func(t *testing.T) {
			t.Parallel()

			f := tt.setup(t) // サブテストの t を渡す。t.Cleanup がこのケースの終わりに走る
			for _, key := range tt.seed {
				_, err := f.sut.Save(key, []byte("seeded"))
				require.NoError(t, err)
			}

			got, err := f.sut.Save(tt.key, tt.body)
			if tt.wantErr != nil {
				require.ErrorIs(t, err, tt.wantErr)
				assert.Zero(t, got)
			} else {
				require.NoError(t, err)
				assert.Equal(t, tt.wantSize, got.Size())
				if tt.verify != nil {
					tt.verify(t, got)
				}
			}

			// 副作用は共同作業者（保存先）を公開の手段で観測し、want{何} と突き合わせる。
			entries, err := os.ReadDir(f.dir)
			require.NoError(t, err)
			var gotFiles []string // ファイル無しはゼロ値。wantFiles を書かないケースと一致する
			for _, e := range entries {
				gotFiles = append(gotFiles, e.Name())
			}
			assert.Equal(t, tt.wantFiles, gotFiles)
		})
	}
}
