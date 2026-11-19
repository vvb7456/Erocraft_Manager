"""Pydantic schemas for admin Nest, Egg and EggVariable management routes."""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.egg_validator import validate_rules_syntax

RESERVED_ENV_NAMES: frozenset[str] = frozenset(
    {
        "SERVER_MEMORY",
        "SERVER_IP",
        "SERVER_PORT",
        "ENV",
        "HOME",
        "USER",
        "STARTUP",
        "SERVER_UUID",
        "UUID",
    }
)

ENV_VAR_RE = re.compile(r"^[A-Za-z0-9_]{1,191}$")


def _validate_docker_images_dict(value: dict[str, str]) -> dict[str, str]:
    if not value:
        raise ValueError("至少需要配置一个 Docker 镜像")
    cleaned: dict[str, str] = {}
    for raw_k, raw_v in value.items():
        k = str(raw_k).strip()
        v = str(raw_v).strip()
        if not k or not v:
            raise ValueError("Docker 镜像名称与镜像地址均不能为空")
        if len(v) > 191:
            raise ValueError(f"Docker 镜像地址长度不能超过 191: {v[:40]}...")
        cleaned[k] = v
    return cleaned


def _validate_json_object_str(value: str | None, field_label: str) -> str | None:
    if value is None:
        return None
    s = value.strip()
    if not s:
        return None
    try:
        parsed = json.loads(s)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_label} 必须是合法的 JSON 对象字符串: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{field_label} 必须是 JSON 对象（以 {{ 开头）")
    return s


def _clean_str_list(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    return [str(item).strip() for item in value if str(item).strip()]


# ---------------------------------------------------------------------------
# Nest schemas
# ---------------------------------------------------------------------------


class NestOut(BaseModel):
    id: int
    uuid: str
    author: str
    name: str
    description: str | None = None
    eggs_count: int = 0
    servers_count: int = 0
    created_at: str | None = None
    updated_at: str | None = None


class NestListResponse(BaseModel):
    nests: list[NestOut]


class NestCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=191)
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("预设组名称不能为空")
        return s

    @field_validator("description")
    @classmethod
    def _validate_description(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        return s or None


class NestUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=191)
    description: str | None = None

    @model_validator(mode="after")
    def _check_fields(self) -> "NestUpdateIn":
        if "name" in self.model_fields_set:
            if self.name is None or not self.name.strip():
                raise ValueError("预设组名称不能为空")
            self.name = self.name.strip()
        if "description" in self.model_fields_set and self.description is not None:
            self.description = self.description.strip() or None
        return self


# ---------------------------------------------------------------------------
# Egg Variable schemas
# ---------------------------------------------------------------------------


class EggVariableOut(BaseModel):
    id: int
    egg_id: int
    name: str
    description: str
    env_variable: str
    default_value: str
    user_viewable: bool
    user_editable: bool
    rules: str
    created_at: str | None = None
    updated_at: str | None = None


class EggVariableCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=191)
    description: str | None = ""
    env_variable: str = Field(min_length=1, max_length=191)
    default_value: str | None = ""
    user_viewable: bool = True
    user_editable: bool = True
    rules: str = Field(min_length=1)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("变量名称不能为空")
        return s

    @field_validator("env_variable")
    @classmethod
    def _validate_env_variable(cls, v: str) -> str:
        s = v.strip()
        if not ENV_VAR_RE.match(s):
            raise ValueError("环境变量名仅支持字母、数字和下划线，长度 1~191")
        if s.upper() in RESERVED_ENV_NAMES:
            raise ValueError(f"环境变量名 '{s}' 为系统保留名称，禁止使用")
        return s

    @field_validator("rules")
    @classmethod
    def _validate_rules(cls, v: str) -> str:
        return validate_rules_syntax(v)


class EggVariableUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=191)
    description: str | None = None
    env_variable: str | None = Field(default=None, max_length=191)
    default_value: str | None = None
    user_viewable: bool | None = None
    user_editable: bool | None = None
    rules: str | None = None

    @model_validator(mode="after")
    def _check_fields(self) -> "EggVariableUpdateIn":
        if "name" in self.model_fields_set:
            if self.name is None or not self.name.strip():
                raise ValueError("变量名称不能为空")
            self.name = self.name.strip()
        if "env_variable" in self.model_fields_set:
            if self.env_variable is None:
                raise ValueError("环境变量名不能为空")
            s = self.env_variable.strip()
            if not ENV_VAR_RE.match(s):
                raise ValueError("环境变量名仅支持字母、数字和下划线，长度 1~191")
            if s.upper() in RESERVED_ENV_NAMES:
                raise ValueError(f"环境变量名 '{s}' 为系统保留名称，禁止使用")
            self.env_variable = s
        if "rules" in self.model_fields_set:
            if self.rules is None:
                raise ValueError("校验规则不能为空")
            self.rules = validate_rules_syntax(self.rules)
        if "user_viewable" in self.model_fields_set and self.user_viewable is None:
            raise ValueError("user_viewable 不能为 null")
        if "user_editable" in self.model_fields_set and self.user_editable is None:
            raise ValueError("user_editable 不能为 null")
        return self


