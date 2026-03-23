"""
Main Entry Point
=================
Wires together: RC clients (one per bot) → session manager → Claude SDK.
"""

from __future__ import annotations

import asyncio
import threading
import time

from .agent_registry import AgentRegistry
from .config import settings
from .rc_client import RCClient
from .sdk_client import create_claude_client
from .session_manager import Session, SessionManager
from .stream_handler import StreamHandler


class ClaudeWorkspaceBot:
    """
    Main bot service.

    Creates one RCClient per agent (bot user).
    Routes incoming messages to Claude sessions.
    Streams responses back to Rocket.Chat.
    """

    def __init__(self):
        self.agents = AgentRegistry(agents_dir=settings.agents_dir)
        self.sessions = SessionManager()

        # One RC client per bot user
        self.rc_clients: dict[str, RCClient] = {}

        # Asyncio loop for Claude SDK calls (runs in background thread)
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

    def start(self):
        """Login all bot users and connect WebSockets."""
        if not self.agents.list_agents():
            print("\nNo agents configured. Add YAML files to bot/agents/")
            print("See bot/agents/example-project.yaml for reference.")
            return

        print(f"\nStarting bot service...")
        print(f"  RC server: {settings.rc_url}")
        print(f"  Agents: {len(self.agents.list_agents())}")
        print()

        for agent in self.agents.list_agents():
            try:
                rc = RCClient(
                    server_url=settings.rc_url,
                    username=agent.rc_username,
                    password=settings.rc_bot_password,
                )
                rc.login()
                rc.on_message(
                    lambda room_id, sender_id, sender_username, text, _agent=agent, _rc=rc:
                        self._on_message(_rc, _agent.name, room_id, sender_id, sender_username, text)
                )
                rc.connect_ws()
                self.rc_clients[agent.name] = rc
            except Exception as e:
                print(f"  [Error] Failed to start bot for {agent.name}: {e}")

        print(f"\nAll bots connected. Listening for messages.\n")

        # Keep main thread alive
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down...")
            self._shutdown()

    def _on_message(
        self,
        rc: RCClient,
        agent_name: str,
        room_id: str,
        sender_id: str,
        sender_username: str,
        text: str,
    ):
        """Handle incoming message from a specific bot's channel."""
        print(f"\n[{agent_name}] {sender_username}: {text}")

        # Dispatch to asyncio loop
        asyncio.run_coroutine_threadsafe(
            self._handle_message(rc, agent_name, room_id, sender_id, text),
            self.loop,
        )

    async def _handle_message(
        self,
        rc: RCClient,
        agent_name: str,
        room_id: str,
        user_id: str,
        text: str,
    ):
        """Route message to Claude session and stream response."""
        agent = self.agents.get(agent_name)
        if not agent:
            rc.send_message(room_id, f"Agent '{agent_name}' not found.")
            return

        # Cleanup stale sessions opportunistically
        await self.sessions.cleanup_stale()

        # Get or create Claude session
        session = self.sessions.get(user_id, agent_name)
        if not session:
            session = await self._create_session(user_id, agent_name, agent)
            if not session:
                rc.send_message(room_id, "Failed to create Claude session.")
                return

        # Process with lock (serialize messages per session)
        async with session.lock:
            await self._execute_and_stream(rc, session, room_id, text)

    async def _create_session(self, user_id: str, agent_name: str, agent) -> Session | None:
        """Create a new Claude session for a user-bot pair."""
        try:
            client = create_claude_client(agent)
            session = Session(
                user_id=user_id,
                bot_name=agent_name,
                agent_config=agent,
                client=client,
                permission_mode=agent.permission_mode,
            )
            await client.connect()
            session.connected = True
            self.sessions.store(session)
            print(f"  [Session] Created {session.key}")
            return session
        except Exception as e:
            print(f"  [Session] Failed to create for {user_id}:{agent_name}: {e}")
            return None

    async def _execute_and_stream(
        self,
        rc: RCClient,
        session: Session,
        room_id: str,
        text: str,
    ):
        """Send prompt to Claude and stream response back to RC."""
        start_time = time.time()

        # Create placeholder message
        msg_id = rc.send_message(room_id, "⏳ Thinking...")

        streamer = StreamHandler(
            rc=rc,
            room_id=room_id,
            msg_id=msg_id,
            agent_name=session.bot_name,
            interval=settings.stream_update_interval,
        )

        try:
            await session.client.query(text)

            async for msg in session.client.receive_response():
                msg_type = type(msg).__name__

                if msg_type == "AssistantMessage" and hasattr(msg, "content"):
                    for block in msg.content:
                        block_type = type(block).__name__
                        if block_type == "TextBlock" and hasattr(block, "text"):
                            streamer.on_text(block.text)
                        elif block_type == "ToolUseBlock" and hasattr(block, "name"):
                            tool_input = getattr(block, "input", {}) or {}
                            streamer.on_tool_start(block.name, tool_input)

                elif msg_type == "UserMessage" and hasattr(msg, "content"):
                    for block in msg.content:
                        if type(block).__name__ == "ToolResultBlock":
                            content = str(getattr(block, "content", ""))
                            is_error = getattr(block, "is_error", False)
                            streamer.on_tool_result(content, is_error)

                elif msg_type == "SystemMessage":
                    if hasattr(msg, "data") and isinstance(msg.data, dict):
                        sid = msg.data.get("session_id")
                        if sid:
                            session.session_id = sid
                        mode = msg.data.get("permission_mode")
                        if mode:
                            session.permission_mode = mode

                elif msg_type == "ResultMessage":
                    result_sid = getattr(msg, "session_id", None)
                    if result_sid:
                        session.session_id = result_sid
                    break

            duration = f"{time.time() - start_time:.0f}s"
            streamer.finalize(duration, session.permission_mode, session.session_id)

        except Exception as e:
            print(f"  [Error] {session.key}: {e}")
            rc.update_message(room_id, msg_id, f"❌ Error: {e}")
            # Close broken session
            await self.sessions.close(session.user_id, session.bot_name)

    def _shutdown(self):
        """Clean shutdown — close all sessions."""
        for session in list(self.sessions._sessions.values()):
            try:
                asyncio.run_coroutine_threadsafe(
                    self.sessions.close(session.user_id, session.bot_name),
                    self.loop,
                ).result(timeout=5)
            except Exception:
                pass


def main():
    print("=" * 50)
    print("  Claude Workspace Bot Service")
    print("=" * 50)
    print()

    bot = ClaudeWorkspaceBot()
    bot.start()


if __name__ == "__main__":
    main()
