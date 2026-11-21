"""
scanner.py — Backend de VeClean.

Módulos:
  - Escaneo y limpieza de archivos temporales, caché, papelera
  - Info del sistema (CPU, RAM, disco, SO, uptime)
  - Buscador de archivos duplicados (por hash SHA-256)
  - Gestión de programas de inicio (startup)
  - Desinstalador de programas
  - Info de red (IP, DNS, gateway)
  - Generador de reporte del sistema

IMPORTANTE: Solo funciona en Windows. Las rutas y APIs son específicas
de Windows.
"""

import os
import hashlib
import subprocess
import socket
import platform
import logging
import ctypes
import winreg
import datetime
import json
from pathlib import Path
from dataclasses import dataclass, field

logger = logging.getLogger("veclean.scanner")

# psutil es la única dependencia externa real.
# Se importa aquí para que el módulo falle rápido si no está instalado.
try:
    import psutil
except ImportError:
    psutil = None
    logger.warning("psutil no instalado — las funciones de estado del sistema no estarán disponibles")


# ===========================================================================
# Helpers
# ===========================================================================

def _size_fmt(num_bytes: int | float) -> str:
    """Convierte bytes a formato legible: KB, MB, GB."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num_bytes) < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} PB"


def _safe_size(path: str) -> int:
    """Obtiene el tamaño de un archivo. Retorna 0 si no existe o sin permisos."""
    try:
        return os.path.getsize(path)
    except (OSError, PermissionError):
        return 0


def _safe_rmtree(path: str) -> tuple[int, int]:
    """
    Borra un directorio recursivamente.
    Retorna (archivos_borrados, bytes_liberados).
    Ignora errores de permisos en archivos individuales.
    """
    total_files = 0
    total_bytes = 0

    if not os.path.exists(path):
        return 0, 0

    for root, dirs, files in os.walk(path, topdown=False):
        for name in files:
            fp = os.path.join(root, name)
            try:
                size = os.path.getsize(fp)
                os.remove(fp)
                total_files += 1
                total_bytes += size
            except (OSError, PermissionError) as e:
                logger.debug("No se pudo borrar %s: %s", fp, e)
        for name in dirs:
            dp = os.path.join(root, name)
            try:
                os.rmdir(dp)
            except OSError:
                pass

    try:
        os.rmdir(path)
    except OSError:
        pass

    return total_files, total_bytes


def _safe_remove(path: str) -> tuple[int, int]:
    """Borra un archivo individual. Retorna (1, bytes) o (0, 0) si falla."""
    try:
        size = os.path.getsize(path)
        os.remove(path)
        return 1, size
    except (OSError, PermissionError) as e:
        logger.debug("No se pudo borrar %s: %s", path, e)
        return 0, 0


def is_admin() -> bool:
    """Verifica si el proceso actual tiene privilegios de administrador."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except (AttributeError, OSError):
        return False


# ===========================================================================
# Dataclass para resultados de escaneo
# ===========================================================================

@dataclass
class ScanResult:
    """Resultado de un escaneo de una categoría."""
    category: str
    files_found: int = 0
    total_bytes: int = 0
    paths: list[str] = field(default_factory=list)

    @property
    def size_human(self) -> str:
        return _size_fmt(self.total_bytes)


# ===========================================================================
# 1. ESTADO DEL SISTEMA
# ===========================================================================

@dataclass
class SystemInfo:
    """Snapshot del estado actual del sistema."""
    # OS
    os_name: str = ""
    os_version: str = ""
    os_build: str = ""
    hostname: str = ""
    username: str = ""

    # CPU
    cpu_name: str = ""
    cpu_cores_physical: int = 0
    cpu_cores_logical: int = 0
    cpu_percent: float = 0.0
    cpu_freq_mhz: float = 0.0

    # RAM
    ram_total: int = 0
    ram_used: int = 0
    ram_available: int = 0
    ram_percent: float = 0.0

    # Disco
    disks: list[dict] = field(default_factory=list)

    # Uptime
    boot_time: str = ""
    uptime_human: str = ""


