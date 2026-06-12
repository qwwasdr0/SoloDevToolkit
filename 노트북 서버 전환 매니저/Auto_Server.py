# -*- coding: utf-8 -*-
"""
Laptop Server Manager v7.4
- 노트북을 서버 PC처럼 사용하기 위한 Windows 전원 정책/자동 실행 관리 도구
- 관리자 권한 필요
- Python 3.9+ 권장

필수 기능
1) AC/DC 모두 절전/최대절전 차단
2) 노트북 덮개를 닫아도 아무 동작 안 함
3) 디스크/USB/PCIe/네트워크 어댑터 절전 차단
4) 부팅/로그온 시 자동 실행 + 자동 서버 모드 재적용
5) 단일 인스턴스 실행
"""

import base64
import ctypes
import io
import json
import os
import re
import socket
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, scrolledtext

try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_SUPPORTED = True
except Exception:
    TRAY_SUPPORTED = False


# =====================================================================
# [설정]
# =====================================================================
APP_NAME = "노트북 서버 매니저"
APP_VERSION = "v7.4"
APP_ID = "ITSCO.LaptopServerManager.v7.4"
TASK_NAME = "ITSCO_LaptopServerManager_Startup"
SERVER_PLAN_NAME = "ITSCO_Server_Mode"
SERVER_PLAN_DESC = "Laptop server mode: no sleep, no hibernate, lid close do nothing"
IPC_PORT = 64999
CREATE_NO_WINDOW = 0x08000000

# Windows 기본 전원 구성표 GUID
GUID_HIGH_PERFORMANCE = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
GUID_BALANCED = "381b4222-f694-41f0-9685-ff5bb260df2e"

# powercfg GUID / alias
GUID_SUB_BUTTONS = "4f971e89-eebd-4455-a8de-9e59040e7347"
GUID_LIDACTION = "5ca73304-a2a4-4367-944e-3367098e29a5"

# 일부 Windows/Server 환경에서는 powercfg alias가 먹지 않는 경우가 있어
# USB 선택적 절전은 GUID로도 한 번 더 처리합니다.
GUID_SUB_USB = "2a737441-1930-4402-8d77-b2bebba308a3"
GUID_USB_SELECTIVE = "48e6b7a6-50f5-4782-a5d4-53bb8f07e226"

CONFIG_PATH = Path(os.getenv("PROGRAMDATA", r"C:\ProgramData")) / "ITSCO" / "LaptopServerManager" / "config.json"


# =====================================================================
# [공통 유틸]
# =====================================================================
class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_byte),
        ("BatteryFlag", ctypes.c_byte),
        ("BatteryLifePercent", ctypes.c_byte),
        ("SystemStatusFlag", ctypes.c_byte),
        ("BatteryLifeTime", ctypes.c_ulong),
        ("BatteryFullLifeTime", ctypes.c_ulong),
    ]


def resource_path(relative_path: str) -> str:
    try:
        base_path = sys._MEIPASS  # type: ignore[attr-defined]
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> None:
    if getattr(sys, "frozen", False):
        exe_path = sys.executable
        params = " ".join([f'"{arg}"' for arg in sys.argv[1:]])
    else:
        exe_path = sys.executable
        script_path = os.path.abspath(sys.argv[0])
        params = f'"{script_path}" ' + " ".join([f'"{arg}"' for arg in sys.argv[1:]])

    ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe_path, params, None, 1)
    if ret <= 32:
        ctypes.windll.user32.MessageBoxW(0, "관리자 권한으로 실행하지 못했습니다.", "권한 오류", 0x10)
    sys.exit(0)


def hide_console() -> None:
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


def decode_output(data: bytes) -> str:
    """Windows 명령 출력 디코딩.

    기존 방식처럼 utf-8을 errors=replace로 바로 디코딩하면 cp949 한글이
    깨진 상태로 확정됩니다. strict로 먼저 검사한 뒤 실패하면 다음
    인코딩을 시도해야 합니다.
    """
    if not data:
        return ""

    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        try:
            return data.decode("utf-16", errors="replace")
        except Exception:
            pass

    for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-16", "utf-8"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
        except Exception:
            continue

    for enc in ("cp949", "utf-8", "latin1"):
        try:
            return data.decode(enc, errors="replace")
        except Exception:
            continue
    return data.decode(errors="replace")


def run_raw(args, timeout: int = 30) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            args,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
        out = decode_output(completed.stdout)
        err = decode_output(completed.stderr)
        text = (out + "\n" + err).strip()
        return completed.returncode == 0, text
    except subprocess.TimeoutExpired:
        return False, "명령 실행 시간이 초과되었습니다."
    except Exception as exc:
        return False, str(exc)


def run_cmd(command: str, timeout: int = 30) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
        out = decode_output(completed.stdout)
        err = decode_output(completed.stderr)
        text = (out + "\n" + err).strip()
        return completed.returncode == 0, text
    except subprocess.TimeoutExpired:
        return False, "명령 실행 시간이 초과되었습니다."
    except Exception as exc:
        return False, str(exc)


def run_ps(script: str, timeout: int = 60) -> tuple[bool, str]:
    prefix = r"""
$ProgressPreference = 'SilentlyContinue'
$VerbosePreference = 'SilentlyContinue'
$InformationPreference = 'SilentlyContinue'
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {}
"""
    encoded = base64.b64encode((prefix + "\n" + script).encode("utf-16le")).decode("ascii")
    return run_raw(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-OutputFormat",
            "Text",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded,
        ],
        timeout=timeout,
    )


