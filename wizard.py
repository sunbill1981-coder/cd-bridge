#!/usr/bin/env python3
"""
cd-bridge wizard — 键盘导航式 TUI
↑↓ 选择  Enter 确认  Esc/q 返回/退出
"""

import json
import os
import select
import shutil
import subprocess
import sys
import time
import tty
import termios
from pathlib import Path
import urllib.request

SH_PATH = Path(__file__).resolve().parent / "cd-bridge.sh"
INSTALL_DIR = Path.home() / ".cd-bridge"
CONFIG_PATH = INSTALL_DIR / "config.json"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / "com.cd-bridge.proxy.plist"

C = lambda n, s: f"\033[{n}m{s}\033[0m"
B = lambda s: C(1, s)
D = lambda s: C(2, s)
G = lambda s: C(32, s)
Y = lambda s: C(33, s)
R = lambda s: C(31, s)
CYN = lambda s: C(36, s)
HI = lambda s: f"\033[7m{s}\033[27m"


def dw(s):
    return sum(2 if 0x2e80 < ord(c) < 0x30000 else 1 for c in s)


def read_config():
    try:
        return json.loads(CONFIG_PATH.read_text())
    except:
        return {}

def write_config(d):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")

def get_providers(cfg=None):
    if cfg is None:
        cfg = read_config()
    provs = cfg.get("providers", [])
    if not provs and cfg.get("sensenova_key"):  # 旧格式迁移
        provs = [{"name": "sensenova", "api_key": cfg["sensenova_key"],
                  "base_url": cfg.get("sensenova_base_url", "https://token.sensenova.cn/v1")}]
    return provs

def env():
    e = {}
    cfg = read_config()

    e["OMLX_KEY"] = os.environ.get("OMLX_KEY", "") or cfg.get("omlx_key", "") or ""
    e["OMLX_MODEL"] = os.environ.get("OMLX_MODEL", "") or cfg.get("omlx_model", "") or ""
    e["providers"] = get_providers(cfg)

    return e

def _proxy_port():
    return int(os.environ.get("PROXY_PORT", "") or read_config().get("proxy_port", "") or 3099)

def _omlx_port():
    return int(os.environ.get("OMLX_PORT", "") or read_config().get("omlx_port", "") or 8000)

def tsize():
    try:
        return os.get_terminal_size()
    except:
        return (80, 24)


def rkey(fd):
    ch = os.read(fd, 3)
    if len(ch) >= 1 and ch[0:1] == b"\x1b":
        if ch == b"\x1b[A":
            return "UP"
        if ch == b"\x1b[B":
            return "DOWN"
        if ch == b"\x1b[C":
            return "RIGHT"
        if ch == b"\x1b[D":
            return "LEFT"
        if len(ch) == 1:
            r, _, _ = select.select([fd], [], [], 0.15)
            if r:
                m = os.read(fd, 2)
                if m == b"[A":
                    return "UP"
                if m == b"[B":
                    return "DOWN"
                if m == b"[C":
                    return "RIGHT"
                if m == b"[D":
                    return "LEFT"
        return "ESC"
    if ch in (b"\n", b"\r"):
        return "ENTER"
    if ch == b"q":
        return "Q"
    if ch == b"\x03":
        return "CTRLC"
    return ""


