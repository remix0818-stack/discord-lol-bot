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
    return web.Response(text="pong")

app.router.add_get('/ping', handle_ping)

# 비활성화 방지를 위한 태스크
@tasks.loop(minutes=10)  # 10분마다 실행
async def keep_alive():
    """봇을 활성 상태로 유지하는 태스크"""
    try:
        # 간단한 로그 출력으로 봇이 살아있음을 확인
        logger.info("봇이 활성 상태를 유지하고 있습니다...")
            
    except Exception as e:
        logger.error(f"keep_alive 태스크 오류: {e}")

@keep_alive.before_loop
async def before_keep_alive():
    """봇이 준비될 때까지 대기"""
    await bot.wait_until_ready()


class RegisterModal(Modal):
    def __init__(self, view_ref, default_name="", default_score="", edit_index=None):
        super().__init__(title="참가자 등록 / 수정")
        self.view_ref = view_ref
        self.edit_index = edit_index
        self.name = TextInput(label="이름", placeholder="홍길동", default=default_name)
        self.score = TextInput(
            label="점수", placeholder="100 (선택)", style=discord.TextStyle.short, default=default_score, required=False
        )
        self.add_item(self.name)
        self.add_item(self.score)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            score_val = int(self.score.value) if self.score.value.strip() != "" else 0
        except ValueError:
            await interaction.response.send_message("점수는 숫자여야 합니다.", ephemeral=True)
            return

        if self.edit_index is not None:
            self.view_ref.players[self.edit_index] = (self.name.value, score_val)
            await interaction.response.send_message(f"{self.name.value}님의 정보가 수정되었습니다.", ephemeral=True)
        else:
            if len(self.view_ref.players) >= 10:
                await interaction.response.send_message("참가자는 최대 10명입니다.", ephemeral=True)
                return
            self.view_ref.players.append((self.name.value, score_val))
            await interaction.response.send_message(f"{self.name.value}님이 점수 {score_val}점으로 등록되었습니다.", ephemeral=True)

        self.view_ref.refresh_buttons()
        if interaction.message:
            await interaction.message.edit(content="참가자 등록 후 팀 짜기를 눌러주세요.", view=self.view_ref)


class PairInputModal(Modal):
    def __init__(self, view_ref):
        super().__init__(title="같은 팀으로 묶을 참가자 입력")
        self.view_ref = view_ref
        self.name1 = TextInput(label="첫 번째 참가자 이름", placeholder="홍길동", required=False)
        self.name2 = TextInput(label="두 번째 참가자 이름", placeholder="김철수", required=False)
        self.disable_same_team = TextInput(
            label="같은 팀 묶기 없이 진행하려면 '예' 입력", required=False, placeholder="예"
        )
        self.add_item(self.name1)
        self.add_item(self.name2)
        self.add_item(self.disable_same_team)

    async def on_submit(self, interaction: discord.Interaction):
        disable_flag = self.disable_same_team.value.strip().lower()
        if disable_flag == "예":
            await self.view_ref.make_teams_with_pair(interaction, None, None)
            return

        name1 = self.name1.value.strip()
        name2 = self.name2.value.strip()
        names = [p[0] for p in self.view_ref.players]

        if name1 == "" or name2 == "":
            await interaction.response.send_message(
                "두 명의 이름을 모두 입력하거나, 같은 팀 묶기 없이 진행하려면 '예'를 입력하세요.", ephemeral=True
            )
            return

        if name1 not in names or name2 not in names:
            await interaction.response.send_message(
                "입력한 이름 중 참가자 명단에 없는 사람이 있습니다.", ephemeral=True
            )
            return

        await self.view_ref.make_teams_with_pair(interaction, name1, name2)


