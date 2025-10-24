# coding=utf-8
import discord
from discord.ext import commands, tasks
from discord import Embed, Option, ApplicationContext
from discord.ui import View, Button
import os
import logging
import zoneinfo
from pathlib import Path
import datetime
from websockets.asyncio.client import connect
import asyncio
from json import loads, dumps
from pprint import pprint

from roboweb_api import RobowebAPI

error_color = 0xF1411C
default_color = 0x012a5e
now_tz = zoneinfo.ZoneInfo("Asia/Taipei")
base_dir = os.path.abspath(os.path.dirname(__file__))
parent_dir = str(Path(__file__).parent.parent.absolute())

NOTIFY_CHANNEL_ID = int(os.getenv("NOTIFY_CHANNEL_ID", "1128232150135738529"))
ABSENT_REQ_CHANNEL_ID = int(os.getenv("ABSENT_REQ_CHANNEL_ID", "1126031617614426142"))
MEETING_TASKS: dict[str, dict[str, tasks.Loop | None]] = {}


class Meeting(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.rwapi = None

    class MeetingURLView(View):
        def __init__(self, meeting_id: int):
            super().__init__()
            self.add_item(Button(
                label="查看會議詳情",
                style=discord.ButtonStyle.link,
                url=f"https://frc7636.dpdns.org/meeting/{meeting_id}/",
                emoji="🔗"
            ))

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.rwapi:
            self.rwapi = RobowebAPI(os.getenv("ROBOWEB_API_TOKEN"))
        await self.reload_meetings(None)

        max_retries = 15
        retries = 0
        retry_delay = 2
        while retries <= max_retries:
            logging.info(f"Attempting to connect to WebSocket (Attempt {retries + 1}/{max_retries})...")
            try:
                async with (connect(f"{os.getenv('WS_URL')}meeting/",
                                    additional_headers={"Authorization": f"Token {os.getenv("ROBOWEB_API_TOKEN")}"})
                            as websocket):
                    logging.info("Connected to WebSocket successfully.")
                    retries = 0
                    retry_delay = 2
                    while True:
                        data = loads(await websocket.recv())
                        # don't send notifications for past meetings
                        if "meeting" in data["type"] and "absent_request" not in data["type"]:
                            start_time = datetime.datetime.fromisoformat(data["meeting"]["start_time"])
                            if start_time < datetime.datetime.now(now_tz):
                                continue
                        if data["type"] in ("meeting.create", "meeting.edit"):
                            is_edit = (data["type"] == 'meeting.edit')
                            meeting = data["meeting"]
                            meeting_id = meeting["id"]
                            logging.info(
                                f"Received new meeting {'edit' if is_edit else 'creation'} event "
                                f"for meeting #{meeting_id}")
                            embed = Embed(
                                title="會議更新" if is_edit else "新會議",
                                description=f"會議 `#{meeting_id}` 的資訊已更新。" if is_edit else f"已預定新的會議 `#{meeting_id}`。",
                                color=default_color,
                            )
                            embed.add_field(name="名稱", value=meeting["name"], inline=False)
                            if meeting["can_absent"]:
                                embed.add_field(name="允許請假", value="成員可透過網頁面板請假。", inline=False)
                            else:
                                embed.add_field(name="不允許請假",
                                                value="已停用此會議的請假功能。\n若無法參加會議，請直接與主幹聯絡。",
                                                inline=False)
                            host_discord_id = int(
                                (await self.rwapi.get_member_info(meeting["host"], True))["discord_id"])
                            embed.add_field(name="主持人", value=f"<@{host_discord_id}>", inline=False)
                            embed.add_field(name="開始時間",
                                            value=f"<t:{int(datetime.datetime.fromisoformat(
                                                meeting['start_time']).timestamp())}:F>", inline=False)
                            embed.add_field(name="地點", value=meeting["location"], inline=False)
                            embed.set_footer(text="如要進行更多操作 (編輯、請假、審核假單)，請至網頁面板查看。")
                            ch = self.bot.get_channel(NOTIFY_CHANNEL_ID)
                            await ch.send(embed=embed, view=self.MeetingURLView(meeting_id))
                            self.setup_tasks(meeting)
                        elif data["type"] == "meeting.delete":
                            meeting = data["meeting"]
                            meeting_id = meeting["id"]
                            logging.info(f"Received meeting deletion event for meeting #{meeting_id}")
                            if meeting_id in MEETING_TASKS.keys():
                                for _, task in MEETING_TASKS[meeting_id].items():
                                    if task:
                                        task.cancel()
                                del MEETING_TASKS[meeting_id]
                            embed = Embed(
                                title="會議取消",
                                description=f"會議 `#{meeting_id}` 已取消。",
                                color=error_color,
                            )
                            embed.add_field(name="名稱", value=meeting["name"], inline=False)
                            ch = self.bot.get_channel(NOTIFY_CHANNEL_ID)
                            await ch.send(embed=embed)
                        elif data["type"] == "meeting.new_absent_request":
                            absent_request = data["absent_request"]
                            pprint(absent_request)
                            logging.info(f"Received new absent request event for request #{absent_request['id']}")
                            member_discord_id = int(
                                (await self.rwapi.get_member_info(absent_request["member"], True))["discord_id"]
                            )
                            meeting = await self.rwapi.get_meeting_info(absent_request["meeting"])
                            embed = Embed(
                                title="收到新的假單",
                                description="有一筆新的假單，請至網頁面板進行審核。",
                                color=default_color
                            )
                            embed.add_field(
                                name="會議名稱及 ID",
                                value=f"{meeting['name']} (`#{meeting['id']}`)",
                                inline=False
                            )
                            embed.add_field(name="成員", value=f"<@{member_discord_id}>", inline=False)
                            embed.add_field(name="請假事由", value=absent_request["reason"], inline=False)
                            ch = self.bot.get_channel(ABSENT_REQ_CHANNEL_ID)
                            await ch.send(embed=embed, view=self.MeetingURLView(meeting["id"]))
                        elif data["type"] == "meeting.review_absent_request":
                            absent_request = data["absent_request"]
                            logging.info(f"Received absent request review event for request #{absent_request['id']}")
                            status = {"approved": "✅ 批准", "rejected": "❌ 拒絕"}
                            member_discord_id = int(
                                (await self.rwapi.get_member_info(absent_request["member"], True))["discord_id"]
                            )
                            reviewer_discord_id = int(
                                (await self.rwapi.get_member_info(absent_request["reviewer"], True))["discord_id"]
                            )
                            meeting = await self.rwapi.get_meeting_info(absent_request["meeting"])
                            embed = Embed(title="假單審核結果", description="你的假單已經過主幹審核，結果如下：",
                                          color=default_color)
                            embed.add_field(name="會議名稱及 ID", value=f"{meeting['name']} (`#{meeting['id']}`)",
                                            inline=False)
                            embed.add_field(name="審核人員", value=f"<@{reviewer_discord_id}>", inline=False)
                            embed.add_field(name="審核結果", value=status.get(absent_request["status"], "未知"),
                                            inline=False)
                            if absent_request.get("reviewer_comment", None):
                                embed.add_field(name="審核意見", value=absent_request["reviewer_comment"], inline=False)
                            embed.set_footer(text="若對審核結果有異議，請直接與主幹聯絡。")
                            try:
                                await self.bot.get_user(member_discord_id).send(embed=embed)
                            except discord.Forbidden:
                                logging.warning(
                                    f"成員 {member_discord_id} 似乎關閉了陌生人私訊功能，因此無法傳送通知。"
                                )
                            except Exception as e:
                                logging.error(
                                    f"傳送私訊給成員 {member_discord_id} 時發生錯誤：{type(e).__name__}: {str(e)}")
                        else:
                            logging.info(f"Received unknown event: {data}")
            except Exception as e:
                retries += 1
                retry_delay *= 2  # Exponential backoff
                logging.error(f"An error occurred: {type(e).__name__}: {str(e)}. "
                              f"Attempting to reconnect in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
        logging.error("Max retries reached. Could not connect to WebSocket.")

    def setup_tasks(self, meeting: dict):
        meeting_id = meeting["id"]
        logging.debug(f"Setting up tasks for meeting #{meeting_id}")
        if meeting_id in MEETING_TASKS.keys():
            for task_type, task in MEETING_TASKS[meeting_id].items():
                if task:
                    logging.debug(f"(#{meeting_id:2d}) Cancelling existing \"{task_type}\" task")
                    task.cancel()
        start_time = datetime.datetime.fromisoformat(meeting["start_time"]).replace(tzinfo=now_tz)
        if not start_time - datetime.datetime.now(now_tz) >= datetime.timedelta(minutes=5):
            notify_time = datetime.datetime.now(now_tz) + datetime.timedelta(seconds=5)
            logging.debug(f"(#{meeting_id:2d}) Notify time is less than 5 minutes away, setting to 5 seconds from now")
        else:
            notify_time = start_time - datetime.timedelta(minutes=5)
            logging.debug(f"(#{meeting_id:2d}) Notify time set to {notify_time.isoformat()}")
        start_time = datetime.datetime.fromisoformat(meeting["start_time"]).replace(tzinfo=now_tz)
        MEETING_TASKS[meeting_id] = {
            "notify": tasks.Loop(
                coro=self.notify_meeting,
                seconds=tasks.MISSING,
                minutes=tasks.MISSING,
                hours=tasks.MISSING,
                time=notify_time.timetz(),
                count=None,
                reconnect=True,
                loop=self.bot.loop,
            ),
            "start": tasks.Loop(
                coro=self.notify_start_meeting,
                seconds=tasks.MISSING,
                minutes=tasks.MISSING,
                hours=tasks.MISSING,
                time=start_time.timetz(),
                count=None,
                reconnect=True,
                loop=self.bot.loop,
            ),
        }
        MEETING_TASKS[meeting_id]["notify"].start(meeting)
        MEETING_TASKS[meeting_id]["start"].start(meeting)
        return notify_time

    async def notify_meeting(self, meeting: dict):
        start_time = datetime.datetime.fromisoformat(meeting["start_time"]).astimezone(now_tz)
        if start_time - datetime.datetime.now(now_tz) > datetime.timedelta(seconds=1000):
            return
        embed = Embed(
            title="會議即將開始！",
            description=f"會議**「{meeting['name']}」**(`#{meeting['id']}`) 即將於 "
                        f"<t:{int(start_time.timestamp())}:R> 開始！",
            color=default_color,
        )
        if meeting["description"] != "":
            embed.add_field(
                name="簡介",
                value=meeting["description"],
                inline=False,
            )
        embed.add_field(name="會議地點", value=meeting["location"], inline=False)
        ch = self.bot.get_channel(NOTIFY_CHANNEL_ID)
        await ch.send(content="@everyone", embed=embed)
        absent_requests = await self.rwapi.get_absent_requests(meeting_id=meeting["id"])
        for absent_request in absent_requests:
            if absent_request["status"] in ("pending", "rejected"):
                member_discord_id = int(
                    (await self.rwapi.get_member_info(absent_request["member"], True))["discord_id"]
                )
                embed = Embed(
                    title="請準時參加會議",
                    description="你的假單因 "
                                f"**{'尚未經過審核' if absent_request['status'] == 'pending' else '未通過審核'}**"
                                "，因此仍需準時出席會議。\n"
                                "如因故無法參加會議，請立即告知主幹。",
                    color=default_color,
                )
                embed.add_field(name="會議名稱及 ID", value=f"{meeting['name']} (`#{meeting['id']}`)", inline=False)
                embed.add_field(
                    name="開始時間", value=f"<t:{int(start_time.timestamp())}:R>", inline=False
                )
                try:
                    await self.bot.get_user(member_discord_id).send(embed=embed)
                except discord.Forbidden:
                    logging.warning(
                        f"成員 {member_discord_id} 似乎關閉了陌生人私訊功能，因此無法傳送通知。"
                    )
                except Exception as e:
                    logging.error(f"傳送私訊給成員 {member_discord_id} 時發生錯誤：{type(e).__name__}: {str(e)}")
        MEETING_TASKS[meeting["id"]]["notify"].stop()
        del MEETING_TASKS[meeting["id"]]["notify"]

    async def notify_start_meeting(self, meeting: dict):
        start_time = datetime.datetime.fromisoformat(meeting["start_time"])
        if start_time - datetime.datetime.now(now_tz) > datetime.timedelta(seconds=1000):
            return
        embed = Embed(
            title="會議開始！",
            description=f"會議**「{meeting['name']}」**(`#{meeting['id']}`) 已經在 "
                        f"<t:{int(start_time.timestamp())}:F> 開始！",
            color=default_color,
        )
        if meeting["description"] != "":
            embed.add_field(
                name="簡介",
                value=meeting["description"],
                inline=False,
            )
        host_discord_id = (await self.rwapi.get_member_info(meeting["host"], True))["discord_id"]
        embed.add_field(name="主持人", value=f"<@{host_discord_id}>", inline=False)
        embed.add_field(name="會議地點", value=meeting["location"], inline=False)
        absent_requests = await self.rwapi.get_absent_requests(meeting_id=meeting["id"])
        absent_request_str = ""
        for absent_request in absent_requests:
            if absent_request.get("status") == "approved":
                member = await self.rwapi.get_member_info(absent_request["member"], True)
                absent_request_str += f"<@{member['discord_id']}>({member['real_name']})\n"
        if absent_request_str != "":
            embed.add_field(name="請假人員", value=absent_request_str, inline=False)
        ch = self.bot.get_channel(NOTIFY_CHANNEL_ID)
        await ch.send(content="@everyone", embed=embed)
        MEETING_TASKS[meeting["id"]]["start"].stop()
        del MEETING_TASKS[meeting["id"]]["start"]

    MEETING_CMDS = discord.SlashCommandGroup("meeting")

    @MEETING_CMDS.command(name="建立", description="預定新的會議。")
    @commands.has_role(1114205838144454807)
    async def create_new_meeting(self, ctx: ApplicationContext):
        embed = Embed(
            title="預定會議",
            description="請點擊下方的按鈕建立會議。",
            color=default_color,
        )

        def new_meeting_btn():
            view = discord.ui.View()
            view.add_item(discord.ui.Button(
                emoji="📅",
                label="建立會議",
                style=discord.ButtonStyle.link,
                url="https://frc7636.dpdns.org/meeting/new/",
            ))
            return view

        await ctx.respond(
            embed=embed, view=new_meeting_btn(), ephemeral=True
        )

    @MEETING_CMDS.command(name="查詢", description="查詢會議資訊。")
    async def get_meeting_info(
            self,
            ctx: ApplicationContext,
            meeting_id: Option(int, "欲查詢的會議ID", name="會議id", min_value=1, max_value=999, required=True),
    ):
        try:
            meeting_info = await self.rwapi.get_meeting_info(meeting_id)
            embed = Embed(
                title="會議資訊",
                description=f"會議 `{meeting_id}` 的詳細資訊",
                color=default_color,
            )
            embed.add_field(name="名稱", value=meeting_info.get("name"), inline=False)
            if meeting_info.get("description", None) and meeting_info.get("description") != "":
                embed.add_field(name="說明", value=meeting_info.get("description"), inline=False)
            host_info = await self.rwapi.get_member_info(meeting_info.get("host"))
            embed.add_field(name="主持人", value=f"<@{host_info.get('discord_id')}>", inline=False)
            embed.add_field(name="開始時間",
                            value=f"<t:"
                                  f"{int(datetime.datetime.fromisoformat(meeting_info.get('start_time')).timestamp())}"
                                  f":F>",
                            inline=False)
            if meeting_info.get("end_time", None):
                embed.add_field(name="結束時間",
                                value=f"<t:"
                                      f"{int(datetime.datetime.fromisoformat(
                                          meeting_info.get('end_time')
                                      ).timestamp())}:F>",
                                inline=False)
            embed.add_field(name="地點", value=meeting_info.get("location"), inline=False)
            if meeting_info.get("can_absent", False):
                embed.add_field(name="允許請假", value="成員可透過網頁面板請假。", inline=False)
            else:
                embed.add_field(name="不允許請假",
                                value="已停用此會議的請假功能。\n若無法參加會議，請直接與主幹聯絡。",
                                inline=False)
            await ctx.respond(embed=embed)
        except Exception as e:
            embed = Embed(title="錯誤：會議不存在", description="輸入的會議 ID 可能不存在，或是 API 發生錯誤。",
                          color=error_color)
            embed.add_field(name="錯誤訊息", value=f"```{type(e).__name__}: {str(e)}```", inline=False)
            await ctx.respond(embed=embed, ephemeral=True)

    @MEETING_CMDS.command(name="請假", description="提出會議請假申請。")
    async def request_meeting_absent(self, ctx: ApplicationContext,
                                     meeting_id: Option(int, "欲請假的會議ID", name="會議id", min_value=1,  # noqa
                                                        max_value=999, required=True),
                                     reason: Option(str, "請假事由", name="事由", min_length=5, max_length=100,  # noqa
                                                    required=True)):
        try:
            meeting_info = await self.rwapi.get_meeting_info(meeting_id)
            if not meeting_info.get("can_absent", False):
                embed = Embed(title="錯誤：不允許請假",
                              description="此會議不允許請假，因此無法透過此指令請假。\n請直接連絡主持人或主幹，避免遭到記點。",
                              color=error_color)
            elif (datetime.datetime.fromisoformat(meeting_info.get("start_time")) - datetime.datetime.now().astimezone(
                    now_tz)) <= datetime.timedelta(minutes=5):
                embed = Embed(title="錯誤：會議即將開始",
                              description="此會議即將開始，無法請假。",
                              color=error_color)
            elif datetime.datetime.fromisoformat(meeting_info.get("start_time")) < datetime.datetime.now().astimezone(
                    now_tz):
                embed = Embed(title="錯誤：會議已經開始",
                              description="此會議已經開始，無法請假。",
                              color=error_color)
            else:
                member_search = await self.rwapi.search_members(discord_id=str(ctx.author.id))
                if not member_search or len(member_search) == 0:
                    embed = Embed(title="錯誤：成員不存在",
                                  description="你的 Discord ID 尚未註冊至資料庫中，因此無法進行請假。\n"
                                              "請先使用 `/執行新版驗證` 指令進行驗證。",
                                  color=error_color)
                else:
                    member_id = member_search[0].get("id")
                    current_absent_requests = await self.rwapi.get_absent_requests(meeting_id=meeting_id)
                    for req in current_absent_requests:
                        if req.get("member") == member_id:
                            embed = Embed(title="錯誤：重複請假",
                                          description=f"你已經送出過會議 `#{meeting_id}` 的假單，無法重複請假。\n"
                                                      f"如需修改請假事由，請直接連絡主持人或主幹。",
                                          color=error_color)
                            await ctx.respond(embed=embed, ephemeral=True)
                            return
                    await self.rwapi.create_absent_request(meeting_id=meeting_id, member_id=member_id,
                                                           reason=reason)
                    embed = Embed(title="成功：已送出假單",
                                  description=f"你已成功送出會議 `#{meeting_id}` 的假單，請等待主持人或主幹審核。",
                                  color=default_color)
            await ctx.respond(embed=embed, ephemeral=True)
        except Exception as e:
            embed = Embed(title="錯誤：會議不存在", description="輸入的會議 ID 可能不存在，或是 API 發生錯誤。",
                          color=error_color)
            embed.add_field(name="錯誤訊息", value=f"```{type(e).__name__}: {str(e)}```", inline=False)
            await ctx.respond(embed=embed, ephemeral=True)

    @MEETING_CMDS.command(name="重新載入提醒", description="重新載入會議提醒。")
    async def reload_meetings(self, ctx: ApplicationContext = None):
        try:
            upcoming_meetings = await self.rwapi.get_upcoming_meetings()
            for meeting_id in MEETING_TASKS.keys():
                for _, task in MEETING_TASKS[meeting_id].items():
                    if task is not None:
                        task.cancel()
            MEETING_TASKS.clear()
            for meeting in upcoming_meetings:
                self.setup_tasks(meeting)
            embed = Embed(title="成功：已重新載入會議提醒",
                          description="已重新載入所有未來的會議提醒。",
                          color=default_color)
        except Exception as e:
            embed = Embed(title="錯誤：無法重新載入會議",
                          description="重新載入會議時發生錯誤。",
                          color=error_color)
            embed.add_field(name="錯誤訊息", value=f"```{type(e).__name__}: {str(e)}```", inline=False)
        if ctx:
            await ctx.respond(embed=embed, ephemeral=True)


def setup(bot):
    bot.add_cog(Meeting(bot))
    logging.info(f'已載入 "{Meeting.__name__}"。')
