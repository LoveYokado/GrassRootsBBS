import cv2
import numpy as np
import time
import logging

# アスキーアートに使用する文字セット（暗い -> 明るい）
ASCII_CHARS = "0123456789ABCDEF"


def resize_image(image, new_width=80):
    """画像を新しい幅にリサイズし、アスペクト比を維持する"""
    (old_height, old_width) = image.shape
    # アスペクト比を考慮し、文字の縦横比（約2:1）を補正
    aspect_ratio = old_height / old_width
    new_height = int(aspect_ratio * new_width * 0.55)
    return cv2.resize(image, (new_width, new_height))


def pixels_to_ascii(image):
    """画像のピクセルをアスキー文字に変換する"""
    pixels = image.flatten()
    # 各ピクセルの輝度値 (0-255) をASCII_CHARSのインデックスにマッピング
    indices = (pixels / 255 * (len(ASCII_CHARS) - 1)).astype(int)
    ascii_str = "".join([ASCII_CHARS[i] for i in indices])
    return ascii_str


def run(context):
    """プラグインのエントリーポイント"""
    api = context['api']

    api.send(b"\x1b[2J")  # 画面クリア
    api.send("カメラを初期化しています...\r\n".encode('utf-8'))
    api.send("Press any key to exit.\r\n".encode('utf-8'))

    # カメラデバイスを開く (0は通常、内蔵カメラ)
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        api.send("エラー: カメラを開けませんでした。\r\n".encode('utf-8'))
        logging.error("camera_to_ascii: cv2.VideoCapture(0) を開けませんでした。")
        return

    time.sleep(2)  # カメラの準備待ち

    try:
        while True:
            # ユーザーからの入力があればループを抜ける (非ブロッキング)
            if api.get_input(timeout=0.01) is not None:
                break

            # フレームをキャプチャ
            ret, frame = cap.read()
            if not ret:
                api.send("エラー: フレームをキャプチャできませんでした。\r\n".encode('utf-8'))
                logging.error(
                    "camera_to_ascii: cap.read() でフレームをキャプチャできませんでした。")
                break

            gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            resized_frame = resize_image(gray_frame, new_width=80)
            ascii_art = pixels_to_ascii(resized_frame)

            output = b"\x1b[H"  # カーソルをホームポジション(左上)に移動
            for i in range(resized_frame.shape[0]):
                start = i * resized_frame.shape[1]
                end = (i + 1) * resized_frame.shape[1]
                output += ascii_art[start:end].encode('utf-8') + b'\r\n'
            api.send(output)

            time.sleep(1/15)  # 描画レートを調整 (約15fps)
    finally:
        cap.release()
        api.send(b"\x1b[2J")  # 終了時に画面をクリア
        logging.info("camera_to_ascii: カメラを解放しました。")