class MatchView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.players = []
        self._view_id = id(self)
        self.refresh_buttons()

    def refresh_buttons(self):
        self.clear_items()

        add_btn = Button(
            label="참가자 등록",
            style=discord.ButtonStyle.primary,
            custom_id=f"add_player_{self._view_id}",
        )
        add_btn.callback = self.add_player
        self.add_item(add_btn)

        make_btn = Button(
            label="팀 짜기",
            style=discord.ButtonStyle.success,
            custom_id=f"make_teams_{self._view_id}",
        )
        make_btn.disabled = len(self.players) != 10
        make_btn.callback = self.make_teams_button
        self.add_item(make_btn)

        reset_btn = Button(
            label="초기화",
            style=discord.ButtonStyle.danger,
            custom_id=f"reset_{self._view_id}",
        )
        reset_btn.callback = self.reset
        self.add_item(reset_btn)

        for i, (name, score) in enumerate(self.players):
            btn = Button(
                label=f"{name} ({score}점)",
                style=discord.ButtonStyle.secondary,
                custom_id=f"edit_{self._view_id}_{i}",
            )
            btn.callback = self.make_edit_callback(i)
            self.add_item(btn)

    async def add_player(self, interaction: discord.Interaction):
        modal = RegisterModal(view_ref=self)
        await interaction.response.send_modal(modal)

    async def make_teams_button(self, interaction: discord.Interaction):
        modal = PairInputModal(self)
        await interaction.response.send_modal(modal)

    async def make_teams_with_pair(self, interaction: discord.Interaction, fixed_name1, fixed_name2):
        if len(self.players) != 10:
            await interaction.response.send_message(
                f"참가자가 10명이 아닙니다. 현재 {len(self.players)}명 등록됨.", ephemeral=True
            )
            return

        roles = ["탑", "정글", "미드", "원딜", "서폿"]
        random.shuffle(roles)

        if fixed_name1 is None or fixed_name2 is None:
            await self.make_teams_default(interaction)
            return

        fixed_pair = []
        others = []

        for p in self.players:
            if p[0] == fixed_name1 or p[0] == fixed_name2:
                fixed_pair.append(p)
            else:
                others.append(p)

        if len(fixed_pair) != 2:
            await interaction.response.send_message(
                "같은 팀으로 묶을 참가자 2명이 올바르게 등록되어 있지 않습니다.", ephemeral=True
            )
            return

        # 나머지 8명 준비
        remaining_players = others[:]
        random.shuffle(remaining_players)

        team1 = []
        team2 = []

        # 묶인 두명 무조건 팀1에 넣기 + 역할 두 개 할당 (roles[0], roles[1])
        team1.append((fixed_pair[0][0], fixed_pair[0][1], roles[0]))
        team1.append((fixed_pair[1][0], fixed_pair[1][1], roles[1]))

        # 남은 8명 중 3명은 팀1, 5명은 팀2
        team1_others = remaining_players[:3]
        team2_others = remaining_players[3:]

        role_idx = 2  # 역할 인덱스 시작

        for player in team1_others:
            role = roles[role_idx % len(roles)]
            team1.append((player[0], player[1], role))
            role_idx += 1

        for player in team2_others:
            role = roles[role_idx % len(roles)]
            team2.append((player[0], player[1], role))
            role_idx += 1

        def format_team(team):
            return "\n".join(
                [f"{name} ({score}점){' - ' + role if role else ''}" for name, score, role in team]
            )

        msg = f"**팀 1:**\n{format_team(team1)}\n\n**팀 2:**\n{format_team(team2)}"
        await interaction.response.send_message(msg)

    async def make_teams_default(self, interaction: discord.Interaction):
        roles = ["탑", "정글", "미드", "원딜", "서폿"]
        random.shuffle(roles)

        scored_players = [p for p in self.players if p[1] and p[1] > 0]
        no_score_players = [p for p in self.players if not p[1] or p[1] == 0]

        pairs = []

        sorted_scored = sorted(scored_players, key=lambda x: x[1], reverse=True)
        for i in range(0, len(sorted_scored) - len(sorted_scored) % 2, 2):
            pairs.append([sorted_scored[i], sorted_scored[i + 1]])

        random.shuffle(no_score_players)
        for i in range(0, len(no_score_players) - len(no_score_players) % 2, 2):
            pairs.append([no_score_players[i], no_score_players[i + 1]])

        leftover = None
        total_players_count = len(self.players)
        if total_players_count % 2 != 0:
            if len(scored_players) % 2 != 0:
                leftover = sorted_scored[-1]
            elif len(no_score_players) % 2 != 0:
                leftover = no_score_players[-1]

        team1 = []
        team2 = []

        for i, pair in enumerate(pairs):
            role = roles[i % len(roles)]
            if random.choice([True, False]):
                team1.append((pair[0][0], pair[0][1], role))
                team2.append((pair[1][0], pair[1][1], role))
            else:
                team1.append((pair[1][0], pair[1][1], role))
                team2.append((pair[0][0], pair[0][1], role))

        if leftover:
            if random.choice([True, False]):
                team1.append((leftover[0], leftover[1], ""))
            else:
                team2.append((leftover[0], leftover[1], ""))

        def format_team(team):
            return "\n".join(
                [f"{name} ({score}점){' - ' + role if role else ''}" for name, score, role in team]
            )

        msg = f"**팀 1:**\n{format_team(team1)}\n\n**팀 2:**\n{format_team(team2)}"
        await interaction.response.send_message(msg)

    async def reset(self, interaction: discord.Interaction):
        self.players.clear()
        self.refresh_buttons()
        if interaction.message:
            await interaction.message.edit(content="모든 참가자 정보가 초기화되었습니다.", view=self)
        await interaction.response.send_message("참가자 정보가 초기화 되었습니다.", ephemeral=True)

    def make_edit_callback(self, index):
        async def callback(interaction: discord.Interaction):
            name, score = self.players[index]
            modal = RegisterModal(
                default_name=name, default_score=str(score), view_ref=self, edit_index=index
            )
            await interaction.response.send_modal(modal)

        return callback


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
    asyncio.run(main())
