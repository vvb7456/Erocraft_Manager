"""Egg variable rule validator — Laravel rule subset.

Pterodactyl stores per-variable validation rules in ``egg_variables.rules``
as a Laravel-style pipe-separated rule string, e.g.::

    required|string|regex:/^\\S*$/|in:true,false

Panel runs these through the full Laravel validator. We re-implement a
practical subset here so ``panel_db.create_server`` can refuse bad input
before writing rows. The set covers everything used by the SillyTavern
egg and the common rules used by other Pterodactyl eggs.

Supported rules
---------------
required, nullable, sometimes, string, numeric, integer, boolean,
in:a,b,c, not_in:a,b,c, max:N, min:N, between:M,N, size:N, alpha_num,
alpha_dash, url, email, starts_with:a,b, ends_with:a,b, regex:/.../,
not_regex:/.../, digits:N, min_digits:N, max_digits:N, digits_between:M,N,
ip, uuid

Unsupported rules are skipped with a warning so we can find them in
production logs and extend this validator over time.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import uuid as _uuid
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class EggValidationError(ValueError):
    """Raised when an environment value violates an egg variable's rule."""

    def __init__(self, env_variable: str, rule: str, message: str) -> None:
        self.env_variable = env_variable
        self.rule = rule
        super().__init__(f"环境变量 {env_variable} 校验失败 ({rule}): {message}")


_BOOLEAN_TRUE = {"1", "true", "on", "yes", 1, True}
_BOOLEAN_FALSE = {"0", "false", "off", "no", 0, False, ""}
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_ALPHA_NUM_RE = re.compile(r"^[A-Za-z0-9]+$")
_ALPHA_DASH_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_DIGITS_RE = re.compile(r"^\d+$")


_KNOWN_LARAVEL_RULES: frozenset[str] = frozenset(
    {
        # Runtime-enforced rules in this module
        "required",
        "nullable",
        "sometimes",
        "string",
        "numeric",
        "integer",
        "boolean",
        "in",
        "not_in",
        "max",
        "min",
        "between",
        "size",
        "alpha_num",
        "alpha_dash",
        "url",
        "email",
        "starts_with",
        "ends_with",
        "regex",
        "not_regex",
        "digits",
        "min_digits",
        "max_digits",
        "digits_between",
        "ip",
        "uuid",
        # Additional standard Laravel scalar validation rules accepted on egg import/edit
        "present",
        "filled",
        "bail",
        "array",
        "alpha",
        "ascii",
        "active_url",
        "doesnt_start_with",
        "doesnt_end_with",
        "gt",
        "gte",
        "lt",
        "lte",
        "ipv4",
        "ipv6",
        "mac_address",
        "ulid",
        "json",
        "date",
        "lowercase",
        "uppercase",
        "accepted",
        "declined",
        "confirmed",
        "different",
        "same",
        "required_if",
        "required_unless",
        "required_with",
        "required_without",
        "prohibited",
        "decimal",
        "multiple_of",
    }
)


def _split_rules(rules: str) -> list[str]:
    """Split a Laravel rule string (supports both ``;;`` and ``|`` separators)."""
    # Pterodactyl allows `;;` as a separator when a regex rule itself contains `|`.
    if ";;" in rules:
        return [r.strip() for r in rules.split(";;") if r.strip()]
    return [r.strip() for r in rules.split("|") if r.strip()]


def _parse_non_negative_int(raw: str, rule: str) -> int:
    text = raw.strip()
    if not _DIGITS_RE.fullmatch(text):
        raise ValueError(f"规则 {rule!r} 的参数必须是非负整数")
    return int(text)