def get_system_info() -> SystemInfo:
    """
    Recopila información del sistema usando psutil y platform.
    Cada campo se obtiene en un try/except para que un fallo parcial
    no impida mostrar el resto.
    """
    info = SystemInfo()

    # --- OS ---
    try:
        info.os_name = f"{platform.system()} {platform.release()}"
        info.os_version = platform.version()
        info.os_build = platform.platform()
        info.hostname = platform.node()
        info.username = os.environ.get("USERNAME", os.environ.get("USER", ""))
    except Exception as e:
        logger.debug("Error obteniendo info del OS: %s", e)

    if psutil is None:
        return info

    # --- CPU ---
    try:
        info.cpu_cores_physical = psutil.cpu_count(logical=False) or 0
        info.cpu_cores_logical = psutil.cpu_count(logical=True) or 0
        # interval=1 bloquea 1 segundo pero da lectura real
        info.cpu_percent = psutil.cpu_percent(interval=1)

        freq = psutil.cpu_freq()
        if freq:
            info.cpu_freq_mhz = freq.current
    except Exception as e:
        logger.debug("Error obteniendo info de CPU: %s", e)

    # Nombre del CPU desde el registro (más confiable que platform.processor)
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
        )
        info.cpu_name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
        info.cpu_name = info.cpu_name.strip()
        winreg.CloseKey(key)
    except (OSError, PermissionError):
        info.cpu_name = platform.processor() or "Desconocido"

    # --- RAM ---
    try:
        mem = psutil.virtual_memory()
        info.ram_total = mem.total
        info.ram_used = mem.used
        info.ram_available = mem.available
        info.ram_percent = mem.percent
    except Exception as e:
        logger.debug("Error obteniendo info de RAM: %s", e)

    # --- Discos ---
    try:
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                info.disks.append({
                    "device": part.device,
                    "mountpoint": part.mountpoint,
                    "fstype": part.fstype,
                    "total": usage.total,
                    "used": usage.used,
                    "free": usage.free,
                    "percent": usage.percent,
                })
            except (OSError, PermissionError):
                pass
    except Exception as e:
        logger.debug("Error obteniendo info de discos: %s", e)

    # --- Uptime ---
    try:
        boot = datetime.datetime.fromtimestamp(psutil.boot_time())
        info.boot_time = boot.strftime("%Y-%m-%d %H:%M:%S")
        delta = datetime.datetime.now() - boot
        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes = remainder // 60
        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        parts.append(f"{minutes}m")
        info.uptime_human = " ".join(parts)
    except Exception as e:
        logger.debug("Error obteniendo uptime: %s", e)

    return info


# ===========================================================================
# 2. ESCÁNERES DE LIMPIEZA
# ===========================================================================

def scan_temp_files() -> ScanResult:
    """Escanea directorios temporales: %TEMP%, Windows\\Temp."""
    result = ScanResult(category="Archivos temporales")
    temp_dirs = [
        os.environ.get("TEMP", ""),
        os.environ.get("TMP", ""),
        os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "Temp"),
    ]
    temp_dirs = list({d for d in temp_dirs if d and os.path.isdir(d)})

    for temp_dir in temp_dirs:
        for root, dirs, files in os.walk(temp_dir):
            for name in files:
                fp = os.path.join(root, name)
                size = _safe_size(fp)
                if size > 0:
                    result.files_found += 1
                    result.total_bytes += size
                    result.paths.append(fp)

    return result


def scan_prefetch() -> ScanResult:
    """Escanea C:\\Windows\\Prefetch (requiere admin)."""
    result = ScanResult(category="Prefetch")
    prefetch_dir = os.path.join(
        os.environ.get("SYSTEMROOT", r"C:\Windows"), "Prefetch"
    )
    if not os.path.isdir(prefetch_dir):
        return result

    for name in os.listdir(prefetch_dir):
        fp = os.path.join(prefetch_dir, name)
        if os.path.isfile(fp):
            size = _safe_size(fp)
            result.files_found += 1
            result.total_bytes += size
            result.paths.append(fp)

    return result


