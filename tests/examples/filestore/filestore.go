// Package filestore は、規約の例のためだけの小さな被験体である。
// Given にディレクトリという資源が要る型（setup が要る型）の例として使う。
package filestore

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
)

// ErrEmptyKey は、キーが空で保存先の名前を決められないことを表す。
var ErrEmptyKey = errors.New("key is empty")

// ErrExists は、同じキーが保存済みで上書きしないという正当な結果を表す。
var ErrExists = errors.New("key already exists")

// Store は、1つのディレクトリにキー名のファイルとして本文を保存する。
type Store struct {
	dir string
}

// Open は既存のディレクトリを保存先にした Store を返す。ディレクトリでなければ error を返す。
func Open(dir string) (*Store, error) {
	info, err := os.Stat(dir)
	if err != nil {
		return nil, fmt.Errorf("open store: %w", err)
	}
	if !info.IsDir() {
		return nil, fmt.Errorf("open store: %s is not a directory", dir)
	}
	return &Store{dir: dir}, nil
}

// Saved は保存の結果。保存先の絶対パスと本文のバイト数を持つ。
type Saved struct {
	path string
	size int
}

// Path は保存先の絶対パスを返す。
func (r Saved) Path() string { return r.path }

// Size は保存した本文のバイト数を返す。
func (r Saved) Size() int { return r.size }

// Save は key を名前にしたファイルへ body を書き、保存の結果を返す。
// key が空なら ErrEmptyKey、同じ key が保存済みなら ErrExists を返し、ファイルは作らない。
func (s *Store) Save(key string, body []byte) (Saved, error) {
	if key == "" {
		return Saved{}, ErrEmptyKey
	}
	path, err := filepath.Abs(filepath.Join(s.dir, key))
	if err != nil {
		return Saved{}, fmt.Errorf("save %s: %w", key, err)
	}
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if errors.Is(err, os.ErrExist) {
		return Saved{}, fmt.Errorf("save %s: %w", key, ErrExists)
	}
	if err != nil {
		return Saved{}, fmt.Errorf("save %s: %w", key, err)
	}
	n, err := f.Write(body)
	if err != nil {
		_ = f.Close() // 書き込みの失敗を返す。閉じる失敗はそれに劣後する
		return Saved{}, fmt.Errorf("save %s: %w", key, err)
	}
	if err := f.Close(); err != nil {
		return Saved{}, fmt.Errorf("save %s: %w", key, err)
	}
	return Saved{path: path, size: n}, nil
}
