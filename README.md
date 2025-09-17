# GrassRootsBBS

GrassRootsBBS は、1990 年代のパソコン通信（BBS）の懐かしい体験を現代の技術で再現する、Web ベースのターミナル風掲示板システムです。

![Screenshot](https://user-images.githubusercontent.com/1365634/189474099-b9e3f1e8-7e1b-4b1f-8a0f-62d29402e1c9.png)

## 📜 プロジェクトの背景

このソフトウェアは、かつて日本のパソコン通信文化に大きな影響を与えた BBS ホストプログラム「BIG-Model」への深いリスペクトから生まれました。インターネットが主流となり、当時の BBS が姿を消していく中で、その独特の操作感や雰囲気を現代に伝えたいという想いから開発が始まりました。

開発にあたり、「BIG-Model」の著作権者であるネットコンプレックス株式会社 代表取締役 川村清様にご連絡し、類似の操作感を持つソフトウェアの開発と公開について快くご許諾をいただきました。この場を借りて、川村様の寛大なご配慮と、草の根 BBS 文化への熱い想いに心より感謝申し上げます。

本プロジェクトは、BIG-Model がそうであったように、シスオペや利用者の皆様からのフィードバックによって成長していくことを目指しています。

## 🙏 謝辞

このプロジェクトは、多くの方々の助けなしには実現できませんでした。特に、開発初期から多大なるご協力をいただいた threads の papanpa 様、そして「いいね」を通じて応援してくださった皆様に、心から感謝いたします。

## ✨ 主な機能

- **レトロな Web ターミナル UI**: キーボード操作中心の CUI ライクなインターフェース。
- **多彩なコミュニケーション機能**:
  - 階層構造を持つ掲示板（レス機能付き/なし）
  - リアルタイムチャットルーム
  - ユーザー間でのメール・電報
- **モダンな認証・通知機能**:
  - Passkey（FIDO2）によるパスワードレス認証
  - Web Push 通知（チャット入室通知など）
- **柔軟なカスタマイズ**:
  - YAML ファイルによるメニュー構造の編集
  - 管理画面からの詳細な設定
- **管理者向け Web UI**: ユーザー、掲示板、システム設定などを直感的に管理できる Web 管理画面。
- **データ管理**: 手動・自動バックアップ、リストア、データ全消去機能。
- **セキュリティ**:
  - ClamAV によるファイルスキャンと隔離
  - レートリミットによる総当たり攻撃対策

## 🚀 Installation & Setup / インストールとセットアップ

**必要なもの:** Docker, Docker Compose, Python 3

### 1. リポジトリのクローン

```bash
git clone https://github.com/your-username/GrassRootsBBS.git
cd GrassRootsBBS
```

### 2. 環境変数の設定

`.env.example` をコピーして `.env` ファイルを作成し、内容を編集します。

```bash
cp .env.example .env
```

`.env`ファイルを開き、システム管理者（シスオペ）のアカウント情報を設定してください。

```bash
# .env
GRASSROOTSBBS_SYSOP_ID=your_sysop_id
GRASSROOTSBBS_SYSOP_PASSWORD=your_strong_password
GRASSROOTSBBS_SYSOP_EMAIL=your_email@example.com
```

### 3. 設定ファイルの編集

`setting/config.toml`を編集して、あなたの環境に合わせた設定を行います。

```toml
# setting/config.toml

[webapp]
# BBSにアクセスする際のURL。PasskeyやPush通知で必要です。
ORIGIN = "http://localhost:5000"

[push]
# Push通知の送信者情報として使用されるメールアドレス
VAPID_CLAIMS_EMAIL = "mailto:your_email@example.com"

# この後、VAPIDキーを生成して設定します。
VAPID_PUBLIC_KEY = ""
```

### 4. VAPID キーの生成 (Push 通知用)

Push 通知機能を使用するには、VAPID キーペアが必要です。以下のコマンドを実行してキーを生成してください。

```bash
python3 tools/generate_vapid_keys.py
```

このコマンドにより、プロジェクトのルートディレクトリに `private_key.pem` と `public_key.pem` が作成されます。

1.  生成された `private_key.pem` は、プロジェクトのルートディレクトリにそのまま配置しておきます。
2.  `public_key.pem` の中身（`-----BEGIN...`から`...END PUBLIC KEY-----`まで全て）をコピーし、`setting/config.toml` ファイルの `VAPID_PUBLIC_KEY` の値として貼り付けます。

### 5. サーバーの起動

設定が完了したら、Docker Compose を使って BBS を起動します。

```bash
docker-compose up --build -d
```

初回起動時に、データベースのテーブル作成と、`.env` で設定したシスオペアカウントの作成が自動的に行われます。

### 6. BBS へのアクセス

Web ブラウザで `http://localhost:5000` にアクセスしてください。

管理画面には `http://localhost:5000/admin` からアクセスできます。