def scan_browser_cache() -> ScanResult:
    """Escanea cachés de Chrome, Edge, Firefox, Brave."""
    result = ScanResult(category="Caché de navegadores")
    local = os.environ.get("LOCALAPPDATA", "")
    roaming = os.environ.get("APPDATA", "")

    if not local:
        return result

    chromium_caches = [
        os.path.join(local, "Google", "Chrome", "User Data", "Default", "Cache"),
        os.path.join(local, "Google", "Chrome", "User Data", "Default", "Code Cache"),
        os.path.join(local, "Microsoft", "Edge", "User Data", "Default", "Cache"),
        os.path.join(local, "Microsoft", "Edge", "User Data", "Default", "Code Cache"),
        os.path.join(local, "BraveSoftware", "Brave-Browser", "User Data", "Default", "Cache"),
    ]

    for cache_dir in chromium_caches:
        if not os.path.isdir(cache_dir):
            continue
        for root, dirs, files in os.walk(cache_dir):
            for name in files:
                fp = os.path.join(root, name)
                size = _safe_size(fp)
                if size > 0:
                    result.files_found += 1
                    result.total_bytes += size
                    result.paths.append(fp)

    if roaming:
        ff_profiles = os.path.join(roaming, "Mozilla", "Firefox", "Profiles")
        if os.path.isdir(ff_profiles):
            for profile in os.listdir(ff_profiles):
                cache_dir = os.path.join(ff_profiles, profile, "cache2", "entries")
                if not os.path.isdir(cache_dir):
                    continue
                for name in os.listdir(cache_dir):
                    fp = os.path.join(cache_dir, name)
                    if os.path.isfile(fp):
                        size = _safe_size(fp)
                        result.files_found += 1
                        result.total_bytes += size
                        result.paths.append(fp)

    return result


def scan_recycle_bin() -> ScanResult:
    """Escanea la papelera de reciclaje con la API de Windows."""
    result = ScanResult(category="Papelera de reciclaje")

    class SHQUERYRBINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_ulong),
            ("i64Size", ctypes.c_longlong),
            ("i64NumItems", ctypes.c_longlong),
        ]

    try:
        info = SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(SHQUERYRBINFO)
        hr = ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
        if hr == 0:
            result.total_bytes = info.i64Size
            result.files_found = info.i64NumItems
    except (AttributeError, OSError) as e:
        logger.warning("No se pudo consultar la papelera: %s", e)

    return result


def scan_large_files(
    min_size_mb: int = 100,
    scan_dirs: list[str] | None = None,
) -> ScanResult:
    """Busca archivos grandes (>min_size_mb) en directorios del usuario."""
    result = ScanResult(category=f"Archivos grandes (>{min_size_mb} MB)")
    user_profile = os.environ.get("USERPROFILE", "")

    if not user_profile:
        return result

    if scan_dirs is None:
        scan_dirs = [
            os.path.join(user_profile, "Downloads"),
            os.path.join(user_profile, "Desktop"),
            os.path.join(user_profile, "Documents"),
        ]

    min_bytes = min_size_mb * 1024 * 1024
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv"}

    for scan_dir in scan_dirs:
        if not os.path.isdir(scan_dir):
            continue
        for root, dirs, files in os.walk(scan_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in skip_dirs]
            for name in files:
                fp = os.path.join(root, name)
                size = _safe_size(fp)
                if size >= min_bytes:
                    result.files_found += 1
                    result.total_bytes += size
                    result.paths.append(fp)

    result.paths.sort(key=lambda p: _safe_size(p), reverse=True)
    return result


def scan_windows_update_cache() -> ScanResult:
    """Escanea la caché de Windows Update."""
    result = ScanResult(category="Caché de Windows Update")
    wu_dir = os.path.join(
        os.environ.get("SYSTEMROOT", r"C:\Windows"),
        "SoftwareDistribution", "Download",
    )
    if not os.path.isdir(wu_dir):
        return result

    for root, dirs, files in os.walk(wu_dir):
        for name in files:
            fp = os.path.join(root, name)
            size = _safe_size(fp)
            if size > 0:
                result.files_found += 1
                result.total_bytes += size
                result.paths.append(fp)

    return result


# ===========================================================================
# 3. FUNCIONES DE LIMPIEZA
# ===========================================================================