def validate_rules_syntax(rules: str) -> str:
    """Validate Laravel validation rule string syntax (mirrors Panel ValidatesValidationRules).

    Returns the stripped rule string if valid; raises ``ValueError`` if empty,
    contains unknown rules, malformed numeric arguments, or an uncompilable regex.
    """
    cleaned = rules.strip()
    if not cleaned:
        raise ValueError("校验规则不能为空")

    parts = _split_rules(cleaned)
    if not parts:
        raise ValueError("校验规则不能为空")

    for rule in parts:
        name, sep, args = rule.partition(":")
        name_lower = name.strip().lower()
        if not name_lower or name_lower not in _KNOWN_LARAVEL_RULES:
            raise ValueError(f"不支持或拼写错误的校验规则: {rule!r}")

        if name_lower in ("regex", "not_regex"):
            if not sep or not args:
                raise ValueError(f"规则 {name_lower} 缺少正则表达式参数")
            pattern = _strip_regex_delimiters(args)
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"规则 {rule!r} 正则表达式无效: {exc}") from exc
        elif name_lower in ("digits", "min_digits", "max_digits"):
            if not sep or not args.strip():
                raise ValueError(f"规则 {name_lower} 缺少整数参数")
            _parse_non_negative_int(args, rule)
        elif name_lower == "digits_between":
            nums = [a.strip() for a in args.split(",")] if sep else []
            if len(nums) != 2:
                raise ValueError(f"规则 {rule!r} 需要恰好两个整数参数（例如 digits_between:1,10）")
            lo_int = _parse_non_negative_int(nums[0], rule)
            hi_int = _parse_non_negative_int(nums[1], rule)
            if lo_int > hi_int:
                raise ValueError(f"规则 {rule!r} 下界不能大于上界")
        elif name_lower in ("max", "min", "size"):
            if not sep or not args.strip():
                raise ValueError(f"规则 {name_lower} 缺少数值参数")
            try:
                float(args.strip())
            except ValueError as exc:
                raise ValueError(f"规则 {rule!r} 的参数必须是数字") from exc
        elif name_lower == "between":
            nums = [a.strip() for a in args.split(",")] if sep else []
            if len(nums) != 2:
                raise ValueError(f"规则 {rule!r} 需要恰好两个数值参数（例如 between:1,10）")
            try:
                lo, hi = float(nums[0]), float(nums[1])
            except ValueError as exc:
                raise ValueError(f"规则 {rule!r} 的参数必须是数字") from exc
            if lo > hi:
                raise ValueError(f"规则 {rule!r} 下界不能大于上界")
        elif name_lower in ("in", "not_in", "starts_with", "ends_with"):
            if not sep or not args:
                raise ValueError(f"规则 {name_lower} 缺少参数列表")

    return cleaned


def _strip_regex_delimiters(pattern: str) -> str:
    """Convert Laravel ``/.../`` (with optional flags) to a plain regex.

    Laravel passes the raw string to PHP ``preg_match``, which expects a
    delimited pattern. PCRE flags (``i``, ``m``, ``s``, ``u``, ``x``) after
    the closing delimiter are converted to inline flags ``(?i)`` etc. so
    Python ``re`` can use them.
    """
    if len(pattern) >= 2 and pattern[0] == pattern[-1] and pattern[0] in "/#~":
        return pattern[1:-1]
    if len(pattern) >= 2 and pattern[0] == "/":
        # has trailing flags
        last_slash = pattern.rfind("/")
        if last_slash > 0:
            body = pattern[1:last_slash]
            flags = pattern[last_slash + 1 :]
            inline = ""
            for f in flags:
                if f in "imsxu":
                    inline += f
            if inline:
                return f"(?{inline}){body}"
            return body
    return pattern


