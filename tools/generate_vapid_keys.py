# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

import os
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.backends import default_backend
import logging


def generate_keys():
    """
    Web Push通知で使用するVAPIDの秘密鍵と公開鍵を生成し、
    プロジェクトルートにPEMファイルとして保存します。
    """
    # プロジェクトのルートディレクトリを基準にパスを設定
    project_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..'))
    private_key_path = os.path.join(project_root, 'private_key.pem')
    public_key_path = os.path.join(project_root, 'public_key.pem')

    try:
        print("Generating VAPID keys...")
        # 楕円曲線暗号(ECC)のキーペアを生成 (P-256カーブを使用)
        private_key = ec.generate_private_key(
            ec.SECP256R1(), default_backend()
        )

        # --- 秘密鍵をPEM形式で保存 ---
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        with open(private_key_path, 'wb') as f:
            f.write(private_pem)

        # --- 公開鍵をPEM形式で保存 ---
        public_key = private_key.public_key()
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        with open(public_key_path, 'wb') as f:
            f.write(public_pem)

        print("\n" + "="*50)
        print("VAPID keys have been generated successfully!")
        print(f"  - Private Key: {private_key_path}")
        print(f"  - Public Key:  {public_key_path}")
        print("\nNext Steps:")
        print(
            "Set the values for VAPID_CLAIMS_EMAIL and VAPID_PRIVATE_KEY in 'config.toml' under [push] section.")
        print("="*50 + "\n")

    except Exception as e:
        logging.error(
            f"An error occurred during key generation: {e}", exc_info=True)


if __name__ == "__main__":
    generate_keys()