def clean_temp_files() -> tuple[int, int]:
    """Limpia archivos temporales del usuario."""
    total_files = 0
    total_bytes = 0
    temp_dirs = list({
        d for d in [os.environ.get("TEMP", ""), os.environ.get("TMP", "")]
        if d and os.path.isdir(d)
    })

    for temp_dir in temp_dirs:
        for root, dirs, files in os.walk(temp_dir, topdown=False):
            for name in files:
                f, b = _safe_remove(os.path.join(root, name))
                total_files += f
                total_bytes += b
            for name in dirs:
                try:
                    os.rmdir(os.path.join(root, name))
                except OSError:
                    pass
    return total_files, total_bytes


def clean_prefetch() -> tuple[int, int]:
    """Limpia el directorio Prefetch (requiere admin)."""
    prefetch_dir = os.path.join(
        os.environ.get("SYSTEMROOT", r"C:\Windows"), "Prefetch"
    )
    total_files = 0
    total_bytes = 0
    if not os.path.isdir(prefetch_dir):
        return 0, 0

    for name in os.listdir(prefetch_dir):
        fp = os.path.join(prefetch_dir, name)
        if os.path.isfile(fp):
            f, b = _safe_remove(fp)
            total_files += f
            total_bytes += b
    return total_files, total_bytes


def clean_browser_cache() -> tuple[int, int]:
    """Limpia cachés de todos los navegadores detectados."""
    total_files = 0
    total_bytes = 0
    local = os.environ.get("LOCALAPPDATA", "")
    roaming = os.environ.get("APPDATA", "")

    cache_dirs = []
    if local:
        cache_dirs.extend([
            os.path.join(local, "Google", "Chrome", "User Data", "Default", "Cache"),
            os.path.join(local, "Google", "Chrome", "User Data", "Default", "Code Cache"),
            os.path.join(local, "Microsoft", "Edge", "User Data", "Default", "Cache"),
            os.path.join(local, "Microsoft", "Edge", "User Data", "Default", "Code Cache"),
            os.path.join(local, "BraveSoftware", "Brave-Browser", "User Data", "Default", "Cache"),
        ])

    if roaming:
        ff_profiles = os.path.join(roaming, "Mozilla", "Firefox", "Profiles")
        if os.path.isdir(ff_profiles):
            for profile in os.listdir(ff_profiles):
                cache_dirs.append(
                    os.path.join(ff_profiles, profile, "cache2", "entries")
                )

    for cache_dir in cache_dirs:
        if os.path.isdir(cache_dir):
            f, b = _safe_rmtree(cache_dir)
            total_files += f
            total_bytes += b
    return total_files, total_bytes


def clean_recycle_bin() -> tuple[int, int]:
    """Vacía la papelera de reciclaje."""
    scan = scan_recycle_bin()
    try:
        flags = 0x00000001 | 0x00000002 | 0x00000004
        ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags)
    except (AttributeError, OSError) as e:
        logger.warning("No se pudo vaciar la papelera: %s", e)
        return 0, 0
    return scan.files_found, scan.total_bytes


def clean_windows_update_cache() -> tuple[int, int]:
    """Limpia la caché de Windows Update (requiere admin)."""
    wu_dir = os.path.join(
        os.environ.get("SYSTEMROOT", r"C:\Windows"),
        "SoftwareDistribution", "Download",
    )
    if not os.path.isdir(wu_dir):
        return 0, 0
    return _safe_rmtree(wu_dir)


# ===========================================================================
# 4. BUSCADOR DE DUPLICADOS
# ===========================================================================

@dataclass
class DuplicateGroup:
    """Grupo de archivos que son duplicados entre sí."""
    file_hash: str
    size: int
    paths: list[str] = field(default_factory=list)

    @property
    def size_human(self) -> str:
        return _size_fmt(self.size)

    @property
    def wasted_bytes(self) -> int:
        """Espacio desperdiciado = tamaño * (copias - 1)."""
        return self.size * (len(self.paths) - 1)