def _to_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _as_digits_str(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value
    return None


def _validate_one(env_variable: str, value: Any, rule: str, *, numeric_context: bool = False) -> None:
    """Validate ``value`` against a single rule. Raises EggValidationError on failure.

    ``numeric_context`` controls how ``max``/``min``/``between`` interpret the
    value: when True, compare numerically; when False, compare by string
    length (Laravel ``size`` semantics).
    """
    name, _, args = rule.partition(":")
    name = name.strip().lower()
    args_list = [a for a in args.split(",")] if args else []

    # Treat Python None and empty string equivalently to Laravel "missing"
    is_empty = value is None or value == ""

    if name == "required":
        if is_empty:
            raise EggValidationError(env_variable, rule, "必填")
        return
    if name == "nullable":
        # Just a marker — short-circuit: subsequent rules skip if empty
        return
    if name == "sometimes":
        return

    # All rules below are skipped if value is empty AND no `required` rule
    # is enforcing presence (Laravel semantics)
    if is_empty:
        return

    if name == "string":
        if not isinstance(value, str):
            raise EggValidationError(env_variable, rule, "必须是字符串")
        return
    if name == "numeric":
        if _to_number(value) is None:
            raise EggValidationError(env_variable, rule, "必须是数字")
        return
    if name == "integer":
        if isinstance(value, bool):
            raise EggValidationError(env_variable, rule, "必须是整数")
        if isinstance(value, int):
            return
        if isinstance(value, str) and re.match(r"^-?\d+$", value):
            return
        raise EggValidationError(env_variable, rule, "必须是整数")
    if name == "boolean":
        if value in _BOOLEAN_TRUE or value in _BOOLEAN_FALSE:
            return
        raise EggValidationError(env_variable, rule, "必须是布尔值")
    if name == "in":
        if str(value) not in args_list:
            raise EggValidationError(env_variable, rule, f"必须是 {args_list} 之一")
        return
    if name == "not_in":
        if str(value) in args_list:
            raise EggValidationError(env_variable, rule, f"不能是 {args_list} 中任一")
        return
    if name == "max":
        if not args_list:
            return
        bound = float(args_list[0])
        if numeric_context:
            num = _to_number(value)
            if num is not None and num > bound:
                raise EggValidationError(env_variable, rule, f"不能大于 {bound}")
        else:
            if isinstance(value, str) and len(value) > bound:
                raise EggValidationError(env_variable, rule, f"长度不能超过 {int(bound)}")
        return
    if name == "min":
        if not args_list:
            return
        bound = float(args_list[0])
        if numeric_context:
            num = _to_number(value)
            if num is not None and num < bound:
                raise EggValidationError(env_variable, rule, f"不能小于 {bound}")
        else:
            if isinstance(value, str) and len(value) < bound:
                raise EggValidationError(env_variable, rule, f"长度不能小于 {int(bound)}")
        return
    if name == "between":
        if len(args_list) < 2:
            return
        lo = float(args_list[0])
        hi = float(args_list[1])
        if numeric_context:
            n = _to_number(value)
            if n is None:
                return
        else:
            n = len(value) if isinstance(value, str) else 0
        if not (lo <= n <= hi):
            raise EggValidationError(env_variable, rule, f"必须在 {lo}~{hi} 之间")
        return
    if name == "size":
        # Laravel: numeric/integer → exact value; string → exact length;
        # array → exact count; file → exact KB. We support number + string.
        if not args_list:
            return
        target = float(args_list[0])
        if numeric_context:
            n = _to_number(value)
            if n is None or n != target:
                raise EggValidationError(env_variable, rule, f"必须等于 {target}")
        else:
            length = len(value) if isinstance(value, str) else 0
            if length != int(target):
                raise EggValidationError(
                    env_variable, rule, f"长度必须正好是 {int(target)}"
                )
        return
    if name == "alpha_num":
        if not isinstance(value, str) or not _ALPHA_NUM_RE.match(value):
            raise EggValidationError(env_variable, rule, "只能包含字母和数字")
        return
    if name == "alpha_dash":
        if not isinstance(value, str) or not _ALPHA_DASH_RE.match(value):
            raise EggValidationError(env_variable, rule, "只能包含字母数字、下划线和短横线")
        return
    if name == "url":
        if not isinstance(value, str):
            raise EggValidationError(env_variable, rule, "必须是有效 URL")
        try:
            parsed = urlparse(value)
        except ValueError as exc:
            raise EggValidationError(env_variable, rule, "必须是有效 URL") from exc
        if not parsed.scheme or not parsed.netloc:
            raise EggValidationError(env_variable, rule, "必须是有效 URL")
        return
    if name == "email":
        if not isinstance(value, str) or not _EMAIL_RE.match(value):
            raise EggValidationError(env_variable, rule, "必须是有效邮箱")
        return
    if name == "starts_with":
        if not isinstance(value, str) or not any(value.startswith(a) for a in args_list):
            raise EggValidationError(env_variable, rule, f"必须以 {args_list} 中之一开头")
        return
    if name == "ends_with":
        if not isinstance(value, str) or not any(value.endswith(a) for a in args_list):
            raise EggValidationError(env_variable, rule, f"必须以 {args_list} 中之一结尾")
        return
    if name == "regex":
        try:
            pattern = _strip_regex_delimiters(args)
            if not re.search(pattern, str(value)):
                raise EggValidationError(env_variable, rule, "格式不匹配")
        except re.error as exc:
            raise EggValidationError(env_variable, rule, f"无效正则: {exc}") from exc
        return
    if name == "not_regex":
        try:
            pattern = _strip_regex_delimiters(args)
            if re.search(pattern, str(value)):
                raise EggValidationError(env_variable, rule, "格式不能匹配")
        except re.error as exc:
            raise EggValidationError(env_variable, rule, f"无效正则: {exc}") from exc
        return
    if name == "digits":
        if not args_list:
            return
        n = int(args_list[0].strip())
        digits_text = _as_digits_str(value)
        if digits_text is None or not _DIGITS_RE.match(digits_text) or len(digits_text) != n:
            raise EggValidationError(env_variable, rule, f"必须是 {n} 位数字")
        return
    if name == "min_digits":
        if not args_list:
            return
        n = int(args_list[0].strip())
        digits_text = _as_digits_str(value)
        if digits_text is None or not _DIGITS_RE.match(digits_text) or len(digits_text) < n:
            raise EggValidationError(env_variable, rule, f"至少需要 {n} 位数字")
        return
    if name == "max_digits":
        if not args_list:
            return
        n = int(args_list[0].strip())
        digits_text = _as_digits_str(value)
        if digits_text is None or not _DIGITS_RE.match(digits_text) or len(digits_text) > n:
            raise EggValidationError(env_variable, rule, f"最多只能有 {n} 位数字")
        return
    if name == "digits_between":
        if len(args_list) < 2:
            return
        lo = int(args_list[0].strip())
        hi = int(args_list[1].strip())
        digits_text = _as_digits_str(value)
        if (
            digits_text is None
            or not _DIGITS_RE.match(digits_text)
            or not (lo <= len(digits_text) <= hi)
        ):
            raise EggValidationError(env_variable, rule, f"必须是 {lo}~{hi} 位数字")
        return
    if name == "ip":
        try:
            ipaddress.ip_address(str(value))
        except ValueError as exc:
            raise EggValidationError(env_variable, rule, "必须是有效 IP 地址") from exc
        return
    if name == "uuid":
        try:
            _uuid.UUID(str(value))
        except (ValueError, AttributeError) as exc:
            raise EggValidationError(env_variable, rule, "必须是有效 UUID") from exc
        return

    # Unknown rule → log a warning and fail-open. Laravel itself would raise
    # an internal error here, but we'd rather let Wings catch a bad value
    # than block all creates because of a custom egg rule we haven't
    # implemented yet. The warning surfaces unsupported rules in production
    # so we can extend this validator.
    logger.warning(
        "egg_validator: unsupported rule %r for variable %s — value passed through",
        rule, env_variable,
    )


def validate_environment(
    env_variable: str,
    value: Any,
    rules: str | None,
) -> None:
    """Validate a single environment variable value against its rule string.

    Raises ``EggValidationError`` on failure. ``rules=None`` is a no-op.
    """
    if not rules:
        return

    parts = _split_rules(rules)

    # Special case: if the rule list contains `nullable` (or `sometimes`)
    # without `required`, an empty value is allowed. We surface that by
    # short-circuiting all subsequent type/format rules in `_validate_one`.
    rule_names_lower = {p.partition(":")[0].strip().lower() for p in parts}
    has_required = "required" in rule_names_lower
    numeric_context = "numeric" in rule_names_lower or "integer" in rule_names_lower
    is_empty = value is None or value == ""
    if is_empty and not has_required:
        return

    for rule in parts:
        _validate_one(env_variable, value, rule, numeric_context=numeric_context)