# ---------------------------------------------------------------------------
# Egg schemas
# ---------------------------------------------------------------------------


class EggRef(BaseModel):
    id: int
    name: str


class EggSummaryOut(BaseModel):
    id: int
    uuid: str
    nest_id: int
    nest_name: str
    author: str
    name: str
    description: str | None = None
    docker_images: dict[str, str] = Field(default_factory=dict)
    servers_count: int = 0
    plans_count: int = 0
    variables_count: int = 0
    created_at: str | None = None
    updated_at: str | None = None


class EggListResponse(BaseModel):
    eggs: list[EggSummaryOut]


class NestDetailOut(NestOut):
    eggs: list[EggSummaryOut] = Field(default_factory=list)


class EggEffectiveConfig(BaseModel):
    config_files: str | None = None
    config_startup: str | None = None
    config_logs: str | None = None
    config_stop: str | None = None
    features: list[str] = Field(default_factory=list)
    file_denylist: list[str] = Field(default_factory=list)


class EggEffectiveScripts(BaseModel):
    script_install: str | None = None
    script_container: str
    script_entry: str
    script_is_privileged: bool


class EggDetailOut(BaseModel):
    id: int
    uuid: str
    nest_id: int
    nest_name: str
    author: str
    name: str
    description: str | None = None
    features: list[str] | None = None
    docker_images: dict[str, str] = Field(default_factory=dict)
    file_denylist: list[str] = Field(default_factory=list)
    update_url: str | None = None
    config_files: str | None = None
    config_startup: str | None = None
    config_logs: str | None = None
    config_stop: str | None = None
    config_from: int | None = None
    startup: str | None = None
    script_container: str
    copy_script_from: int | None = None
    script_entry: str
    script_is_privileged: bool
    script_install: str | None = None
    force_outgoing_ip: bool
    created_at: str | None = None
    updated_at: str | None = None

    effective_config: EggEffectiveConfig
    effective_scripts: EggEffectiveScripts
    config_from_candidates: list[EggRef] = Field(default_factory=list)
    copy_script_from_candidates: list[EggRef] = Field(default_factory=list)
    dependent_config_eggs: list[EggRef] = Field(default_factory=list)
    dependent_script_eggs: list[EggRef] = Field(default_factory=list)
    variables: list[EggVariableOut] = Field(default_factory=list)
    servers_count: int = 0
    plans_count: int = 0
    in_special_registry: bool = False