def _hash_file(path: str, chunk_size: int = 8192) -> str | None:
    """
    Calcula el hash SHA-256 de un archivo.
    Lee en chunks para no cargar archivos enormes en memoria.
    Retorna None si no se puede leer.
    """
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except (OSError, PermissionError):
        return None


def scan_duplicates(
    scan_dirs: list[str] | None = None,
    min_size_mb: float = 1.0,
    progress_callback=None,
) -> list[DuplicateGroup]:
    """
    Busca archivos duplicados en los directorios dados.

    Estrategia en dos fases para ser eficiente:
    1. Agrupa por tamaño (si un tamaño es único, no es duplicado).
    2. Solo hashea los archivos que comparten tamaño con otro.

    Esto evita hashear miles de archivos innecesariamente.

    Args:
        scan_dirs: Directorios a escanear. Default: Descargas, Escritorio, Documentos.
        min_size_mb: Tamaño mínimo en MB para considerar un archivo.
        progress_callback: Función(status_text) para actualizar la UI.
    """
    user_profile = os.environ.get("USERPROFILE", "")
    if scan_dirs is None and user_profile:
        scan_dirs = [
            os.path.join(user_profile, "Downloads"),
            os.path.join(user_profile, "Desktop"),
            os.path.join(user_profile, "Documents"),
        ]
    elif scan_dirs is None:
        return []

    min_bytes = int(min_size_mb * 1024 * 1024)
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv"}

    # --- Fase 1: Agrupar por tamaño ---
    if progress_callback:
        progress_callback("Fase 1: Indexando archivos por tamaño...")

    size_map: dict[int, list[str]] = {}
    for scan_dir in scan_dirs:
        if not os.path.isdir(scan_dir):
            continue
        for root, dirs, files in os.walk(scan_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in skip_dirs]
            for name in files:
                fp = os.path.join(root, name)
                size = _safe_size(fp)
                if size >= min_bytes:
                    size_map.setdefault(size, []).append(fp)

    # Filtrar: solo tamaños con más de un archivo
    candidates = {s: paths for s, paths in size_map.items() if len(paths) > 1}

    if not candidates:
        return []

    # --- Fase 2: Hashear solo candidatos ---
    total_to_hash = sum(len(p) for p in candidates.values())
    hashed = 0

    hash_map: dict[str, list[str]] = {}
    sizes_by_hash: dict[str, int] = {}

    for size, paths in candidates.items():
        for path in paths:
            if progress_callback:
                hashed += 1
                progress_callback(
                    f"Fase 2: Verificando {hashed}/{total_to_hash} archivos..."
                )
            file_hash = _hash_file(path)
            if file_hash:
                hash_map.setdefault(file_hash, []).append(path)
                sizes_by_hash[file_hash] = size

    # Construir resultado: solo hashes con más de un archivo
    groups = []
    for file_hash, paths in hash_map.items():
        if len(paths) > 1:
            groups.append(DuplicateGroup(
                file_hash=file_hash,
                size=sizes_by_hash[file_hash],
                paths=sorted(paths),
            ))

    # Ordenar por espacio desperdiciado (mayor primero)
    groups.sort(key=lambda g: g.wasted_bytes, reverse=True)
    return groups


# ===========================================================================
# 5. STARTUP MANAGER
# ===========================================================================

def get_startup_programs() -> list[dict]:
    """
    Lee los programas de inicio desde el registro de Windows.
    Busca en HKCU y HKLM (Run y RunOnce) + carpeta Startup.
    """
    programs = []
    locations = [
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", "HKCU"),
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\RunOnce", "HKCU"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run", "HKLM"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\RunOnce", "HKLM"),
    ]

    for hive, key_path, hive_name in locations:
        try:
            key = winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ)
        except (FileNotFoundError, PermissionError):
            continue

        try:
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                    programs.append({
                        "name": name,
                        "command": value,
                        "key_path": key_path,
                        "hive": hive,
                        "hive_name": hive_name,
                        "enabled": True,
                    })
                    i += 1
                except OSError:
                    break
        finally:
            winreg.CloseKey(key)

    startup_folder = os.path.join(
        os.environ.get("APPDATA", ""),
        "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
    )
    if os.path.isdir(startup_folder):
        for name in os.listdir(startup_folder):
            fp = os.path.join(startup_folder, name)
            programs.append({
                "name": name,
                "command": fp,
                "key_path": startup_folder,
                "hive": None,
                "hive_name": "Carpeta",
                "enabled": True,
            })

    return programs


