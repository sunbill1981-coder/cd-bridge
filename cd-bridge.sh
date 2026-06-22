#!/bin/bash
# cd-bridge — Claude Desktop 本地/云端模型代理
# Usage: ./cd-bridge.sh [command]

set -euo pipefail

# ── Config: ~/.cd-bridge/config.json ──────────────

_CONFIG_FILE="$HOME/.cd-bridge/config.json"

_cfg() {
  [ -f "$_CONFIG_FILE" ] && python3 -c "
import json,sys
c = json.load(open('$_CONFIG_FILE'))
print(c.get(sys.argv[1],'') or '')
" "$1" 2>/dev/null || true
}

# ── Credentials (config.json → env var) ──

OMLX_KEY="${OMLX_KEY:-$(_cfg omlx_key)}"
OMLX_MODEL="${OMLX_MODEL:-$(_cfg omlx_model)}"

# Ports
PROXY_PORT="${PROXY_PORT:-$(_cfg proxy_port)}"
: "${PROXY_PORT:=3099}"
OMLX_PORT="${OMLX_PORT:-$(_cfg omlx_port)}"
: "${OMLX_PORT:=8000}"
# ── Config ─────────────────────────────────────────

MODEL="${OMLX_MODEL:-}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
_CD_BRIDGE_DIR="${HOME}/.cd-bridge"
_PROXY_JS="$SCRIPT_DIR/proxy.js"
_LOG_DIR="$_CD_BRIDGE_DIR"
if [ ! -f "$_PROXY_JS" ] && [ -f "$_CD_BRIDGE_DIR/proxy.js" ]; then
  _PROXY_JS="$_CD_BRIDGE_DIR/proxy.js"
fi

# ── Helpers ────────────────────────────────────────

