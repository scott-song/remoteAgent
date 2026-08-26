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
            bot._on_message("chat1", "user1", "User", "/help", "msg1", [])
            bot.feishu.reply.assert_called_once_with("msg1", HELP_TEXT)

    def test_unknown_message(self):
        with patch("hr.main.FeishuClient") as mock_cls:
            from hr.main import HRBot

            bot = HRBot()
            bot.feishu = mock_cls.return_value
            bot._on_message("chat1", "user1", "User", "book a meeting", "msg1", [])
            bot.feishu.reply.assert_called_once()
            reply_text = bot.feishu.reply.call_args[0][1]
            assert "under construction" in reply_text


class TestWidenedCallback:
    """The message callback gained a trailing attachments list (T4)."""

    def test_attachments_are_accepted_and_ignored(self):
        with patch("hr.main.FeishuClient") as mock_cls:
            from hr.main import HRBot

            bot = HRBot()
            bot._on_message("chat1", "user1", "User", "hello", "msg1", ["ignored"])
            assert mock_cls.return_value.reply.call_count == 1

    def test_callback_still_works_without_the_new_argument(self):
        """Defaulted so a caller that predates the change is not broken."""
        with patch("hr.main.FeishuClient") as mock_cls:
            from hr.main import HRBot

            bot = HRBot()
            bot._on_message("chat1", "user1", "User", "hello", "msg1")
            assert mock_cls.return_value.reply.call_count == 1
