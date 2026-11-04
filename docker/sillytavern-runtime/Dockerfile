ARG NODE_IMAGE=docker.io/library/node@sha256:f89529b660b0873f0ead26a0e848a5afcd62a9820d35d9bc7b9e9d9c546f6a69
FROM ${NODE_IMAGE} AS node24

FROM registry.cn-shanghai.aliyuncs.com/pterodactyl-china/yolks@sha256:de6af955bb8d7ec837b0760652d845b19cbd4fa0ef14bf387ba7bfb8a18b2983

USER root
ENV NODE_VERSION=24.22.2

# 先移除旧 npm 和头文件，避免合并目录后残留 Node 20 的文件。
RUN rm -rf /usr/local/lib/node_modules/npm /usr/local/include/node /usr/local/share/doc/node
COPY --from=node24 /usr/local/bin/node /usr/local/bin/node
COPY --from=node24 /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
COPY --from=node24 /usr/local/include/node /usr/local/include/node
COPY --from=node24 /usr/local/share/doc/node /usr/local/share/doc/node
COPY --from=node24 /usr/local/share/man/man1/node.1 /usr/local/share/man/man1/node.1

USER container
