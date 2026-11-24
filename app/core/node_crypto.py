"""Node daemon_token encryption using Fernet."""

from __future__ import annotations

from app.core.config import get_settings
from app.core.security import decrypt_value, encrypt_value

# Standard Fernet tokens begin with version byte 0x80 + 8-byte big-endian timestamp
# (top 3 bytes are 0x00 until year >10000), which base64url-encodes to "gAAAAA".
_FERNET_PREFIX = "gAAAAA"


class NodeTokenCryptoError(RuntimeError):
    """Raised when node daemon_token encryption or decryption fails."""


def is_fernet_token(ciphertext: str) -> bool:
    return isinstance(ciphertext, str) and ciphertext.startswith(_FERNET_PREFIX)


def encrypt_node_token(plaintext: str) -> str:
    if not isinstance(plaintext, str) or not plaintext.strip():
        raise NodeTokenCryptoError("节点通信密钥明文不能为空")
    return encrypt_value(plaintext, get_settings().settings_encryption_key)


def decrypt_node_token(ciphertext: str) -> str:
    if not isinstance(ciphertext, str) or not ciphertext.strip():
        raise NodeTokenCryptoError("节点通信密钥密文不能为空")
    if not is_fernet_token(ciphertext):
        raise NodeTokenCryptoError("无法识别的节点通信密钥密文格式")
    try:
        plaintext = decrypt_value(ciphertext, get_settings().settings_encryption_key)
    except ValueError as exc:
        raise NodeTokenCryptoError("Fernet 节点通信密钥解密失败") from exc
    if not plaintext.strip():
        raise NodeTokenCryptoError("Fernet 节点通信密钥明文为空")
    return plaintext
