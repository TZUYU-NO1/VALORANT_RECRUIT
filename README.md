# Discord募集自動化・管理Bot

Discordサーバー用の募集自動化・管理BOTです。<br>
ゲームモード（コンペティティブ、アンレート、カスタム）ごとの<br>
募集投稿、参加者の管理、運用データの集計・可視化機能を提供します。


<img width="498" height="230" alt="Image" src="https://github.com/user-attachments/assets/f01d14e4-e1b6-47c6-b0ef-9da214fc2142" />



## ディレクトリ構成

```text
/RECRUIT/ (プロジェクトルート)
├── bot/
│   ├── bot.py             # BOT起動、Discordイベントハンドラ
│   └── requirements.txt   # 必要なライブラリリスト
├── data/
│   └── participation_log.json　# 永続化データ(JSON)
└── logs/
    ├── bot.log            # BOT動作記録（追記モードで7日間保持）
    └── op.log             # ユーザー操作ログ（追記モードで7日間保持）
```

## 主な機能

* **募集の自動化**：ボタン操作で簡単にメンバー募集を開始。
* **ボイスチャンネル連携**：募集主のVCのリンクを表示。
* **ログ記録**：毎日の動作および運用の詳細をタイムスタンプ付きで記録（7日間保持）。
* **ランキング可視化**：`!ranking` コマンドで、月間の参加回数ランキングをグラフ画像としてDiscordに投稿。
* **募集の締め切り管理**：募集主による手動での募集締め切り。
* **メンション通知機能**：活動時間に合わせて、参加メンバー全員へボイスチャンネルへの集合通知を送信。

## 導入手順

### 1. プロジェクトルートで必要なライブラリをインストール
```bash
pip install -r ./bot/requirements.txt
```
### 2. IPAフォントの導入
```bash
以下のコマンドでIPAフォントを導入します。
curl -OL https://moji.or.jp/wp-content/ipafont/IPAexfont/IPAexfont00301.zip
yum -y install unzip
unzip IPAexfont00301.zip
mv IPAexfont00301 /usr/share/fonts/
fc-cache -fv
```
### 3. チャンネルIDの記述
```bash
`bot.py` の325行目にある `channel_ids = [テキストチャンネルIDを記載してください]` の箇所に、
 BOTで募集を行うテキストチャンネルのチャンネルIDを記述してください。
 記載例：`channel_ids = [1085856366276640848]`
```
### 4. BOTトークンの記述
```bash
`bot.py` の末尾にある `bot.run('YOUR_BOT_TOKEN')` の箇所に、
 ご自身のDiscord Botトークンを記述してください。
```
### 5. BOTの起動
```bash
以下のコマンドでBOTを起動します。
python3 ./bot/bot.py
```

## 運用上の注意

### 1. ログおよびデータフォルダについて
存在しない場合、BOT起動時に自動作成されます。

### 2. ログの管理について
ログは毎日0時にローテーションされ、
7日以上前のファイルは自動で整理されます。