class EggCreateIn(BaseModel):
    nest_id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=191)
    description: str | None = None
    features: list[str] | None = None
    docker_images: dict[str, str]
    file_denylist: list[str] | None = None
    update_url: str | None = None
    startup: str = Field(min_length=1)
    config_from: int | None = None
    config_stop: str | None = Field(default=None, max_length=191)
    config_startup: str | None = None
    config_logs: str | None = None
    config_files: str | None = None
    force_outgoing_ip: bool = False
    script_install: str | None = None
    script_is_privileged: bool = True
    script_container: str = Field(default="alpine:3.4", min_length=1, max_length=191)
    script_entry: str = Field(default="ash", min_length=1, max_length=191)
    copy_script_from: int | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("Egg 名称不能为空")
        return s

    @field_validator("startup")
    @classmethod
    def _validate_startup(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("启动命令不能为空")
        return s

    @field_validator("docker_images")
    @classmethod
    def _validate_images(cls, v: dict[str, str]) -> dict[str, str]:
        return _validate_docker_images_dict(v)

    @field_validator("features", "file_denylist")
    @classmethod
    def _validate_str_lists(cls, v: list[str] | None) -> list[str] | None:
        return _clean_str_list(v)

    @field_validator("script_container", "script_entry")
    @classmethod
    def _validate_script_nonempty(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("脚本容器与入口点不能为空")
        return s

    @model_validator(mode="after")
    def _validate_configs(self) -> "EggCreateIn":
        self.config_files = _validate_json_object_str(self.config_files, "config_files")
        self.config_startup = _validate_json_object_str(self.config_startup, "config_startup")
        self.config_logs = _validate_json_object_str(self.config_logs, "config_logs")
        if self.config_stop is not None:
            self.config_stop = self.config_stop.strip() or None
        if self.script_install is not None and not self.script_install.strip():
            self.script_install = None
        if self.config_from is None:
            if not self.config_stop:
                raise ValueError("未设置 config_from 时，config_stop 为必填项")
            if self.config_files is None:
                raise ValueError("未设置 config_from 时，config_files 为必填项")
            if self.config_startup is None:
                raise ValueError("未设置 config_from 时，config_startup 为必填项")
            if self.config_logs is None:
                raise ValueError("未设置 config_from 时，config_logs 为必填项")
        return self


class EggUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=191)
    description: str | None = None
    features: list[str] | None = None
    docker_images: dict[str, str] | None = None
    file_denylist: list[str] | None = None
    update_url: str | None = None
    startup: str | None = None
    config_from: int | None = None
    config_stop: str | None = Field(default=None, max_length=191)
    config_startup: str | None = None
    config_logs: str | None = None
    config_files: str | None = None
    force_outgoing_ip: bool | None = None

    @model_validator(mode="after")
    def _check_fields(self) -> "EggUpdateIn":
        if "name" in self.model_fields_set:
            if self.name is None or not self.name.strip():
                raise ValueError("Egg 名称不能为空")
            self.name = self.name.strip()
        if "startup" in self.model_fields_set:
            if self.startup is None or not self.startup.strip():
                raise ValueError("启动命令不能为空")
            self.startup = self.startup.strip()
        if "docker_images" in self.model_fields_set:
            if self.docker_images is None:
                raise ValueError("docker_images 不能为空")
            self.docker_images = _validate_docker_images_dict(self.docker_images)
        if "features" in self.model_fields_set:
            self.features = _clean_str_list(self.features)
        if "file_denylist" in self.model_fields_set:
            self.file_denylist = _clean_str_list(self.file_denylist)
        if "config_files" in self.model_fields_set:
            self.config_files = _validate_json_object_str(self.config_files, "config_files")
        if "config_startup" in self.model_fields_set:
            self.config_startup = _validate_json_object_str(self.config_startup, "config_startup")
        if "config_logs" in self.model_fields_set:
            self.config_logs = _validate_json_object_str(self.config_logs, "config_logs")
        if "config_stop" in self.model_fields_set and self.config_stop is not None:
            self.config_stop = self.config_stop.strip() or None
        if "force_outgoing_ip" in self.model_fields_set and self.force_outgoing_ip is None:
            raise ValueError("force_outgoing_ip 不能为 null")
        return self


class EggScriptsUpdateIn(BaseModel):
    script_install: str | None = None
    script_is_privileged: bool | None = None
    script_container: str | None = Field(default=None, max_length=191)
    script_entry: str | None = Field(default=None, max_length=191)
    copy_script_from: int | None = None

    @model_validator(mode="after")
    def _check_fields(self) -> "EggScriptsUpdateIn":
        if "script_install" in self.model_fields_set and self.script_install is not None:
            if not self.script_install.strip():
                self.script_install = None
        if "script_container" in self.model_fields_set:
            if self.script_container is None or not self.script_container.strip():
                raise ValueError("script_container 不能为空")
            self.script_container = self.script_container.strip()
        if "script_entry" in self.model_fields_set:
            if self.script_entry is None or not self.script_entry.strip():
                raise ValueError("script_entry 不能为空")
            self.script_entry = self.script_entry.strip()
        if "script_is_privileged" in self.model_fields_set and self.script_is_privileged is None:
            raise ValueError("script_is_privileged 不能为 null")
        return self


class AffectedPlanWarning(BaseModel):
    id: int
    code: str
    name: str
    is_active: bool
    reason: str


class EggMutationResponse(BaseModel):
    egg: EggDetailOut
    affected_plans: list[AffectedPlanWarning] = Field(default_factory=list)


class EggVariableMutationResponse(BaseModel):
    variable: EggVariableOut
    affected_plans: list[AffectedPlanWarning] = Field(default_factory=list)


class EggVariableDeleteResponse(BaseModel):
    message: str
    affected_plans: list[AffectedPlanWarning] = Field(default_factory=list)
