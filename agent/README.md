# Erocraft Agent V2

节点侧管理代理。Manager 主动拉取监控数据（Pull）并下发控制命令（Push），与 Panel↔Wings 采用相同的通信模式。

## 安装（节点机器）

运行目录约定为 `/opt/erocraft-agent`（或使用 `scripts/deploy/deploy-agent.sh` 自动拉取发布包部署）：

```bash
sudo mkdir -p /opt/erocraft-agent
cd /opt/erocraft-agent
python3 -m venv venv
venv/bin/pip install -r /path/to/erocraft_manager/agent/requirements.txt
sudo cp -r /path/to/erocraft_manager/agent ./agent
sudo cp agent/config.example.yaml ./agent.yaml
sudo $EDITOR ./agent.yaml          # 配置 role / bind / token / wings / cert_install_targets

# 测试运行
venv/bin/python -m agent.agent ./agent.yaml

# 注册 systemd 服务
sudo cp agent/erocraft-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now erocraft-agent
```

## HTTP 端点

除 `/healthz` 外，所有接口均要求 `Authorization: Bearer <token>` 鉴权；`/v1/wings/*` 仅在 `role=wings_node` 时注册：

| 路径 | 鉴权 | 用途 |
|---|---|---|
| `GET /healthz` | 否 | 存活探测 |
| `GET /v1/status` | Bearer | Agent 版本、角色与支持的能力集（capabilities） |
| `GET /v1/metrics` | Bearer | 主机指标（CPU / 内存 / 磁盘 / 网络 / 容器汇总）与探针快照 |
| `GET /v1/cert/status` | Bearer | Wings 证书路径、命名证书目标及 Agent 自身监听证书状态 |
| `POST /v1/commands` | Bearer | 同步执行控制命令（`ping`、`cert.install`、`wings.restart` 等） |
| `GET /v1/wings/config` | Bearer | Wings 配置摘要（脱敏） |
| `GET /v1/wings/service` | Bearer | Wings systemd 服务状态 |
| `GET /v1/wings/logs/stream` | Bearer | Wings 实时日志流（SSE） |

## 配置与采集说明

完整配置项示例见 [config.example.yaml](config.example.yaml)。

- **容器环境兼容**：当 Agent 运行在容器（如 LXC / Docker）内时，内核暴露的 Load Average 与 `/proc/diskstats` 属于宿主机全局数据，不能代表当前容器。Agent 检测到容器环境后会将 `load_avg` 返回为空列表、整机磁盘读写速率返回为 `null`；CPU 核数使用当前进程实际允许调度的核心数（`sched_getaffinity`）。
