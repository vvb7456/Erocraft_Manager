# SillyTavern Node 24 运行镜像

使用已通过生产 11 个 SillyTavern 版本启动验证的上游镜像固定摘要，保留其全部运行内容。GitHub Actions 发布到：

```text
ghcr.io/vvb7456/sillytavern-runtime:latest
```

使用内存比例参数的实例，启动命令应写为：

```bash
node --max-old-space-size=$((${SERVER_MEMORY}*${NODE_HEAP_PCT}/100)) server.js
```

计算式中的乘号两侧不能添加空格，否则上游入口脚本会把单独的乘号展开成文件名，导致启动失败。CI 会通过镜像的真实入口验证 Node 主版本和此内存参数。
