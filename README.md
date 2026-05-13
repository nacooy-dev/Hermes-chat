# Hermes WebChat

一个轻量级 Web Chat 前端，通过 NATS 消息总线连接 Hermes Agent。

## 架构

```
浏览器 (Web UI)
    ↓ WebSocket
bridge.py (:6789)     ← WebSocket 服务器 + NATS 订阅者
    ↓
Hermes Agent          ← hermes chat -q "..." -Q
    ↓
bridge.py             ← 返回结果
    ↓ WebSocket
浏览器显示回复
```

## 快速开始

```bash
# 1. 安装依赖
pip install nats-py websockets

# 2. 确保 NATS 已安装
brew install nats-server

# 3. 启动
chmod +x start.sh
./start.sh
```

浏览器打开 http://localhost:18356

## 组件

| 组件 | 端口 | 说明 |
|------|------|------|
| Web UI | 18356 | 聊天界面 (静态 HTML) |
| Bridge WS | 6789 | 浏览器 WebSocket 连接点 |
| NATS | 4222 | 消息总线 |
| NATS WS | 8765 | NATS WebSocket (供其他客户端) |

## 手动启动

```bash
# 分别启动各组件
nats-server -c nats/nats.conf
python3 -m http.server 18356 -d web/
python3 bridge.py
```

## 通过 NATS 调用（供其他服务使用）

```bash
# 安装 nats CLI
brew install nats-server

# 发送请求
nats req hermes.request '{"message":"你好"}'

# 或者用 nats-python
python3 -c "
import asyncio, json
from nats.aio.client import Client as NATS

async def main():
    nc = NATS()
    await nc.connect('nats://localhost:4222')
    resp = await nc.request('hermes.request', json.dumps({'message':'你好'}).encode(), timeout=30)
    print(json.loads(resp.data))

asyncio.run(main())
"
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HERMES_MODEL` | deepseek-v4-flash | 默认模型 |
| `HERMES_PROVIDER` | sensenova | 默认 Provider |

编辑 `bridge.py` 顶部配置区可修改。