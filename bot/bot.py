import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput
import datetime
import pytz
import time
import json
import logging
from logging.handlers import TimedRotatingFileHandler
import os
import matplotlib.pyplot as plt
import io
from collections import Counter

# --- パス設定とディレクトリの自動作成 ---
# bot.pyが /HSVREC/bot/bot.py にある前提で、親ディレクトリをベースにする
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, 'logs')
DATA_DIR = os.path.join(BASE_DIR, 'data')

# 起動時にディレクトリがなければ作成
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# --- ログ設定 ---
def setup_logger(name, log_file):
    handler = TimedRotatingFileHandler(log_file, when="midnight", interval=1, backupCount=7, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    return logger

bot_logger = setup_logger('bot_logger', os.path.join(LOG_DIR, 'bot.log'))
op_logger = setup_logger('op_logger', os.path.join(LOG_DIR, 'op.log'))

# --- 設定 ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)
active_recruitments = {}

# --- 参加履歴記録用関数 ---
def log_participation(user_name):
    file_path = os.path.join(DATA_DIR, 'participation_log.json')
    with open(file_path, 'a', encoding='utf-8') as f:
        json.dump({"user": user_name, "date": datetime.datetime.now().strftime("%Y-%m-%d")}, f)
        f.write("\n")

# ---- Embed付き募集メッセージ用の View ----
class RecruitmentEmbedView(View):
    def __init__(self, author: discord.Member, title_text: str, mode_name: str, capacity: int, channel_id: int, *, timeout=None):
        super().__init__(timeout=None)
        self.author = author
        self.title_text = title_text
        self.mode_name = mode_name
        self.max_count = capacity
        self.closed = False
        self.channel_id = channel_id
        self.participants = [author]

    def make_embed(self) -> discord.Embed:
        count_str = f"({len(self.participants)}/{self.max_count})"
        embed_title = f"{count_str} {self.title_text}\n**{self.mode_name}**"
        lines = ["メンバー:"] + [p.mention for p in self.participants]
        if self.author.voice and self.author.voice.channel:
            lines.extend(["", f"<#{self.author.voice.channel.id}>"])
        lines.extend(["", "【締め切り】" if self.closed else "【募集中】"])
        return discord.Embed(title=embed_title, description="\n".join(lines), color=discord.Color.blue())

    @discord.ui.button(label="参加する", style=discord.ButtonStyle.blurple)
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.closed or len(self.participants) >= self.max_count or interaction.user in self.participants:
            return await interaction.response.send_message("参加不可、または既に参加済みです。", ephemeral=True)
        self.participants.append(interaction.user)
        log_participation(interaction.user.name)
        op_logger.info(f"{interaction.user.name} が参加しました。")
        await interaction.response.defer()
        await interaction.message.edit(embed=self.make_embed(), view=self)

    @discord.ui.button(label="離脱する", style=discord.ButtonStyle.gray)
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.closed or interaction.user not in self.participants: return
        self.participants.remove(interaction.user)
        op_logger.info(f"{interaction.user.name} が離脱しました。")
        await interaction.response.defer()
        await interaction.message.edit(embed=self.make_embed(), view=self)

    @discord.ui.button(label="募集を締め切る", style=discord.ButtonStyle.red)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id: return
        self.closed = True
        op_logger.info(f"{self.author.name} が募集を締め切りました。")
        await interaction.response.defer()
        await interaction.message.edit(embed=self.make_embed(), view=self)
        await interaction.message.reply("この募集は締め切られました。")
        key = (self.channel_id, self.author.id)
        if key in active_recruitments: del active_recruitments[key]

    @discord.ui.button(label="メンションする", style=discord.ButtonStyle.secondary)
    async def mention_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        mentions = " ".join(p.mention for p in self.participants)
        await interaction.response.send_message(f"{mentions}\n活動時間になりました。")

class RecruitmentModal(Modal):
    def __init__(self, author, mode_name, channel_id):
        super().__init__(title="募集詳細")
        self.author, self.mode_name, self.channel_id = author, mode_name, channel_id
        self.title_input = TextInput(label="タイトル", required=True)
        self.num_input = TextInput(label="自分以外の人数", required=True)
        self.add_item(self.title_input)
        self.add_item(self.num_input)

    async def on_submit(self, interaction: discord.Interaction):
        capacity = 1 + int(self.num_input.value)
        view = RecruitmentEmbedView(self.author, self.title_input.value, self.mode_name, capacity, self.channel_id)
        message = await interaction.response.send_message(embed=view.make_embed(), view=view)
        op_logger.info(f"{self.author.name} が募集を開始しました。")
        active_recruitments[(self.channel_id, self.author.id)] = {"message_id": message.id, "closed": False}

# ---- ランキング表示コマンド ----
@bot.command()
async def ranking(ctx):
    now = datetime.datetime.now()
    counts = Counter()
    log_path = os.path.join(DATA_DIR, 'participation_log.json')
    if os.path.exists(log_path):
        with open(log_path, 'r', encoding='utf-8') as f:
            for line in f:
                data = json.loads(line)
                if data['date'].startswith(now.strftime("%Y-%m")):
                    counts[data['user']] += 1
    
    top_10 = counts.most_common(10)
    if not top_10: return await ctx.send("今月のデータがありません。")

    names, values = zip(*top_10)
    plt.figure(figsize=(8, 4))
    plt.bar(names, values)
    plt.title(f"{now.month}月度 参加ランキング")
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    await ctx.send(file=discord.File(buf, 'ranking.png'))
    plt.close()

@bot.event
async def on_ready():
    bot_logger.info("Botが起動しました。")
    print(f"Logged in as {bot.user}")

bot.run('YOUR_TOKEN')
