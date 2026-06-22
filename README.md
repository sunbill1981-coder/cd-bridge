# cd-bridge

让 Claude Desktop 使用任意 OpenAI 兼容模型的本地代理。绕开 Gateway 模型名校验。

```
Claude Desktop  →  proxy:3099  →  oMLX (localhost:8000)     — 本地
                               └→  任意 OpenAI 兼容 API      — 云端
```

## 为什么需要它？

Claude Desktop 的第三方推理（Gateway）模式会校验模型名，只认 `claude-sonnet-4-6`、`claude-opus-4-7` 等官方 ID，无法直接使用其他模型。

`cd-bridge` 在中间层代理请求：用官方模型名通过校验，实际路由到你要用的模型。

## 工作原理

| 接口 | 行为 |
|---|---|
| `GET /v1/models` | 返回 Anthropic 模型 ID（通过 Gateway 校验） |
| `POST /v1/messages` | 按模型名路由到本地 oMLX 或云端服务商 |
| `POST /_admin/switch` | 运行时切换模型（无需重启） |
| `GET /_admin/status` | 返回代理状态和当前模型 |

**本地模型**：名称不含 `/` → 原样转发到 `localhost:8000`，响应以 SSE 流透传。

**云端模型**：格式为 `服务商/模型名`（如 `sensenova/deepseek-v4`）→ 翻译为 OpenAI Chat Completions 格式，调用服务商 API，结果翻译回 Anthropic 格式。

## 系统要求

- **macOS** 14+
- **Claude Desktop**（已配置第三方推理）
- **Node.js**
- **oMLX**（可选，仅本地模型需要）

## 快速开始

```bash
git clone <本仓库> && cd cd-bridge
./cd-bridge.sh configure              # 配置凭据
./cd-bridge.sh wizard                 # 交互式菜单
```

或直接用命令行：

```bash
./cd-bridge.sh                                    # 启动代理 + Claude Desktop
./cd-bridge.sh add-provider                       # 添加云端服务商
./cd-bridge.sh list-models                        # 列出可用模型
./cd-bridge.sh switch sensenova/deepseek-v4-flash # 切换模型
./cd-bridge.sh status                             # 查看状态
```

### 首次配置 Claude Desktop（只需一次）

1. **Claude → Developer → Configure Third-Party Inference**
2. 连接方式：**Gateway**
3. Gateway 地址：`http://127.0.0.1:3099`
4. Gateway API Key：`proxy`
5. 认证方式：**bearer**
6. 点击 Apply locally → Relaunch now

## 文件说明

| 文件 | 作用 |
|---|---|
| `proxy.js` | 代理服务（Node.js，零 npm 依赖） |
| `cd-bridge.sh` | CLI 启动器 + 命令入口 |
| `wizard.py` | 交互式菜单（通过 `wizard` 命令启动） |

## 配置文件

所有凭据存在 `~/.cd-bridge/config.json`：

```json
{
  "omlx_key": "你的 oMLX 密钥",
  "omlx_model": "Qwen3-Coder-Next-4bit",
  "proxy_port": 3099,
  "providers": [
    {
      "name": "sensenova",
      "api_key": "sk-xxx",
      "base_url": "https://token.sensenova.cn/v1"
    }
  ]
}
```

环境变量优先级高于配置文件：`OMLX_KEY`、`OMLX_MODEL`、`PROXY_PORT`、`OMLX_PORT`。

## 命令列表

| 命令 | 作用 |
|---|---|
| _（无参数）_ | 启动代理（如果未运行）+ 打开 Claude Desktop |
| `wizard` | 交互式菜单（↑↓ 选择，Enter 确认，Esc 返回） |
| `configure` | 交互式配置 oMLX 密钥和模型 |
| `add-provider` | 添加云端服务商 |
| `remove-provider <名称>` | 移除云端服务商 |
| `list-providers` | 列出已配置的云端服务商 |
| `install` | 安装到系统（含 launchd 开机自启） |
| `uninstall` | 卸载并清除所有文件 |
| `list` / `list-models` | 列出本地和云端可用模型 |
| `switch <模型名>` | 切换模型（即时生效 + 持久化） |
| `status` | 查看代理、oMLX、开机自启状态 |
| `proxy` | 后台启动代理服务 |
| `proxy-stop` | 停止代理服务 |

## 模型命名规则

- **本地模型**：名称不含 `/`，如 `Qwen3-Coder-Next-4bit`
- **云端模型**：`服务商名/模型名`，如 `sensenova/deepseek-v4-flash`

代理根据名称自动判断后端：包含 `/` → 云端，否则 → 本地。

## 默认端口

| 服务 | 默认端口 | 可通过以下方式修改 |
|---|---|---|
| 代理 | `3099` | 环境变量 `PROXY_PORT` 或 `config.json` 的 `proxy_port` |
| oMLX | `8000` | 环境变量 `OMLX_PORT` 或 `config.json` 的 `omlx_port` |

## 协议

MIT
