# -*- coding: utf-8 -*-

import os
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

# このスクリプトは、Web Push通知で使用するVAPIDキーペアを生成します。
# 実行すると、プロジェクトルートに private_key.pem と public_key.pem を生成し、
# config.tomlに貼り付けるための秘密鍵の内容をコンソールに出力します。


def generate_keys():
    """VAPIDキーペアを生成し、ファイルに保存＆コンソールに出力します。"""
    # このスクリプトの場所からプロジェクトのルートディレクトリを特定
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)

    private_key_path = os.path.join(project_root, 'private_key.pem')
    public_key_path = os.path.join(project_root, 'public_key.pem')

    # 1. 楕円曲線(P-256)の秘密鍵を生成
    private_key = ec.generate_private_key(ec.SECP256R1())

    # 2. 秘密鍵をPEM形式（PKCS8）でシリアライズ
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )

    # 3. 秘密鍵をファイルに保存
    with open(private_key_path, 'wb') as f:
        f.write(private_pem)
    print(f"秘密鍵を '{private_key_path}' に保存しました。")

    # 4. 秘密鍵から公開鍵を生成し、PEM形式でシリアライズ
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )

    # 5. 公開鍵をファイルに保存
    with open(public_key_path, 'wb') as f:
        f.write(public_pem)
    print(f"公開鍵を '{public_key_path}' に保存しました。")

    # 6. config.tomlに貼り付けるための秘密鍵をコンソールに出力
    print("\n" + "="*50)
    print("以下の内容を setting/config.toml の VAPID_PRIVATE_KEY に貼り付けてください:")
    print("="*50)
    print(private_pem.decode('utf-8'))


if __name__ == '__main__':
    generate_keys()
