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

## 完整使用流程（wizard 向导版）

以下从下载项目开始，一步步完成从配置到使用的全过程。

### 第一步：下载项目

```bash
git clone https://github.com/sunbill1981-coder/cd-bridge
cd cd-bridge
```

### 第二步：启动向导

```bash
./cd-bridge.sh wizard
```

进入主菜单，你会看到：

```
  ┌────────────────────────────────────────────────────────┐
  │  Claude Bridge Wizard            ↑↓ Enter Esc 返回     │
  └────────────────────────────────────────────────────────┘

  主菜单

  ○  查看状态
  ○  列出可用模型
  ○  切换模型
  ○  启动/重启 Claude Desktop
  ○  设置
  ○  帮助
  ○  退出

  ↑↓ 选择  Enter 确认  q/Esc 退出
```

### 第三步：配置凭据

在主菜单选择 **设置 → 配置模型**，进入模型管理菜单：

```
  模型管理

  ○  配置本地后端 (oMLX)
  ○  添加云端服务商
  ○  移除云端服务商
  ○  查看云端服务商
  ○  返回主菜单
```

**如果你有云端 API（如 DeepSeek、智谱等）：**

选择 **添加云端服务商**，依次输入：
- 名称：`sensenova`（或其他自定义名称）
- Base URL：`https://token.sensenova.cn/v1`（服务商 API 地址）
- API Key：你的密钥

**如果你使用本地 oMLX 模型：**

选择 **配置本地后端 (oMLX)**，输入 oMLX API Key 和默认模型名。

### 第四步：配置 Claude Desktop（只需一次）

这一步在 Claude Desktop 应用内操作，**不是**在向导内：

1. 打开 **Claude Desktop**
2. **Claude → Developer → Configure Third-Party Inference**
3. 连接方式：选择 **Gateway**
4. Gateway 地址：输入 `http://127.0.0.1:3099`
5. Gateway API Key：输入 `proxy`
6. 认证方式：选择 **bearer**
7. 点击 **Apply locally** → **Relaunch now**

### 第五步：启动代理

回到向导主菜单，选择 **设置 → 代理 → 启动**。

启动成功后，菜单中会显示代理状态为 `● 运行中`。

### 第六步：切换模型

在主菜单选择 **切换模型**，向导会扫描可用的本地和云端模型：

```
  切换模型
  当前: sensenova/deepseek-v4-flash (云端)

  本地模型 (oMLX)
  ○  🖥  Qwen3-Coder-Next-4bit
  ○  🖥  deepseek-v4-flash

  云端模型 (sensenova)
  ○  ☁️  sensenova/deepseek-v4-flash
  ○  ☁️  sensenova/deepseek-v4

  ↑↓ 选择  Enter 切换  Esc 返回
```

选择你要用的模型，回车确认即可切换（即时生效，无需重启）。

### 第七步：启动 Claude Desktop

在主菜单选择 **启动/重启 Claude Desktop**，Claude Desktop 会自动打开。

现在你可以像平常一样使用 Claude，但实际后端已切换到你所选的模型。

### 后续使用流程

以后只需两步：

```bash
cd cd-bridge
./cd-bridge.sh wizard
```

然后在向导中：
1. **设置 → 代理 → 启动**（启动代理）
2. **启动/重启 Claude Desktop**（打开 Claude）

或一步到位（命令行模式）：

```bash
./cd-bridge.sh                                    # 启动代理 + 打开 Claude Desktop
```

---

## 命令行速查（免向导）

```bash
./cd-bridge.sh                                    # 启动代理 + Claude Desktop
./cd-bridge.sh wizard                             # 交互式菜单（推荐新手）
./cd-bridge.sh configure                          # 配置 oMLX 凭据
./cd-bridge.sh add-provider                       # 添加云端服务商
./cd-bridge.sh list-models                        # 列出可用模型
./cd-bridge.sh switch sensenova/deepseek-v4-flash # 切换模型
./cd-bridge.sh status                             # 查看全链路状态
./cd-bridge.sh proxy                              # 仅启动后台代理
./cd-bridge.sh proxy-stop                         # 停止代理
./cd-bridge.sh install                            # 安装到系统（开机自启）
./cd-bridge.sh uninstall                          # 卸载
```

## 文件说明

| 文件 | 作用 |
|---|---|
| `proxy.js` | 代理服务（Node.js，零 npm 依赖） |
| `cd-bridge.sh` | CLI 启动器 + 命令入口 |
| `wizard.py` | 交互式菜单（通过 `wizard` 命令启动） |

## 配置文件

所有凭据存在 `~/.claude-bridge/config.json`：

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

## 已知限制

- **仅验证环境**：目前仅在 **Apple M 系列芯片 macOS** + **oMLX** 后端下验证通过。其他平台（Intel Mac、Linux、Windows）或其他后端（如 Ollama、LM Studio）未经测试，可能存在兼容性问题。
- **非流式响应**：云端模型请求暂未支持 SSE 流式输出，响应采用完整 JSON 返回。
- **零 npm 依赖**：`proxy.js` 使用 Node.js 内置模块，无需 `npm install`。

## 协议

MIT
