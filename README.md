# GrassRootsBBS

GrassRootsBBS is a web-based, terminal-style bulletin board system that recreates the nostalgic experience of 1990s PC communication (BBS) using modern technology.

## Project Background

This software was born out of a deep respect for "BIG-Model," a BBS host program that had a massive influence on Japanese PC communication culture. As the internet became mainstream and traditional BBSs began to disappear, this project was started with the desire to pass on that unique operational feel and atmosphere to the modern era.

Many may remember those days: people chatting all night while worrying about mounting phone bills, users patrolling and posting "storms" of messages multiple times a day, the occasional flame war, people getting married, or those who went a bit too far at offline drinking meetups. It was a unique atmosphere that doesn't quite exist in today's internet.

While it may be difficult to bring back the peak of text-based BBS culture now, this project allows anyone to stand up a PC communication host program with minimal effort as a way to preserve those memories. Even if a full reenactment isn't possible, I hope people can learn and appreciate "this is how we used to do things."

During development, I contacted Mr. Kiyoshi Kawamura, CEO of NetComplex Co., Ltd. and copyright holder of "BIG-Model." He graciously granted permission to develop and release software with a similar UI/UX. I would like to take this opportunity to express my sincere gratitude to Mr. Kawamura for his generous consideration and his passion for grassroots BBS culture.

Like the original BIG-Model, this project aims to grow through feedback from SysOps and users alike.

## Acknowledgments

This project would not have been possible without the help of many people. In particular, I would like to express my heartfelt thanks to **papanpa** from Threads for their extensive cooperation since the early stages of development, and to everyone who supported the project through "Likes" and encouragement.

## Support the Project ☕

GrassRootsBBS is a labor of love to bring back the golden age of BBS culture. If you enjoy using this software and want to show some love, feel free to buy me a coffee! Your support helps keep the development moving forward.