def read_config() -> dict:
    try:
        if CONFIG_PATH.exists():
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def write_config(data: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_current_script_action() -> tuple[str, str, str]:
    """작업 스케줄러 Action용 Execute, Argument, WorkingDirectory 반환."""
    if getattr(sys, "frozen", False):
        exe = sys.executable
        args = "--startup --apply-server --tray"
        work_dir = os.path.dirname(sys.executable)
        return exe, args, work_dir

    script_path = os.path.abspath(sys.argv[0])
    py_exe = sys.executable
    pyw = os.path.join(os.path.dirname(py_exe), "pythonw.exe")
    exe = pyw if os.path.exists(pyw) else py_exe
    args = f'"{script_path}" --startup --apply-server --tray'
    work_dir = os.path.dirname(script_path)
    return exe, args, work_dir


def parse_guid(text: str) -> str | None:
    match = re.search(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})", text or "")
    return match.group(1) if match else None


# =====================================================================
# [전원 정책 엔진]
# =====================================================================
class PowerPolicyEngine:
    def __init__(self, logger=None):
        self.logger = logger or (lambda msg: None)

    def log(self, msg: str) -> None:
        self.logger(msg)

    def get_active_scheme_guid(self) -> str | None:
        ok, out = run_cmd("powercfg /getactivescheme")
        if not ok:
            return None
        return parse_guid(out)

    def list_schemes(self) -> list[tuple[str, str, bool]]:
        ok, out = run_cmd("powercfg /list")
        if not ok:
            return []
        schemes = []
        for line in out.splitlines():
            guid = parse_guid(line)
            if not guid:
                continue
            name_match = re.search(r"\((.*?)\)", line)
            name = name_match.group(1).strip() if name_match else ""
            active = "*" in line
            schemes.append((guid, name, active))
        return schemes

    def find_scheme_by_name(self, name: str) -> str | None:
        for guid, scheme_name, _ in self.list_schemes():
            if scheme_name.strip().lower() == name.strip().lower():
                return guid
        return None

    def ensure_server_scheme(self) -> str:
        existing = self.find_scheme_by_name(SERVER_PLAN_NAME)
        if existing:
            self.log(f"  ├─ 전원 구성표 확인: [정상] {SERVER_PLAN_NAME} / {existing}")
            return existing

        self.log("  ├─ 전원 구성표 생성: 서버 전용 구성표를 새로 생성합니다.")
        ok, out = run_cmd(f"powercfg /duplicatescheme {GUID_HIGH_PERFORMANCE}")
        if not ok:
            raise RuntimeError(f"고성능 전원 구성표 복제 실패: {out}")

        new_guid = parse_guid(out)
        if not new_guid:
            # 일부 Windows에서 출력 파싱이 실패할 수 있으므로 목록에서 재검색
            new_guid = self.find_scheme_by_name("High performance") or self.find_scheme_by_name("고성능")
        if not new_guid:
            raise RuntimeError(f"새 전원 구성표 GUID를 확인하지 못했습니다: {out}")

        run_cmd(f'powercfg /changename {new_guid} "{SERVER_PLAN_NAME}" "{SERVER_PLAN_DESC}"')
        self.log(f"  ├─ 전원 구성표 생성: [성공] {new_guid}")
        return new_guid

    def set_value(self, scheme: str, acdc: str, subgroup: str, setting: str, value: int, log_failure: bool = True) -> bool:
        cmd = f"powercfg /set{acdc}valueindex {scheme} {subgroup} {setting} {value}"
        ok, out = run_cmd(cmd)
        if not ok and log_failure:
            self.log(f"  ├─ 정책 적용 실패: {setting}={value} / {out}")
        return ok

    def apply_server_mode(self) -> None:
        self.log("==========================================")
        self.log("🚀 노트북 서버 모드 적용 시작")

        previous = self.get_active_scheme_guid()
        cfg = read_config()
        if previous and previous != self.find_scheme_by_name(SERVER_PLAN_NAME):
            cfg["previous_scheme_guid"] = previous
            write_config(cfg)

        scheme = self.ensure_server_scheme()

        # 숨김 옵션 노출: 덮개 닫기 동작
        run_cmd(f"powercfg -attributes {GUID_SUB_BUTTONS} {GUID_LIDACTION} -ATTRIB_HIDE")

        # 핵심: AC/DC 모두 적용해야 배터리 상태에서도 서버가 죽지 않음
        settings = [
            # 덮개 닫기: 0 = 아무 것도 안 함
            ("SUB_BUTTONS", "LIDACTION", 0, "덮개 닫기 동작: 아무 것도 안 함"),
            # 절전/최대절전 차단
            ("SUB_SLEEP", "STANDBYIDLE", 0, "자동 절전: 사용 안 함"),
            ("SUB_SLEEP", "HIBERNATEIDLE", 0, "자동 최대절전: 사용 안 함"),
            ("SUB_SLEEP", "HYBRIDSLEEP", 0, "하이브리드 절전: 사용 안 함"),
            # 디스크/PCIe 절전 차단
            ("SUB_DISK", "DISKIDLE", 0, "디스크 절전: 사용 안 함"),
            ("SUB_PCIEXPRESS", "ASPM", 0, "PCIe 링크 절전: 사용 안 함"),
            # 화면 꺼짐도 0으로 고정. 화면만 끄고 싶으면 이 값을 5~10분으로 바꾸면 됨.
            ("SUB_VIDEO", "VIDEOIDLE", 0, "화면 자동 꺼짐: 사용 안 함"),
        ]

        for subgroup, setting, value, label in settings:
            ac_ok = self.set_value(scheme, "ac", subgroup, setting, value)
            dc_ok = self.set_value(scheme, "dc", subgroup, setting, value)
            result = "[성공]" if ac_ok and dc_ok else "[주의] 일부 실패"
            self.log(f"  ├─ {label}: {result}")

        # USB 선택적 절전은 Windows 빌드/Server 계열에서 alias가 실패하는 사례가 있어
        # alias 방식과 GUID 방식을 순차 시도합니다.
        # alias 실패 후 GUID 성공이면 정상 상황이므로 중간 실패 로그는 남기지 않습니다.
        usb_ac_ok = self.set_value(scheme, "ac", "SUB_USB", "USBSELECTIVE", 0, log_failure=False)
        usb_dc_ok = self.set_value(scheme, "dc", "SUB_USB", "USBSELECTIVE", 0, log_failure=False)
        if not (usb_ac_ok and usb_dc_ok):
            usb_ac_ok = self.set_value(scheme, "ac", GUID_SUB_USB, GUID_USB_SELECTIVE, 0)
            usb_dc_ok = self.set_value(scheme, "dc", GUID_SUB_USB, GUID_USB_SELECTIVE, 0)
        self.log(f"  ├─ USB 선택적 절전: {'[성공]' if usb_ac_ok and usb_dc_ok else '[주의] 이 장치/OS에서 항목 없음 또는 적용 불가'}")

        # powercfg /x도 같이 적용해 Windows UI 값까지 동기화
        for cmd in [
            "powercfg /x -monitor-timeout-ac 0",
            "powercfg /x -monitor-timeout-dc 0",
            "powercfg /x -standby-timeout-ac 0",
            "powercfg /x -standby-timeout-dc 0",
            "powercfg /x -hibernate-timeout-ac 0",
            "powercfg /x -hibernate-timeout-dc 0",
        ]:
            run_cmd(cmd)

        # 최대절전 자체 비활성화: 서버 PC 용도에서는 예기치 않은 hibernate 진입을 막는 편이 안전
        ok, out = run_cmd("powercfg /hibernate off")
        self.log(f"  ├─ 최대절전 파일 비활성화: {'[성공]' if ok else '[주의] 실패 - ' + out}")

        # 네트워크 어댑터 절전 차단
        ps_network = r"""
$ErrorActionPreference = 'SilentlyContinue'
Get-NetAdapter -Physical | ForEach-Object {
    try {
        Disable-NetAdapterPowerManagement -Name $_.Name -NoRestart -ErrorAction SilentlyContinue | Out-Null
    } catch {}
}
"""
        ok, out = run_ps(ps_network, timeout=60)
        self.log(f"  ├─ 네트워크 어댑터 절전 차단: {'[성공]' if ok else '[주의] 확인 필요 - ' + out}")

        ok, out = run_cmd(f"powercfg /setactive {scheme}")
        if not ok:
            raise RuntimeError(f"서버 전원 구성표 활성화 실패: {out}")

        cfg = read_config()
        cfg.update({
            "server_mode_applied": True,
            "last_server_apply_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "server_scheme_guid": scheme,
            "lid_action_requested": 0,
        })
        write_config(cfg)

        self.log(f"  └─ 서버 전원 구성표 활성화: [성공] {scheme}")
        self.log("✅ 서버 모드 적용 완료: 절전/최대절전/덮개 닫기 절전 진입을 차단했습니다.")
        self.log("==========================================\n")

    def restore_normal_mode(self) -> None:
        self.log("==========================================")
        self.log("💻 일반 모드 복구 시작")
        cfg = read_config()
        previous = cfg.get("previous_scheme_guid") or GUID_BALANCED
        ok, out = run_cmd(f"powercfg /setactive {previous}")
        if not ok:
            self.log(f"  ├─ 이전 전원 구성표 복구 실패, 균형 조정으로 복구합니다: {out}")
            run_cmd(f"powercfg /setactive {GUID_BALANCED}")

        # 일반 사용성을 위해 최대절전 재활성화
        run_cmd("powercfg /hibernate on")

        ps_network = r"""
$ErrorActionPreference = 'SilentlyContinue'
Get-NetAdapter -Physical | ForEach-Object {
    try {
        Enable-NetAdapterPowerManagement -Name $_.Name -NoRestart -ErrorAction SilentlyContinue | Out-Null
    } catch {}
}
"""
        run_ps(ps_network, timeout=60)
        cfg = read_config()
        cfg["server_mode_applied"] = False
        cfg["last_normal_restore_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        write_config(cfg)
        self.log("  └─ 일반 모드 복구 완료")
        self.log("==========================================\n")

    def query_lid_action(self) -> tuple[int | None, int | None]:
        """덮개 닫기 동작의 AC/DC 값을 확인합니다.

        v7.4는 powercfg 출력 파싱보다 Windows 전원 정책 레지스트리를 먼저 조회합니다.
        이 방식은 한글/영문 Windows 출력 형식 차이의 영향을 거의 받지 않습니다.
        """
        run_cmd(f"powercfg -attributes {GUID_SUB_BUTTONS} {GUID_LIDACTION} -ATTRIB_HIDE")

        scheme_candidates: list[str] = []
        active_scheme = self.get_active_scheme_guid()
        server_scheme = self.find_scheme_by_name(SERVER_PLAN_NAME)
        for item in (active_scheme, server_scheme):
            if item and item not in scheme_candidates:
                scheme_candidates.append(item)

        guid_pattern = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

        # 1차: 레지스트리 직접 조회. 언어/로케일 영향을 받지 않아 가장 안정적입니다.
        for scheme in scheme_candidates:
            if not guid_pattern.match(scheme):
                continue
            ps = f"""
$ErrorActionPreference = 'Stop'
$Path = 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Power\\User\\PowerSchemes\\{scheme}\\{GUID_SUB_BUTTONS}\\{GUID_LIDACTION}'
$Item = Get-ItemProperty -LiteralPath $Path
$Ac = [int]$Item.ACSettingIndex
$Dc = [int]$Item.DCSettingIndex
Write-Output "$Ac,$Dc"
"""
            ok, out = run_ps(ps, timeout=20)
            if ok and out:
                match = re.search(r"(\d+)\s*,\s*(\d+)", out)
                if match:
                    return int(match.group(1)), int(match.group(2))

        # 2차: powercfg /q를 GUID 기준으로 조회해서 Current AC/DC 줄을 파싱합니다.
        # 영어/한글 환경에 따라 라벨이 달라도 마지막 16진수 값 기준으로 보완합니다.
        for scheme in scheme_candidates + ["SCHEME_CURRENT"]:
            ok, out = run_cmd(f"powercfg /q {scheme} {GUID_SUB_BUTTONS} {GUID_LIDACTION}")
            if not ok or not out:
                continue

            ac_patterns = [
                r"Current\s+AC\s+Power\s+Setting\s+Index:\s*0x([0-9a-fA-F]+)",
                r"현재\s*AC[^\r\n]*0x([0-9a-fA-F]+)",
                r"AC[^\r\n]*Setting[^\r\n]*Index[^\r\n]*0x([0-9a-fA-F]+)",
            ]
            dc_patterns = [
                r"Current\s+DC\s+Power\s+Setting\s+Index:\s*0x([0-9a-fA-F]+)",
                r"현재\s*DC[^\r\n]*0x([0-9a-fA-F]+)",
                r"DC[^\r\n]*Setting[^\r\n]*Index[^\r\n]*0x([0-9a-fA-F]+)",
            ]

            ac_value = None
            dc_value = None
            for pattern in ac_patterns:
                m = re.search(pattern, out, re.IGNORECASE)
                if m:
                    ac_value = int(m.group(1), 16)
                    break
            for pattern in dc_patterns:
                m = re.search(pattern, out, re.IGNORECASE)
                if m:
                    dc_value = int(m.group(1), 16)
                    break

            if ac_value is not None and dc_value is not None:
                return ac_value, dc_value

            # 해당 설정만 /q 했을 때는 출력 말미 2개가 현재 AC/DC 값인 경우가 많습니다.
            all_hex = re.findall(r"0x([0-9a-fA-F]+)", out)
            if len(all_hex) >= 2:
                tail = [int(x, 16) for x in all_hex[-2:]]
                if all(v in (0, 1, 2, 3) for v in tail):
                    return tail[0], tail[1]

        return None, None

    def check_status(self) -> dict:
        active_guid = self.get_active_scheme_guid()
        server_guid = self.find_scheme_by_name(SERVER_PLAN_NAME)
        ac_lid, dc_lid = self.query_lid_action()

        ps = SYSTEM_POWER_STATUS()
        ac_connected = False
        battery_percent = None
        if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(ps)):
            ac_connected = ps.ACLineStatus == 1
            battery_percent = int(ps.BatteryLifePercent)

        ip = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
        except Exception:
            pass

        boot_text = "측정 불가"
        ok, out = run_cmd("wmic os get lastbootuptime")
        match = re.search(r"(\d{14})", out or "")
        if ok and match:
            boot_time = datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
            diff = datetime.now() - boot_time
            boot_text = f"{diff.days}일 {diff.seconds // 3600}시간 {(diff.seconds % 3600) // 60}분"
        else:
            ps_boot = r"""
$dt = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
if ($dt) { $dt.ToString('yyyy-MM-dd HH:mm:ss') }
"""
            ok2, out2 = run_ps(ps_boot, timeout=20)
            try:
                if ok2 and out2.strip():
                    boot_time = datetime.strptime(out2.strip().splitlines()[-1], "%Y-%m-%d %H:%M:%S")
                    diff = datetime.now() - boot_time
                    boot_text = f"{diff.days}일 {diff.seconds // 3600}시간 {(diff.seconds % 3600) // 60}분"
            except Exception:
                pass

        startup_ok = StartupManager().is_registered()
        cfg = read_config()
        last_apply_time = cfg.get("last_server_apply_time")
        lid_assumed_ok = bool(
            ac_lid is None
            and dc_lid is None
            and cfg.get("server_mode_applied") is True
            and cfg.get("lid_action_requested") == 0
            and active_guid
            and server_guid
            and active_guid.lower() == server_guid.lower()
        )

        ok, netstat = run_cmd("netstat -ano", timeout=20)
        ports = {}
        if ok:
            for port in (80, 443, 3306, 33061, 8080):
                ports[port] = bool(re.search(rf"TCP\s+.*:{port}\s+.*LISTENING", netstat, re.IGNORECASE))

        return {
            "active_guid": active_guid,
            "server_guid": server_guid,
            "is_server_active": bool(active_guid and server_guid and active_guid.lower() == server_guid.lower()),
            "lid_ac": ac_lid,
            "lid_dc": dc_lid,
            "lid_ok": (ac_lid == 0 and dc_lid == 0) or lid_assumed_ok,
            "lid_assumed_ok": lid_assumed_ok,
            "last_apply_time": last_apply_time,
            "ac_connected": ac_connected,
            "battery_percent": battery_percent,
            "ip": ip,
            "uptime": boot_text,
            "startup_ok": startup_ok,
            "ports": ports,
        }


