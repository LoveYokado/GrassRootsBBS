import ssh_input
import util
import sqlite3
import datetime


def sysop_menu(chan, dbname):
    """シスオペメニュー"""
    sendm = util.txt_reads("serverprefmenu.txt")
    for s in sendm:
        chan.send(s + '\r')
        print(s)
    chan.send("Server Preferences: ")
    input_buffer = ssh_input.process_input(chan)
    while input_buffer != "Q" and input_buffer != "q":
        if input_buffer == "":
            for s in sendm:
                chan.send(s + '\r')
                print(s)

        # 設定一覧表示
        if input_buffer == "0":
            conn = sqlite3.connect(dbname)
            cur = conn.cursor()
            cur.execute("SELECT * FROM server_pref;")
            server_prefs = cur.fetchall()
            conn.close()
            if server_prefs:
                chan.send('サーバ設定一覧\r\n')
                chan.send('-'*40+"\r\n")
                chan.send('{:<20} {:<20}\r\n'.format('項目名', '値'))
                chan.send('-'*40+"\r\n")

                for server_pref in server_prefs:
                    chan.send('{:<20} {:<20}\r\n'.format(
                        'bbs', server_pref[0]))
                    chan.send('{:<20} {:<20}\r\n'.format(
                        'chat', server_pref[1]))
                    chan.send('{:<20} {:<20}\r\n'.format(
                        'mail', server_pref[2]))
                    chan.send('{:<20} {:<20}\r\n'.format(
                        'telegram', server_pref[3]))
                    chan.send('{:<20} {:<20}\r\n'.format(
                        'userpref', server_pref[4]))
                    chan.send('{:<20} {:<20}\r\n'.format(
                        'who', server_pref[5]))
                    chan.send('-'*40+"\r\n")
            else:
                chan.send("設定がありません\r\n")

        # 各BBSメニューのユーザレベルごとのパーミッション
        if input_buffer == "1":
            chan.send("各BBSメニューのユーザレベルごとのパーミッションを設定します\r\n")
            chan.send(
                "ユーザレベルを設定する機能を選択してください(bbs,chat,mail,telegram,userpref,who): ")
            input_buffer = ssh_input.process_input(chan).lower()
            valid_menus = ['bbs', 'chat', 'mail',
                           'telegram', 'userpref', 'who']
            if input_buffer not in valid_menus:
                chan.send("有効なメニューを選択してください\r\n")
            else:
                try:
                    chan.send("0:無効 1:ゲスト 2:一般ユーザ 3:シグオペ 4:サブオペ 5:シスオペ\r\n")
                    chan.send("ユーザレベルを入力してください(0~5): ")
                    user_level = int(ssh_input.process_input(chan))
                    if user_level < 0 and user_level > 5:
                        chan.send("ユーザレベルは0~5の範囲で入力してください\r\n")
                        chan.send(
                            "0:無効 1:ゲスト 2:一般ユーザ 3:シグオペ 4:サブオペ 5:シスオペ\r\n")
                except ValueError:
                    chan.send("ユーザレベルは0~5の整数で入力してください\r\n")
                try:
                    conn = sqlite3.connect(dbname)
                    cur = conn.cursor()
                    sql = f"UPDATE server_pref SET {input_buffer}=?"
                    cur.execute(sql, (user_level,))
                    conn.commit()
                    chan.send(
                        f"{input_buffer}メニューのユーザレベルを{user_level}に変更しました\r\n")
                except sqlite3.Error as e:
                    chan.send(f"データベースエラー: {e}\r\n")
                finally:
                    if conn:
                        conn.close()

        # ユーザ情報変更メニュー
        if input_buffer == "2":
            sendm = util.txt_reads("useredit.txt")
            for s in sendm:
                chan.send(s + '\r')
                print(s)
            chan.send("選択してください: ")
            input_buffer = ssh_input.process_input(chan)
            # ユーザ一覧表示
            if input_buffer == "1":
                conn = sqlite3.connect(dbname)
                cur = conn.cursor()
                cursol = cur.execute("SELECT * FROM users")
                users = cursol.fetchall()
                chan.send(
                    "ID    ユーザ名     レベル 登録日時             最終ログイン         コメント     メール\r\n")
                for user in users:
                    regdt = str(datetime.datetime.fromtimestamp(
                        user[3]).strftime('%Y-%m-%d %H:%M:%S'))
                    lastlogin = str(datetime.datetime.fromtimestamp(
                        user[5]).strftime('%Y-%m-%d %H:%M:%S'))
                    chan.send(
                        f"{user[0]:<5} {user[1]:<12} {str(user[4]):<6} {regdt:<20} {lastlogin:<20} {user[7]:<12} {user[8]:<12}\r\n")
                conn.close()

        chan.send("Server Preferences: ")
        input_buffer = ssh_input.process_input(chan)
