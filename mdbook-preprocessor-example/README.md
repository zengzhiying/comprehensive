# mdBook Preprocessor Example

一个使用 Python 编写的 mdBook 预处理器示例项目，用于在渲染前自动去除 Markdown 文件头部的 YAML 元数据（front matter）。

## 项目结构

```
├── book.toml                          # mdBook 配置文件
├── preprocessors/
│   └── strip_front_matter.py          # Python 预处理器脚本
└── src/
    ├── SUMMARY.md                     # 书籍目录
    ├── json-canonicalization-scheme.md
    └── rust-build-scripts-generate-protobuf-usage.md
```

## 工作原理

mdBook 预处理器通过 stdin/stdout 与 mdBook 进程通信：

1. mdBook 向预处理器的 stdin 写入 JSON 数组 `[context, book]`
2. 预处理器处理后将修改过的 `book` 对象通过 stdout 输出
3. 当传入 `supports` 参数时，预处理器以退出码 0 表示支持该渲染器

本预处理器使用正则表达式匹配并移除 Markdown 文件开头 `---` 分隔的 YAML front matter：

```yaml
---
title: 文章标题
tags:
  - example
created_time: 2026-01-01
---
```

## 使用方法

### 环境要求

- Python 3.x
- mdBook

### 构建书籍

```bash
mdbook build
```

### 直接测试预处理器

```bash
# 测试 supports 子命令
python3 preprocessors/strip_front_matter.py supports html

# 测试实际预处理，模拟 mdbook 传入的 JSON
cat > /tmp/test_input.json << 'EOF'
[
  {"root": "/tmp", "config": {}, "renderer": "html", "mdbook_version": "0.4.40"},
  {"items": [{"Chapter": {"name": "Test", "content": "---\ntitle: foo\n---\n\n# Hello\n", "number": [1], "sub_items": [], "path": "test.md", "source_path": "test.md", "parent_names": []}}]}
]
EOF

python3 preprocessors/strip_front_matter.py < /tmp/test_input.json | python3 -m json.tool
```

输出结果中 `content` 字段的 front matter 将被移除：

```json
{
    "items": [
        {
            "Chapter": {
                "name": "Test",
                "content": "# Hello\n",
                ...
            }
        }
    ]
}
```

## 配置说明

`book.toml` 中的预处理器配置：

```toml
[preprocessor.strip-front-matter]
command = "python3 preprocessors/strip_front_matter.py"
```

## 参考链接

- [mdBook 官方文档](https://rust-lang.github.io/mdBook/)
- [mdBook 预处理器开发指南](https://rust-lang.github.io/mdBook/for_developers/preprocessors.html)
- [mdBook 配置 - 预处理器](https://rust-lang.github.io/mdBook/format/configuration/preprocessors.html)
