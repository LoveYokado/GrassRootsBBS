import logging
from webauthn import (
    generate_registration_options,
    options_to_json,
    verify_registration_response,
    generate_authentication_options,
    verify_authentication_response,
)
from webauthn.helpers import parse_registration_credential_json, parse_authentication_credential_json
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    UserVerificationRequirement,
    PublicKeyCredentialDescriptor,
    PublicKeyCredentialType,
)
from webauthn.helpers.exceptions import WebAuthnException

from . import database, util

# このファイルは、Passkey（WebAuthn）関連のバックエンドロジックを扱います。
# 今後のステップで、登録・認証のオプション生成や検証処理をここに追加していきます。

# Relying Party (RP) の情報を定義
# モジュール読み込み時点では util.app_config が未初期化のため、
# 各関数内で設定を読み込むように変更します。


def _get_rp_info():
    """Relying Party (RP) のIDと名前を config.toml から取得するヘルパー関数"""
    webapp_config = util.app_config.get('webapp', {})
    rp_id = webapp_config.get('RP_ID', 'localhost')
    rp_name = webapp_config.get('BBS_NAME', 'GR-BBS')
    return rp_id, rp_name


def generate_registration_options_for_user(user_id, username):
    """指定されたユーザーのPasskey登録オプションを生成する"""
    rp_id, rp_name = _get_rp_info()

    logging.info(
        f"ユーザー '{username}' (ID: {user_id}) のPasskey登録オプションを生成します。")

    # 既存のキーを重複登録しないように除外リストを作成
    existing_keys = database.get_passkeys_by_user(user_id)
    exclude_credentials = [
        {"type": "public-key", "id": key["credential_id"]} for key in existing_keys
    ]

    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=rp_name,
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
    rp_id, _ = _get_rp_info()

    # 末尾のスラッシュを削除してオリジンを正規化
    normalized_origin = expected_origin.rstrip('/')

    logging.info(f"ユーザーID {user_id} のPasskey登録を検証します。")

    try:
        # フロントエンドから受け取ったJSONをライブラリのヘルパー関数で安全にパース
        webauthn_credential = parse_registration_credential_json(credential)

        # 検証実行
        verification = verify_registration_response(
            credential=webauthn_credential,
            expected_challenge=expected_challenge,
            expected_origin=normalized_origin,
            expected_rp_id=rp_id,
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


def generate_authentication_options_for_user(username):
    """指定されたユーザーのPasskey認証オプションを生成する"""
    rp_id, _ = _get_rp_info()

    user = database.get_user_auth_info(username)
    if not user:
        return None

    passkeys = database.get_passkeys_by_user(user['id'])
    if not passkeys:
        return None

    options = generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=[
            PublicKeyCredentialDescriptor(
                type=PublicKeyCredentialType.PUBLIC_KEY, id=pk["credential_id"])
            for pk in passkeys
        ],
        user_verification=UserVerificationRequirement.PREFERRED,
    )

    return options_to_json(options)


def verify_authentication_for_user(credential, expected_challenge, expected_origin):
    """ユーザーからの認証レスポンスを検証し、成功すればユーザー情報を返す"""
    rp_id, _ = _get_rp_info()

    # 末尾のスラッシュを削除してオリジンを正規化
    normalized_origin = expected_origin.rstrip('/')

    try:
        # フロントエンドから受け取ったJSONをライブラリが扱える形式に変換
        auth_credential = parse_authentication_credential_json(credential)

        # DBから対応するPasskey情報を取得
        db_passkey = database.get_passkey_by_credential_id(
            auth_credential.raw_id)
        if not db_passkey:
            raise WebAuthnException("Credential not found in database")

        # 検証実行
        verification = verify_authentication_response(
            credential=auth_credential,
            expected_challenge=expected_challenge,
            expected_origin=normalized_origin,
            expected_rp_id=rp_id,
            credential_public_key=db_passkey['public_key'],
            credential_current_sign_count=db_passkey['sign_count'],
            require_user_verification=False,
        )

        # 署名カウントを更新
        database.update_passkey_sign_count(
            credential_id=verification.credential_id,
            new_sign_count=verification.new_sign_count
        )

        return database.get_user_by_id(db_passkey['user_id'])
    except WebAuthnException as e:
        logging.error(f"Passkey認証検証エラー: {e}")
        return None
    except Exception as e:
        logging.error(f"Passkey認証中に予期せぬエラー: {e}", exc_info=True)
        return None