_is_cloud_model() {
  [[ "$1" == */* ]] || [[ "$1" =~ ^sensenova ]]
}

_get_provider_name() {
  # sensenova-deepseek-v4-flash → sensenova
  if [[ "$1" =~ ^sensenova ]]; then
    echo "sensenova"
    return
  fi
  echo "${1%%/*}"
}

_get_cloud_model_name() {
  local m="$1"
  # sensenova-deepseek-v4-flash → deepseek-v4-flash
  if [[ "$m" =~ ^sensenova- ]]; then
    case "$m" in
      sensenova-6.7-flash-lite|sensenova-u1-fast) echo "$m" ;;
      *) echo "${m#sensenova-}" ;;
    esac
    return
  fi
  echo "${m#*/}"
}

_read_providers() {
  [ -f "$_CONFIG_FILE" ] && python3 -c "
import json, sys
c = json.load(open('$_CONFIG_FILE'))
provs = c.get('providers', [])
if not provs and c.get('sensenova_key'):  # 旧格式迁移
    provs = [{'name': 'sensenova', 'api_key': c['sensenova_key'], 'base_url': c.get('sensenova_base_url','https://token.sensenova.cn/v1')}]
    c['providers'] = provs
    c.pop('sensenova_key', None)
    c.pop('sensenova_base_url', None)
    json.dump(c, open('$_CONFIG_FILE','w'), indent=2, ensure_ascii=False)
print(json.dumps(provs))
" 2>/dev/null || echo "[]"
}

_get_provider_field() {
  local prov_name="$1" field="$2"
  python3 -c "
import json, sys
provs = json.load(sys.stdin)
for p in provs:
    if p.get('name') == '$prov_name':
        print(p.get('$field', '') or '')
        break
" <<< "$(_read_providers)" 2>/dev/null || true
}

check_omlx() {
  if ! curl -sf -H "x-api-key: $OMLX_KEY" "http://localhost:$OMLX_PORT/v1/models" > /dev/null 2>&1; then
    echo "✗ oMLX 未运行，请先启动 oMLX App" >&2
    return 1
  fi
}

check_proxy() {
  curl -sf "http://127.0.0.1:$PROXY_PORT/_admin/status" > /dev/null 2>&1
}

# ── Commands ───────────────────────────────────────

list_models() {
  echo "本地模型 (oMLX):"
  echo
  if curl -sf -H "x-api-key: $OMLX_KEY" "http://localhost:$OMLX_PORT/v1/models" > /dev/null 2>&1; then
    curl -s -H "x-api-key: $OMLX_KEY" http://localhost:$OMLX_PORT/v1/models \
      | python3 -c "
import json, sys
data = json.load(sys.stdin).get('data', [])
for m in data:
  print(f'  {m[\"id\"]}')
" 2>/dev/null
  else
    echo "  (oMLX 未运行)"
  fi

  local provs="$(_read_providers)"
  if [ "$(python3 -c "import json; print(len(json.loads('$provs')))" 2>/dev/null || echo 0)" -gt 0 ]; then
    echo
    python3 -c "
import json, urllib.request
provs = json.loads('$provs')
for p in provs:
    name = p.get('name','?')
    base = p.get('base_url','')
    key = p.get('api_key','')
    print(f'云端模型 ({name} — {base}):')
    print()
    if not key:
        print(f'  (未配置 {name} API Key)')
        continue
    try:
        req = urllib.request.Request(f\"{base.rstrip('/')}/models\", headers={'Authorization': f'Bearer {key}'})
        data = json.loads(urllib.request.urlopen(req, timeout=5).read()).get('data', [])
        for m in data:
            mid = m['id']
            print(f'  {name}/{mid}')
    except Exception as e:
        print(f'  (获取失败: {e})')
    print()
" 2>/dev/null || echo "  (获取云端模型失败)"
  else
    echo
    echo "云端模型:"
    echo "  (未配置云端服务商，运行 'configure' 添加)"
  fi
}

do_switch() {
  local target="$1"

  # 向后兼容: sensenova-deepseek-v4-flash → sensenova/deepseek-v4-flash
  if [[ "$target" =~ ^sensenova- ]]; then
    local rest="${target#sensenova-}"
    target="sensenova/$rest"
  fi

  if _is_cloud_model "$target"; then
    local pname="$(_get_provider_name "$target")"
    local pkey="$(_get_provider_field "$pname" api_key)"
    if [ -z "$pkey" ]; then
      echo "✗ 云端服务商 '$pname' 未配置，请先运行 'configure' 添加" >&2
      return 1
    fi
    echo "切换到云端模型: $target"
    MODEL="$target"
  else
    check_omlx
    if ! curl -s -H "x-api-key: $OMLX_KEY" http://localhost:$OMLX_PORT/v1/models \
      | python3 -c "import json,sys; models=[m['id'] for m in json.load(sys.stdin)['data']]; sys.exit(0 if '$target' in models else 1)" 2>/dev/null; then
      echo "✗ 模型 '$target' 不在 oMLX 列表中"
      echo "  运行 './cd-bridge.sh list-models' 查看可用模型"
      return 1
    fi
    MODEL="$target"
    echo "切换到本地模型: $MODEL"
  fi

  # 运行时切换
  if check_proxy; then
    curl -s -X POST "http://127.0.0.1:$PROXY_PORT/_admin/switch" \
      -H "Content-Type: application/json" \
      -d "{\"model\":\"$MODEL\"}" > /dev/null
    echo "✓ 已即时切换（无需重启代理）"
  fi

  # 持久化：更新 config.json 中的当前模型
  _write_cfg_omlx_model "$MODEL"

  # 持久化：更新 launchd plist
  _PLIST="$HOME/Library/LaunchAgents/com.cd-bridge.proxy.plist"
  if [ -f "$_PLIST" ]; then
    launchctl bootout gui/$(id -u)/com.cd-bridge.proxy 2>/dev/null || true
    NODE_PATH="$(command -v node)"
    cat > "$_PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.cd-bridge.proxy</string>
    <key>ProgramArguments</key>
    <array>
        <string>$NODE_PATH</string>
        <string>$_CD_BRIDGE_DIR/proxy.js</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$_CD_BRIDGE_DIR/proxy.log</string>
    <key>StandardErrorPath</key>
    <string>$_CD_BRIDGE_DIR/proxy.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>OMLX_MODEL</key>
        <string>$MODEL</string>
        <key>PROXY_PORT</key>
        <string>$PROXY_PORT</string>
    </dict>
</dict>
</plist>
EOF
    launchctl bootstrap gui/$(id -u) "$_PLIST" 2>/dev/null || true
    echo "✓ 已写入开机自启配置"
  fi

  local bt="本地"
  ! _is_cloud_model "$MODEL" || bt="云端"
  echo "当前模型: $MODEL ($bt)"
}

_write_cfg_omlx_model() {
  local model="$1"
  python3 -c "
import json
p = '$HOME/.cd-bridge/config.json'
try:
    c = json.load(open(p))
except:
    c = {}
c['omlx_model'] = '$model'
json.dump(c, open(p, 'w'), indent=2, ensure_ascii=False)
" 2>/dev/null || true
}

do_status() {
  echo "=== oMLX ==="
  if curl -sf -H "x-api-key: $OMLX_KEY" "http://localhost:$OMLX_PORT/v1/models" > /dev/null 2>&1; then
    echo "  Status: ✓ 运行中"
  else
    echo "  Status: ✗ 未运行"
  fi

  echo
  echo "=== 代理 ==="
  if check_proxy; then
    curl -s "http://127.0.0.1:$PROXY_PORT/_admin/status" \
      | python3 -c "
import json,sys
d = json.load(sys.stdin)
p = d['proxy']
print(f'  Status: ✓ 运行中')
print(f'  端口:   {p[\"port\"]}')
print(f'  类型:   {p[\"backend\"]}')
print(f'  模型:   {p[\"model\"]}')
" 2>/dev/null
  else
    echo "  Status: ✗ 未运行"
  fi

  echo
  echo "=== 开机自启 ==="
  if launchctl list com.cd-bridge.proxy &>/dev/null; then
    echo "  ✓ launchd 已注册"
  else
    echo "  ✗ 未注册"
  fi

  echo
  echo "=== 云端服务商 ==="
  local provs="$(_read_providers)"
  local pc="$(python3 -c "import json; print(len(json.loads('$provs')))" 2>/dev/null || echo 0)"
  if [ "$pc" -gt 0 ]; then
    python3 -c "
import json
for p in json.loads('$provs'):
    print(f'  {p[\"name\"]}  ({p.get(\"base_url\",\"?\")})')
" 2>/dev/null
  else
    echo "  (未配置)"
  fi

  echo
  echo "=== 代理文件 ==="
  echo "  proxy.js (源码目录)"

  echo
  echo "=== Claude Desktop 配置 ==="
  local cfg="$HOME/Library/Application Support/Claude-3p/configLibrary"
  if [ -d "$cfg" ]; then
    for f in "$cfg"/*.json; do
      if [ "$(basename "$f")" != "_meta.json" ]; then
        python3 -c "
import json
d = json.load(open('$f'))
print(f'  Gateway URL: {d.get(\"inferenceGatewayBaseUrl\",\"?\")}')
print(f'  模型: {[m.get(\"name\",m.get(\"labelOverride\",\"?\")) for m in d.get(\"inferenceModels\",[])]}')
" 2>/dev/null
      fi
    done
  else
    echo "  (未配置)"
  fi
}

install() {
  echo "安装 cd-bridge..."

  NODE_PATH="$(command -v node || echo /opt/homebrew/bin/node)"
  mkdir -p "$_CD_BRIDGE_DIR"
  cp -f "$SCRIPT_DIR/proxy.js" "$_CD_BRIDGE_DIR/proxy.js"
  cp -f "$SCRIPT_DIR/cd-bridge.sh" "$_CD_BRIDGE_DIR/cd-bridge.sh"

  mkdir -p "$HOME/Library/LaunchAgents"
  _PLIST="$HOME/Library/LaunchAgents/com.cd-bridge.proxy.plist"
  cat > "$_PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.cd-bridge.proxy</string>
    <key>ProgramArguments</key>
    <array>
        <string>$NODE_PATH</string>
        <string>$_CD_BRIDGE_DIR/proxy.js</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$_CD_BRIDGE_DIR/proxy.log</string>
    <key>StandardErrorPath</key>
    <string>$_CD_BRIDGE_DIR/proxy.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>OMLX_MODEL</key>
        <string>$MODEL</string>
        <key>PROXY_PORT</key>
        <string>$PROXY_PORT</string>
    </dict>
</dict>
</plist>
EOF

  launchctl bootout gui/$(id -u)/com.cd-bridge.proxy 2>/dev/null || true
  launchctl bootstrap gui/$(id -u) "$_PLIST"

  echo "✓ 已安装"
  echo ""
  echo "首次使用还需配置 Claude Desktop:"
  echo "  Developer → Configure Third-Party Inference"
  echo "  确认 URL 为 http://127.0.0.1:$PROXY_PORT"
  echo ""
  echo "可用命令:"
  echo "  ./cd-bridge.sh                 启动 Claude Desktop"
  echo "  ./cd-bridge.sh wizard          交互式向导 (↑↓ 键盘导航)"
  echo "  ./cd-bridge.sh configure       配置凭据 (API Key 等)"
  echo "  ./cd-bridge.sh add-provider    添加云端服务商"
  echo "  ./cd-bridge.sh list-providers  列出云端服务商"
  echo "  ./cd-bridge.sh list-models     列出可用模型"
  echo "  ./cd-bridge.sh switch <模型>   切换模型"
  echo "  ./cd-bridge.sh uninstall       卸载"
  echo "  ./cd-bridge.sh help            显示帮助信息"
}

uninstall() {
  echo "卸载 cd-bridge..."

  pkill -f "node.*proxy.js" 2>/dev/null || true
  launchctl bootout gui/$(id -u)/com.cd-bridge.proxy 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/com.cd-bridge.proxy.plist"
  rm -rf "$_CD_BRIDGE_DIR"

  echo "✓ 已卸载，所有文件已清除"
}

do_configure() {
  local cfg_file="$HOME/.cd-bridge/config.json"
  mkdir -p "$HOME/.cd-bridge"

  local omlx_key=""; local omlx_model=""
  if [ -f "$cfg_file" ]; then
    omlx_key="$(_cfg omlx_key)"
    omlx_model="$(_cfg omlx_model)"
  fi

  echo "配置 cd-bridge（留空则保留原值）"
  echo
  echo "── 本地后端 (oMLX) ──"
  read -p "oMLX API Key [${omlx_key:-(未设置)}]: " input
  [ -n "$input" ] && omlx_key="$input"
  read -p "oMLX 默认模型 [${omlx_model:-(未设置)}]: " input
  [ -n "$input" ] && omlx_model="$input"

  # 读取现有 providers
  local provs
  provs="$(python3 -c "
import json
p='$cfg_file'
try:
    c=json.load(open(p))
    provs=c.get('providers',[])
    if not provs and c.get('sensenova_key'):  # 旧格式迁移
        provs=[{'name':'sensenova','api_key':c['sensenova_key'],'base_url':c.get('sensenova_base_url','https://token.sensenova.cn/v1')}]
        c['providers']=provs
        c.pop('sensenova_key',None)
        c.pop('sensenova_base_url',None)
        json.dump(c, open(p,'w'), indent=2, ensure_ascii=False)
    print(json.dumps(provs))
except:
    print('[]')
" 2>/dev/null || echo '[]')"

  echo
  echo "── 云端服务商 ──"
  if [ "$(python3 -c "import json; print(len(json.loads('$provs')))" 2>/dev/null || echo 0)" -gt 0 ]; then
    python3 -c "
import json
for p in json.loads('$provs'):
    key = p.get('api_key','')
    masked = key[:4]+'****'+key[-4:] if len(key)>8 else '****'
    print(f'  {p[\"name\"]}: {masked}  ({p.get(\"base_url\",\"?\")})')
" 2>/dev/null
  else
    echo "  (暂无，可通过 add-provider 命令添加)"
  fi
  echo
  echo "可用操作: add-provider, remove-provider, list-providers"

  # 写回 config.json（保留 providers）
  cat > "$cfg_file" << CFGEOF
{
  "omlx_key": "$omlx_key",
  "omlx_model": "$omlx_model",
  "proxy_port": ${PROXY_PORT:-3099},
  "providers": $provs
}
CFGEOF

  echo
  echo "✓ 配置已保存到 ~/.cd-bridge/config.json"
}

do_add_provider() {
  local cfg_file="$HOME/.cd-bridge/config.json"
  mkdir -p "$HOME/.cd-bridge"

  echo "添加云端服务商"
  echo
  read -p "名称 (如 sensenova, nvidia): " name
  [ -z "$name" ] && echo "✗ 名称不能为空" && return 1
  read -p "API Base URL (如 https://token.sensenova.cn/v1): " base_url
  [ -z "$base_url" ] && echo "✗ Base URL 不能为空" && return 1
  read -p "API Key: " api_key
  [ -z "$api_key" ] && echo "✗ API Key 不能为空" && return 1

  python3 -c "
import json
p='$cfg_file'
try:
    c=json.load(open(p))
except:
    c={}
provs=c.get('providers',[])
# 旧格式迁移
if not provs and c.get('sensenova_key'):
    provs=[{'name':'sensenova','api_key':c['sensenova_key'],'base_url':c.get('sensenova_base_url','https://token.sensenova.cn/v1')}]
# 去重：同名覆盖
for i,pr in enumerate(provs):
    if pr['name']=='$name':
        provs[i]={'name':'$name','api_key':'$api_key','base_url':'$base_url'}
        break
else:
    provs.append({'name':'$name','api_key':'$api_key','base_url':'$base_url'})
c['providers']=provs
# 清除旧字段
c.pop('sensenova_key',None)
c.pop('sensenova_base_url',None)
json.dump(c, open(p,'w'), indent=2, ensure_ascii=False)
print(f'✓ 已添加/更新服务商: $name')
" 2>/dev/null || echo "✗ 写入失败"
}

do_remove_provider() {
  local name="$1"
  [ -z "$name" ] && echo "用法: ./cd-bridge.sh remove-provider <名称>" && return 1

  python3 -c "
import json
p='$HOME/.cd-bridge/config.json'
try:
    c=json.load(open(p))
except:
    print('✗ 配置文件不存在')
    exit(1)
provs=c.get('providers',[])
before=len(provs)
c['providers']=[pr for pr in provs if pr['name']!='$name']
if len(c['providers'])==before:
    print(f'✗ 未找到服务商: $name')
else:
    json.dump(c, open(p,'w'), indent=2, ensure_ascii=False)
    print(f'✓ 已移除服务商: $name')
" 2>/dev/null || true
}

do_list_providers() {
  local provs="$(_read_providers)"
  local count="$(python3 -c "import json; print(len(json.loads('$provs')))" 2>/dev/null || echo 0)"
  if [ "$count" -eq 0 ]; then
    echo "未配置云端服务商"
    echo "运行 './cd-bridge.sh add-provider' 添加"
    return
  fi
  echo "云端服务商:"
  python3 -c "
import json
for p in json.loads('$provs'):
    key = p.get('api_key','')
    masked = key[:4]+'****'+key[-4:] if len(key)>8 else '****'
    print(f'  {p[\"name\"]}')
    print(f'    API Key:   {masked}')
    print(f'    Base URL:  {p.get(\"base_url\",\"?\")}')
    print()
" 2>/dev/null
}

launch() {
  if ! check_proxy; then
    echo "Starting proxy..."
    mkdir -p "$_LOG_DIR"
    OMLX_MODEL="$MODEL" \
    PROXY_PORT="$PROXY_PORT" \
    nohup node "$_PROXY_JS" > "$_LOG_DIR/proxy.log" 2>&1 &
    sleep 1
  fi
  local bt="local"
  ! _is_cloud_model "$MODEL" || bt="cloud"
  echo "✓ Proxy ready ($bt backend)"

  if ! _is_cloud_model "$MODEL"; then
    if ! curl -sf -H "x-api-key: $OMLX_KEY" "http://localhost:$OMLX_PORT/v1/models" > /dev/null 2>&1; then
      echo "Starting oMLX..."
      open /Applications/oMLX.app
      sleep 3
    fi
    echo "✓ oMLX ready"
  fi

  open /Applications/Claude.app
  echo "✓ Claude Desktop launched"
}

proxy() {
  if check_proxy; then
    echo "✓ Proxy already running"
    return
  fi
  echo "Starting proxy..."
  mkdir -p "$_LOG_DIR"
  OMLX_MODEL="$MODEL" \
  PROXY_PORT="$PROXY_PORT" \
  nohup node "$_PROXY_JS" > "$_LOG_DIR/proxy.log" 2>&1 &
  sleep 1
  local bt="local"
  ! _is_cloud_model "$MODEL" || bt="cloud"
  echo "✓ Proxy started ($bt backend)"
}

proxy_stop() {
  local pid
  pid=$(lsof -ti:"$PROXY_PORT" 2>/dev/null || true)
  if [ -n "$pid" ]; then
    kill "$pid" 2>/dev/null || true
    echo "✓ Proxy stopped"
  else
    echo "Proxy not running"
  fi
}

show_help() {
  echo "cd-bridge — Claude Desktop 本地/云端模型代理"
  echo
  echo "用法: ./cd-bridge.sh [command]"
  echo
  echo "命令:"
  echo "  wizard             交互式向导 (↑↓ 键盘导航)"
  echo "  configure          配置本地凭据"
  echo "  add-provider       添加云端服务商"
  echo "  remove-provider    移除云端服务商"
  echo "  list-providers     列出云端服务商"
  echo "  install            安装到系统，注册开机自启"
  echo "  list-models        列出可用模型"
  echo "  switch <模型>      切换到指定模型"
  echo "  status             查看全链路状态"
  echo "  uninstall          卸载并清除所有文件"
  echo "  help               显示此帮助信息"
  echo
  echo "无命令              启动代理 + Claude Desktop"
  echo
  echo "示例:"
  echo "  ./cd-bridge.sh                          # 启动"
  echo "  ./cd-bridge.sh wizard                   # 交互式向导"
  echo "  ./cd-bridge.sh add-provider             # 添加云端服务商"
  echo "  ./cd-bridge.sh switch deepseek-v4-flash # 本地 oMLX 模型"
  echo "  ./cd-bridge.sh switch sensenova/deepseek-v4 # 云端模型"
  echo "  ./cd-bridge.sh status                   # 查看状态"
}

# ── Dispatch ───────────────────────────────────────

case "${1:-}" in
  wizard) exec python3 "$SCRIPT_DIR/wizard.py" ;;
  configure) do_configure ;;
  add-provider) do_add_provider ;;
  remove-provider) shift; do_remove_provider "$1" ;;
  list-providers) do_list_providers ;;
  install) install ;;
  list-models|list) list_models ;;
  switch) shift; [ $# -eq 0 ] && echo "用法: ./cd-bridge.sh switch <模型名>" && exit 1; do_switch "$1" ;;
  uninstall) uninstall ;;
  status) do_status ;;
  help|--help|-h) show_help ;;
  proxy) proxy ;;
  proxy-stop) proxy_stop ;;
  "")
    launch
    ;;
  *)
    echo "错误: 未知命令 '$1'" >&2
    echo "" >&2
    show_help >&2
    exit 1
    ;;
esac