# =====================================================================
# [자동 실행 관리자]
# =====================================================================
class StartupManager:
    def is_registered(self) -> bool:
        ps = f"""
$task = Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue
if ($null -ne $task) {{ Write-Output 'FOUND' }}
"""
        ok, out = run_ps(ps, timeout=20)
        return ok and "FOUND" in out

    def register(self) -> tuple[bool, str]:
        exe, args, work_dir = get_current_script_action()
        exe_ps = exe.replace("'", "''")
        args_ps = args.replace("'", "''")
        work_ps = work_dir.replace("'", "''")

        ps = f"""
$ErrorActionPreference = 'Stop'
$TaskName = '{TASK_NAME}'
$Execute = '{exe_ps}'
$Argument = '{args_ps}'
$WorkDir = '{work_ps}'

$Action = New-ScheduledTaskAction -Execute $Execute -Argument $Argument -WorkingDirectory $WorkDir
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\\$env:USERNAME" -LogonType Interactive -RunLevel Highest
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Days 9999)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Description 'Start laptop server manager and re-apply server power policy at user logon.' -Force | Out-Null
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
Write-Output "REGISTERED: $($task.TaskName)"
Write-Output "EXECUTE: $Execute"
Write-Output "ARGUMENT: $Argument"
"""
        return run_ps(ps, timeout=60)

    def unregister(self) -> tuple[bool, str]:
        ps = f"""
$task = Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue
if ($null -ne $task) {{
    Unregister-ScheduledTask -TaskName '{TASK_NAME}' -Confirm:$false
    Write-Output 'UNREGISTERED'
}} else {{
    Write-Output 'NOT_FOUND'
}}
"""
        return run_ps(ps, timeout=30)

    def run_now(self) -> tuple[bool, str]:
        ps = f"""
Start-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction Stop
Write-Output 'STARTED'
"""
        return run_ps(ps, timeout=20)


