# coding=utf-8
import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import zoneinfo

import logger
from roboweb_api import RobowebAPI


# 機器人
intents = discord.Intents.all()
bot = commands.Bot(intents=intents, help_command=None)
# 常用物件、變數
base_dir = os.path.abspath(os.path.dirname(__file__))
now_tz = zoneinfo.ZoneInfo("Asia/Taipei")
default_color = 0x012A5E
error_color = 0xF1411C
real_logger = logger.MyLogger()
# 載入TOKEN
load_dotenv(dotenv_path=os.path.join(base_dir, "TOKEN.env"))
DISCORD_TOKEN = str(os.getenv("DISCORD_TOKEN"))


@bot.event
async def on_ready():
    rw_api = RobowebAPI(os.getenv("ROBOWEB_API_TOKEN"))
    await rw_api.index_members()
    await rw_api.session.close()


@bot.slash_command(name="ping")
async def ping(ctx: discord.ApplicationContext):
    await ctx.respond("Pong!")


bot.load_extensions("cogs.general", "cogs.new_verification", "cogs.meeting", "cogs.member", "cogs.announcement")
bot.run(DISCORD_TOKEN)
