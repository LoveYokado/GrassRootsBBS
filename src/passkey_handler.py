# SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
# SPDX-License-Identifier: MIT

"""Passkey (WebAuthn) ハンドラ。

このモジュールは、Passkey (WebAuthn) 認証のバックエンドロジックを扱います。
登録および認証オプションの生成と、クライアントの認証器（例: 指紋スキャナ、
セキュリティキー）からのレスポンスの検証を担当します。
"""

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


def _get_rp_info():
    """Relying Party (RP) のIDと名前を config.toml から取得するヘルパー関数。"""
    webapp_config = util.app_config.get('webapp', {})
    rp_id = webapp_config.get('RP_ID', 'localhost')
    rp_name = webapp_config.get('BBS_NAME', 'GR-BBS')
    return rp_id, rp_name


def generate_registration_options_for_user(user_id, username):
    """指定されたユーザーのPasskey登録オプションを生成します。"""
    rp_id, rp_name = _get_rp_info()

    logging.info(
        f"ユーザー '{username}' (ID: {user_id}) のPasskey登録オプションを生成します。")

    # このユーザーが既に登録しているキーを、重複登録しないように除外リストとして渡します。
    existing_keys = database.get_passkeys_by_user(user_id)
    if existing_keys is None:
        existing_keys = []  # DBエラーなどでNoneが返ってきた場合は空リストとして扱う

    exclude_credentials = [PublicKeyCredentialDescriptor(
        type=PublicKeyCredentialType.PUBLIC_KEY,
        id=key["credential_id"]
    ) for key in existing_keys]

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
    """ユーザーからの登録レスポンスを検証し、成功すればDBに保存します。"""
    rp_id, _ = _get_rp_info()

    # オリジンを正規化（末尾のスラッシュを削除）
    normalized_origin = expected_origin.rstrip('/')

    logging.info(f"ユーザーID {user_id} のPasskey登録を検証します。")

    try:
        # --- 1. フロントエンドから受け取ったJSONをライブラリが扱える形式にパース ---
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

        # --- 3. 検証成功後、データベースにPasskey情報を保存 ---
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
    """指定されたユーザーのPasskey認証オプションを生成します。"""
    rp_id, _ = _get_rp_info()
    allow_credentials = []

    # ユーザー名が指定されている場合、そのユーザーのキーのみを許可
    if username:
        user = database.get_user_auth_info(username)
        if not user:
            return None

        passkeys = database.get_passkeys_by_user(user['id'])
        if not passkeys:
            return None

        allow_credentials = [
            PublicKeyCredentialDescriptor(
                type=PublicKeyCredentialType.PUBLIC_KEY, id=pk["credential_id"])
            for pk in passkeys
        ]

    options = generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=allow_credentials,
        user_verification=UserVerificationRequirement.PREFERRED,
    )

    return options_to_json(options)


def verify_authentication_for_user(credential, expected_challenge, expected_origin):
    """ユーザーからの認証レスポンスを検証し、成功すればユーザー情報を返します。"""
    rp_id, _ = _get_rp_info()

    # オリジンを正規化（末尾のスラッシュを削除）
    normalized_origin = expected_origin.rstrip('/')

    try:
        # --- 1. フロントエンドから受け取ったJSONをライブラリが扱える形式にパース ---
        auth_credential = parse_authentication_credential_json(credential)

        # DBから対応するPasskey情報を取得
        db_passkey = database.get_passkey_by_credential_id(
            auth_credential.raw_id)
        if not db_passkey:
            raise WebAuthnException("Credential not found in database")

        # --- 2. 認証レスポンスを検証 ---
        verification = verify_authentication_response(
            credential=auth_credential,
            expected_challenge=expected_challenge,
            expected_origin=normalized_origin,
            expected_rp_id=rp_id,
            credential_public_key=db_passkey['public_key'],
            credential_current_sign_count=db_passkey['sign_count'],
            require_user_verification=False,
        )

        # --- 3. 署名カウントを更新（リプレイ攻撃対策） ---
        database.update_passkey_sign_count(
            credential_id=verification.credential_id,
            new_sign_count=verification.new_sign_count
        )

        # --- 4. 認証成功。ユーザー情報を返す ---
        return database.get_user_by_id(db_passkey['user_id'])
    except WebAuthnException as e:
        logging.error(f"Passkey認証検証エラー: {e}")
        return None
    except Exception as e:
        logging.error(f"Passkey認証中に予期せぬエラー: {e}", exc_info=True)
        return None
