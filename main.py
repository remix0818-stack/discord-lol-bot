import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput
import random
import os
from dotenv import load_dotenv
import logging
from aiohttp import web
import asyncio

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# .env 파일 로드
load_dotenv()

# 환경변수에서 토큰 가져오기
TOKEN = os.getenv('DISCORD_TOKEN')
if not TOKEN:
    raise ValueError("DISCORD_TOKEN 환경변수가 설정되지 않았습니다. .env 파일을 확인해주세요.")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# 간단한 웹 서버 (핑용)
app = web.Application()

async def handle_ping(request):
    return web.Response(text="OK", status=200)

# GET + HEAD 둘 다 허용
app.router.add_get('/ping', handle_ping)
app.router.add_head('/ping', handle_ping)

# 비활성화 방지를 위한 태스크
@tasks.loop(minutes=10)  # 10분마다 실행
async def keep_alive():
    try:
        logger.info("봇이 활성 상태를 유지하고 있습니다...")
    except Exception as e:
        logger.error(f"keep_alive 태스크 오류: {e}")

@keep_alive.before_loop
async def before_keep_alive():
    await bot.wait_until_ready()

# ────────────── (중략: Modal, View 클래스 등은 기존 코드 그대로 유지) ──────────────

@bot.event
async def on_ready():
    logger.info(f"{bot.user} 봇이 준비되었습니다.")
    logger.info(f"봇이 {len(bot.guilds)}개의 서버에서 실행 중입니다.")
    keep_alive.start()

@bot.command()
async def match(ctx):
    view = MatchView()
    await ctx.send("참가자 등록 후 팀 짜기를 눌러주세요.", view=view)

# 웹 서버와 봇을 함께 실행
async def main():
    # 웹 서버 시작
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get('PORT', 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"웹 서버가 포트 {port}에서 시작되었습니다.")
    
    # 봇 실행
    await bot.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
