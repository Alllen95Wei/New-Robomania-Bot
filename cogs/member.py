# coding=utf-8
import discord
from discord.ext import commands
from discord import Option, Embed
import os
import zoneinfo
from pathlib import Path
import logging
from websockets.asyncio.client import connect, USER_AGENT
import asyncio
from json import loads

from roboweb_api import RobowebAPI

base_dir = os.path.abspath(os.path.dirname(__file__))
parent_dir = str(Path(__file__).parent.parent.absolute())
now_tz = zoneinfo.ZoneInfo("Asia/Taipei")
default_color = 0x012a5e
error_color = 0xF1411C


class Member(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.rwapi: RobowebAPI | None = None

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.rwapi:
            self.rwapi = RobowebAPI(os.getenv("ROBOWEB_API_TOKEN"))

        max_retries = 15
        retries = 0
        retry_delay = 2
        while retries <= max_retries:
            logging.info(f"Attempting to connect to WebSocket (Attempt {retries + 1}/{max_retries})...")
            try:
                async with (connect(f"{os.getenv('WS_URL')}member/",
                                    additional_headers={"Authorization": f"Token {os.getenv("ROBOWEB_API_TOKEN")}"},
                                    user_agent_header=USER_AGENT + " New-Robomania-Bot")
                            as websocket):
                    logging.info("Connected to WebSocket successfully.")
                    retries = 0
                    retry_delay = 2
                    while True:
                        data = loads(await websocket.recv())
                        if data["type"] == "member.add_warning_points":
                            warning_detail = data["warning_detail"]
                            logging.info(f"Received warning points event for #{warning_detail['id']}")
                            member_discord_id = int((await self.rwapi.get_member_info(
                                warning_detail["member"], True))["discord_id"])
                            operator_discord_id = int((await self.rwapi.get_member_info(
                                warning_detail["operator"], True))["discord_id"])
                            current_points = (
                                await self.rwapi.get_member_info(warning_detail["member"]))["warning_points"]
                            is_positive = warning_detail["points"] < 0
                            embed = Embed(
                                title=f"{'銷點' if is_positive else '記點'}通知",
                                description=f"剛才有主幹對你進行了 **{'銷點' if is_positive else '記點'}** 操作，資料如下：",
                                color=default_color
                            )
                            embed.add_field(name="點數", value=f"`{warning_detail['points']}` 點", inline=False)
                            embed.add_field(name="操作後點數", value=f"`{current_points}` 點", inline=False)
                            embed.add_field(name="操作者", value=f"<@{operator_discord_id}>", inline=False)
                            embed.add_field(name="事由", value=warning_detail["reason"], inline=False)
                            if warning_detail["notes"]:
                                embed.add_field(name="附註", value=warning_detail["notes"], inline=False)
                            embed.set_footer(text="若有任何疑問，請立即聯絡主幹。")
                            user = self.bot.get_user(member_discord_id)
                            try:
                                await user.send(embed=embed)
                            except Exception as e:
                                logging.error(f"無法傳送訊息給 {member_discord_id}: {e}")
                        else:
                            logging.info(f"Received unknown event: {data}")
            except Exception as e:
                retries += 1
                retry_delay *= 2  # Exponential backoff
                logging.error(f"An error occurred: {type(e).__name__}: {str(e)}. "
                              f"Attempting to reconnect in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
        logging.error("Max retries reached. Could not connect to WebSocket.")

    MEMBER_CMD = discord.SlashCommandGroup(name="member", description="隊員資訊相關指令。")

    @MEMBER_CMD.command(name="查詢", description="查看隊員資訊。")
    async def member_info(self, ctx: discord.ApplicationContext,
                          member: Option(discord.Member, name="隊員", required=False) = None):
        if member is None:
            member = ctx.author
        try:
            member_data = await self.rwapi.search_members(discord_id=member.id)
        except Exception as e:
            embed = Embed(title="錯誤", description="發生未知錯誤。", color=error_color)
            embed.add_field(name="錯誤訊息", value=f"```{type(e).__name__}: {e}```", inline=False)
            await ctx.respond(embed=embed, ephemeral=True)
            return
        if len(member_data) == 0:
            embed = Embed(title="錯誤：找不到成員", description="找不到該隊員的資料，請確認該隊員是否已註冊。", color=error_color)
            await ctx.respond(embed=embed, ephemeral=True)
        else:
            member_data = member_data[0]
            embed = Embed(title="隊員資訊", description=f"{member.mention} 的資訊", color=default_color)
            embed.add_field(name="真實姓名", value=member_data["real_name"], inline=False)
            jobs_str = ""
            if member_data["jobs"]:
                for job in member_data["jobs"]:
                    jobs_str += f"- {job}\n"
            else:
                jobs_str = "(無)"
            embed.add_field(name="職務", value=jobs_str, inline=False)
            embed.add_field(name="警告點數", value=f"`{member_data['warning_points']}` 點", inline=False)
            embed.set_thumbnail(url=member.display_avatar)
            await ctx.respond(embed=embed)

    @MEMBER_CMD.command(name="查詢記點人員", description="列出點數不為 0 的隊員。")
    async def member_list_bad_guys(self, ctx: discord.ApplicationContext):
        try:
            members = await self.rwapi.get_bad_guys()
        except Exception as e:
            embed = Embed(title="錯誤", description="發生未知錯誤。", color=error_color)
            embed.add_field(name="錯誤訊息", value=f"```{type(e).__name__}: {e}```", inline=False)
            await ctx.respond(embed=embed, ephemeral=True)
            return
        if len(members) == 0:
            embed = Embed(title="無記點隊員", description="目前沒有隊員被記點。", color=default_color)
            await ctx.respond(embed=embed)
        else:
            members.sort(key=lambda x: x["warning_points"], reverse=True)
            if len(members) > 25:
                members = members[:25]
            embed = Embed(title="遭記點隊員清單", description=f"以下為點數不為 0 的前 {len(members)} 名隊員：",
                          color=default_color)
            for idx, member in enumerate(members):
                medals = ("🥇", "🥈", "🥉")
                name_display = member["real_name"]
                if idx <= 2:
                    name_display = medals[idx] + " " + name_display
                embed.add_field(name=name_display, value=f"`{member['warning_points']}` 點", inline=False)
            await ctx.respond(embed=embed)

    @discord.user_command(name="查看此隊員的資訊")
    async def member_info_user(self, ctx, user: discord.Member):
        await self.member_info(ctx, user)


def setup(bot: commands.Bot):
    bot.add_cog(Member(bot))
    logging.info(f'已載入 "{Member.__name__}"。')
