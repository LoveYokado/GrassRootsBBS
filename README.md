# GrassRootsBBS

GrassRootsBBS は、1990 年代のパソコン通信(BBS)の懐かしい体験を現代の技術で再現する、Web ベースのターミナル風掲示板システムです。

## プロジェクトの背景

このソフトウェアは、かつて日本のパソコン通信文化に大きな影響を与えた BBS ホストプログラム「BIG-Model」への深いリスペクトから生まれました。インターネットが主流となり、当時の BBS が姿を消していく中で、その独特の操作感や雰囲気を現代に伝えたいという想いから開発が始まりました。
主に文字のみのコミュニケーションながら、毎夜毎夜電話料金を嵩ませながらチャットする人、日に何度も巡回して掲示板に怒涛の書き込みをする人、他にも喧嘩したり結婚したりオフの飲み会で羽目を外しすぎたり、今のインターネットにはない独特な空気が流れていたのを覚えている人もいると思います。
今更文字主体の BBS を盛り上げるのは無理だと思います。が、ひとつの思い出として今の時代でも少しの手間で誰でもパソコン通信のホストプログラムを立ち上げられる。追体験は無理でも、こんなことをやってたんだって知ってもらえれば幸いです。

開発にあたり、「BIG-Model」の著作権者であるネットコンプレックス株式会社 代表取締役 川村清様にご連絡し、類似の操作感を持つソフトウェアの開発と公開について快くご許諾をいただきました。この場を借りて、川村様の寛大なご配慮と、草の根 BBS 文化への熱い想いに心より感謝申し上げます。
本プロジェクトは、BIG-Model がそうであったように、シスオペや利用者の皆様からのフィードバックによって成長していくことを目指しています。

## 謝辞

このプロジェクトは、多くの方々の助けなしには実現できませんでした。特に、開発初期から多大なるご協力をいただいた threads の papanpa 様、そして「いいね」を通じて応援してくださった皆様に、心から感謝いたします。

## 本家 Big-model との違い

- 接続は Web ブラウザ上のターミナルから行う。
- 簡易スレッド式掲示板を追加
- 接続数の上限がない
- 住所や電話番号を聞く時代ではなくなっているのでオンラインサインアップを採用
- オンラインサインアップ採用のため、ユーザレベルを導入
- 類似掲示板メニューを統合
- メニューモード 1 は Big-model クローンだが、それ以外は GrassRootsBBS 独自になっている。

## 主な機能

- **レトロ&モダンな Web ターミナル UI**:
  - キーボード操作中心の CUI ライクなインターフェース。
  - ユーザーが自由に選べるテーマ（緑・琥珀色など）とフォント。
  - 遊び心のある DIP スイッチ風設定画面。
  - PWA 対応によるスマートフォンへのインストール。
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
- **プラグインによる拡張性**: `GrbbsApi` を通じて、BBS の機能を安全に拡張可能。
- **強力な管理機能**:
  - ユーザー、掲示板、システム設定などを直感的に管理できる Web UI。
  - ユーザー情報や掲示板データのエクスポート/インポート。
  - 手動・自動バックアップ、リストア、データベース最適化機能。
- **セキュリティ**:
  - プロキシ・VPN 経由の接続を判別。
  - ClamAV によるファイルスキャンと隔離
  - レートリミットによる総当たり攻撃対策
  - IP アドレスによる Kick/Ban 機能

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

## Installation & Setup / インストールとセットアップ

**必要なもの:** Docker, Docker Compose, Python 3

### 1. リポジトリのクローン

```bash
git clone https://github.com/LoveYokado/grassrootsbbs.git
cd GrassRootsBBS
```

### 2. 環境変数の設定

`.env.example` をコピーして `.env` ファイルを作成し、内容を編集します。このファイルで、管理者アカウントとデータベースの接続情報を設定します。

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

データベースのパスワードを変更してください。

```bash
# .env
DB_USER=grbbs_user
DB_PASSWORD=your_secure_database_password
DB_NAME=grbbs

MYSQL_ROOT_PASSWORD=your_secret_root_password

```

### 3. 設定ファイルの編集

`setting/config.toml`を編集して、あなたの環境に合わせた設定を行います。

[security]
GUEST_ID_SALT = "hogehoge" # 必ずランダムで複雑な文字列に変更してください

[webapp]
ORIGIN = "http://localhost:5000" # BBS にアクセスする際の完全な URL (プロトコル、ホスト、ポートを含む)
RP_ID = "localhost" # Passkey で使われるドメイン名 (ポート番号は含めない)

[push]
VAPID_PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
hogehogheohgoehogheohgoehohgoeoge
hgoheoghoehogehoghhogehoghoehohgg
hgoheoghoehogehoghoehogheohgoehog
-----END PRIVATE KEY-----
"""
VAPID_CLAIMS_EMAIL = "mailto:your-email@example.com" # あなたのメールアドレスに変更

が最低限変更する部分です。

VAPID は

```toml
$ cd tools/
$ python  generate_vapid_keys.py
==================================================
VAPID keys have been generated successfully!
  - Private Key: /path/to/GrassRootsBBS/private_key.pem
  - Public Key:  /path/to/GrassRootsBBS/public_key.pem

Next Steps:
Set the values for VAPID_CLAIMS_EMAIL and VAPID_PRIVATE_KEY in 'config.toml' under [push] section.
==================================================
```

で出力された private_key.pem の内容をペーストしてください。

### 4. PWA マニフェストの設定

PWA（プログレッシブ・ウェブアプリ）としてスマートフォンなどにインストールする際のアプリ名やアイコンを設定します。
`manifest.json.example`をコピーして manifest.json を作成し、必要に応じて内容を編集してください。

```bash
cp static/manifest.json.example static/manifest.json
```

特に、BBS の名前を変更したい場合は manifest.json 内の name と short_name を変更します。

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
管理画面には `http://localhost:5000/admin` からアクセスできます。（この `/admin` の部分は `setting/config.toml` で変更可能です）

BBS の詳しい使い方や管理方法については、manual.md を参照してください。

### 8. （推奨）本番環境向け: Nginx によるリバースプロキシ設定

実際にインターネットに公開する際は、セキュリティとパフォーマンス向上のため、Nginx をリバースプロキシとして BBS アプリケーションの前に配置することを強く推奨します。これにより、HTTPS(SSL/TLS)化も容易になります。

#### a. Nginx 設定ファイルの準備

`nginx.config.example` をコピーして、Nginx 用の設定ファイルを作成します。

```bash
cp nginx.config.example nginx.conf
```

次に、`nginx.conf` を開き、あなたの環境に合わせて `TODO` と書かれた箇所を編集します。

- **`server_name`**: `example.com` をあなたのドメイン名に書き換えます。
- **SSL 証明書のパス**: Let's Encrypt などで取得した SSL 証明書と秘密鍵への正しいパスを指定します。Let's Encrypt を使用する場合、証明書は通常 `/etc/letsencrypt/live/your_domain/` 以下に配置されます。

#### b. SSL 証明書の取得 (Let's Encrypt を使用する場合)

無料で SSL 証明書を発行できる Let's Encrypt と、そのクライアントである Certbot を使用するのが一般的です。

Certbot をホストマシンにインストールした後、以下のコマンド例のように実行して証明書を取得します。（Web サーバーを一時的に停止する必要がある場合があります）

```bash
# 'your_domain' とメールアドレスを置き換えてください
sudo certbot certonly --standalone -d your_domain --email your_email@example.com
```

証明書が取得できたら、`nginx.conf` の `ssl_certificate` と `ssl_certificate_key` のパスが正しいか確認してください。
