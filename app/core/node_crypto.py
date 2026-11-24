"""Node daemon_token encryption (Fernet write, Fernet + legacy Laravel dual-read)."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
from typing import Any, Literal

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.core.config import get_settings
from app.core.security import decrypt_value, encrypt_value

# Standard Fernet tokens begin with version byte 0x80 + 8-byte big-endian timestamp
# (top 3 bytes are 0x00 until year >10000), which base64url-encodes to "gAAAAA".
_FERNET_PREFIX = "gAAAAA"
_PHP_SERIALIZED_STRING_RE = re.compile(rb's:(\d+):"(.*)";', flags=re.DOTALL)


class NodeTokenCryptoError(RuntimeError):
    """Raised when node daemon_token encryption or decryption fails."""


def _parse_laravel_envelope(ciphertext: str) -> dict[str, Any] | None:
    if not isinstance(ciphertext, str) or not ciphertext:
        return None
    try:
        raw = base64.b64decode(ciphertext, validate=True)
        payload = json.loads(raw.decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    iv = payload.get("iv")
    value = payload.get("value")
    if not isinstance(iv, str) or not iv or not isinstance(value, str) or not value:
        return None
    return payload


def is_fernet_token(ciphertext: str) -> bool:
    return isinstance(ciphertext, str) and ciphertext.startswith(_FERNET_PREFIX)


def is_laravel_token(ciphertext: str) -> bool:
    if is_fernet_token(ciphertext):
        return False
    return _parse_laravel_envelope(ciphertext) is not None


def detect_node_token_format(ciphertext: str) -> Literal["fernet", "laravel", "unknown"]:
    if is_fernet_token(ciphertext):
        return "fernet"
    if is_laravel_token(ciphertext):
        return "laravel"
    return "unknown"


def _get_laravel_app_key() -> bytes:
    raw = (get_settings().panel_app_key or "").strip()
    if not raw:
        raise NodeTokenCryptoError("PANEL_APP_KEY 未配置")
    if raw.startswith("base64:"):
        try:
            key = base64.b64decode(raw[7:], validate=True)
        except (binascii.Error, ValueError) as exc:
            raise NodeTokenCryptoError("PANEL_APP_KEY Base64 格式无效") from exc
    else:
        key = raw.encode("utf-8")
    if len(key) not in (16, 24, 32):
        raise NodeTokenCryptoError("PANEL_APP_KEY 密钥长度无效")
    return key


def encrypt_node_token(plaintext: str) -> str:
    if not isinstance(plaintext, str) or not plaintext:
        raise NodeTokenCryptoError("节点通信密钥明文不能为空")
    return encrypt_value(plaintext, get_settings().settings_encryption_key)


def _decrypt_laravel_envelope(payload: dict[str, Any]) -> str:
    key = _get_laravel_app_key()
    iv_b64 = payload["iv"]
    value_b64 = payload["value"]
    mac = payload.get("mac")
    if not isinstance(mac, str) or not mac:
        raise NodeTokenCryptoError("Laravel 节点密文缺少 mac 字段")

    try:
        mac_input = (iv_b64 + value_b64).encode("ascii")
    except UnicodeEncodeError as exc:
        raise NodeTokenCryptoError("Laravel 节点密文字段编码无效") from exc

    expected_mac = hmac.new(key, mac_input, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_mac, mac):
        raise NodeTokenCryptoError("Laravel 节点密文 MAC 校验失败")

    try:
        iv = base64.b64decode(iv_b64, validate=True)
        value = base64.b64decode(value_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise NodeTokenCryptoError("Laravel 节点密文 Base64 解码失败") from exc

    if len(iv) != 16 or len(value) == 0 or len(value) % 16 != 0:
        raise NodeTokenCryptoError("Laravel 节点密文 IV 或块长度无效")

    try:
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        decrypted = decryptor.update(value) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        plaintext_bytes = unpadder.update(decrypted) + unpadder.finalize()
    except ValueError as exc:
        raise NodeTokenCryptoError("Laravel 节点密文解密或填充校验失败") from exc

    match = _PHP_SERIALIZED_STRING_RE.fullmatch(plaintext_bytes)
    if match is None:
        raise NodeTokenCryptoError("Laravel 节点密文 PHP 序列化格式无效")

    declared_len = int(match.group(1))
    value_bytes = match.group(2)
    if declared_len != len(value_bytes):
        raise NodeTokenCryptoError("Laravel 节点密文 PHP 序列化长度不匹配")

    try:
        return value_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise NodeTokenCryptoError("Laravel 节点密文明文编码无效") from exc


def decrypt_node_token(ciphertext: str) -> str:
    if not isinstance(ciphertext, str) or not ciphertext:
        raise NodeTokenCryptoError("节点通信密钥密文不能为空")

    # Strict format isolation: Fernet errors never fall back to Laravel and vice versa.
    if is_fernet_token(ciphertext):
        try:
            return decrypt_value(ciphertext, get_settings().settings_encryption_key)
        except ValueError as exc:
            raise NodeTokenCryptoError("Fernet 节点通信密钥解密失败") from exc

    laravel_payload = _parse_laravel_envelope(ciphertext)
    if laravel_payload is not None:
        return _decrypt_laravel_envelope(laravel_payload)

    raise NodeTokenCryptoError("无法识别的节点通信密钥密文格式")


def encrypt_laravel_node_token(plaintext: str) -> str:
    """Test-only Laravel Crypt::encrypt() encoder for dual-read compatibility fixtures.

    Production write paths must always use :func:`encrypt_node_token`.
    """
    if not isinstance(plaintext, str) or not plaintext:
        raise NodeTokenCryptoError("节点通信密钥明文不能为空")
    key = _get_laravel_app_key()
    raw_bytes = plaintext.encode("utf-8")
    serialised = b"s:" + str(len(raw_bytes)).encode("ascii") + b':"' + raw_bytes + b'";'
    padder = padding.PKCS7(128).padder()
    padded = padder.update(serialised) + padder.finalize()
    iv = secrets.token_bytes(16)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    iv_b64 = base64.b64encode(iv).decode("ascii")
    value_b64 = base64.b64encode(ciphertext).decode("ascii")
    mac = hmac.new(key, (iv_b64 + value_b64).encode("ascii"), hashlib.sha256).hexdigest()
    envelope = json.dumps(
        {"iv": iv_b64, "value": value_b64, "mac": mac, "tag": ""},
        separators=(",", ":"),
    )
    return base64.b64encode(envelope.encode("utf-8")).decode("ascii")
