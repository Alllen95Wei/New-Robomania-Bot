# coding=utf-8
import discord
from discord.ext import commands, tasks
from discord import Option, Embed
import os
import datetime
import zoneinfo
from pathlib import Path
import logging
from websockets.asyncio.client import connect, ClientConnection
from json import loads

from roboweb_api import RobowebAPI

base_dir = os.path.abspath(os.path.dirname(__file__))
parent_dir = str(Path(__file__).parent.parent.absolute())
now_tz = zoneinfo.ZoneInfo("Asia/Taipei")
default_color = 0x012a5e
error_color = 0xF1411C

NOTIFY_CHANNEL_ID = int(os.getenv("NOTIFY_CHANNEL_ID", "1128232150135738529"))
ANNOUNCEMENT_TASKS: dict[str, dict[str, tasks.Loop | None]] = {}


class Announcement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.rwapi: RobowebAPI | None = None
        self.ws: ClientConnection | None = None

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.rwapi:
            self.rwapi = RobowebAPI(os.getenv("ROBOWEB_API_TOKEN"))
        async with (connect(f"{os.getenv('WS_URL')}announcement/",
                            additional_headers={"Authorization": f"Token {os.getenv("ROBOWEB_API_TOKEN")}"})
                    as websocket):
            self.ws = websocket
            while True:
                data = loads(await websocket.recv())
                if data["type"] == "announcement.pin":
                    announcement = data["announcement"]
                    self.setup_tasks(announcement)
                elif data["type"] == "announcement.announce":
                    announcement = data["announcement"]
                    message = f"""\
@everyone
> 此公告由 Robomania Bot Web 同步發布至此。
# {announcement['title']}
{announcement['content']}
"""
                    if len(message) > 2000:
                        message = message[:1997] + "..."
                    channel = self.bot.get_channel(NOTIFY_CHANNEL_ID)
                    await channel.send(message)
                elif data["type"] in ("announcement.delete", "announcement.unpin"):
                    announcement_id = data["announcement"]["id"]
                    if announcement_id in ANNOUNCEMENT_TASKS.keys():
                        for task_type, task in ANNOUNCEMENT_TASKS[announcement_id].items():
                            if task:
                                logging.debug(f"(#{announcement_id:2d}) Cancelling existing \"{task_type}\" task")
                                task.cancel()
                        del ANNOUNCEMENT_TASKS[announcement_id]
                else:
                    logging.info(f"Received unknown event: {data}")

    def setup_tasks(self, announcement: dict):
        announcement_id = announcement["id"]
        logging.debug(f"Setting up tasks for announcement #{announcement_id}")
        if announcement_id in ANNOUNCEMENT_TASKS.keys():
            for task_type, task in ANNOUNCEMENT_TASKS[announcement_id].items():
                if task:
                    logging.debug(f"(#{announcement_id:2d}) Cancelling existing \"{task_type}\" task")
                    task.cancel()
        pin_due_time = datetime.datetime.fromisoformat(announcement["pin_until"])
        ANNOUNCEMENT_TASKS[announcement_id] = {
            "unpin": tasks.Loop(
                coro=self.unpin_announcement,
                seconds=tasks.MISSING,
                minutes=tasks.MISSING,
                hours=tasks.MISSING,
                time=pin_due_time.timetz(),
                count=None,
                reconnect=True,
                loop=self.bot.loop,
            )
        }
        ANNOUNCEMENT_TASKS[announcement_id]["unpin"].start(announcement)

    async def unpin_announcement(self, announcement: dict):
        pin_due_date = datetime.datetime.fromisoformat(announcement["pin_until"])
        if pin_due_date - datetime.datetime.now(now_tz) > datetime.timedelta(seconds=1000):
            return
        if self.ws:
            await self.ws.send(f'{{"type":"announcement.unpin","announcement_id":{announcement["id"]}}}')
            logging.info(f"Unpinned announcement #{announcement['id']}")
        else:
            logging.error(f"Unable to unpin announcement #{announcement['id']}: WebSocket not connected")
        ANNOUNCEMENT_TASKS[announcement["id"]]["unpin"].stop()
        del ANNOUNCEMENT_TASKS[announcement["id"]]

    ANNOUNCEMENT_CMDS = discord.SlashCommandGroup("announcement", "公告相關指令。")

    @ANNOUNCEMENT_CMDS.command(name="test")
    @commands.is_owner()
    async def test(self, ctx: discord.ApplicationContext):
        await self.ws.send('{"type":"test.message","message":"test"}')
        await ctx.respond("Test message sent.")


def setup(bot: commands.Bot):
    bot.add_cog(Announcement(bot))
    logging.info(f'已載入 "{Announcement.__name__}"。')