# =====================================================================
# [GUI]
# =====================================================================
class LaptopServerManagerApp:
    def __init__(self, root: tk.Tk, start_in_tray: bool = False, auto_apply: bool = False):
        self.root = root
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.root.geometry("860x800")
        self.root.resizable(False, False)
        self.root.configure(bg="#F0F2F5")
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window_to_tray)

        self.icon_path = resource_path("1202702.ico")
        self.tray_icon = None
        self.policy = PowerPolicyEngine(self.log)
        self.startup = StartupManager()
        self.operation_lock = threading.Lock()
        self.pending_status_after_busy = False

        self.setup_ui()
        self.apply_icon_to_window(self.root)
        self.root.after(150, lambda: self.apply_icon_to_window(self.root))
        self.log(f"[성공] {APP_NAME} {APP_VERSION} 실행 완료")

        if auto_apply:
            self.root.after(500, lambda: self.start_thread(self.policy.apply_server_mode))
        else:
            self.root.after(900, self.start_status_check)

        if start_in_tray:
            self.root.after(1600, self.hide_window_to_tray)

    def setup_ui(self) -> None:
        header = tk.Frame(self.root, bg="#263238", height=70)
        header.pack(side=tk.TOP, fill=tk.X)
        header.pack_propagate(False)

        tk.Label(
            header,
            text=f"노트북 서버 매니저 {APP_VERSION}",
            font=("Malgun Gothic", 18, "bold"),
            fg="white",
            bg="#263238",
        ).pack(side=tk.LEFT, padx=20)

        tk.Label(
            header,
            text="절전 차단 · 덮개 닫기 유지 · 자동 실행",
            font=("Malgun Gothic", 10),
            fg="#CFD8DC",
            bg="#263238",
        ).pack(side=tk.LEFT, padx=5)

        button_frame = tk.Frame(self.root, bg="#F0F2F5", pady=15)
        button_frame.pack(side=tk.TOP, fill=tk.X, padx=15)

        f_bold = ("Malgun Gothic", 11, "bold")
        tk.Button(
            button_frame,
            text="🚀 서버 모드 적용",
            command=lambda: self.start_thread(self.policy.apply_server_mode),
            width=18,
            height=2,
            bg="#1B5E20",
            fg="white",
            font=f_bold,
        ).pack(side=tk.LEFT, padx=5, expand=True)

        tk.Button(
            button_frame,
            text="🔍 상태 검사",
            command=self.start_status_check,
            width=18,
            height=2,
            bg="#FF8F00",
            fg="white",
            font=f_bold,
        ).pack(side=tk.LEFT, padx=5, expand=True)

        tk.Button(
            button_frame,
            text="⚙️ 자동 실행 등록/해제",
            command=self.open_startup_popup,
            width=18,
            height=2,
            bg="#455A64",
            fg="white",
            font=f_bold,
        ).pack(side=tk.LEFT, padx=5, expand=True)

        tk.Button(
            button_frame,
            text="💻 일반 모드 복구",
            command=lambda: self.start_thread(self.policy.restore_normal_mode),
            width=18,
            height=2,
            bg="#0D47A1",
            fg="white",
            font=f_bold,
        ).pack(side=tk.LEFT, padx=5, expand=True)

        info_frame = tk.LabelFrame(
            self.root,
            text=" 핵심 상태 ",
            bg="#F0F2F5",
            padx=10,
            pady=8,
            font=("Malgun Gothic", 10, "bold"),
        )
        info_frame.pack(side=tk.TOP, fill=tk.X, padx=15, pady=5)

        self.status_label = tk.Label(
            info_frame,
            text="상태 검사 전입니다. 서버 모드 적용 후 상태 검사를 실행하세요.",
            anchor="w",
            justify=tk.LEFT,
            bg="#F0F2F5",
            fg="#263238",
            font=("Malgun Gothic", 10, "bold"),
        )
        self.status_label.pack(fill=tk.X)

        log_frame = tk.LabelFrame(
            self.root,
            text=" 실행 로그 ",
            bg="#F0F2F5",
            padx=10,
            pady=10,
            font=("Malgun Gothic", 10, "bold"),
        )
        log_frame.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True, padx=15, pady=15)

        self.log_area = scrolledtext.ScrolledText(
            log_frame,
            wrap=tk.WORD,
            height=26,
            font=("Malgun Gothic", 10, "bold"),
            bg="#1E1E1E",
            fg="#D4D4D4",
        )
        self.log_area.pack(fill=tk.BOTH, expand=True)

        self.log_area.tag_configure("time", foreground="#7F848E")
        self.log_area.tag_configure("success", foreground="#98C379")
        self.log_area.tag_configure("warning", foreground="#E5C07B")
        self.log_area.tag_configure("danger", foreground="#E06C75")
        self.log_area.tag_configure("header", foreground="#61AFEF")

    def apply_icon_to_window(self, window) -> None:
        """메인 창과 모든 Toplevel 팝업에 동일한 아이콘을 적용합니다.

        Tkinter의 iconbitmap만으로는 Windows 작업표시줄/팝업 타이틀바에
        아이콘이 늦게 반영되거나 누락되는 경우가 있어 WM_SETICON까지 같이 적용합니다.
        """
        if not os.path.exists(self.icon_path):
            return

        try:
            window.iconbitmap(self.icon_path)
        except Exception:
            pass

        try:
            window.update_idletasks()
        except Exception:
            pass

        try:
            hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
            if not hwnd:
                return

            IMAGE_ICON = 1
            LR_LOADFROMFILE = 0x0010
            WM_SETICON = 0x0080
            ICON_SMALL = 0
            ICON_BIG = 1

            hicon = ctypes.windll.user32.LoadImageW(
                0,
                self.icon_path,
                IMAGE_ICON,
                0,
                0,
                LR_LOADFROMFILE,
            )
            if hicon:
                ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon)
                ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon)
        except Exception:
            pass

    def log(self, msg: str) -> None:
        def _write():
            timestamp = datetime.now().strftime("[%H:%M:%S] ")
            self.log_area.insert(tk.END, timestamp, "time")

            tag = ""
            if any(x in msg for x in ("[성공]", "[정상]", "✅", "완료", "ON")):
                tag = "success"
            elif any(x in msg for x in ("[주의]", "확인 필요", "정보")):
                tag = "warning"
            elif any(x in msg for x in ("[실패]", "오류", "위험", "OFF")):
                tag = "danger"
            elif any(x in msg for x in ("===", "🚀", "🔍", "💻")):
                tag = "header"

            self.log_area.insert(tk.END, msg + "\n", tag)
            self.log_area.see(tk.END)

        try:
            self.root.after(0, _write)
        except Exception:
            pass

    def start_thread(self, target, refresh_after: bool = True, is_status: bool = False) -> None:
        threading.Thread(
            target=self.thread_wrapper,
            args=(target, refresh_after, is_status),
            daemon=True,
        ).start()

    def thread_wrapper(self, target, refresh_after: bool = True, is_status: bool = False) -> None:
        acquired = self.operation_lock.acquire(blocking=False)
        if not acquired:
            if is_status:
                self.pending_status_after_busy = True
            else:
                self.log("[주의] 다른 작업이 진행 중입니다. 현재 작업 완료 후 다시 실행하세요.")
            return

        try:
            target()
        except Exception as exc:
            self.log(f"[실패] {exc}")
            self.root.after(0, lambda: messagebox.showerror("오류", str(exc)))
        finally:
            self.operation_lock.release()

        if refresh_after or self.pending_status_after_busy:
            self.pending_status_after_busy = False
            self.root.after(300, self.start_status_check)

    def start_status_check(self) -> None:
        self.start_thread(self.print_status, refresh_after=False, is_status=True)

    def print_status(self) -> None:
        status = self.policy.check_status()
        self.log("==========================================")
        self.log("🔍 서버 운영 상태 검사")
        self.log(f"  ├─ 서버 전원 구성표 활성화: {'[정상]' if status['is_server_active'] else '[주의] 비활성'}")
        if status['lid_ac'] is None or status['lid_dc'] is None:
            if status.get('lid_assumed_ok'):
                self.log("  ├─ 덮개 닫기 AC/DC: [정상] 적용됨 / 현재값 조회만 불가")
                if status.get('last_apply_time'):
                    self.log(f"  │  └─ 최근 서버 모드 적용: {status['last_apply_time']}")
            else:
                self.log("  ├─ 덮개 닫기 AC/DC: [주의] 현재값 검증 불가 / 서버 모드 재적용 권장")
        else:
            lid_mark = "[정상]" if status.get('lid_ok') else "[주의]"
            self.log(f"  ├─ 덮개 닫기 AC/DC: {lid_mark} AC={status['lid_ac']} / DC={status['lid_dc']} / 0이면 정상")
        self.log(f"  ├─ 자동 실행 등록: {'[정상] 등록됨' if status['startup_ok'] else '[주의] 미등록'}")
        self.log(f"  ├─ 전원 연결: {'[정상] AC 연결' if status['ac_connected'] else '[주의] 배터리 사용 중'}")
        if status["battery_percent"] is not None:
            self.log(f"  ├─ 배터리: {status['battery_percent']}%")
        self.log(f"  ├─ 로컬 IP: {status['ip'] or '[실패] 확인 불가'}")
        self.log(f"  ├─ 가동 시간: {status['uptime']}")

        ports_text = []
        for port, on in status["ports"].items():
            ports_text.append(f"{port}:{'ON' if on else 'OFF'}")
        self.log(f"  ├─ 포트 확인: {', '.join(ports_text) if ports_text else '확인 불가'}")
        overall_ok = bool(status['is_server_active'] and status['lid_ok'] and status['startup_ok'])
        self.log(f"  └─ 최종 판정: {'[정상] 서버 운영 가능' if overall_ok else '[주의] 확인 필요'}")
        self.log("==========================================\n")

        if status['lid_ac'] is not None and status['lid_dc'] is not None:
            lid_text = f"AC={status['lid_ac']} / DC={status['lid_dc']}"
        elif status.get('lid_assumed_ok'):
            lid_text = "적용됨 / 조회만 불가"
        else:
            lid_text = "검증 불가"

        overall_ok = bool(status['is_server_active'] and status['lid_ok'] and status['startup_ok'])
        verdict = "정상 운영 가능" if overall_ok else "확인 필요"
        summary = (
            f"최종 판정: {verdict}\n"
            f"서버 모드: {'정상' if status['is_server_active'] else '비활성'} | "
            f"덮개: {lid_text} | "
            f"자동 실행: {'등록됨' if status['startup_ok'] else '미등록'} | "
            f"IP: {status['ip'] or '확인 불가'}"
        )
        color = "#1B5E20" if overall_ok else "#E65100"
        self.root.after(0, lambda: self.status_label.config(text=summary, fg=color))

    def open_startup_popup(self) -> None:
        popup = tk.Toplevel(self.root)
        popup.title("자동 실행 설정")
        popup.geometry("660x270")
        popup.configure(bg="#FFFFFF")
        popup.transient(self.root)
        popup.grab_set()
        self.apply_icon_to_window(popup)
        popup.after(150, lambda: self.apply_icon_to_window(popup))

        registered = self.startup.is_registered()
        state_text = "현재 상태: 등록됨" if registered else "현재 상태: 미등록"

        tk.Label(
            popup,
            text="부팅/로그온 시 자동 실행 설정",
            font=("Malgun Gothic", 14, "bold"),
            bg="#FFFFFF",
            fg="#263238",
        ).pack(pady=(20, 8))

        tk.Label(
            popup,
            text=state_text,
            font=("Malgun Gothic", 11, "bold"),
            bg="#FFFFFF",
            fg="#1B5E20" if registered else "#D32F2F",
        ).pack(pady=5)

        tk.Label(
            popup,
            text="등록하면 Windows 로그온 시 관리자 권한 작업으로 실행되고\n서버 모드가 자동으로 다시 적용됩니다.",
            font=("Malgun Gothic", 10),
            bg="#FFFFFF",
            fg="#455A64",
            justify=tk.CENTER,
        ).pack(pady=5)

        button_frame = tk.Frame(popup, bg="#FFFFFF")
        button_frame.pack(pady=18)

        def register_task():
            ok, out = self.startup.register()
            self.log(f"자동 실행 등록 결과: {'[성공]' if ok else '[실패]'} {out}")
            if ok:
                messagebox.showinfo("완료", "자동 실행이 등록되었습니다. 다음 로그온부터 서버 모드가 자동 적용됩니다.")
                popup.destroy()
                self.start_status_check()
            else:
                messagebox.showerror("등록 실패", out or "알 수 없는 오류")

        def unregister_task():
            ok, out = self.startup.unregister()
            self.log(f"자동 실행 해제 결과: {'[성공]' if ok else '[실패]'} {out}")
            if ok:
                messagebox.showinfo("완료", "자동 실행이 해제되었습니다.")
                popup.destroy()
                self.start_status_check()
            else:
                messagebox.showerror("해제 실패", out or "알 수 없는 오류")

        def test_task():
            ok, out = self.startup.run_now()
            self.log(f"자동 실행 즉시 테스트: {'[성공]' if ok else '[실패]'} {out}")
            if ok:
                messagebox.showinfo("완료", "작업 스케줄러 실행 요청을 보냈습니다. 기존 창이 있으면 중복 실행하지 않고 깨웁니다.")
            else:
                messagebox.showerror("테스트 실패", out or "알 수 없는 오류")

        tk.Button(
            button_frame,
            text="자동 실행 등록",
            command=register_task,
            width=16,
            height=2,
            bg="#1B5E20",
            fg="white",
            font=("Malgun Gothic", 10, "bold"),
        ).pack(side=tk.LEFT, padx=6)

        tk.Button(
            button_frame,
            text="자동 실행 해제",
            command=unregister_task,
            width=16,
            height=2,
            bg="#B71C1C",
            fg="white",
            font=("Malgun Gothic", 10, "bold"),
        ).pack(side=tk.LEFT, padx=6)

        tk.Button(
            button_frame,
            text="즉시 테스트",
            command=test_task,
            width=12,
            height=2,
            bg="#6A1B9A",
            fg="white",
            font=("Malgun Gothic", 10, "bold"),
        ).pack(side=tk.LEFT, padx=6)

        tk.Button(
            button_frame,
            text="닫기",
            command=popup.destroy,
            width=10,
            height=2,
            bg="#607D8B",
            fg="white",
            font=("Malgun Gothic", 10, "bold"),
        ).pack(side=tk.LEFT, padx=6)

    def make_tray_image(self):
        if os.path.exists(self.icon_path):
            try:
                with open(self.icon_path, "rb") as f:
                    return Image.open(io.BytesIO(f.read())).convert("RGBA")
            except Exception:
                pass

        img = Image.new("RGBA", (64, 64), (38, 50, 56, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle((14, 18, 50, 42), outline=(255, 255, 255, 255), width=3)
        draw.rectangle((24, 44, 40, 49), fill=(255, 255, 255, 255))
        return img

    def hide_window_to_tray(self) -> None:
        if not TRAY_SUPPORTED:
            self.root.withdraw()
            return

        self.root.withdraw()
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass

        menu = pystray.Menu(
            pystray.MenuItem("열기", self.show_window_from_tray, default=True),
            pystray.MenuItem("서버 모드 재적용", lambda icon, item: self.start_thread(self.policy.apply_server_mode)),
            pystray.MenuItem("종료", self.exit_program),
        )
        self.tray_icon = pystray.Icon("LaptopServerManager", self.make_tray_image(), APP_NAME, menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def show_window_from_tray(self, icon=None, item=None) -> None:
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.root.after(0, self.root.deiconify)
        self.root.after(10, self.root.lift)
        self.root.after(20, lambda: self.root.attributes("-topmost", True))
        self.root.after(150, lambda: self.root.attributes("-topmost", False))
        self.start_status_check()

    def exit_program(self, icon=None, item=None) -> None:
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.root.quit()
        sys.exit(0)


# =====================================================================
# [단일 인스턴스]
# =====================================================================
def setup_single_instance(on_wakeup) -> bool:
    global _lock_socket
    try:
        _lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _lock_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _lock_socket.bind(("127.0.0.1", IPC_PORT))
        _lock_socket.listen(5)

        def listen():
            while True:
                try:
                    conn, _ = _lock_socket.accept()
                    data = conn.recv(1024)
                    if data == b"WAKE_UP":
                        on_wakeup()
                    conn.close()
                except Exception:
                    break

        threading.Thread(target=listen, daemon=True).start()
        return True
    except OSError:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect(("127.0.0.1", IPC_PORT))
                s.sendall(b"WAKE_UP")
        except Exception:
            pass
        return False


# =====================================================================
# [CLI]
# =====================================================================
def run_cli_if_requested() -> bool:
    args = {arg.lower() for arg in sys.argv[1:]}

    if "--install-startup" in args:
        ok, out = StartupManager().register()
        print(out)
        return True

    if "--uninstall-startup" in args:
        ok, out = StartupManager().unregister()
        print(out)
        return True

    if "--apply-server-only" in args:
        PowerPolicyEngine(print).apply_server_mode()
        return True

    if "--restore-normal-only" in args:
        PowerPolicyEngine(print).restore_normal_mode()
        return True

    return False


# =====================================================================
# [메인]
# =====================================================================
def main() -> None:
    if os.name != "nt":
        print("이 프로그램은 Windows 전용입니다.")
        return

    if not is_admin():
        relaunch_as_admin()

    if run_cli_if_requested():
        return

    hide_console()
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass

    root = tk.Tk()
    app_holder = {"app": None}

    def wakeup():
        app = app_holder.get("app")
        if app:
            app.root.after(0, app.show_window_from_tray)

    if not setup_single_instance(wakeup):
        return

    start_in_tray = "--startup" in {arg.lower() for arg in sys.argv[1:]} or "--tray" in {arg.lower() for arg in sys.argv[1:]}
    auto_apply = "--apply-server" in {arg.lower() for arg in sys.argv[1:]}

    app = LaptopServerManagerApp(root, start_in_tray=start_in_tray, auto_apply=auto_apply)
    app_holder["app"] = app
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        try:
            import traceback
            msg = traceback.format_exc()
            ctypes.windll.user32.MessageBoxW(0, msg, "프로그램 오류", 0x10)
        except Exception:
            print(exc)