def run_sh(*args):
    try:
        r = subprocess.run(["bash", str(SH_PATH)] + list(args),
                           capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "(超时)"
    except Exception as e:
        return -1, "", str(e)


def proxy_running():
    try:
        return urllib.request.urlopen(f"http://127.0.0.1:{_proxy_port()}/_admin/status", timeout=2).status == 200
    except:
        return False


def omlx_running():
    k = env().get("OMLX_KEY", "")
    if not k:
        return False
    try:
        r = urllib.request.Request(f"http://127.0.0.1:{_omlx_port()}/v1/models", headers={"x-api-key": k})
        return urllib.request.urlopen(r, timeout=1).status == 200
    except:
        return False


def launchd_registered():
    return subprocess.run(["launchctl", "list", "com.cd-bridge.proxy"],
                          capture_output=True, timeout=5).returncode == 0


def is_installed():
    return INSTALL_DIR.exists() and (INSTALL_DIR / "proxy.js").exists() and launchd_registered()


def proxy_status_str():
    if not proxy_running():
        return R("● 已停止")
    d = env()
    try:
        r = urllib.request.urlopen(f"http://127.0.0.1:{_proxy_port()}/_admin/status", timeout=2)
        s = json.loads(r.read())
        model = s["proxy"]["model"]
        bt = s["proxy"]["backend"]
        label = "☁️ 云端" if bt == "cloud" else "🖥 本地"
        return G("● 运行中") + f"  {label}  {B(model)}"
    except:
        return G("● 运行中")


class Wizard:
    def __init__(self):
        self.running = True

    def clear(self):
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()

    def hide(self):
        sys.stdout.write("\033[?25l")
        sys.stdout.flush()

    def show(self):
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()

    def header(self):
        w, _ = tsize()
        W = min(w - 2, 56)
        if W < 30:
            W = 30
        bar = "━" * W
        left = "  Claude Bridge Wizard  "
        right = "↑↓ Enter Esc 返回"
        pad = W - dw(left) - dw(right)
        if pad < 1:
            left = " Claude Bridge "
            right = "↑↓ Enter Esc 返回"
            pad = W - dw(left) - dw(right)
            if pad < 1:
                pad = 1
        print(f"{CYN('┏' + bar + '┓')}")
        print(f"{CYN('┃')}{B(left)}{D(right)}{' ' * pad}{CYN('┃')}")
        print(f"{CYN('┗' + bar + '┛')}")

    def wait_key(self, msg=None):
        if msg:
            print(f"\n  {D(msg)}")
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            k = rkey(fd)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        return k

    def confirm(self, msg):
        return self.wait_key(f"{Y('⚠')}  {msg}  {B('回车确认')}  {D('Esc 取消')}") == "ENTER"

    def main_screen(self):
        items = [
            ("查看状态", "status"),
            ("列出可用模型", "list"),
            ("切换模型", "switch"),
            ("启动/重启 Claude Desktop", "launch"),
            ("设置", "settings"),
            ("帮助", "help"),
            ("退出", "quit"),
        ]
        sel = 0
        while self.running:
            self.clear()
            self.header()
            print()
            print(f"  {B('主菜单')}")
            print()
            for i, (label, key) in enumerate(items):
                tag = ""
                disabled = False
                prefix = "◉" if i == sel else "○"
                line = f"  {prefix}  {label}{tag}"
                if i == sel:
                    print(f"  {HI(f'{prefix}  {label}{tag} ')}")
                elif disabled:
                    print(f"  {D(f'{prefix}  {label}{tag}')}")
                else:
                    print(f"  {prefix}  {label}{tag}")
            print()
            print(f"  {D('↑↓ 选择  Enter 确认  q/Esc 退出')}")
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                k = rkey(fd)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)

            if k == "UP":
                sel = (sel - 1) % len(items)
            elif k == "DOWN":
                sel = (sel + 1) % len(items)
            elif k == "ENTER":
                key = items[sel][1]
                if key == "quit":
                    self.running = False
                elif key == "install" and is_installed():
                    self.msg_screen("已安装到系统，无需重复操作")
                elif key == "uninstall" and not is_installed():
                    self.msg_screen("尚未安装，无法卸载")
                else:
                    self.dispatch(key)
            elif k in ("Q", "ESC", "CTRLC"):
                self.running = False

    def dispatch(self, key):
        if key == "status":
            self.status_screen()
        elif key == "switch":
            self.switch_screen()
        elif key == "list":
            self.list_screen()
        elif key == "settings":
            self.settings_screen()
        elif key == "launch":
            self.launch_screen()
        elif key == "help":
            self.help_screen()

    def mask_key(self, k):
        if len(k) <= 8:
            return "****"
        return k[:4] + "****" + k[-4:]

    def config_screen(self):
        cfg = read_config()
        provs = get_providers(cfg)
        self.clear()
        self.header()
        print()
        print(f"  {B('设置凭据')}")
        print()
        print(f"  {B('本地后端 (oMLX):')}")
        omlx_key = cfg.get("omlx_key", "")
        omlx_model = cfg.get("omlx_model", "")
        print(f"    API Key:   {self.mask_key(omlx_key) if omlx_key else D('(未设置)')}")
        print(f"    默认模型:  {omlx_model or D('(未设置)')}")
        print()
        print(f"  {B('云端服务商:')}")
        if provs:
            for p in provs:
                key = p.get("api_key", "")
                masked = self.mask_key(key) if key else D("(未设置)")
                print(f"    {p['name']}: {masked}")
                print(f"      {D(p.get('base_url', '?'))}")
        else:
            print(f"    {D('(未配置)')}")
        print()
        print(f"  代理端口: {cfg.get('proxy_port', 3099)}")
        print()
        rc = self.wait_key(f"{B('回车')} 管理凭据  {D('Esc 返回')}")
        if rc == "ENTER":
            self.config_menu()
        self.main_screen()

    def settings_screen(self):
        items = [
            ("配置模型", "config"),
            ("代理", "proxy"),
            ("安装到系统", "install"),
            ("返回主菜单", "back"),
        ]
        sel = 0
        while True:
            self.clear()
            self.header()
            inst = is_installed()
            print()
            print(f"  {B('设置')}")
            print()
            for i, (label, key) in enumerate(items):
                tag = ""
                if key == "install":
                    label = "卸载" if inst else "安装到系统"
                    tag = D(" [已安装]") if inst else G(" [未安装]")
                prefix = "◉" if i == sel else "○"
                if i == sel:
                    print(f"  {HI(f'{prefix}  {label}{tag} ')}")
                else:
                    print(f"  {prefix}  {label}{tag}")
            print()
            print(f"  {D('↑↓ 选择  Enter 确认  Esc 返回')}")
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                k = rkey(fd)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
            if k == "UP":
                sel = (sel - 1) % len(items)
            elif k == "DOWN":
                sel = (sel + 1) % len(items)
            elif k == "ENTER":
                key = items[sel][1]
                if key == "back":
                    return
                elif key == "config":
                    self.config_screen()
                    return
                elif key == "proxy":
                    self.proxy_screen()
                    return
                elif key == "install":
                    if inst:
                        self.uninstall_screen()
                    else:
                        self.install_screen()
                    return
            elif k in ("ESC", "Q"):
                return

    def config_menu(self):
        items = [
            ("配置本地后端 (oMLX)", "omlx"),
            ("添加云端服务商", "add"),
            ("移除云端服务商", "remove"),
            ("查看云端服务商", "list"),
            ("返回主菜单", "back"),
        ]
        sel = 0
        while True:
            self.clear()
            self.header()
            print()
            print(f"  {B('模型管理')}")
            print()
            for i, (label, key) in enumerate(items):
                prefix = "◉" if i == sel else "○"
                if i == sel:
                    print(f"  {HI(f'{prefix}  {label} ')}")
                else:
                    print(f"  {prefix}  {label}")
            print()
            print(f"  {D('↑↓ 选择  Enter 确认  Esc 返回')}")
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                k = rkey(fd)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
            if k == "UP":
                sel = (sel - 1) % len(items)
            elif k == "DOWN":
                sel = (sel + 1) % len(items)
            elif k == "ENTER":
                key = items[sel][1]
                if key == "back":
                    return
                elif key == "omlx":
                    self.config_edit_omlx()
                    return
                elif key == "add":
                    self.config_add_provider()
                    return
                elif key == "remove":
                    self.config_remove_provider()
                    return
                elif key == "list":
                    self.config_list_providers()
                    return
            elif k in ("ESC", "Q"):
                return

    def config_edit_omlx(self):
        cfg = read_config()
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        print()
        print("  ── 本地后端 (oMLX) ──")
        print()
        print("  " + D("Ctrl+C 取消编辑"))
        print()
        omlx_key = cfg.get("omlx_key", "")
        omlx_model = cfg.get("omlx_model", "")
        saved = False
        try:
            inp = input(f"  API Key [{omlx_key or '(未设置)'}]: ").strip()
            if inp:
                cfg["omlx_key"] = inp
            inp = input(f"  默认模型 [{omlx_model or '(未设置)'}]: ").strip()
            if inp:
                cfg["omlx_model"] = inp
            write_config(cfg)
            saved = True
        except KeyboardInterrupt:
            pass
        print()
        if saved:
            print("  ✓ 已保存")
        else:
            print("  " + D("已取消，未保存"))
        print("  " + D("按回车继续"))
        input()
        self.config_screen()

    def config_add_provider(self):
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        print()
        print("  ── 添加云端服务商 ──")
        print()
        print("  " + D("Ctrl+C 取消编辑"))
        print()
        saved = False
        try:
            name = input("  名称 (如 sensenova, nvidia): ").strip()
            base_url = input("  Base URL: ").strip()
            api_key = input("  API Key: ").strip()
            if name and base_url and api_key:
                cfg = read_config()
                provs = get_providers(cfg)
                for i, p in enumerate(provs):
                    if p["name"] == name:
                        provs[i] = {"name": name, "api_key": api_key, "base_url": base_url}
                        break
                else:
                    provs.append({"name": name, "api_key": api_key, "base_url": base_url})
                cfg["providers"] = provs
                cfg.pop("sensenova_key", None)
                cfg.pop("sensenova_base_url", None)
                write_config(cfg)
                saved = True
            else:
                print()
                print("  " + D("名称、URL、Key 都不能为空"))
        except KeyboardInterrupt:
            pass
        print()
        if saved:
            print(f"  ✓ 已添加/更新服务商: {name}")
        else:
            print("  " + D("已取消，未保存"))
        print("  " + D("按回车继续"))
        input()
        self.config_screen()

    def config_remove_provider(self):
        cfg = read_config()
        provs = get_providers(cfg)
        if not provs:
            self.msg_screen("没有已配置的云端服务商")
            return
        items = [(p['name'], p['name']) for p in provs] + [("取消", "cancel")]
        sel = 0
        while True:
            self.clear()
            self.header()
            print()
            print(f"  {B('移除云端服务商')}")
            print()
            for i, (label, key) in enumerate(items):
                prefix = "◉" if i == sel else "○"
                if i == sel:
                    print(f"  {HI(f'{prefix}  {label} ')}")
                else:
                    print(f"  {prefix}  {label}")
            print()
            print(f"  {D('↑↓ 选择  Enter 确认  Esc 返回')}")
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                k = rkey(fd)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
            if k == "UP":
                sel = (sel - 1) % len(items)
            elif k == "DOWN":
                sel = (sel + 1) % len(items)
            elif k == "ENTER":
                name = items[sel][1]
                if name == "cancel":
                    self.config_menu()
                    return
                self.clear()
                self.header()
                print()
                if self.confirm(f"移除 {B(name)}?"):
                    cfg = read_config()
                    provs = get_providers(cfg)
                    cfg["providers"] = [p for p in provs if p["name"] != name]
                    write_config(cfg)
                    self.msg_screen(f"已移除服务商: {name}")
                    return
                else:
                    self.config_menu()
                    return
            elif k in ("ESC", "Q"):
                self.config_menu()
                return

    def config_list_providers(self):
        cfg = read_config()
        provs = get_providers(cfg)
        self.clear()
        self.header()
        print()
        print(f"  {B('云端服务商列表')}")
        print()
        if provs:
            for p in provs:
                key = p.get("api_key", "")
                masked = self.mask_key(key) if key else D("(未设置)")
                print(f"  {B(p['name'])}")
                print(f"    API Key:   {masked}")
                print(f"    Base URL:  {D(p.get('base_url', '?'))}")
                print()
        else:
            print(f"  {D('(未配置云端服务商)')}")
            print()
        self.wait_key("回车返回")
        self.config_menu()

    def status_screen(self):
        self.clear()
        self.header()
        print()
        print(f"  {B('状态')}")
        print()
        p = proxy_running()
        print(f"  {'●' if p else '○'}  代理  {G('运行中') if p else R('已停止')}")
        if p:
            try:
                r = urllib.request.urlopen(f"http://127.0.0.1:{_proxy_port()}/_admin/status", timeout=2)
                d = json.loads(r.read())
                print(f"      端口:  {d['proxy']['port']}")
                print(f"      类型:  {d['proxy']['backend']}")
                print(f"      模型:  {B(d['proxy']['model'])}")
            except:
                pass
        print()
        o = omlx_running()
        print(f"  {'●' if o else '○'}  oMLX  {G('运行中') if o else R('已停止')}")
        print()
        l = launchd_registered()
        print(f"  {'●' if l else '○'}  开机自启  {G('已注册') if l else R('未注册')}")
        print()
        self.wait_key("回车返回")
        self.main_screen()

    def msg_screen(self, msg):
        self.clear()
        self.header()
        print()
        print(f"  {msg}")
        print()
        self.wait_key("回车返回")
        self.main_screen()

    def result_screen(self, title, returncode, stdout, stderr):
        self.clear()
        self.header()
        print()
        print(f"  {B(title)}")
        print()
        if returncode == 0:
            print(f"  {G('✓ 执行成功')}")
            if stdout:
                for line in stdout.strip().split("\n"):
                    print(f"    {line}")
        else:
            print(f"  {R('✗ 执行失败')}")
            for line in (stderr or stdout or "").strip().split("\n"):
                if line:
                    print(f"    {R(line)}")
        print()
        self.wait_key("回车返回")
        self.main_screen()

    def list_screen(self):
        self.clear()
        self.header()
        print()
        print(f"  {B('可用模型')}")
        print()
        e = env()
        omlx_key = e.get("OMLX_KEY", "")
        provs = e.get("providers", [])

        if omlx_key:
            print(f"  {B('本地模型 (oMLX):')}")
            print()
            try:
                r = urllib.request.Request(f"http://127.0.0.1:{_omlx_port()}/v1/models",
                                           headers={"x-api-key": omlx_key})
                data = json.loads(urllib.request.urlopen(r, timeout=3).read())
                for m in data.get("data", []):
                    print(f"    {G('🖥')}  {m['id']}")
            except:
                print(f"    {D('(oMLX 未运行)')}")
        else:
            print(f"  {B('本地模型 (oMLX):')}")
            print(f"    {D('(未配置 OMLX_KEY)')}")

        if provs:
            print()
            for p in provs:
                name = p["name"]
                base = p["base_url"]
                key = p.get("api_key", "")
                print(f"  {B(f'云端模型 ({name}):')}")
                print()
                if not key:
                    print(f"    {D('(未配置 API Key)')}")
                    continue
                try:
                    r = urllib.request.Request(f"{base.rstrip('/')}/models",
                                               headers={"Authorization": f"Bearer {key}"})
                    data = json.loads(urllib.request.urlopen(r, timeout=5).read())
                    for m in data.get("data", []):
                        print(f"    {CYN('☁️')}  {name}/{m['id']}")
                except Exception as ex:
                    print(f"    {D('(获取失败)')}  {D(str(ex))}")
                print()
        else:
            print()
            print(f"  {B('云端模型:')}")
            print(f"    {D('(未配置云端服务商)')}")
        print()
        self.wait_key("回车返回")
        self.main_screen()

    def switch_screen(self):
        self.clear()
        self.header()
        print()
        print(f"  {D('正在获取模型列表...')}")
        print()
        fd = sys.stdin.fileno()
        old_attr = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            e = env()
            omlx_key = e.get("OMLX_KEY", "")
            provs = e.get("providers", [])

            all_models = []
            all_models.append(("header", "本地模型 (oMLX)", ""))
            if omlx_key and omlx_running():
                try:
                    r = urllib.request.Request(f"http://127.0.0.1:{_omlx_port()}/v1/models",
                                               headers={"x-api-key": omlx_key})
                    data = json.loads(urllib.request.urlopen(r, timeout=3).read()).get("data", [])
                    if data:
                        for m in data:
                            all_models.append(("local", f"🖥  {m['id']}", m['id']))
                    else:
                        all_models.append(("note", D("(无可用模型)"), ""))
                except:
                    all_models.append(("note", D("(oMLX 无响应)"), ""))
            elif omlx_key and not omlx_running():
                all_models.append(("note", D("(oMLX 未运行)"), ""))
            else:
                all_models.append(("note", D("(未配置 OMLX_KEY)"), ""))

            for p in provs:
                key = p.get("api_key", "")
                base = p.get("base_url", "")
                pname = p["name"]
                if not key or not base:
                    continue
                try:
                    r = urllib.request.Request(f"{base.rstrip('/')}/models",
                                               headers={"Authorization": f"Bearer {key}"})
                    data = json.loads(urllib.request.urlopen(r, timeout=5).read()).get("data", [])
                    if data:
                        all_models.append(("header", f"云端模型 ({pname})", ""))
                        for m in data:
                            all_models.append(("cloud", f"☁️  {pname}/{m['id']}", f"{pname}/{m['id']}"))
                except:
                    pass

            if not all_models:
                termios.tcflush(fd, termios.TCIFLUSH)
                self.msg_screen("没有可用模型")
                return

            current = env().get("OMLX_MODEL", "")
            if not current:
                try:
                    import plistlib
                    with open(PLIST_PATH, "rb") as f:
                        current = plistlib.load(f).get("EnvironmentVariables", {}).get("OMLX_MODEL", "")
                except:
                    pass
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_attr)
        termios.tcflush(fd, termios.TCIFLUSH)

        sel = 0
        top = 0
        _, term_rows = tsize()
        max_visible = term_rows - 9
        if max_visible < 5:
            max_visible = 5

        while True:
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                no_echo = list(old)
                no_echo[3] = old[3] & ~termios.ECHO
                termios.tcsetattr(fd, termios.TCSADRAIN, no_echo)

                self.clear()
                self.header()
                print()
                print(f"  {B('切换模型')}")
                if current:
                    bt = "云端" if "/" in current or current.startswith("sensenova-") else "本地"
                    print(f"  {D('当前:')} {B(current)}  {D(f'({bt})')}")
                print()
                if sel < top:
                    top = sel
                if sel >= top + max_visible:
                    top = sel - max_visible + 1
                visible = all_models[top:top + max_visible]
                for i, item in enumerate(visible):
                    idx = top + i
                    mtype, display, raw = item
                    if mtype == "header":
                        print(f"  {B(display)}")
                    elif mtype == "note":
                        print(f"  {display}")
                    else:
                        mark = "◉" if raw == current else "○"
                        if idx == sel:
                            print(f"  {HI(f'{mark}  {display} ')}")
                        else:
                            print(f"  {mark}  {display}")
                if top + max_visible < len(all_models):
                    print(f"  {D('… 更多模型 …')}")
                print()
                print(f"  {D('↑↓ 选择  Enter 切换  Esc 返回')}")

                tty.setraw(fd)
                k = rkey(fd)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
            if k == "UP":
                sel = (sel - 1) % len(all_models)
                while all_models[sel][0] in ("header", "note"):
                    sel = (sel - 1) % len(all_models)
            elif k == "DOWN":
                sel = (sel + 1) % len(all_models)
                while all_models[sel][0] in ("header", "note"):
                    sel = (sel + 1) % len(all_models)
            elif k == "ENTER":
                target = all_models[sel]
                model_name = target[2]
                if model_name == current:
                    termios.tcflush(fd, termios.TCIFLUSH)
                    self.msg_screen(f"已经是 {model_name}")
                    return
                self.clear()
                self.header()
                print()
                print(f"  {B('切换模型')}")
                print()
                if self.confirm(f"切换到 {B(model_name)}?"):
                    rc, out, err = run_sh("switch", model_name)
                    if rc == 0:
                        current = model_name
                        termios.tcflush(fd, termios.TCIFLUSH)
                        self.result_screen("切换结果", rc, out, err)
                    else:
                        termios.tcflush(fd, termios.TCIFLUSH)
                        self.result_screen("切换结果", rc, out, err)
                    return
            elif k in ("ESC", "Q"):
                termios.tcflush(fd, termios.TCIFLUSH)
                self.main_screen()
                return

    def install_screen(self):
        self.clear()
        self.header()
        print()
        if self.confirm("安装 cd-bridge 到系统并注册开机自启?"):
            rc, out, err = run_sh("install")
            self.result_screen("安装结果", rc, out, err)
        else:
            self.main_screen()

    def uninstall_screen(self):
        self.clear()
        self.header()
        print()
        if self.confirm("确定卸载 cd-bridge? 所有文件将被清除"):
            rc, out, err = run_sh("uninstall")
            self.result_screen("卸载结果", rc, out, err)
        else:
            self.main_screen()

    def launch_screen(self):
        self.clear()
        self.header()
        print()
        import subprocess as sp
        claude_pid = sp.run(["pgrep", "-x", "Claude"], capture_output=True, text=True).stdout.strip()
        if claude_pid:
            print(f"  Claude Desktop 正在运行中 (PID {claude_pid})")
            print()
            print(f"  重启后才能加载新配置")
            print()
            if not self.confirm("重启 Claude Desktop?"):
                self.main_screen()
                return
            self.clear()
            self.header()
            print()
            print("  ⏳ 关闭 Claude Desktop...")
            sp.run(["kill", claude_pid])
            for _ in range(30):
                if not sp.run(["pgrep", "-x", "Claude"], capture_output=True).stdout.strip():
                    break
                time.sleep(0.3)
            rc, out, err = run_sh()
            self.result_screen("启动结果", rc, out, err)
        else:
            rc, out, err = run_sh()
            self.result_screen("启动结果", rc, out, err)

    def proxy_screen(self):
        items = [
            ("启动", "start"),
            ("停止", "stop"),
            ("返回", "back"),
        ]
        p = proxy_running()
        sel = 1 if p else 0
        while True:
            self.clear()
            self.header()
            print()
            print(f"  {B('代理')}")
            print()
            print(f"    {'●' if p else '○'}  状态:  {G('运行中') if p else R('已停止')}")
            print()
            for i, (label, key) in enumerate(items):
                disabled = (key == "start" and p) or (key == "stop" and not p)
                prefix = "◉" if i == sel else "○"
                if i == sel:
                    print(f"  {HI(f'{prefix}  {label} ')}" if not disabled else f"  {D(f'{prefix}  {label}')}")
                elif disabled:
                    print(f"  {D(f'{prefix}  {label}')}")
                else:
                    print(f"  {prefix}  {label}")
            print()
            print(f"  {D('↑↓ 选择  Enter 确认  Esc 返回')}")
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                k = rkey(fd)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
            if k == "UP":
                sel = (sel - 1) % len(items)
                while items[sel][1] == "start" and p or items[sel][1] == "stop" and not p:
                    sel = (sel - 1) % len(items)
            elif k == "DOWN":
                sel = (sel + 1) % len(items)
                while items[sel][1] == "start" and p or items[sel][1] == "stop" and not p:
                    sel = (sel + 1) % len(items)
            elif k == "ENTER":
                key = items[sel][1]
                if key == "back":
                    return
                elif key == "start":
                    rc, out, err = run_sh("proxy")
                    time.sleep(1)
                    if proxy_running():
                        self.result_screen("启动代理", rc, out, err)
                    else:
                        log = ""
                        for p in [Path.home() / ".cd-bridge" / "proxy.log",
                                  SH_PATH.parent / "proxy.log"]:
                            if p.exists():
                                log = p.read_text().strip()[-300:]
                                break
                        detail = err or log or "(无日志)"
                        self.result_screen("启动代理", -1, out, detail)
                    return
                elif key == "stop":
                    rc, out, err = run_sh("proxy-stop")
                    if proxy_running():
                        self.result_screen("停止代理", -1, "", "代理未能停止")
                    else:
                        self.result_screen("停止代理", rc, out, err)
                    return
            elif k in ("ESC", "Q"):
                return

    def help_screen(self):
        self.clear()
        self.header()
        print()
        rc, out, err = run_sh("help")
        if out:
            for line in out.split("\n"):
                line = line.replace(str(SH_PATH.parent), ".").replace(str(SH_PATH), "./cd-bridge.sh")
                print(f"  {line}")
        print()
        self.wait_key("回车返回")
        self.main_screen()

    def run(self):
        self.hide()
        try:
            self.main_screen()
        finally:
            self.show()


if __name__ == "__main__":
    Wizard().run()
