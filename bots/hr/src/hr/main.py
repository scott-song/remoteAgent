"""
HR bot — responds to Feishu messages with HR assistant functionality.
Placeholder implementation.
"""

from __future__ import annotations

import asyncio
import threading
import time

from core.config import core_settings
from core.feishu_client import FeishuClient

HELP_TEXT = (
    "**HR Assistant Commands:**\n\n"
    "`/leave <date> <reason>` — request time off\n"
    "`/meeting <topic>` — schedule a meeting\n"
    "`/policy <keyword>` — look up company policy\n"
    "`/help` — this message\n\n"
    "Or just ask me anything about HR."
)


class HRBot:
    def __init__(self):
        self.feishu = FeishuClient(
            app_id=core_settings.feishu_app_id,
            app_secret=core_settings.feishu_app_secret,
        )
        self.feishu.on_message(self._on_message)

    def start(self):
        loop = asyncio.new_event_loop()
        threading.Thread(target=loop.run_forever, daemon=True).start()

        print(f"\nHR Bot")
        print(f"  Feishu app: {core_settings.feishu_app_id[:8]}...")
        self.feishu.start(loop)
        print("Listening for messages. Press Ctrl+C to stop.\n")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down...")

    def _on_message(self, chat_id: str, sender_id: str, sender_name: str, text: str, message_id: str):
        print(f"\n[Message] {sender_id[:8]}...: {text}")

        if text.strip().lower() in ("help", "/help", "hi", "hello"):
            self.feishu.reply(message_id, HELP_TEXT)
        else:
            self.feishu.reply(message_id, "🚧 HR bot is under construction. Stay tuned!")


def main():
    print("=" * 50)
    print("  HR Bot (Feishu)")
    print("=" * 50)
    HRBot().start()


if __name__ == "__main__":
    main()
