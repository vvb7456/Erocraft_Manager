"""核对安装镜像除 Node.js/npm 外的运行环境与生产基线一致。"""

import json
import subprocess
import sys


BASE = (
    "registry.cn-hangzhou.aliyuncs.com/erocraft/sillytavern-installer"
    "@sha256:138e01a1213aac762788e00ec297a98fcb5a656ef3e52d0f5e96c6985a76e83f"
)


def run(image: str, *command: str) -> str:
    return subprocess.check_output(
        ["docker", "run", "--rm", "--network", "none", image, *command], text=True
    ).strip()


def config(image: str) -> dict:
    return json.loads(
        subprocess.check_output(["docker", "image", "inspect", image], text=True)
    )[0]["Config"]


def packages(image: str) -> list[str]:
    output = run(image, "dpkg-query", "-W", "-f=${binary:Package}\t${Version}\n")
    return sorted(line for line in output.splitlines() if not line.startswith("nodejs\t"))


def main() -> None:
    image = sys.argv[1]
    old, new = config(BASE), config(image)
    for key in ("Env", "User", "WorkingDir", "Entrypoint", "Cmd", "Volumes", "StopSignal"):
        if old.get(key) != new.get(key):
            raise SystemExit(f"镜像配置发生额外变化：{key}")
    if packages(BASE) != packages(image):
        raise SystemExit("除 nodejs 外的系统软件包发生变化")
    for command in (
        ("cat", "/etc/os-release"),
        ("cat", "/etc/apt/sources.list"),
        ("npm", "config", "get", "registry"),
    ):
        if run(BASE, *command) != run(image, *command):
            raise SystemExit(f"基础环境发生额外变化：{' '.join(command)}")
    node = run(image, "node", "--version")
    if not node.startswith("v24."):
        raise SystemExit(f"Node.js 版本不符：{node}")
    npm = run(image, "npm", "--version")
    print(f"安装环境核对通过：Node.js {node}，npm {npm}；其他系统软件包及配置保持一致。")


if __name__ == "__main__":
    main()
