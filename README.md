# GrassRootsBBS

GrassRootsBBS は、1990 年代のパソコン通信(BBS)の懐かしい体験を現代の技術で再現する、Web ベースのターミナル風掲示板システムです。

![Screenshot](https://user-images.githubusercontent.com/1365634/189474099-b9e3f1e8-7e1b-4b1f-8a0f-62d29402e1c9.png)

## 📜 プロジェクトの背景

このソフトウェアは、かつて日本のパソコン通信文化に大きな影響を与えた BBS ホストプログラム「BIG-Model」への深いリスペクトから生まれました。インターネットが主流となり、当時の BBS が姿を消していく中で、その独特の操作感や雰囲気を現代に伝えたいという想いから開発が始まりました。
主に文字のみのコミュニケーションながら、毎夜毎夜電話料金を嵩ませながらチャットする人、日に何度も巡回して掲示板に怒涛の書き込みをする人、他にも喧嘩したり結婚したりオフの飲み会で羽目を外しすぎたり、今のインターネットにはない独特な空気が流れていたのを覚えている人もいると思います。
今更文字主体の BBS を盛り上げるのは無理だと思います。が、ひとつの思い出として今の時代でも少しの手間で誰でもパソコン通信のホストプログラムを立ち上げられる。追体験は無理でも、こんなことをやってたんだって知ってもらえれば幸いです。

開発にあたり、「BIG-Model」の著作権者であるネットコンプレックス株式会社 代表取締役 川村清様にご連絡し、類似の操作感を持つソフトウェアの開発と公開について快くご許諾をいただきました。この場を借りて、川村様の寛大なご配慮と、草の根 BBS 文化への熱い想いに心より感謝申し上げます。

本プロジェクトは、BIG-Model がそうであったように、シスオペや利用者の皆様からのフィードバックによって成長していくことを目指しています。

## 🙏 謝辞

このプロジェクトは、多くの方々の助けなしには実現できませんでした。特に、開発初期から多大なるご協力をいただいた threads の papanpa 様、そして「いいね」を通じて応援してくださった皆様に、心から感謝いたします。

## 本家 Big-model との違い

- 接続は Web ブラウザ上のターミナルから行う。
- 簡易スレッド式掲示板を追加
- 接続数の上限がない
- 住所や電話番号を聞く時代ではなくなっているのでオンラインサインアップを採用
- オンラインサインアップ採用のため、ユーザレベルを導入
- 類似掲示板メニューを統合
- メニューモード 1 は Big-model クローンだが、それ以外は GrassRootsBBS 独自になっている。

## ✨ 主な機能

- **レトロな Web ターミナル UI**: キーボード操作中心の CUI ライクなインターフェース。
- **多彩なコミュニケーション機能**:
  - 階層構造を持つ掲示板(レス機能付き/なし)
  - リアルタイムチャットルーム
  - ユーザー間でのメール・電報
- **モダンな認証・通知機能**:
  - Passkey(FIDO2)によるパスワードレス認証
  - Web Push 通知(チャット入室通知など)
- **柔軟なカスタマイズ**:
  - YAML ファイルによるメニュー構造の編集
  - 管理画面からの詳細な設定
- **管理者向け Web UI**: ユーザー、掲示板、システム設定などを直感的に管理できる Web 管理画面。
- **データ管理**: 手動・自動バックアップ、リストア、データ全消去機能。
- **セキュリティ**:
  - ClamAV によるファイルスキャンと隔離
  - レートリミットによる総当たり攻撃対策

### 掲示板

- 探索リストに追加/削除
- B/W リスト編集[sysop/sigop]掲示板の属性によって動作が変わります。
  - open/readonly 掲示板の場合はブラックリスト
  - close 掲示板の場合はホワイトリスト
- シグオペ変更[sysop]
- シグ看板編集[sysop/sigop]

他の BBS にあったボードオペの概念を導入してあります。
ボード管理者はシグ看板の編集・ブラック/ホワイトリストの編集・一般ユーザの書き込みの削除と復元が可能です。
ボード単位でユーザレベルによる読み書きの設定が可能です。

### オンラインサインアップとゲストと一般会員

オンラインサインアップ直後はゲストと同じ権限しかありません。
シスオペが確認後、ユーザレベルを一般会員に変更して登録完了となります。

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

`.env`ファイルを開き、システム管理者(シスオペ)のアカウント情報を設定してください。

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
2.  `public_key.pem` の中身(`-----BEGIN...`から`...END PUBLIC KEY-----`まで全て)をコピーし、`setting/config.toml` ファイルの `VAPID_PUBLIC_KEY` の値として貼り付けます。

### 5. サーバーの起動

`docker-compose.yml.example` を `docker-compose.yml` としてコピーします。

```bash
cp docker-compose.yml.example docker-compose.yml
```

設定が完了したら、Docker Compose を使って BBS を起動します。

```bash
docker-compose up --build -d
```

初回起動時に、データベースのテーブル作成と、`.env` で設定したシスオペアカウントの作成が自動的に行われます。

### 6. BBS へのアクセス

Web ブラウザで `http://localhost:5000` にアクセスしてください。

BBS の詳しい使い方や管理方法については、manual.md を参照してください。

管理画面には `http://localhost:5000/admin` からアクセスできます。
