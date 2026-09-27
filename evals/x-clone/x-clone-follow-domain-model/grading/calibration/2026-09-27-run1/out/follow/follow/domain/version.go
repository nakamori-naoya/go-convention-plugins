package domain

// Version は、保存されたフォローの版である。コマンドを受けるたびに一つ進む。
type Version struct{ n int64 }

// FirstVersion は、フォローしたときに生まれたフォローの版である。
var FirstVersion = Version{n: 1}

// Next は、一つ進めた版を返す。
func (v Version) Next() Version { return Version{n: v.n + 1} }
