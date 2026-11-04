# SillyTavern Node 24 安装镜像

以生产安装镜像的固定摘要为基础，仅把 NodeSource 软件源从 Node 20 改为 Node 24，并升级 `nodejs` 软件包及其自带的 npm。Debian 12、原有工具、APT/npm 镜像源、代理环境变量和启动方式保持一致。Egg 中的安装脚本仍由 Panel 下发。

## 本地构建与核对

在仓库根目录执行：

```bash
docker build -t sillytavern-installer:node24 docker/sillytavern-installer
python3 docker/sillytavern-installer/verify.py sillytavern-installer:node24
```

本地下载 Node 软件包较慢时，可给构建命令添加 `--build-arg NODE_DOWNLOAD_PROXY=http://代理地址:端口`。该参数只用于构建时下载，不写入镜像的运行环境。构建只刷新 NodeSource 索引，避免无关的 Debian 软件源阻塞升级。

核对脚本检查 Node 主版本、所有其他系统软件包，以及原有的镜像启动配置和软件源配置。

## GitHub Actions 发布

工作流 `.github/workflows/docker-build.yml` 在运行镜像目录、本目录或工作流发生变更时运行，也支持手动触发。PR 只构建和验证；主分支推送及手动运行会在验证通过后发布运行镜像与安装镜像。

验证包括环境一致性，以及 SillyTavern `1.12.14` 和 `1.19.0` 的依赖安装与加载。CI 使用公网 npm 源；生产 Egg 继续使用现有的内网缓存源。

- 安装镜像：`ghcr.io/vvb7456/sillytavern-installer:latest`。
- 运行镜像：`ghcr.io/vvb7456/sillytavern-runtime:latest`。
- 使用工作流自带的 `GITHUB_TOKEN` 发布；镜像标签为 `latest`，构建提交记录在镜像标签元数据中。部署时记录实际镜像摘要。

基础镜像为现有的 `linux/amd64` 生产镜像，本工作流只发布该架构。新镜像发布后，确认 GHCR 软件包对 Wings 节点可拉取，再修改 Egg 的安装镜像地址。
