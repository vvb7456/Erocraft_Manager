# Erocraft Agent V2

节点侧管理代理。Manager 主动 Pull 监控数据 + Push 命令，与 Panel↔Wings 同模式。

## 架构

详见 `docs/MONITORING_AND_AGENT.md`（合并自原 `MONITORING_DESIGN.md` 与 `AGENT_V2_ARCHITECTURE.md`，两份原稿现归档于 `docs/_archive/`）。

## 安装（节点机器）

```bash
sudo mkdir -p /opt/erocraft-agent
cd /opt/erocraft-agent
python3 -m venv venv
venv/bin/pip install fastapi uvicorn[standard] httpx psutil pyyaml pydantic
# 拷贝 agent/ 目录到 /opt/erocraft-agent/agent/
sudo cp /path/to/agent/config.example.yaml ./agent.yaml
sudo $EDITOR ./agent.yaml          # 配置 token / wings.config_path

# 测试
venv/bin/python -m agent.agent ./agent.yaml

# systemd
sudo cp agent/erocraft-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now erocraft-agent
```

## 端点

| 路径 | 鉴权 | 用途 |
|---|---|---|
| `GET /healthz` | 否 | 存活探测 |
| `GET /v1/metrics` | Bearer | 全量指标快照 |
| `GET /v1/wings/config` | Bearer | wings 配置摘要（脱敏）|
| `POST /v1/commands` | Bearer | 同步执行命令（Phase 1 仅 ping）|
| `GET /v1/status` | Bearer | agent 自身状态 |

## 配置

见 [config.example.yaml](config.example.yaml)。
# Erocraft Monitoring Agent
# 
# Dependencies: psutil httpx pyyaml
#
# Deploy to /opt/erocraft-agent/ on each Wings node host.
# See config.example.yaml for configuration.
