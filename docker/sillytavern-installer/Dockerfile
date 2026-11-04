# 固定生产安装镜像，保留 Debian、工具包及 npm/代理配置，仅升级 Node.js。
FROM registry.cn-hangzhou.aliyuncs.com/erocraft/sillytavern-installer@sha256:138e01a1213aac762788e00ec297a98fcb5a656ef3e52d0f5e96c6985a76e83f

ARG NODE_DOWNLOAD_PROXY

# 先下载再替换 Node 包，避免 overlay2/ZFS 为旧头文件逐个创建备份时极慢。
RUN sed -i 's|node_20.x|node_24.x|' /etc/apt/sources.list.d/nodesource.list \
    && apt-get -o Dir::Etc::sourcelist=/etc/apt/sources.list.d/nodesource.list \
        -o Dir::Etc::sourceparts=- -o Acquire::https::Proxy="${NODE_DOWNLOAD_PROXY:-DIRECT}" \
        -o Acquire::https::Timeout=30 -o Acquire::Retries=1 update \
    && apt-get -o Acquire::https::Proxy="${NODE_DOWNLOAD_PROXY:-DIRECT}" \
        -o Acquire::https::Timeout=30 -o Acquire::Retries=1 install -y --download-only --only-upgrade nodejs \
    && dpkg --remove nodejs \
    && dpkg --install /var/cache/apt/archives/nodejs_*.deb \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
