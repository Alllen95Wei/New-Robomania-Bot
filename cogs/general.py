# coding=utf-8
import discord
from discord.ext import commands
from discord import Option, Embed
from discord.ui import View, Button
import os
import subprocess
from shlex import split
import logging
import time
import datetime
import zoneinfo
from typing import Literal
from pathlib import Path
from websockets.asyncio.client import connect, ClientConnection, USER_AGENT
from json import loads
import asyncio

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
        self.ws: ClientConnection | None = None

    class GenerateLoginCodeView(View):
        def __init__(self, rwapi: RobowebAPI):
            super().__init__(timeout=None)
            self.rwapi = rwapi
            self.cooldown = commands.CooldownMapping.from_cooldown(1, 90, commands.BucketType.user)

        @discord.ui.button(label="產生登入代碼", custom_id="generate_login_code_button",
                           style=discord.ButtonStyle.green, emoji="🗝️")
        async def generate_login_code_button(
                self, button: discord.ui.Button, interaction: discord.Interaction
        ):
            await interaction.response.defer(ephemeral=True)
            # check cooldown
            bucket = self.cooldown.get_bucket(interaction.message)
            retry_after = bucket.update_rate_limit()
            if retry_after:
                embed = Embed(
                    title="錯誤：冷卻中",
                    description=f"每次操作需要間隔至少 90 秒。請稍等 {int(retry_after)} 秒後再試。",
                    color=error_color,
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            member = await self.rwapi.search_members(discord_id=interaction.user.id)
            # check if member exists in web database
            if not isinstance(member, list) or len(member) == 0:
                embed = Embed(
                    title="錯誤：成員不存在",
                    description="你的 Discord ID 尚未註冊至資料庫中，因此無法產生登入代碼。\n"
                                "請先使用 `/執行新版驗證` 指令進行驗證。",
                    color=error_color,
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            try:
                login_code = await self.rwapi.create_login_code(member[0].get("id"))
                create_time = int(
                    datetime.datetime.fromisoformat(login_code.get("created_at")).astimezone(now_tz).timestamp())
                embed = Embed(
                    title="成功產生登入代碼",
                    description=f"你的代碼已顯示於下方。\n請妥善保管，並於 <t:{create_time + 90}:R> 使用此代碼。",
                    color=default_color,
                )
                embed.add_field(name="登入代碼", value=f"`{login_code['code']}`", inline=False)
                embed.add_field(name="建立時間", value=f"<t:{create_time}:F>", inline=False)
                await interaction.user.send(embed=embed, view=General.LoginButton())
                await interaction.followup.send("已透過私人訊息傳送登入代碼。", ephemeral=True)
            except discord.errors.HTTPException as error:
                if error.code == 50007:
                    embed = Embed(
                        title="錯誤：無法傳送私人訊息",
                        description="請前往此伺服器的隱私設定，確認你的帳號允許來自此伺服器的私訊，然後再試一次。",
                        color=error_color,
                    )
                    embed.add_field(name="錯誤訊息", value=f"```{type(error).__name__}: {str(error)}```", inline=False)
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    raise
            except Exception as e:
                embed = Embed(
                    title="錯誤：無法產生登入代碼",
                    description="發生未知錯誤，請稍後再試。",
                    color=error_color,
                )
                embed.add_field(name="錯誤訊息", value=f"```{type(e).__name__}: {str(e)}```", inline=False)
                await interaction.followup.send(embed=embed, ephemeral=True)

    class LoginButton(View):
        def __init__(self):
            super().__init__(timeout=None)
            self.add_item(Button(label="前往登入頁面", url="https://panel.team7636.com/accounts/login/"))

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.rwapi:
            self.rwapi = RobowebAPI(os.getenv("ROBOWEB_API_TOKEN"))
        self.bot.add_view(self.GenerateLoginCodeView(self.rwapi))

        max_retries = 15
        retries = 0
        retry_delay = 2
        while retries <= max_retries:
            logging.info(f"Attempting to connect to WebSocket (Attempt {retries + 1}/{max_retries})...")
            try:
                async with (connect(f"{os.getenv('WS_URL')}auth/",
                                    additional_headers={"Authorization": f"Token {os.getenv("ROBOWEB_API_TOKEN")}"},
                                    user_agent_header=USER_AGENT + " New-Robomania-Bot")
                            as websocket):
                    self.ws = websocket
                    logging.info("Connected to WebSocket successfully.")
                    retries = 0
                    retry_delay = 2
                    while True:
                        data = loads(await websocket.recv())
                        if data["type"] == "auth.new_login":
                            embed = Embed(
                                title="新的登入通知",
                                description="有人在隊務管理面板登入了你的帳號。請確認是否為你本人所進行的操作。\n"
                                            "如果你懷疑你的帳號遭到盜用，請立即更換密碼，並告知管理員。",
                                color=default_color,
                            )
                            embed.add_field(name="IP 位址", value=f"`{data['ip']}`", inline=False)
                            embed.add_field(name="使用者代理", value=f"```{data['user_agent']}```", inline=False)
                            embed.add_field(name="登入方式", value=data["method"], inline=False)
                            embed.timestamp = datetime.datetime.now(tz=now_tz)
                            member = self.bot.get_user(int(data["member_discord_id"]))
                            await member.send(embed=embed)
                        else:
                            logging.info(f"Received unknown event: {data}")
            except Exception as e:
                retries += 1
                retry_delay *= 2  # Exponential backoff
                logging.error(f"An error occurred: {type(e).__name__}: {str(e)}. "
                              f"Attempting to reconnect in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
        logging.error("Max retries reached. Could not connect to WebSocket.")

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

    @commands.slash_command(name="建立登入代碼按鈕", description="在目前頻道建立「產生登入代碼」的按鈕。")
    @commands.is_owner()
    async def create_login_code_button(
            self,
            ctx: discord.ApplicationContext,
    ):
        await ctx.defer(ephemeral=True)
        view = self.GenerateLoginCodeView(self.rwapi)
        embed = Embed(
            title="產生登入代碼",
            description="按下下方的按鈕，以產生你的登入代碼。",
            color=default_color,
        )
        await ctx.channel.send(embed=embed, view=view)
        embed = Embed(
            title="成功",
            description="已在目前頻道建立「產生登入代碼」的按鈕。",
            color=default_color,
        )
        await ctx.respond(embed=embed, ephemeral=True)


def setup(bot: commands.Bot):
    bot.add_cog(General(bot))
    logging.info(f'已載入 "{General.__name__}"。')
