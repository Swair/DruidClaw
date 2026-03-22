# DruidClaw 测试文档

本文档说明如何运行和编写 DruidClaw 的测试。

## 运行测试

### 安装测试依赖

```bash
source venv/bin/activate  # 激活虚拟环境
pip install pytest httpx
```

### 运行所有测试

```bash
pytest
# 或指定详细输出
pytest -v
```

### 运行特定测试文件

```bash
pytest tests/test_ringbuf.py       # 环形缓冲区测试
pytest tests/test_imbot.py         # IM 机器人测试
pytest tests/test_routes.py        # API 路由测试
pytest tests/test_state.py         # 状态管理测试
pytest tests/test_session.py       # 会话管理测试
pytest tests/test_bridge.py        # 桥接逻辑测试
```

### 运行特定测试类

```bash
pytest tests/test_ringbuf.py::TestRingBufWrite
pytest tests/test_imbot.py::TestFeishuBot
```

### 运行特定测试函数

```bash
pytest tests/test_ringbuf.py::TestRingBufWrite::test_write_small_data
```

### 显示输出信息

```bash
pytest -s  # 显示 print 输出
pytest -v  # 显示详细测试信息
```

### 显示覆盖率

```bash
pip install pytest-cov
pytest --cov=druidclaw --cov-report=html
```

查看覆盖率报告：打开 `htmlcov/index.html`

## 测试文件结构

```
tests/
├── test_ringbuf.py    # 环形缓冲区测试 (22 个测试)
├── test_session.py    # 会话管理测试 (7 个测试)
├── test_state.py      # 状态管理测试 (6 个测试)
├── test_imbot.py      # IM 机器人测试 (23 个测试)
├── test_bridge.py     # 桥接逻辑测试 (15 个测试)
└── test_routes.py     # API 路由测试 (12 个测试)
```

总计：**86 个测试用例**

## 测试结果示例

```
======================== 86 passed in 114.22s ========================
```

## 编写新测试

### 测试文件命名

- 文件名：`test_<module>.py`
- 测试类：`Test<ClassName>`
- 测试函数：`test_<description>`

### 测试模板

```python
"""Tests for druidclaw.<module>."""
import pytest
from druidclaw.<module> import <function>


class Test<FunctionName>:
    """Test <function> functionality."""

    def test_description(self):
        """Should do something."""
        result = <function>(args)
        assert result == expected

    def test_another_case(self):
        """Should handle another case."""
        # Test code here
```

### 常用断言

```python
assert value == expected      # 相等
assert value != unexpected    # 不相等
assert len(items) == 3        # 长度
assert value in collection    # 包含
assert isinstance(obj, Type)  # 类型检查
assert obj is None            # None 检查

# 异常检查
with pytest.raises(ValueError, match="error message"):
    function_that_raises()
```

### 使用临时文件

```python
def test_with_temp_file(self, tmp_path):
    """Should work with temporary files."""
    temp_file = tmp_path / "test.txt"
    temp_file.write_text("content")
    # Test code
```

### Mock 外部依赖

```python
from unittest.mock import patch, MagicMock

def test_with_mock(self):
    """Should work with mocked dependencies."""
    with patch('module.function') as mock_fn:
        mock_fn.return_value = "mocked"
        # Test code
```

## 测试覆盖的模块

### 核心模块 (core/)

- `ringbuf.py` - 环形缓冲区
- `session.py` - Claude 会话管理
- `daemon.py` - 守护进程

### IM 机器人 (imbot/)

- `feishu.py` - 飞书机器人
- `telegram.py` - Telegram 机器人
- `dingtalk.py` - 钉钉机器人
- `qq.py` - QQ 机器人
- `wework.py` - 企业微信机器人

### Web 模块 (web/)

- `bridge.py` - IM 桥接逻辑
- `state.py` - 全局状态管理
- `routes/` - API 路由

## 持续集成

在 CI/CD 中运行测试：

```yaml
# GitHub Actions 示例
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      - run: pip install -r requirements.txt pytest
      - run: pytest
```

## 常见问题

### Q: 测试失败因为 claude 未安装

A: 某些测试需要 Claude Code，可以跳过这些测试：

```bash
pytest -k "not claude"
```

### Q: 如何调试测试

A: 使用 `-s` 显示输出，或在测试中使用 `print()`：

```bash
pytest -s tests/test_file.py::test_name
```

### Q: 测试运行缓慢

A: 使用 `-x` 在首次失败时停止，或使用 `-q` 减少输出：

```bash
pytest -x -q
```
