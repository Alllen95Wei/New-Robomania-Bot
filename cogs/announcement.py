# coding=utf-8
import discord
from discord.ext import commands, tasks
from discord import Embed
import os
import datetime
import zoneinfo
from pathlib import Path
import logging
from websockets.asyncio.client import connect, ClientConnection
import asyncio
from json import loads

from roboweb_api import RobowebAPI

base_dir = os.path.abspath(os.path.dirname(__file__))
parent_dir = str(Path(__file__).parent.parent.absolute())
now_tz = zoneinfo.ZoneInfo("Asia/Taipei")
default_color = 0x012a5e
error_color = 0xF1411C

ANNOUNCE_CHANNEL_ID = int(os.getenv("ANNOUNCE_CHANNEL_ID", "1128232150135738529"))
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
        await self.reload_unpin_tasks(None)

        max_retries = 15
        retries = 0
        retry_delay = 2
        while retries <= max_retries:
            logging.info(f"Attempting to connect to WebSocket (Attempt {retries + 1}/{max_retries})...")
            try:
                async with (connect(f"{os.getenv('WS_URL')}announcement/",
                                    additional_headers={"Authorization": f"Token {os.getenv("ROBOWEB_API_TOKEN")}"})
                            as websocket):
                    self.ws = websocket
                    logging.info("Connected to WebSocket successfully.")
                    retries = 0
                    retry_delay = 2
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
                            channel = self.bot.get_channel(ANNOUNCE_CHANNEL_ID)
                            await channel.send(message)
                        elif data["type"] in ("announcement.delete", "announcement.unpin"):
                            announcement_id = data["announcement"]["id"]
                            if announcement_id in ANNOUNCEMENT_TASKS.keys():
                                for task_type, task in ANNOUNCEMENT_TASKS[announcement_id].items():
                                    if task:
                                        logging.debug(f"(#{announcement_id:2d}) "
                                                      f"Cancelling existing \"{task_type}\" task")
                                        task.cancel()
                                del ANNOUNCEMENT_TASKS[announcement_id]
                        else:
                            logging.info(f"Received unknown event: {data}")
            except Exception as e:
                retries += 1
                retry_delay *= 2  # Exponential backoff
                logging.error(f"An error occurred: {type(e).__name__}: {str(e)}. "
                              f"Attempting to reconnect in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
        logging.error("Max retries reached. Could not connect to WebSocket.")

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

    async def unpin_announcement(self, announcement: dict, is_manual: bool = False):
        pin_due_date = datetime.datetime.fromisoformat(announcement["pin_until"])
        if pin_due_date - datetime.datetime.now(now_tz) > datetime.timedelta(seconds=1000):
            return
        if self.ws:
            await self.ws.send(f'{{"type":"announcement.unpin","announcement_id":{announcement["id"]}}}')
            logging.info(f"Unpinned announcement #{announcement['id']}")
        else:
            logging.error(f"Unable to unpin announcement #{announcement['id']}: WebSocket not connected")
        if not is_manual:
            ANNOUNCEMENT_TASKS[announcement["id"]]["unpin"].stop()
            del ANNOUNCEMENT_TASKS[announcement["id"]]

    ANNOUNCEMENT_CMDS = discord.SlashCommandGroup("announcement", "公告相關指令。")

    @ANNOUNCEMENT_CMDS.command(name="test")
    @commands.is_owner()
    async def test(self, ctx: discord.ApplicationContext):
        await self.ws.send('{"type":"test.message","message":"test"}')
        await ctx.respond("Test message sent.")

    @ANNOUNCEMENT_CMDS.command(name="重新載入任務", description="重新載入所有取消釘選公告的任務。")
    @commands.is_owner()
    async def reload_unpin_tasks(self, ctx: discord.ApplicationContext = None):
        try:
            announcements = await self.rwapi.get_pinned_announcements()
            for ann_id in ANNOUNCEMENT_TASKS.keys():
                for _, task in ANNOUNCEMENT_TASKS[ann_id].items():
                    if task:
                        task.cancel()
            ANNOUNCEMENT_TASKS.clear()
            for announcement in announcements:
                pin_due_date = datetime.datetime.fromisoformat(announcement["pin_until"])
                if pin_due_date < datetime.datetime.now(now_tz):
                    await self.unpin_announcement(announcement)
                else:
                    self.setup_tasks(announcement)
            embed = Embed(title="成功：已重新載入取消釘選任務",
                          description="已重新載入所有未來的取消釘選任務。",
                          color=default_color)
        except Exception as e:
            embed = Embed(title="錯誤：無法重新載入取消釘選任務",
                          description="重新載入取消釘選任務時發生錯誤。",
                          color=error_color)
            embed.add_field(name="錯誤訊息", value=f"```{type(e).__name__}: {str(e)}```", inline=False)
            logging.error(f"Failed to reload unpin tasks: {type(e).__name__}: {str(e)}")
        if ctx:
            await ctx.respond(embed=embed)


def setup(bot: commands.Bot):
    bot.add_cog(Announcement(bot))
    logging.info(f'已載入 "{Announcement.__name__}"。')