def disable_startup_program(program: dict) -> bool:
    """Deshabilita un programa de inicio (registro o carpeta Startup)."""
    if program["hive"] is None:
        fp = program["command"]
        try:
            os.rename(fp, fp + ".disabled")
            return True
        except OSError as e:
            logger.warning("No se pudo deshabilitar %s: %s", fp, e)
            return False

    try:
        hive = program["hive"]
        key = winreg.OpenKey(hive, program["key_path"], 0, winreg.KEY_SET_VALUE)
        winreg.DeleteValue(key, program["name"])
        winreg.CloseKey(key)

        disabled_path = program["key_path"].replace("Run", "Run_VeClean_Disabled")
        try:
            disabled_key = winreg.OpenKey(hive, disabled_path, 0, winreg.KEY_SET_VALUE)
        except FileNotFoundError:
            disabled_key = winreg.CreateKey(hive, disabled_path)
        winreg.SetValueEx(disabled_key, program["name"], 0, winreg.REG_SZ, program["command"])
        winreg.CloseKey(disabled_key)
        return True
    except (OSError, PermissionError) as e:
        logger.warning("No se pudo deshabilitar %s: %s", program["name"], e)
        return False


def enable_startup_program(program: dict) -> bool:
    """Re-habilita un programa de inicio."""
    if program["hive"] is None:
        fp = program["command"]
        try:
            os.rename(fp + ".disabled", fp)
            return True
        except OSError:
            return False

    try:
        hive = program["hive"]
        key = winreg.OpenKey(hive, program["key_path"], 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, program["name"], 0, winreg.REG_SZ, program["command"])
        winreg.CloseKey(key)

        disabled_path = program["key_path"].replace("Run", "Run_VeClean_Disabled")
        try:
            disabled_key = winreg.OpenKey(hive, disabled_path, 0, winreg.KEY_SET_VALUE)
            winreg.DeleteValue(disabled_key, program["name"])
            winreg.CloseKey(disabled_key)
        except (FileNotFoundError, OSError):
            pass
        return True
    except (OSError, PermissionError) as e:
        logger.warning("No se pudo habilitar %s: %s", program["name"], e)
        return False


# ===========================================================================
# 6. DESINSTALADOR DE PROGRAMAS
# ===========================================================================

@dataclass
class InstalledProgram:
    """Programa instalado detectado en el registro."""
    name: str
    version: str = ""
    publisher: str = ""
    install_date: str = ""
    install_location: str = ""
    uninstall_string: str = ""
    estimated_size_kb: int = 0

    @property
    def size_human(self) -> str:
        if self.estimated_size_kb > 0:
            return _size_fmt(self.estimated_size_kb * 1024)
        return ""


