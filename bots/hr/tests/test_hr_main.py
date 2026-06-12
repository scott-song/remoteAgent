"""Tests for hr.main module."""

from unittest.mock import patch


class TestHRBot:
    def test_creates_bot(self):
        with patch("hr.main.FeishuClient"):
            from hr.main import HRBot

            bot = HRBot()
            assert bot.feishu is not None

    def test_help_command(self):
        with patch("hr.main.FeishuClient") as mock_cls:
            from hr.main import HELP_TEXT, HRBot

            bot = HRBot()
            bot.feishu = mock_cls.return_value
            bot._on_message("chat1", "user1", "User", "/help", "msg1")
            bot.feishu.reply.assert_called_once_with("msg1", HELP_TEXT)

    def test_unknown_message(self):
        with patch("hr.main.FeishuClient") as mock_cls:
            from hr.main import HRBot

            bot = HRBot()
            bot.feishu = mock_cls.return_value
            bot._on_message("chat1", "user1", "User", "book a meeting", "msg1")
            bot.feishu.reply.assert_called_once()
            reply_text = bot.feishu.reply.call_args[0][1]
            assert "under construction" in reply_text
