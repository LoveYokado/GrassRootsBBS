# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

from pywebpush import vapid
import os


def generate_keys():
    """
    Generates VAPID private and public keys and saves them as PEM files.
    VAPIDの秘密鍵と公開鍵を生成し、PEMファイルとして保存します。
    """
    # プロジェクトのルートディレクトリを基準にパスを設定
    project_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..'))
    private_key_path = os.path.join(project_root, 'private_key.pem')
    public_key_path = os.path.join(project_root, 'public_key.pem')

    # vapid.main()は内部で鍵を生成し、ファイルに保存する
    # --private オプションで秘密鍵のパスを指定
    # --public オプションで公開鍵のパスを指定
    try:
        print("Generating VAPID keys...")
        vapid.main(['--private', private_key_path,
                   '--public', public_key_path])

        print("\n" + "="*50)
        print("VAPID keys have been generated successfully!")
        print(f"  - Private Key: {private_key_path}")
        print(f"  - Public Key:  {public_key_path}")
        print("\nNext Steps:")
        print("1. Ensure 'private_key.pem' is in the project root directory.")
        print(
            "2. Copy the content of 'public_key.pem' into your config.toml under [push] -> VAPID_PUBLIC_KEY.")
        print("="*50 + "\n")

    except Exception as e:
        print(f"\nAn error occurred during key generation: {e}")


if __name__ == "__main__":
    generate_keys()
