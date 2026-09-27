---
type: regex
target: trace
pattern: '^(?:(?!"name":"(?:Write|Edit)","input":\{"file_path":"(?![^"]*/builders/)[^"]*/domain/[^"]*(?<!_test)\.go")[\s\S])*?(?:\[build failed\]|\[setup failed\]|undefined: |-{3} FAIL)'
---
