import logging
import json
from webauthn import (
    generate_registration_options,
    options_to_json,
    verify_registration_response,
)
from webauthn.helpers import parse_registration_credential_json
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)
from webauthn.helpers.exceptions import WebAuthnException

from . import database, util

# このファイルは、Passkey（WebAuthn）関連のバックエンドロジックを扱います。
# 今後のステップで、登録・認証のオプション生成や検証処理をここに追加していきます。

# Relying Party (RP) の情報を定義
# モジュール読み込み時点では util.app_config が未初期化のため、
# 各関数内で設定を読み込むように変更します。


def generate_registration_options_for_user(user_id, username):
    """指定されたユーザーのPasskey登録オプションを生成する"""
    webapp_config = util.app_config.get('webapp', {})
    RP_ID = webapp_config.get('RP_ID', 'localhost')
    RP_NAME = webapp_config.get('BBS_NAME', 'GR-BBS')

    logging.info(
        f"ユーザー '{username}' (ID: {user_id}) のPasskey登録オプションを生成します。")

    # 既存のキーを重複登録しないように除外リストを作成
    existing_keys = database.get_passkeys_by_user(user_id)
    exclude_credentials = [
        {"type": "public-key", "id": key["credential_id"]} for key in existing_keys
    ]

    options = generate_registration_options(
        rp_id=RP_ID,
        rp_name=RP_NAME,
        user_id=str(user_id).encode('utf-8'),
        user_name=username,
        user_display_name=username,
        attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=exclude_credentials,
    )

    return options_to_json(options)


def verify_registration_for_user(user_id, credential, expected_challenge, expected_origin, nickname):
    """ユーザーからの登録レスポンスを検証し、成功すればDBに保存する"""
    webapp_config = util.app_config.get('webapp', {})
    RP_ID = webapp_config.get('RP_ID', 'localhost')

    logging.info(f"ユーザーID {user_id} のPasskey登録を検証します。")

    try:
        # フロントエンドから受け取ったJSONをライブラリのヘルパー関数で安全にパース
        webauthn_credential = parse_registration_credential_json(credential)

        # 検証実行
        verification = verify_registration_response(
            credential=webauthn_credential,
            expected_challenge=expected_challenge,
            expected_origin=expected_origin,
            expected_rp_id=RP_ID,
            require_user_verification=False,  # PREFERREDなので必須ではない
        )

        logging.info(
            f"Passkey検証成功: Credential ID: {verification.credential_id.hex()}")

        # DBに保存
        success = database.save_passkey(
            user_id=user_id,
            credential_id=verification.credential_id,
            public_key=verification.credential_public_key,
            sign_count=verification.sign_count,
            transports=webauthn_credential.response.transports or [],
            nickname=nickname,
        )

        return success
    except WebAuthnException as e:
        logging.error(f"Passkey登録検証エラー (UserID: {user_id}): {e}")
        return False
    except Exception as e:
        logging.error(
            f"Passkey登録中に予期せぬエラー (UserID: {user_id}): {e}", exc_info=True)
        return False
