# coding=utf-8
import discord
from discord import Embed, ButtonStyle, InputTextStyle
from discord.ext import commands
from discord.ui import View, Modal, Button, InputText
from datetime import datetime
import os
import zoneinfo
from pathlib import Path
import logging

from google_api import GoogleAPI
from roboweb_api import RobowebAPI

error_color = 0xF1411C
default_color = 0x012a5e
now_tz = zoneinfo.ZoneInfo("Asia/Taipei")
base_dir = os.path.abspath(os.path.dirname(__file__))
parent_dir = str(Path(__file__).parent.parent.absolute())

VERIFICATION_CHANNEL_ID = 1114444831054376971


class NewVerification(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rwapi = None

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.rwapi:
            self.rwapi = RobowebAPI(os.getenv("ROBOWEB_API_TOKEN"))

    class Step1(View):
        def __init__(self, outer_instance):
            super().__init__(timeout=None, disable_on_timeout=True)
            self.outer_instance = outer_instance

            self.add_item(
                Button(
                    label="使用中科實中 Google 帳戶登入",
                    style=ButtonStyle.url,
                    url="https://accounts.google.com/o/oauth2/v2/auth/oauthchooseaccount?"
                        "scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fuserinfo.email%20"
                        "https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fuserinfo.profile&"
                        "response_type=token&redirect_uri=https%3A%2F%2Falllen95wei.github.io%2F&"
                        "client_id=204070935721-sbjql09rsmu67a1h820m9a49og1g4kck.apps.googleusercontent.com&"
                        "service=lso&o2v=2&ddm=0&flowName=GeneralOAuthFlow",
                    emoji="🔐",
                )
            )

        @discord.ui.button(label="提交你的 Refresh Token", style=ButtonStyle.green, emoji="📝")
        async def submit_btn(self, button: Button, interaction: discord.Interaction):
            await interaction.response.send_modal(NewVerification.Step2(self.outer_instance))

    class Step2(Modal):
        def __init__(self, outer_instance):
            super().__init__(title="提交 Refresh Token", timeout=None)
            self.outer_instance = outer_instance

            self.add_item(InputText(
                label="貼上 Refresh Token",
                placeholder="在此貼上剪貼簿中的 Refresh Token，再按下「提交」",
                style=InputTextStyle.long,
                required=True,
            )
            )

        async def callback(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            token = self.children[0].value
            if GoogleAPI.refresh_token_is_valid(token):
                google_api_obj = GoogleAPI()
                google_api_obj.setup_credentials(token)
                user_data = google_api_obj.get_basic_data_from_google()
                embed = Embed(
                    title="已從你的 Google 帳戶取得所需資料！",
                    description="下方是我們從你的 Google 帳戶取得的資料，請核對是否正確。\n"
                                "- 沒有問題：按下「▶️ 下一步」按鈕，即可直接傳送下列資料至管理員進行審核。\n"
                                "- 資料有誤：按下「🖋️ 先修正再繼續」按鈕，即可開啟編輯器；完成修正後，再傳送至管理員。\n"
                                "**⚠️注意：資料送出後即無法更改，僅可連絡管理員進行手動修正！**",
                    color=default_color
                )
                embed.add_field(name="真實姓名", value=user_data["name"], inline=False)
                embed.add_field(name="校內電子郵件地址", value=user_data["email_address"], inline=False)
                embed.set_thumbnail(url=user_data["photo"])
                await interaction.edit_original_response(
                    embed=embed, view=NewVerification.Step3(self.outer_instance, user_data)
                )
            else:
                embed = Embed(
                    title="錯誤：Refresh Token 無效",
                    description="你所提交的 Refresh Token 無效。請再試一次。\n"
                                "- 直接貼上從網頁複製的文字即可，無須進行編輯。\n"
                                "如果仍然出現這個錯誤，請聯絡管理員。",
                    color=error_color,
                )
                await interaction.edit_original_response(embed=embed)

    class Step3(View):
        def __init__(self, outer_instance, user_data: dict):
            super().__init__(timeout=None, disable_on_timeout=True)
            self.outer_instance = outer_instance
            self.user_data = user_data

        @discord.ui.button(label="下一步", style=ButtonStyle.green, emoji="▶️")
        async def next_btn(self, button: Button, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            embed = Embed(
                title="已提交新的審核要求！", description="你的回應已送出！請等待管理員的審核。", color=default_color
            )
            embed.add_field(
                name="你的帳號名稱",
                value=interaction.user.name,
                inline=False,
            )
            embed.add_field(name="真實姓名", value=self.user_data["name"], inline=False)
            embed.add_field(name="校內電子郵件地址", value=self.user_data["email_address"], inline=False)
            await interaction.edit_original_response(embed=embed, view=None)
            # 管理員端提示
            embed = Embed(
                title="收到新的審核要求", description="有新的審核要求，請盡快處理。", color=default_color
            )
            embed.set_thumbnail(url=interaction.user.display_avatar)
            embed.add_field(
                name="帳號名稱", value=interaction.user.mention, inline=False
            )
            embed.add_field(name="真實姓名", value=self.user_data["name"], inline=False)
            embed.add_field(name="校內電子郵件地址", value=self.user_data["email_address"], inline=False)
            embed.add_field(
                name="按鈕功能說明",
                value="點擊「確認，身分無誤」後，機器人會：\n"
                      "1. 設定該成員真名、電子郵件地址為提交內容\n"
                      "2. 變更該成員暱稱為真名\n"
                      "3. 傳送通知給該成員",
                inline=False
            )
            await self.outer_instance.bot.get_channel(VERIFICATION_CHANNEL_ID).send(
                content="@everyone", embed=embed,
                view=NewVerification.ConfirmIdentity(self.outer_instance, interaction.user, self.user_data)
            )

        @discord.ui.button(label="先修正再繼續", style=ButtonStyle.green, emoji="🖋️")
        async def edit_btn(self, button: Button, interaction: discord.Interaction):
            await interaction.response.send_modal(NewVerification.EditWindow(self.outer_instance, self.user_data))

    class ConfirmIdentity(View):
        def __init__(self, outer_instance, user: discord.User, user_data: dict):
            super().__init__()
            self.outer_instance = outer_instance
            self.member = user
            self.user_data = user_data

        @discord.ui.button(label="確認，身分無誤", style=discord.ButtonStyle.green, emoji="✅")
        async def valid_button_callback(
                self, button: discord.ui.Button, interaction: discord.Interaction
        ):
            await interaction.response.defer()
            logging.info(f"{self.member.name} 的身分已經過 {interaction.user.name} 確認無誤")
            print((self.member.id,
                   self.user_data["name"],
                   datetime.now(tz=now_tz).year - 2016,
                   self.user_data["email_address"]))
            await self.outer_instance.rwapi.create_member(
                self.member.id,
                self.user_data["name"],
                datetime.now(tz=now_tz).year - 2016,
                self.user_data["email_address"],
                self.member.display_avatar.url,
            )
            frc_guild: discord.Guild = self.outer_instance.bot.get_guild(1114203090950836284)
            self.member = frc_guild.get_member(self.member.id)
            edit_nickname = False
            try:
                await self.member.edit(nick=self.user_data["name"])  # noqa
                edit_nickname = True
            except Exception as e:
                logging.warning(f"無法更改 {self.member.name} 的暱稱為其真名")
                logging.warning(f"{type(e).__name__}: {e}")
            notify_embed = Embed(
                title="你的身分已經過驗證！",
                description="管理員在經過審核後，已確認了你的身分。\n"
                            "你的真名已經記錄在資料庫中，"
                            "並且設為你在伺服器中的暱稱。" if edit_nickname else "但是尚未設為你在伺服器中的暱稱。"
                            "\n感謝你的配合！",
                color=default_color
            )
            await self.member.send(embed=notify_embed)
            self.disable_all_items()
            embed = Embed(title="已完成審核", description=f"{interaction.user.mention} 已確認 {self.member.mention} 的審核要求。",
                          color=default_color)
            embed.add_field(name="審核結果", value="✅ 通過", inline=False)
            if not edit_nickname:
                embed.add_field(name="⚠️ 無法設定暱稱", value="設定此成員暱稱為真名時發生錯誤。請手動將該成員的暱稱設定為真名，以利辨識。", inline=False)
            await interaction.edit_original_response(view=self)
            await interaction.followup.send(embed=embed)

        @discord.ui.button(label="此身分有問題", style=discord.ButtonStyle.red, emoji="❌")
        async def invalid_button_callback(
                self, button: discord.ui.Button, interaction: discord.Interaction
        ):
            await interaction.response.defer()
            logging.info(f"{self.member.name} 的身分已被 {interaction.user.name} 撤回")
            notify_embed = Embed(
                title="你的身分未通過驗證",
                description="管理員在經過審核後，認為你所提供的身分有問題。\n"
                            "請私訊伺服器管理員以了解詳情。",
                color=error_color
            )
            await self.member.send(embed=notify_embed)
            self.disable_all_items()
            embed = Embed(title="已完成審核", description=f"{interaction.user.mention} 已確認 {self.member.mention} 的審核要求。",
                          color=default_color)
            embed.add_field(name="審核結果", value="❌ 撤回")
            await interaction.edit_original_response(view=self)
            await interaction.followup.send(embed=embed)

    class EditWindow(Modal):
        def __init__(self, outer_instance, user_data: dict):
            super().__init__(title="修正個人資料", timeout=None)
            self.outer_instance = outer_instance
            self.user_data = user_data

            self.add_item(InputText(
                label="真實姓名",
                value=user_data["name"],
                required=True,
                style=InputTextStyle.short,
            ))
            self.add_item(InputText(
                label="校內電子郵件地址",
                value=user_data["email_address"],
                required=True,
                style=InputTextStyle.short,
            ))

        async def callback(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            self.user_data["name"] = self.children[0].value
            self.user_data["email_address"] = self.children[1].value
            embed = Embed(
                title="已修正你的個人資料",
                description="下方是你修正後的個人資料。請再次檢查是否正確。\n"
                            "- 沒有問題：按下「▶️ 下一步」按鈕，即可直接傳送下列資料至管理員進行審核。\n"
                            "- 資料有誤：按下「🖋️ 先修正再繼續」按鈕，即可開啟編輯器；完成修正後，再傳送至管理員。",
                color=default_color
            )
            embed.add_field(name="真實姓名", value=self.user_data["name"], inline=False)
            embed.add_field(name="校內電子郵件地址", value=self.user_data["email_address"], inline=False)
            embed.set_thumbnail(url=self.user_data["photo"])
            await interaction.edit_original_response(
                embed=embed, view=NewVerification.Step3(self.outer_instance, self.user_data)
            )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member | discord.User):
        guild_joined = member.guild
        if not member.bot and guild_joined.id == 1114203090950836284:
            logging.info(f"新成員加入：{member.name}")
            embed = Embed(
                title=f"歡迎加入 {guild_joined.name} ！",
                description="在正式加入此伺服器前，請先完成「自動身分驗證」，以便我們授予你適當的權限！\n"
                            "1. 點擊下方「🔐 使用中科實中 Google 帳戶登入」按鈕，並使用中科實中的 Google 帳戶登入\n"
                            "2. 點擊複製按鈕，取得你的 Refresh Token\n"
                            "3. 點擊下方「📝 提交你的 Refresh Token」按鈕，並在開啟的視窗內貼上 Refresh Token 後提交",
                color=default_color,
            )
            embed.add_field(
                name="為何登入後顯示「已封鎖存取權」錯誤？",
                value="為了資訊安全，此系統目前僅開放「中科實中網域 (結尾為 `@nehs.tc.edu.tw` )」的 Google 帳戶使用。\n"
                      "如果你是中科實中的學生，請切換至學校帳戶並重試；外校學生請直接連絡伺服器管理員。",
                inline=False,
            )
            try:
                await member.send(
                    embed=embed, view=self.Step1(self)
                )
                logging.info("   ⌊已成功傳送驗證提示")
            except discord.errors.HTTPException as error:
                if error.code == 50007:
                    logging.warning("   ⌊無法傳送驗證提示 (私人訊息關閉)")
                    await guild_joined.system_channel.send(
                        f"{member.mention}，由於你的私人訊息已關閉，無法透過機器人進行快速審核。\n"
                        f"請私訊管理員你的**真名**，以便我們授予你適當的身分組！"
                    )
                else:
                    raise error

    @discord.slash_command(name="執行新版驗證", description="執行新版的身分驗證，並使用 Google 帳戶登入取得資料")
    async def new_verify(self, ctx: discord.ApplicationContext):
        await self.on_member_join(ctx.user)
        await ctx.respond(content="已透過私人訊息傳送驗證通知。", ephemeral=True)


def setup(bot):
    bot.add_cog(NewVerification(bot))
    logging.info(f'已載入 "{NewVerification.__name__}"。')

