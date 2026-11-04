"""核对运行镜像只更新 Node/npm，并沿用生产镜像的完整启动方式。"""

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile


BASE = (
    "registry.cn-shanghai.aliyuncs.com/pterodactyl-china/yolks"
    "@sha256:de6af955bb8d7ec837b0760652d845b19cbd4fa0ef14bf387ba7bfb8a18b2983"
)
NODE_FILES = {
    "usr/local/bin/node",
    "usr/local/share/man/man1/node.1",
}
NODE_DIRECTORIES = (
    "usr/local/lib/node_modules/npm",
    "usr/local/include/node",
    "usr/local/share/doc/node",
)


def run(image: str, *command: str) -> str:
    return subprocess.check_output(
        ["docker", "run", "--rm", "--network", "none", "--entrypoint", command[0], image, *command[1:]],
        text=True,
    ).strip()


def config(image: str) -> dict:
    return json.loads(subprocess.check_output(["docker", "image", "inspect", image], text=True))[0]["Config"]


def filesystem(image: str) -> dict:
    container = subprocess.check_output(["docker", "create", image], text=True).strip()
    result = {}
    try:
        with subprocess.Popen(["docker", "export", container], stdout=subprocess.PIPE) as process:
            with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
                for member in archive:
                    name = member.name.removeprefix("./").rstrip("/")
                    # Docker 在每个临时容器中生成这三个文件，内容不属于镜像。
                    if name in {"etc/hostname", "etc/hosts", "etc/resolv.conf"} | NODE_FILES:
                        continue
                    if any(name == directory or name.startswith(directory + "/") for directory in NODE_DIRECTORIES):
                        continue
                    digest = None
                    if member.isfile():
                        with archive.extractfile(member) as source:
                            digest = hashlib.file_digest(source, "sha256").hexdigest()
                    result[name] = (member.type, member.mode, member.uid, member.gid, member.linkname, digest)
            if process.wait() != 0:
                raise RuntimeError(f"导出镜像文件失败：{image}")
    finally:
        subprocess.run(["docker", "rm", container], check=True, stdout=subprocess.DEVNULL)
    return result


def main() -> None:
    image = sys.argv[1]
    old, new = config(BASE), config(image)
    for key in ("User", "WorkingDir", "Entrypoint", "Cmd", "Volumes", "StopSignal", "ExposedPorts", "Healthcheck", "Shell", "OnBuild"):
        if old.get(key) != new.get(key):
            raise SystemExit(f"镜像启动配置发生额外变化：{key}")
    old_env = dict(item.split("=", 1) for item in old["Env"])
    new_env = dict(item.split("=", 1) for item in new["Env"])
    old_env.pop("NODE_VERSION")
    node_version = new_env.pop("NODE_VERSION")
    if old_env != new_env:
        raise SystemExit("除 NODE_VERSION 外的环境变量发生变化")
    if run(image, "node", "--version") != "v" + node_version or not node_version.startswith("24."):
        raise SystemExit("Node 版本与镜像配置不符")
    if sorted(run(BASE, "apk", "info", "-v").splitlines()) != sorted(run(image, "apk", "info", "-v").splitlines()):
        raise SystemExit("系统软件包发生变化")
    old_files, new_files = filesystem(BASE), filesystem(image)
    changed = sorted(name for name in old_files.keys() | new_files.keys() if old_files.get(name) != new_files.get(name))
    if changed:
        raise SystemExit("Node/npm 之外的文件发生变化：\n" + "\n".join(changed))
    print(f"运行环境核对通过：{len(new_files)} 个非 Node/npm 文件及目录、系统软件包、启动配置均与生产基线一致。")

    probe = Path(__file__).with_name("verify-startup.mjs").resolve()
    for expression in (
        "$((${SERVER_MEMORY}*${NODE_HEAP_PCT}/100))",
        "$(( ${SERVER_MEMORY} * ${NODE_HEAP_PCT} / 100 ))",
    ):
        output = subprocess.check_output([
            "docker", "run", "--rm", "--network", "none",
            "--mount", f"type=bind,source={probe},target=/home/container/verify-startup.mjs,readonly",
            "-e", "SERVER_MEMORY=512", "-e", "NODE_HEAP_PCT=80",
            "-e", f"STARTUP=node --max-old-space-size={expression} verify-startup.mjs", image,
        ], text=True)
        output = re.sub(r"\x1b\[[0-9;]*m", "", output)
        if "container@pterodactyl~ node --max-old-space-size=409 verify-startup.mjs" not in output:
            raise SystemExit("启动日志未按生产旧镜像的方式显示展开后的命令")
        print(output, end="")


if __name__ == "__main__":
    main()
