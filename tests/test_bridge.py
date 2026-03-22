"""Tests for druidclaw.web.bridge module."""
import pytest
from druidclaw.web.bridge import _ANSI_CLEAN_RE


def _strip_ansi(text: str) -> str:
    """Helper for tests - strips ANSI codes using combined regex."""
    return _ANSI_CLEAN_RE.sub('', text)


class TestStripAnsi:
    """Test ANSI stripping utilities."""

    def test_plain_text_unchanged(self):
        """Should leave plain text unchanged."""
        text = "Hello, World!"
        assert _strip_ansi(text) == text

    def test_remove_color_codes(self):
        """Should remove ANSI color codes."""
        # \x1b[31m = red, \x1b[0m = reset
        text = "\x1b[31mRed\x1b[0m"
        assert _strip_ansi(text) == "Red"

    def test_remove_cursor_movement(self):
        """Should remove cursor movement codes."""
        # \x1b[2J = clear screen, \x1b[H = home
        text = "\x1b[2J\x1b[HHello"
        assert _strip_ansi(text) == "Hello"

    def test_remove_bold_underline(self):
        """Should remove bold and underline codes."""
        text = "\x1b[1mBold\x1b[4mUnderline\x1b[0m"
        assert _strip_ansi(text) == "BoldUnderline"

    def test_remove_256_color(self):
        """Should remove 256-color codes."""
        # \x1b[38;5;196m = 256-color red
        text = "\x1b[38;5;196mColor\x1b[0m"
        assert _strip_ansi(text) == "Color"

    def test_remove_rgb_color(self):
        """Should remove true color (RGB) codes."""
        # \x1b[38;2;255;0;0m = RGB red
        text = "\x1b[38;2;255;0;0mRGB\x1b[0m"
        assert _strip_ansi(text) == "RGB"

    def test_remove_window_title(self):
        """Should remove window title (OSC) codes."""
        # \x1b]0;Title\x07 = set window title
        text = "\x1b]0;My Title\x07Hello"
        assert _strip_ansi(text) == "Hello"

    def test_mixed_ansi_sequence(self):
        """Should handle mixed ANSI sequences."""
        text = "\x1b[1;31;44mBold Red on Blue\x1b[0m normal"
        assert _strip_ansi(text) == "Bold Red on Blue normal"

    def test_spinner_characters(self):
        """Should preserve spinner characters."""
        text = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏ Loading"
        result = _strip_ansi(text)
        assert "⠋" in result
        assert "Loading" in result

    def test_unicode_preserved(self):
        """Should preserve Unicode characters."""
        text = "Hello 你好 🌍"
        assert _strip_ansi(text) == text

    def test_empty_string(self):
        """Should handle empty string."""
        assert _strip_ansi("") == ""

    def test_only_ansi_codes(self):
        """Should return empty string for only ANSI codes."""
        text = "\x1b[31m\x1b[0m\x1b[2J"
        assert _strip_ansi(text) == ""


class TestBridgeConfig:
    """Test bridge config functions (mocked)."""

    def test_load_bridge_config_default(self):
        """Should return default config when file doesn't exist."""
        from druidclaw.web.bridge import _load_bridge_config, _bridge_cfg

        # _bridge_cfg has defaults
        assert "reply_delay" in _bridge_cfg
        assert _bridge_cfg["reply_delay"] == 2.0

    def test_save_bridge_config(self, tmp_path, monkeypatch):
        """Should save config to file."""
        from druidclaw.web.bridge import _save_bridge_config, _bridge_cfg, _bridge_cfg_lock
        import druidclaw.web.bridge as bridge_mod

        original = bridge_mod.BRIDGE_CONFIG_FILE
        bridge_mod.BRIDGE_CONFIG_FILE = tmp_path / "bridge.json"

        try:
            with _bridge_cfg_lock:
                _bridge_cfg["reply_delay"] = 3.0
            _save_bridge_config()

            config_file = tmp_path / "bridge.json"
            assert config_file.exists()
        finally:
            bridge_mod.BRIDGE_CONFIG_FILE = original