[![Support me on Ko-fi](https://img.shields.io/badge/Support%20me%20on%20Ko--fi-F16061?logo=ko-fi&logoColor=white)](https://ko-fi.com/loveyokado)
[Support me on Ko-fi](https://ko-fi.com/loveyokado)

## Differences from the Original Big-model

- **Access**: Connections are made via a terminal emulator in a web browser.
- **Threaded Boards**: Added a simplified threaded bulletin board system.
- **No Connection Limits**: No upper limit on the number of simultaneous users.
- **Online Signup**: Since we no longer live in an era where we ask for home addresses and phone numbers, an online signup system is used.
- **User Levels**: Introduced user levels to accommodate online signup.
- **Menu Integration**: Similar board menus have been integrated for better flow.
- **Menu Modes**: While "Menu Mode 1" is a Big-model clone, other modes are unique to GrassRootsBBS.

## Main Features

- **Retro & Modern Web Terminal UI**:
  - CUI-like interface centered on keyboard operation.
  - User-selectable themes (e.g., Green Monitor, Amber Monitor) and fonts.
  - Playful DIP-switch style setting screens.
  - PWA support for installation on smartphones.
- **Diverse Communication**:
  - Hierarchical bulletin boards (with/without reply functions).
  - Real-time chat rooms.
  - User-to-user Mail and Telegram functions.
- **Modern Authentication & Notifications**:
  - Passwordless authentication via Passkey (FIDO2).
  - Web Push notifications (e.g., chat entry alerts).
- **Flexible Customization**:
  - Edit menu structures via YAML files.
  - Detailed configuration through the admin panel.
- **Extensibility**: Safely extend BBS functionality via the `GrbbsApi`.
- **Powerful Management Tools**:
  - Intuitive Web UI for managing users, boards, and system settings.
  - Export/Import of user info and board data.
  - Manual/Automatic backup, restore, and database optimization.
- **Security**:
  - Detection of Proxy/VPN connections.
  - File scanning and quarantine via ClamAV.
  - Rate limiting to prevent brute-force attacks.
  - Kick/Ban functionality by IP address.

### Bulletin Boards (SIGs)

- Add/Remove from Search List.
- **B/W List Editing [SysOp/SigOp]**: Behavior changes based on board attributes:
  - **Open/Read-only boards**: Acts as a Blacklist.
  - **Closed boards**: Acts as a Whitelist.
- Change SigOp [SysOp].
- Edit "Sig-Kanban" (Board Signboard) [SysOp/SigOp].

We have introduced the concept of a "Board Operator" (SigOp) found in other classic BBSs. Board managers can edit the signboard, manage B/W lists, and delete or restore user posts. Read/write permissions can be set per board based on user levels.

### Online Signup, Guests, and General Members

Immediately after signing up online, users have the same limited permissions as "Guests." Once the SysOp verifies the account and upgrades the user level to "General Member," registration is complete.

---

## Installation & Setup

**Prerequisites:** Docker, Docker Compose, Python 3

### 1. Clone the Repository

```bash
git clone https://github.com/LoveYokado/grassrootsbbs.git
cd GrassRootsBBS
```

### 2. Environment Variables

Copy the `.env.example` file to `.env` and edit its contents. This file is used to configure the System Operator (SysOp) account and database connection.

```bash
cp .env.example .env
```

Open the .env file and set the System Operator (SysOp) credentials:

```bash
# .env
GRASSROOTSBBS_SYSOP_ID=your_sysop_id
GRASSROOTSBBS_SYSOP_PASSWORD=your_strong_password
GRASSROOTSBBS_SYSOP_EMAIL=your_email@example.com
```

Change the database passwords:

```bash
# .env
DB_USER=grbbs_user
DB_PASSWORD=your_secure_database_password
DB_NAME=grbbs

MYSQL_ROOT_PASSWORD=your_secret_root_password
```

### 3. Edit Configuration Files

Edit setting/config.toml to match your environment.

The following are the minimum required changes:

```Ini, TOML
[security]
GUEST_ID_SALT = "random_string" # Change this to a complex, random string!

[webapp]
ORIGIN = "http://localhost:5000" # Full URL to access the BBS (protocol, host, port)
RP_ID = "localhost" # Domain name used for Passkeys (do not include port)

[push]
VAPID_PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
[Your Private Key Content]
-----END PRIVATE KEY-----
"""
VAPID_CLAIMS_EMAIL = "mailto:your-email@example.com" # Your email address
```

To generate VAPID keys:

```bash
$ cd tools/
$ python generate_vapid_keys.py
```

Paste the content of the generated `private_key.pem` into the `VAPID_PRIVATE_KEY` section.

### 4. PWA Manifest Settings

Set the app name and icons for PWA installation. Copy manifest.json.example to manifest.json and edit if necessary.

```bash
cp static/manifest.json.example static/manifest.json
```

If you want to change the BBS name, modify the name and short_name fields inside `manifest.json`.

### 5. Launch the Server

Copy the Docker Compose example file:

```bash
cp docker-compose.yml.example docker-compose.yml
```

Start the BBS using Docker Compose:

```bash
docker-compose up --build -d
```

Upon the first run, database tables and the SysOp account defined in `.env` will be created automatically.

### 6. Accessing the BBS

Access the BBS in your browser at `http://localhost:5000`.
The admin panel is located at `http://localhost:5000/admin` (this path can be changed in `setting/config.toml`).

For detailed usage and management instructions, please refer to `manual.md`.

### 7. (Recommended) Production Environment: Nginx Reverse Proxy

When publishing to the internet, we strongly recommend placing Nginx in front of the application as a reverse proxy for security, performance, and easy HTTPS (SSL/TLS) implementation.

#### a. Prepare Nginx Configuration

Copy the example configuration:

```bash
cp nginx.config.example nginx.conf
```

Open `nginx.conf` and edit the sections marked TODO:

- `server_name`: Change `example.com` to your domain.
- SSL Certificate Paths: Specify the correct paths to your SSL certificate and private key (e.g., from Let's Encrypt).

#### b. Obtain SSL Certificates (via Let's Encrypt)

You can use Certbot to obtain free certificates:

```bash
# Replace 'your_domain' and email address
sudo certbot certonly --standalone -d your_domain --email your_email@example.com
```

Once obtained, ensure the `ssl_certificate` and `ssl_certificate_key` paths in `nginx.conf` are correct.
