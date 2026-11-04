# SillyTavern Node 24 运行镜像

以生产旧运行镜像 `pterodactyl-china/yolks:nodejs_20` 的固定摘要为基础，从官方 Node 24.22.2 Alpine 镜像中复制 Node、其自带 npm、头文件及文档。沿用旧镜像的 Alpine 系统、其他工具、用户和完整启动流程。GitHub Actions 发布到：

```text
ghcr.io/vvb7456/sillytavern-runtime:latest
```

使用内存比例参数的实例可以继续使用以下命令：

```bash
node --max-old-space-size=$((${SERVER_MEMORY}*${NODE_HEAP_PCT}/100)) server.js
```

原有带空格的计算式同样支持。启动日志与旧镜像一致，先展开变量并计算内存，再显示和执行命令。

在仓库根目录构建和核对：

```bash
docker build -t sillytavern-runtime:node24 docker/sillytavern-runtime
python3 docker/sillytavern-runtime/verify.py sillytavern-runtime:node24
```

CI 核对系统软件包、Node/npm 之外的完整文件内容和权限、镜像启动配置、环境变量，并通过真实入口验证两种内存计算写法、展开后的启动日志及 Node 直接作为 PID 1 运行。
