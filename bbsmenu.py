import ssh_input
import util
import sqlite3


def server_pref(chan, dbname):
    """サーバセッティングメニュー"""
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
        if input_buffer == "2":
            chan.send("ゲストアクセスを許可しますか? (y/n): ")
            input_buffer = ssh_input.process_input(chan)
            if input_buffer == "Y" or input_buffer == "y":
                chan.send("ゲストアクセスを許可します\r\n")
                guest = 1
            else:
                chan.send("ゲストアクセスを許可しません\r\n")
                guest = 0
            conn = sqlite3.connect(dbname)
            cur = conn.cursor()
            sql = "UPDATE server_pref SET guest=?"
            cur.execute(sql, (guest,))
            conn.commit()
            conn.close()

        chan.send("Server Preferences: ")
        input_buffer = ssh_input.process_input(chan)
