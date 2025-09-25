# coding=utf-8
import discord
from discord.ext import commands
from discord import Option, Embed
import os
import subprocess
from shlex import split
import logging
import time
import datetime
import zoneinfo
from typing import Literal
from pathlib import Path

from roboweb_api import RobowebAPI

error_color = 0xF1411C
default_color = 0x012a5e
now_tz = zoneinfo.ZoneInfo("Asia/Taipei")
base_dir = os.path.abspath(os.path.dirname(__file__))
parent_dir = str(Path(__file__).parent.parent.absolute())


class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.rwapi: RobowebAPI | None = None

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.rwapi:
            self.rwapi = RobowebAPI(os.getenv("ROBOWEB_API_TOKEN"))

    @commands.Cog.listener()
    async def on_voice_state_update(
            self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        if member.bot:
            return
        if (
                before.channel is None
                or after.channel is None
                or before.channel.id != after.channel.id
        ):
            member_real_name = await self.rwapi.search_members(discord_id=member.id)
            if isinstance(member_real_name, list) and len(member_real_name) > 0:
                member_real_name = member_real_name[0]["real_name"]
            if member_real_name is None:
                member_real_name = member.name
            if not isinstance(before.channel, type(None)):
                await before.channel.send(
                    f"<:left:1208779447440777226> **{member_real_name}** "
                    f"在 <t:{int(time.time())}:T> 離開 {before.channel.mention}。",
                    delete_after=43200,
                )
                self.log_vc_activity("leave", member, before.channel)
            if not isinstance(after.channel, type(None)):
                await after.channel.send(
                    f"<:join:1208779348438683668> **{member_real_name}** "
                    f"在 <t:{int(time.time())}:T> 加入 {after.channel.mention}。",
                    delete_after=43200,
                )
                self.log_vc_activity("join", member, after.channel)

    VC_LOGGER = logging.getLogger("VC")

    def log_vc_activity(
            self,
            join_or_leave: Literal["join", "leave"],
            user: discord.User | discord.Member,
            channel: discord.VoiceChannel,
    ):
        log_path = os.path.join(
            base_dir,
            "logs",
            f"VC {datetime.datetime.now(tz=now_tz).strftime('%Y.%m.%d')}.log",
        )
        if not os.path.exists(log_path):
            with open(log_path, "w"):
                pass
        original_handler: logging.FileHandler
        try:
            original_handler = self.VC_LOGGER.handlers[0]
        except IndexError:
            original_handler = logging.FileHandler("logs/VC.log")
        if original_handler.baseFilename != log_path:
            formatter = logging.Formatter(
                fmt="[%(asctime)s] %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
            )
            log_path = os.path.join(
                base_dir,
                "logs",
                f"VC {datetime.datetime.now(tz=now_tz).strftime('%Y.%m.%d')}.log",
            )
            handler = logging.FileHandler(log_path, encoding="utf-8")
            handler.setFormatter(formatter)
            self.VC_LOGGER.addHandler(handler)
            self.VC_LOGGER.removeHandler(original_handler)
        join_or_leave = "加入" if join_or_leave == "join" else "離開"
        message = user.name + " " + join_or_leave + "了 " + channel.name
        self.VC_LOGGER.info(message)

    @commands.slash_command(name="clear", description="清除目前頻道中的訊息。")
    @commands.has_role(1114205838144454807)
    async def clear_messages(
            self,
            ctx: discord.ApplicationContext,
            count: Option(
                int,
                name="刪除訊息數",
                description="要刪除的訊息數量",
                min_value=1,
                max_value=50,
            ),
    ):
        channel = ctx.channel
        channel: discord.TextChannel
        await ctx.defer()
        try:
            await channel.purge(limit=count)
            embed = Embed(
                title="已清除訊息",
                description=f"已成功清除 {channel.mention} 中的 `{count}` 則訊息。",
                color=default_color,
            )
            await ctx.channel.send(embed=embed, delete_after=5)
        except Exception as e:
            embed = Embed(title="錯誤", description="發生未知錯誤。", color=error_color)
            embed.add_field(name="錯誤訊息", value="```" + str(e) + "```", inline=False)
            await ctx.respond(embed=embed)

    @commands.slash_command(name="update", description="更新機器人程式碼。")
    @commands.is_owner()
    async def update_bot(self, ctx: discord.ApplicationContext):
        embed = Embed(title="更新中", description="更新流程啟動。", color=default_color)
        await ctx.respond(embed=embed)
        event = discord.Activity(type=discord.ActivityType.playing, name="更新中...")
        await self.bot.change_presence(status=discord.Status.idle, activity=event)
        subprocess.run(["git", "fetch", "--all"])
        subprocess.run(['git', 'reset', '--hard', 'origin/main'])
        subprocess.run(['git', 'pull'])

    @commands.slash_command(name="cmd", description="在伺服器端執行指令並傳回結果。")
    @commands.is_owner()
    async def cmd(
            self,
            ctx,
            command: Option(str, "要執行的指令", name="指令", required=True),
            desired_module: Option(
                str,
                name="執行模組",
                choices=["subprocess", "os"],
                description="執行指令的模組",
                required=False,
            ) = "subprocess",
            is_private: Option(bool, "是否以私人訊息回應", name="私人訊息", required=False) = False,
    ):
        try:
            await ctx.defer(ephemeral=is_private)
            if split(command)[0] == "cmd":
                embed = Embed(
                    title="錯誤",
                    description="基於安全原因，你不能執行這個指令。",
                    color=error_color,
                )
                await ctx.respond(embed=embed, ephemeral=is_private)
                return
            if desired_module == "subprocess":
                result = str(subprocess.run(command, capture_output=True, text=True).stdout)
            else:
                result = str(os.popen(command).read())
            if result != "":
                embed = Embed(
                    title="執行結果", description=f"```{result}```", color=default_color
                )
            else:
                embed = Embed(
                    title="執行結果", description="終端未傳回回應。", color=default_color
                )
        # except WindowsError as e:
        #     if e.winerror == 2:
        #         embed = Embed(
        #             title="錯誤",
        #             description="找不到指令。請嘗試更換執行模組。",
        #             color=error_color,
        #         )
        #     else:
        #         embed = Embed(
        #             title="錯誤", description=f"發生錯誤：`{e}`", color=error_color
        #         )
        except Exception as e:
            embed = Embed(title="錯誤", description=f"發生錯誤：`{e}`", color=error_color)
        try:
            await ctx.respond(embed=embed, ephemeral=is_private)
        except discord.errors.HTTPException as HTTPError:
            if "fewer in length" in str(HTTPError):
                txt_file_path = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), "full_msg.txt"
                )
                with open(txt_file_path, "w") as file:
                    file.write(str(result))
                await ctx.respond(
                    "由於訊息長度過長，因此改以文字檔方式呈現。",
                    file=discord.File(txt_file_path),
                    ephemeral=is_private,
                )
                os.remove(txt_file_path)


def setup(bot: commands.Bot):
    bot.add_cog(General(bot))
    logging.info(f'已載入 "{General.__name__}"。')