def get_installed_programs() -> list[InstalledProgram]:
    """
    Lee los programas instalados del registro de Windows.
    Busca en las ubicaciones estándar (32-bit y 64-bit).
    Filtra entradas de sistema y actualizaciones.
    """
    programs = []
    seen_names = set()

    reg_paths = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]

    for hive, base_path in reg_paths:
        try:
            base_key = winreg.OpenKey(hive, base_path, 0, winreg.KEY_READ)
        except (FileNotFoundError, PermissionError):
            continue

        try:
            i = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(base_key, i)
                    i += 1
                except OSError:
                    break

                try:
                    subkey = winreg.OpenKey(base_key, subkey_name, 0, winreg.KEY_READ)
                except (FileNotFoundError, PermissionError):
                    continue

                try:
                    # Leer DisplayName — si no existe, no es un programa visible
                    try:
                        name, _ = winreg.QueryValueEx(subkey, "DisplayName")
                    except FileNotFoundError:
                        continue

                    if not name or name in seen_names:
                        continue

                    # Filtrar entradas de sistema (sin UninstallString o marcadas como sistema)
                    try:
                        sys_component, _ = winreg.QueryValueEx(subkey, "SystemComponent")
                        if sys_component == 1:
                            continue
                    except FileNotFoundError:
                        pass

                    # Filtrar actualizaciones de Windows (KB...)
                    try:
                        parent, _ = winreg.QueryValueEx(subkey, "ParentKeyName")
                        if parent:
                            continue
                    except FileNotFoundError:
                        pass

                    def _read(key, val_name):
                        try:
                            v, _ = winreg.QueryValueEx(key, val_name)
                            return str(v) if v else ""
                        except (FileNotFoundError, TypeError):
                            return ""

                    uninstall_str = _read(subkey, "UninstallString")

                    size_str = _read(subkey, "EstimatedSize")
                    try:
                        estimated_size = int(size_str) if size_str else 0
                    except ValueError:
                        estimated_size = 0

                    prog = InstalledProgram(
                        name=name,
                        version=_read(subkey, "DisplayVersion"),
                        publisher=_read(subkey, "Publisher"),
                        install_date=_read(subkey, "InstallDate"),
                        install_location=_read(subkey, "InstallLocation"),
                        uninstall_string=uninstall_str,
                        estimated_size_kb=estimated_size,
                    )
                    programs.append(prog)
                    seen_names.add(name)

                finally:
                    winreg.CloseKey(subkey)
        finally:
            winreg.CloseKey(base_key)

    # Ordenar alfabéticamente
    programs.sort(key=lambda p: p.name.lower())
    return programs


def uninstall_program(program: InstalledProgram) -> bool:
    """
    Ejecuta el desinstalador de un programa.
    Lanza el proceso y retorna True si se inició correctamente.
    El desinstalador generalmente tiene su propia UI.
    """
    if not program.uninstall_string:
        logger.warning("No hay uninstall string para %s", program.name)
        return False

    try:
        cmd = program.uninstall_string
        # Algunos uninstall strings vienen con comillas, otros no
        # subprocess.Popen con shell=True maneja ambos casos
        subprocess.Popen(cmd, shell=True)
        return True
    except (OSError, subprocess.SubprocessError) as e:
        logger.error("Error desinstalando %s: %s", program.name, e)
        return False


# ===========================================================================
# 7. INFO DE RED
# ===========================================================================

@dataclass
class NetworkInfo:
    """Información de red del equipo."""
    hostname: str = ""
    local_ip: str = ""
    public_ip: str = ""
    mac_address: str = ""
    dns_servers: list[str] = field(default_factory=list)
    gateway: str = ""
    interfaces: list[dict] = field(default_factory=list)


def get_network_info() -> NetworkInfo:
    """
    Recopila información de red.
    La IP pública se obtiene con un servicio externo (puede fallar sin internet).
    """
    info = NetworkInfo()

    try:
        info.hostname = socket.gethostname()
    except Exception:
        pass

    # IP local: conectar un socket UDP sin enviar nada para obtener la IP de salida
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        info.local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        info.local_ip = "No disponible"

    # IP pública vía servicio externo
    try:
        import urllib.request
        response = urllib.request.urlopen("https://api.ipify.org", timeout=5)
        info.public_ip = response.read().decode("utf-8").strip()
    except Exception:
        info.public_ip = "No disponible (sin internet)"

    # Interfaces de red con psutil
    if psutil:
        try:
            addrs = psutil.net_if_addrs()
            for iface_name, iface_addrs in addrs.items():
                for addr in iface_addrs:
                    if addr.family == socket.AF_INET and addr.address != "127.0.0.1":
                        iface_info = {
                            "name": iface_name,
                            "ip": addr.address,
                            "netmask": addr.netmask or "",
                        }
                        info.interfaces.append(iface_info)
                    # MAC address
                    if addr.family == psutil.AF_LINK:
                        if addr.address and addr.address != "00:00:00:00:00:00":
                            if not info.mac_address:
                                info.mac_address = addr.address
        except Exception as e:
            logger.debug("Error obteniendo interfaces: %s", e)

    # DNS y Gateway via ipconfig (más confiable en Windows)
    try:
        output = subprocess.check_output(
            ["ipconfig", "/all"], encoding="cp850", errors="replace", timeout=10
        )
        for line in output.splitlines():
            line = line.strip()
            if "Puerta de enlace" in line or "Default Gateway" in line:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    gw = parts[1].strip()
                    if gw and gw != "0.0.0.0" and not info.gateway:
                        info.gateway = gw
            elif "DNS" in line and "Servers" in line or "DNS" in line and "servidores" in line.lower():
                parts = line.split(":", 1)
                if len(parts) == 2:
                    dns = parts[1].strip()
                    if dns:
                        info.dns_servers.append(dns)
    except (subprocess.SubprocessError, OSError):
        pass

    return info


