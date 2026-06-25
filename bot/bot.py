import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput
import datetime
import pytz
import time
import json
import logging
import traceback
from logging.handlers import TimedRotatingFileHandler
import os
import matplotlib.pyplot as plt
import io
from collections import Counter
 
# --- パス設定とディレクトリの自動作成 ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, 'logs')
DATA_DIR = os.path.join(BASE_DIR, 'data')
 
if not os.path.exists(LOG_DIR): os.makedirs(LOG_DIR)
if not os.path.exists(DATA_DIR): os.makedirs(DATA_DIR)
 
# --- ログ設定 ---
def setup_logger(name, log_file):
    handler = TimedRotatingFileHandler(log_file, when="midnight", interval=1, backupCount=7, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M'))
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    return logger
 
bot_logger = setup_logger('bot_logger', os.path.join(LOG_DIR, 'bot.log'))
op_logger = setup_logger('op_logger', os.path.join(LOG_DIR, 'op.log'))
 
intents = discord.Intents.default()
intents.message_content = True
 
bot = commands.Bot(command_prefix='!', intents=intents)
# 毎日AM0:00投稿管理用
last_post_date = None
 
# グローバルな募集中管理辞書
# キー: (channel_id, user_id)
active_recruitments = {}
 
# --- エラーハンドリング ---
@bot.event
async def on_error(event_method, *args, **kwargs):
    error_msg = traceback.format_exc()
    bot_logger.error(f"エラー発生 ({event_method}):\n{error_msg}")
 
# --- 参加履歴記録用関数 ---
def log_participation(user_name):
    file_path = os.path.join(DATA_DIR, 'participation_log.json')
    with open(file_path, 'a', encoding='utf-8') as f:
        json.dump({"user": user_name, "date": datetime.datetime.now().strftime("%Y-%m-%d")}, f)
        f.write("\n")
 
# ---- Embed付き募集メッセージ用の View ----
class RecruitmentEmbedView(View):
    def __init__(self, author: discord.Member, title_text: str, mode_name: str, capacity: int, channel_id: int, *, timeout=None):
        # タイムアウトをNoneにしてViewが切れないように
        super().__init__(timeout=None)
        self.author = author
        self.title_text = title_text
        self.mode_name = mode_name
        self.max_count = capacity
        self.closed = False
        self.channel_id = channel_id
        # 初期参加者: 募集主
        self.participants = [author]
 
    def make_embed(self) -> discord.Embed:
        count_str = f"({len(self.participants)}/{self.max_count})"
        embed_title = f"{count_str} {self.title_text}\n**{self.mode_name}**"
        lines = []
        lines.append("メンバー:")
        for p in self.participants:
            lines.append(p.mention)
        # 募集主がVCにいればVCチャンネルリンクを表示
        if self.author.voice and self.author.voice.channel:
            lines.append("")
            lines.append(f"<#{self.author.voice.channel.id}>")
 
        # --- 状態表示の追加 ---
        lines.append("")
        if not self.closed:
            lines.append("【募集中】")
        else:
            lines.append("【締め切り】")
        # ------------------
 
        description = "\n".join(lines)
        return discord.Embed(title=embed_title, description=description, color=discord.Color.blue())
 
    @discord.ui.button(label="参加する", style=discord.ButtonStyle.blurple)
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.closed:
            return await interaction.response.send_message("この募集は締め切られています。", ephemeral=True)
        if len(self.participants) >= self.max_count:
            return await interaction.response.send_message("満員のため参加出来ません。", ephemeral=True)
        if interaction.user in self.participants:
            return await interaction.response.send_message("あなたは既に参加しています。", ephemeral=True)
        self.participants.append(interaction.user)
        log_participation(interaction.user.name)  # <-- 新機能: 参加記録
        op_logger.info(f"{interaction.user.name} が参加しました。")
        if self.author.voice and self.author.voice.channel:
            try:
                await interaction.user.move_to(self.author.voice.channel)
            except discord.HTTPException:
                pass
        # 更新: グローバル辞書も更新
        key = (self.channel_id, self.author.id)
        if key in active_recruitments:
            active_recruitments[key]["participants"] = [p.id for p in self.participants]
        await interaction.response.defer()
        await interaction.message.edit(embed=self.make_embed(), view=self)
 
    @discord.ui.button(label="離脱する", style=discord.ButtonStyle.gray)
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.closed:
            return await interaction.response.send_message("この募集は締め切られています。", ephemeral=True)
        if interaction.user not in self.participants:
            return await interaction.response.send_message("あなたは参加していません。", ephemeral=True)
        self.participants.remove(interaction.user)
        op_logger.info(f"{interaction.user.name} が離脱しました。")
        key = (self.channel_id, self.author.id)
        if key in active_recruitments:
            active_recruitments[key]["participants"] = [p.id for p in self.participants]
        await interaction.response.defer()
        await interaction.message.edit(embed=self.make_embed(), view=self)
 
    @discord.ui.button(label="募集を締め切る", style=discord.ButtonStyle.red)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id:
            return await interaction.response.send_message("あなたは募集主ではないので締め切る事は出来ません。", ephemeral=True)
        self.closed = True
        op_logger.info(f"{self.author.name} が募集を締め切りました。")
        await interaction.response.defer()
        await interaction.message.edit(embed=self.make_embed(), view=self)
        await interaction.message.reply("この募集は締め切られました。")
        key = (self.channel_id, self.author.id)
        if key in active_recruitments:
            del active_recruitments[key]
 
    @discord.ui.button(label="メンションする", style=discord.ButtonStyle.secondary)
    async def mention_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        key = (self.channel_id, self.author.id)
        data = active_recruitments.get(key)
        if not data:
            return await interaction.response.send_message("現在募集中の情報が取得できませんでした。", ephemeral=True)
        if data.get("closed", False):
            return await interaction.response.send_message("この募集は締め切られています。", ephemeral=True)
 
        now = time.time()
        if now - data.get("last_mention", 0.0) < 180:
            return await interaction.response.send_message("メンションは3分後に可能です。", ephemeral=True)
 
        data["last_mention"] = now
        mentions = " ".join(f"<@{uid}>" for uid in data["participants"])
        await interaction.response.send_message(
            f"{mentions}\n活動時間になりましたのでボイスチャンネルにお集まり下さい。"
        )
 
# ---- Modal: 募集タイトルと人数を入力するモーダル ----
class RecruitmentModal(Modal):
    def __init__(self, author: discord.Member, mode_name: str, channel_id: int):
        super().__init__(title="募集タイトルと人数を入力")
        self.author = author
        self.mode_name = mode_name
        self.channel_id = channel_id
        self.title_input = TextInput(
            label="募集タイトル",
            placeholder="エンジョイなど",
            required=True,
            max_length=50
        )
        self.add_item(self.title_input)
        self.num_input = TextInput(
            label="募集人数(あなた以外の人数)",
            placeholder="1～4 (コンペティティブ/アンレート) または 1～9 (カスタム)",
            required=True,
            max_length=2
        )
        self.add_item(self.num_input)
 
    async def on_submit(self, interaction: discord.Interaction):
        title_text = self.title_input.value
        num_str = self.num_input.value
        if self.mode_name in ["コンペティティブ", "アンレート"]:
            valid_nums = [1, 2, 3, 4]
        elif self.mode_name == "カスタム":
            valid_nums = list(range(1, 10))
        else:
            valid_nums = [1, 2, 3, 4]
        try:
            num_value = int(num_str)
        except ValueError:
            return await interaction.response.send_message("人数は半角数字で入力してください。", ephemeral=True)
        if num_value not in valid_nums:
            return await interaction.response.send_message(f"無効な人数です: {num_value} (モード: {self.mode_name})", ephemeral=True)
        capacity = 1 + num_value
        view = RecruitmentEmbedView(author=self.author, title_text=title_text, mode_name=self.mode_name, capacity=capacity, channel_id=self.channel_id)
        embed = view.make_embed()
        await interaction.response.defer()
        message = await interaction.followup.send(embed=embed, view=view, ephemeral=False)
        op_logger.info(f"{self.author.name} が募集を開始しました。")
        key = (self.channel_id, self.author.id)
        active_recruitments[key] = {
            "message_id": message.id,
            "title_text": title_text,
            "mode_name": self.mode_name,
            "capacity": capacity,
            "closed": False,
            "participants": [self.author.id],
            "last_mention": 0.0,
        }
 
# ---- ユーティリティ: dict から Embed を作成 ----
def build_embed_from_dict(data: dict) -> discord.Embed:
    participants = data["participants"]
    count_str = f"({len(participants)}/{data['capacity']})"
    embed_title = f"{count_str} {data['title_text']}\n**{data['mode_name']}**"
    lines = []
    lines.append("メンバー:")
    for uid in participants:
        lines.append(f"<@{uid}>")
    if not data["closed"]:
        lines.append("")
        lines.append("【募集中】")
    else:
        lines.append("")
        lines.append("【締め切り】")
    return discord.Embed(title=embed_title, description="\n".join(lines), color=discord.Color.blue())
 
# ---- ユーティリティ: dict から View を作成 ----
def build_view_from_dict(channel_id: int, user_id: int, data: dict) -> View:
    new_view = View(timeout=None)
 
    async def join_callback(interaction: discord.Interaction):
        if data["closed"]:
            return await interaction.response.send_message("この募集は締め切られています。", ephemeral=True)
        if len(data["participants"]) >= data["capacity"]:
            return await interaction.response.send_message("満員のため参加出来ません。", ephemeral=True)
        if interaction.user.id in data["participants"]:
            return await interaction.response.send_message("あなたは既に参加しています。", ephemeral=True)
        data["participants"].append(interaction.user.id)
        log_participation(interaction.user.name)
        op_logger.info(f"{interaction.user.name} が参加しました。")
        host_member = interaction.guild.get_member(user_id)
        if host_member and host_member.voice and host_member.voice.channel:
            try:
                await interaction.user.move_to(host_member.voice.channel)
            except discord.HTTPException:
                pass
        await interaction.response.defer()
        new_embed = build_embed_from_dict(data)
        new_view2 = build_view_from_dict(channel_id, user_id, data)
        await interaction.message.edit(content=interaction.message.content, embed=new_embed, view=new_view2)
 
    async def leave_callback(interaction: discord.Interaction):
        if data["closed"]:
            return await interaction.response.send_message("この募集は締め切られています。", ephemeral=True)
        if interaction.user.id not in data["participants"]:
            return await interaction.response.send_message("あなたは参加していません。", ephemeral=True)
        data["participants"].remove(interaction.user.id)
        op_logger.info(f"{interaction.user.name} が離脱しました。")
        await interaction.response.defer()
        new_embed = build_embed_from_dict(data)
        new_view2 = build_view_from_dict(channel_id, user_id, data)
        await interaction.message.edit(content=interaction.message.content, embed=new_embed, view=new_view2)
 
    async def close_callback(interaction: discord.Interaction):
        if interaction.user.id != user_id:
            return await interaction.response.send_message("あなたは募集主ではないので締め切る事は出来ません。", ephemeral=True)
        data["closed"] = True
        op_logger.info(f"{interaction.user.name} が募集を締め切りました。")
        await interaction.response.defer()
        new_embed = build_embed_from_dict(data)
        new_view2 = build_view_from_dict(channel_id, user_id, data)
        await interaction.message.edit(content=interaction.message.content, embed=new_embed, view=new_view2)
        await interaction.message.reply("この募集は締め切られました。")
        key = (channel_id, user_id)
        if key in active_recruitments:
            del active_recruitments[key]
 
    async def mention_callback(interaction: discord.Interaction):
        if data.get("closed", False):
            return await interaction.response.send_message("この募集は締め切られています。", ephemeral=True)
        now = time.time()
        if now - data.get("last_mention", 0.0) < 180:
            return await interaction.response.send_message("メンションは3分後に可能です。", ephemeral=True)
        data["last_mention"] = now
        mentions = " ".join(f"<@{uid}>" for uid in data["participants"])
        await interaction.response.send_message(
            f"{mentions}\n活動時間になりましたのでボイスチャンネルにお集まり下さい。"
        )
 
    join_btn = Button(label="参加する", style=discord.ButtonStyle.blurple)
    leave_btn = Button(label="離脱する", style=discord.ButtonStyle.gray)
    close_btn = Button(label="募集を締め切る", style=discord.ButtonStyle.red)
    mention_btn = Button(label="メンションする", style=discord.ButtonStyle.secondary)
 
    join_btn.callback = join_callback
    leave_btn.callback = leave_callback
    close_btn.callback = close_callback
    mention_btn.callback = mention_callback
 
    new_view.add_item(join_btn)
    new_view.add_item(leave_btn)
    new_view.add_item(close_btn)
    new_view.add_item(mention_btn)
 
    return new_view
 
# ---- 複数のテキストチャンネルに初期メッセージを投稿する関数 ----
async def post_initial_message():
    channel_ids = [1498898992015216761,1085856366276640848]
    top_view = View(timeout=None)
    button = Button(label="募集する", style=discord.ButtonStyle.green)
 
    async def button_callback(interaction: discord.Interaction):
        key = (interaction.channel.id, interaction.user.id)
        if key in active_recruitments:
            existing_message_id = active_recruitments[key]["message_id"]
            guild_id = interaction.guild.id
            channel_id = interaction.channel.id
            message_link = f"https://discord.com/channels/{guild_id}/{channel_id}/{existing_message_id}"
            return await interaction.response.send_message(
                f"募集中の投稿があります。募集を締め切ってから再度募集して下さい。\n募集中の投稿：{message_link}",
                ephemeral=True
            )
        view = View(timeout=None)
        comp_btn = Button(label="コンペティティブ", style=discord.ButtonStyle.primary)
        sageran_btn = Button(label="アンレート", style=discord.ButtonStyle.primary)
        custom_btn = Button(label="カスタム", style=discord.ButtonStyle.primary)
 
        def make_mode_callback(mode_name: str):
            async def callback(inter: discord.Interaction):
                await inter.response.send_modal(RecruitmentModal(interaction.user, mode_name, interaction.channel.id))
            return callback
 
        comp_btn.callback = make_mode_callback("コンペティティブ")
        sageran_btn.callback = make_mode_callback("アンレート")
        custom_btn.callback = make_mode_callback("カスタム")
 
        view.add_item(comp_btn)
        view.add_item(sageran_btn)
        view.add_item(custom_btn)
 
        await interaction.response.send_message("ゲームモードを選択して下さい。", view=view, ephemeral=True)
 
    button.callback = button_callback
    top_view.add_item(button)
 
    msg_text = "フルパーティーのメンバーを募集しましょう。"
    for cid in channel_ids:
        channel = bot.get_channel(cid)
        if channel:
            await channel.send(msg_text, view=top_view)
 
# ---- ダミー編集でインタラクション期限をリフレッシュするタスク ----
@tasks.loop(minutes=10)
async def dummy_edit_loop():
    for (channel_id, author_id), data in list(active_recruitments.items()):
        if data["closed"]:
            continue
        channel = bot.get_channel(channel_id)
        if not channel:
            continue
        try:
            message = await channel.fetch_message(data["message_id"])
        except discord.NotFound:
            continue
        new_view = build_view_from_dict(channel_id, author_id, data)
        new_embed = build_embed_from_dict(data)
        try:
            await message.edit(content=message.content, embed=new_embed, view=new_view)
        except discord.HTTPException:
            pass
 
# --- ランキングコマンド (!ranking) ---
@bot.command()
async def ranking(ctx):
    now = datetime.datetime.now()
    counts = Counter()
    log_path = os.path.join(DATA_DIR, 'participation_log.json')
    if os.path.exists(log_path):
        with open(log_path, 'r', encoding='utf-8') as f:
            for line in f:
                d = json.loads(line)
                if d['date'].startswith(now.strftime("%Y-%m")):
                    counts[d['user']] += 1
    top_10 = counts.most_common(10)
    if not top_10:
        return await ctx.send("今月のデータがありません。")
    names, values = zip(*top_10)
    plt.figure(figsize=(8, 4))
    plt.bar(names, values)
    plt.title(f"{now.month}月度 参加ランキング")
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    await ctx.send(file=discord.File(buf, 'ranking.png'))
    plt.close()
 
# ---- 起動時＆毎日AM0:00に初期メッセージを投稿するタスク ----
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    await post_initial_message()
    daily_post.start()
    dummy_edit_loop.start()
 
@tasks.loop(minutes=1)
async def daily_post():
    global last_post_date
    tz = pytz.timezone("Asia/Tokyo")
    now = datetime.datetime.now(tz)
    if now.hour == 0 and now.minute == 0:
        if last_post_date != now.date():
            await post_initial_message()
            last_post_date = now.date()
 
bot.run('YOUR_BOT_TOKEN')