# ===========================================================================
# 8. GENERADOR DE REPORTE
# ===========================================================================

def generate_report(output_path: str | None = None) -> str:
    """
    Genera un reporte completo del estado del sistema como texto plano.
    Útil para enviar por WhatsApp/email cuando alguien necesita soporte.

    Si output_path es None, genera en el escritorio del usuario.
    Retorna la ruta del archivo generado.
    """
    if output_path is None:
        desktop = os.path.join(os.environ.get("USERPROFILE", "."), "Desktop")
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(desktop, f"VeClean_Reporte_{timestamp}.txt")

    lines = []
    lines.append("=" * 60)
    lines.append("  REPORTE DE ESTADO DEL SISTEMA — VeClean")
    lines.append(f"  Generado: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 60)
    lines.append("")

    # --- Sistema ---
    sys_info = get_system_info()
    lines.append("[ SISTEMA OPERATIVO ]")
    lines.append(f"  OS:        {sys_info.os_name}")
    lines.append(f"  Version:   {sys_info.os_version}")
    lines.append(f"  Equipo:    {sys_info.hostname}")
    lines.append(f"  Usuario:   {sys_info.username}")
    lines.append(f"  Uptime:    {sys_info.uptime_human} (desde {sys_info.boot_time})")
    lines.append(f"  Admin:     {'Si' if is_admin() else 'No'}")
    lines.append("")

    # --- CPU ---
    lines.append("[ CPU ]")
    lines.append(f"  Modelo:    {sys_info.cpu_name}")
    lines.append(f"  Nucleos:   {sys_info.cpu_cores_physical} fisicos / {sys_info.cpu_cores_logical} logicos")
    lines.append(f"  Uso:       {sys_info.cpu_percent}%")
    if sys_info.cpu_freq_mhz:
        lines.append(f"  Frecuencia: {sys_info.cpu_freq_mhz:.0f} MHz")
    lines.append("")

    # --- RAM ---
    lines.append("[ MEMORIA RAM ]")
    lines.append(f"  Total:     {_size_fmt(sys_info.ram_total)}")
    lines.append(f"  Usada:     {_size_fmt(sys_info.ram_used)} ({sys_info.ram_percent}%)")
    lines.append(f"  Libre:     {_size_fmt(sys_info.ram_available)}")
    lines.append("")

    # --- Discos ---
    lines.append("[ DISCOS ]")
    for disk in sys_info.disks:
        lines.append(f"  {disk['device']} ({disk['fstype']})")
        lines.append(f"    Total: {_size_fmt(disk['total'])}  |  "
                     f"Usado: {_size_fmt(disk['used'])} ({disk['percent']}%)  |  "
                     f"Libre: {_size_fmt(disk['free'])}")
    lines.append("")

    # --- Red ---
    net_info = get_network_info()
    lines.append("[ RED ]")
    lines.append(f"  IP Local:  {net_info.local_ip}")
    lines.append(f"  IP Publica: {net_info.public_ip}")
    lines.append(f"  Gateway:   {net_info.gateway}")
    lines.append(f"  MAC:       {net_info.mac_address}")
    if net_info.dns_servers:
        lines.append(f"  DNS:       {', '.join(net_info.dns_servers)}")
    lines.append("")

    lines.append("=" * 60)
    lines.append("  Generado con VeClean — https://github.com/tu-usuario/veclean")
    lines.append("=" * 60)

    report_text = "\n".join(lines)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    return output_path
