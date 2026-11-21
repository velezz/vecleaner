"""
gui.py — Interfaz gráfica de VeClean v2.0.0.

GUI con CustomTkinter organizada en 7 tabs:
  1. Estado       — dashboard del sistema (CPU, RAM, disco, uptime)
  2. Limpieza     — escanear y limpiar archivos basura
  3. Duplicados   — buscar archivos duplicados por hash
  4. Archivos     — encontrar archivos grandes
  5. Inicio       — gestionar programas de inicio de Windows
  6. Programas    — desinstalador de programas
  7. Red          — info de red + generador de reporte

Toda la lógica pesada corre en hilos daemon para no congelar la UI.
Se usa self.after(0, callback) para actualizar widgets desde hilos.
"""

import os
import sys
import subprocess
import threading
import logging
import customtkinter as ctk
from tkinter import messagebox, filedialog
from PIL import Image

import scanner

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

APP_NAME = "VeClean"
APP_VERSION = "2.0.0"
WINDOW_WIDTH = 900
WINDOW_HEIGHT = 650

logger = logging.getLogger("veclean.gui")

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Colores del tema
COLOR_BG_DARK = "#1a1a2e"
COLOR_ACCENT = "#3498db"
COLOR_SUCCESS = "#2ecc71"
COLOR_WARNING = "#e67e22"
COLOR_DANGER = "#e74c3c"
COLOR_MUTED = "#7f8c8d"


def _get_logo_path() -> str | None:
    """Busca el logo en las rutas posibles (dev y empaquetado)."""
    candidates = [
        os.path.join(os.path.dirname(__file__), "logo.ico"),
        os.path.join(getattr(sys, "_MEIPASS", ""), "logo.ico"),
        "logo.ico",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


# ===========================================================================
# Clase principal
# ===========================================================================

class VeCleanApp(ctk.CTk):
    """Ventana principal de VeClean."""

    def __init__(self):
        super().__init__()

        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.minsize(800, 550)
        self.resizable(True, True)

        # Icono de ventana
        logo_path = _get_logo_path()
        if logo_path:
            try:
                self.iconbitmap(logo_path)
            except Exception:
                pass

        # Estado interno
        self._scan_running = False
        self._clean_running = False
        self._scan_results_map: dict[str, scanner.ScanResult] = {}

        self._build_ui()

    # ===================================================================
    # UI principal
    # ===================================================================

    def _build_ui(self):
        """Construye el header y los 7 tabs."""
        # --- Header ---
        header = ctk.CTkFrame(self, height=55, corner_radius=0,
                              fg_color=COLOR_BG_DARK)
        header.pack(fill="x")
        header.pack_propagate(False)

        # Logo + nombre
        logo_path = _get_logo_path()
        if logo_path:
            try:
                logo_img = Image.open(logo_path)
                logo_img = logo_img.resize((36, 36), Image.LANCZOS)
                self._logo_ctk = ctk.CTkImage(logo_img, size=(36, 36))
                ctk.CTkLabel(
                    header, image=self._logo_ctk, text=""
                ).pack(side="left", padx=(15, 5), pady=8)
            except Exception:
                pass

        ctk.CTkLabel(
            header,
            text=f"{APP_NAME}",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).pack(side="left", padx=(5, 2), pady=8)

        ctk.CTkLabel(
            header,
            text=f"v{APP_VERSION}",
            font=ctk.CTkFont(size=11),
            text_color=COLOR_MUTED,
        ).pack(side="left", padx=(0, 20), pady=(14, 8))

        # Indicador de admin
        is_adm = scanner.is_admin()
        admin_text = "⚡ Administrador" if is_adm else "👤 Usuario"
        admin_color = COLOR_SUCCESS if is_adm else COLOR_WARNING
        ctk.CTkLabel(
            header, text=admin_text,
            font=ctk.CTkFont(size=11),
            text_color=admin_color,
        ).pack(side="right", padx=15, pady=8)

        # --- Tabs ---
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=12, pady=(8, 12))

        self.tab_status   = self.tabview.add("💻 Estado")
        self.tab_clean    = self.tabview.add("🗑️ Limpieza")
        self.tab_dupes    = self.tabview.add("📋 Duplicados")
        self.tab_large    = self.tabview.add("📦 Grandes")
        self.tab_startup  = self.tabview.add("🚀 Inicio")
        self.tab_programs = self.tabview.add("📦 Programas")
        self.tab_network  = self.tabview.add("🌐 Red")

        self._build_status_tab()
        self._build_clean_tab()
        self._build_dupes_tab()
        self._build_large_tab()
        self._build_startup_tab()
        self._build_programs_tab()
        self._build_network_tab()

    # ===================================================================
    # Tab 1: Estado del sistema
    # ===================================================================

    def _build_status_tab(self):
        tab = self.tab_status

        # Botón refrescar
        btn_frame = ctk.CTkFrame(tab)
        btn_frame.pack(fill="x", padx=10, pady=(10, 5))

        self.status_refresh_btn = ctk.CTkButton(
            btn_frame, text="🔄 Actualizar estado",
            command=self._on_refresh_status, width=200, height=35,
        )
        self.status_refresh_btn.pack(side="left", padx=10, pady=8)

        self.status_msg = ctk.CTkLabel(
            btn_frame, text="Presiona para ver el estado del sistema",
            font=ctk.CTkFont(size=12), text_color=COLOR_MUTED,
        )
        self.status_msg.pack(side="left", padx=15, pady=8)

        # Frame scrollable para la info
        self.status_info_frame = ctk.CTkScrollableFrame(tab)
        self.status_info_frame.pack(fill="both", expand=True, padx=10, pady=5)

    def _on_refresh_status(self):
        self.status_refresh_btn.configure(state="disabled", text="⏳ Cargando...")
        self.status_msg.configure(text="Recopilando información...")

        for w in self.status_info_frame.winfo_children():
            w.destroy()

        thread = threading.Thread(target=self._status_worker, daemon=True)
        thread.start()

    def _status_worker(self):
        try:
            info = scanner.get_system_info()
            self.after(0, self._render_status, info)
        except Exception as e:
            self.after(0, self.status_msg.configure,
                       {"text": f"Error: {e}", "text_color": COLOR_DANGER})
            self.after(0, self.status_refresh_btn.configure,
                       {"state": "normal", "text": "🔄 Actualizar estado"})

    def _render_status(self, info: scanner.SystemInfo):
        self.status_refresh_btn.configure(state="normal", text="🔄 Actualizar estado")
        self.status_msg.configure(text="Estado actualizado")
        parent = self.status_info_frame

        def section(title):
            ctk.CTkLabel(parent, text=title,
                         font=ctk.CTkFont(size=15, weight="bold"),
                         ).pack(anchor="w", padx=10, pady=(12, 4))

        def row(label, value, color=None):
            f = ctk.CTkFrame(parent)
            f.pack(fill="x", padx=10, pady=1)
            ctk.CTkLabel(f, text=label, font=ctk.CTkFont(size=12),
                         width=160, anchor="w", text_color=COLOR_MUTED,
                         ).pack(side="left", padx=(10, 5), pady=4)
            ctk.CTkLabel(f, text=str(value),
                         font=ctk.CTkFont(size=12, weight="bold"),
                         text_color=color or "white", anchor="w",
                         ).pack(side="left", padx=5, pady=4)

        def bar(percent, label_text=""):
            f = ctk.CTkFrame(parent)
            f.pack(fill="x", padx=10, pady=2)
            if label_text:
                ctk.CTkLabel(f, text=label_text, width=160, anchor="w",
                             font=ctk.CTkFont(size=12), text_color=COLOR_MUTED,
                             ).pack(side="left", padx=(10, 5), pady=4)
            color = COLOR_SUCCESS if percent < 70 else (COLOR_WARNING if percent < 90 else COLOR_DANGER)
            pb = ctk.CTkProgressBar(f, width=300, progress_color=color)
            pb.pack(side="left", padx=5, pady=4)
            pb.set(percent / 100)
            ctk.CTkLabel(f, text=f"{percent:.0f}%",
                         font=ctk.CTkFont(size=12, weight="bold"),
                         text_color=color,
                         ).pack(side="left", padx=10, pady=4)

        # --- Renderizar secciones ---
        section("🖥️ Sistema operativo")
        row("SO", info.os_name)
        row("Versión", info.os_version)
        row("Equipo", info.hostname)
        row("Usuario", info.username)
        row("Uptime", f"{info.uptime_human} (desde {info.boot_time})")

        section("⚙️ Procesador")
        row("CPU", info.cpu_name)
        row("Núcleos", f"{info.cpu_cores_physical} físicos / {info.cpu_cores_logical} lógicos")
        if info.cpu_freq_mhz:
            row("Frecuencia", f"{info.cpu_freq_mhz:.0f} MHz")
        bar(info.cpu_percent, "Uso CPU")

        section("🧠 Memoria RAM")
        row("Total", scanner._size_fmt(info.ram_total))
        row("En uso", scanner._size_fmt(info.ram_used))
        row("Disponible", scanner._size_fmt(info.ram_available))
        bar(info.ram_percent, "Uso RAM")

        section("💾 Discos")
        for disk in info.disks:
            row(disk["device"],
                f"{scanner._size_fmt(disk['used'])} / {scanner._size_fmt(disk['total'])} "
                f"({scanner._size_fmt(disk['free'])} libres)")
            bar(disk["percent"], f"Uso {disk['mountpoint']}")

    # ===================================================================
    # Tab 2: Limpieza
    # ===================================================================

    def _build_clean_tab(self):
        tab = self.tab_clean

        info_frame = ctk.CTkFrame(tab)
        info_frame.pack(fill="x", padx=10, pady=(10, 5))
        ctk.CTkLabel(
            info_frame,
            text="Escanea para ver qué se puede limpiar. Luego selecciona y limpia.",
            font=ctk.CTkFont(size=13), wraplength=750,
        ).pack(padx=15, pady=10)

        # Checkboxes
        self.clean_checks_frame = ctk.CTkScrollableFrame(tab, label_text="Categorías")
        self.clean_checks_frame.pack(fill="both", expand=True, padx=10, pady=5)

        self.clean_vars: dict[str, ctk.BooleanVar] = {}
        self.clean_labels: dict[str, ctk.CTkLabel] = {}

        categories = [
            ("temp", "Archivos temporales", "%TEMP% y Windows\\Temp"),
            ("prefetch", "Prefetch", "Caché de inicio de programas (admin)"),
            ("browser", "Caché de navegadores", "Chrome, Edge, Firefox, Brave"),
            ("recycle", "Papelera de reciclaje", "Archivos eliminados"),
            ("wupdate", "Windows Update", "Descargas de actualizaciones (admin)"),
        ]

        for key, name, description in categories:
            row = ctk.CTkFrame(self.clean_checks_frame)
            row.pack(fill="x", padx=5, pady=3)

            var = ctk.BooleanVar(value=True)
            self.clean_vars[key] = var

            ctk.CTkCheckBox(
                row, text=name, variable=var,
                font=ctk.CTkFont(size=13), width=220,
            ).pack(side="left", padx=(10, 15), pady=8)

            ctk.CTkLabel(
                row, text=description,
                font=ctk.CTkFont(size=11), text_color=COLOR_MUTED,
            ).pack(side="left", padx=5, pady=8)

            size_label = ctk.CTkLabel(
                row, text="",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=COLOR_ACCENT,
            )
            size_label.pack(side="right", padx=15, pady=8)
            self.clean_labels[key] = size_label

        # Barra inferior
        bottom = ctk.CTkFrame(tab)
        bottom.pack(fill="x", padx=10, pady=10)

        self.scan_btn = ctk.CTkButton(
            bottom, text="🔍 Escanear", command=self._on_scan,
            width=130, height=38, font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.scan_btn.pack(side="left", padx=10, pady=10)

        self.clean_btn = ctk.CTkButton(
            bottom, text="🧹 Limpiar seleccionados", command=self._on_clean,
            width=190, height=38, font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=COLOR_DANGER, hover_color="#c0392b", state="disabled",
        )
        self.clean_btn.pack(side="left", padx=10, pady=10)

        self.clean_progress = ctk.CTkProgressBar(bottom, width=180)
        self.clean_progress.pack(side="left", padx=10, pady=10)
        self.clean_progress.set(0)

        self.clean_status = ctk.CTkLabel(
            bottom, text="Listo", font=ctk.CTkFont(size=12),
        )
        self.clean_status.pack(side="right", padx=15, pady=10)

    def _on_scan(self):
        if self._scan_running:
            return
        self._scan_running = True
        self.scan_btn.configure(state="disabled", text="⏳ Escaneando...")
        self.clean_btn.configure(state="disabled")
        self.clean_progress.set(0)
        self.clean_status.configure(text="Escaneando...")
        for label in self.clean_labels.values():
            label.configure(text="", text_color=COLOR_ACCENT)

        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        scanners = {
            "temp": scanner.scan_temp_files,
            "prefetch": scanner.scan_prefetch,
            "browser": scanner.scan_browser_cache,
            "recycle": scanner.scan_recycle_bin,
            "wupdate": scanner.scan_windows_update_cache,
        }
        results = {}
        total = len(scanners)
        for i, (key, fn) in enumerate(scanners.items()):
            try:
                r = fn()
                results[key] = r
                self.after(0, self._update_scan_label, key, r)
            except Exception as e:
                logger.error("Error escaneando %s: %s", key, e)
                results[key] = scanner.ScanResult(category=key)
            self.after(0, self.clean_progress.set, (i + 1) / total)

        self._scan_results_map = results
        self.after(0, self._scan_complete)

    def _update_scan_label(self, key, result):
        if key in self.clean_labels:
            if result.total_bytes > 0:
                text = f"{result.size_human} ({result.files_found} archivos)"
            else:
                text = "Nada"
            self.clean_labels[key].configure(text=text)

    def _scan_complete(self):
        self._scan_running = False
        self.scan_btn.configure(state="normal", text="🔍 Escanear")
        self.clean_btn.configure(state="normal")
        total_bytes = sum(r.total_bytes for r in self._scan_results_map.values())
        self.clean_status.configure(
            text=f"Se pueden liberar: {scanner._size_fmt(total_bytes)}")
        self.clean_progress.set(1)

    def _on_clean(self):
        if self._clean_running:
            return
        selected = [k for k, v in self.clean_vars.items() if v.get()]
        if not selected:
            messagebox.showinfo(APP_NAME, "No hay categorías seleccionadas.")
            return
        if not messagebox.askyesno(
            "Confirmar limpieza",
            "¿Limpiar las categorías seleccionadas?\nEsta acción no se puede deshacer.",
        ):
            return

        self._clean_running = True
        self.clean_btn.configure(state="disabled", text="⏳ Limpiando...")
        self.scan_btn.configure(state="disabled")
        self.clean_progress.set(0)

        threading.Thread(
            target=self._clean_worker, args=(selected,), daemon=True
        ).start()

    def _clean_worker(self, selected):
        cleaners = {
            "temp": scanner.clean_temp_files,
            "prefetch": scanner.clean_prefetch,
            "browser": scanner.clean_browser_cache,
            "recycle": scanner.clean_recycle_bin,
            "wupdate": scanner.clean_windows_update_cache,
        }
        total_files, total_bytes = 0, 0
        total = len(selected)
        for i, key in enumerate(selected):
            if key in cleaners:
                try:
                    self.after(0, self.clean_status.configure,
                              {"text": f"Limpiando: {key}..."})
                    f, b = cleaners[key]()
                    total_files += f
                    total_bytes += b
                    self.after(0, self.clean_labels[key].configure,
                              {"text": "✅ Limpio", "text_color": COLOR_SUCCESS})
                except Exception as e:
                    logger.error("Error limpiando %s: %s", key, e)
                    self.after(0, self.clean_labels[key].configure,
                              {"text": "❌ Error", "text_color": COLOR_DANGER})
            self.after(0, self.clean_progress.set, (i + 1) / total)

        self.after(0, self._clean_complete, total_files, total_bytes)

    def _clean_complete(self, total_files, total_bytes):
        self._clean_running = False
        self.clean_btn.configure(state="normal", text="🧹 Limpiar seleccionados")
        self.scan_btn.configure(state="normal")
        self.clean_progress.set(1)
        freed = scanner._size_fmt(total_bytes)
        self.clean_status.configure(text=f"✅ {total_files} archivos — {freed} liberados")
        messagebox.showinfo("Limpieza completada",
                            f"{total_files} archivos eliminados.\nEspacio liberado: {freed}")

    # ===================================================================
    # Tab 3: Duplicados
    # ===================================================================

    def _build_dupes_tab(self):
        tab = self.tab_dupes

        config = ctk.CTkFrame(tab)
        config.pack(fill="x", padx=10, pady=(10, 5))

        ctk.CTkLabel(config, text="Tamaño mín. (MB):",
                     font=ctk.CTkFont(size=13),
                     ).pack(side="left", padx=(15, 5), pady=10)

        self.dupe_min_size = ctk.StringVar(value="1")
        ctk.CTkEntry(config, textvariable=self.dupe_min_size, width=60,
                     ).pack(side="left", padx=5, pady=10)

        self.dupe_scan_btn = ctk.CTkButton(
            config, text="🔍 Buscar duplicados",
            command=self._on_scan_dupes, width=180, height=35,
        )
        self.dupe_scan_btn.pack(side="left", padx=15, pady=10)

        self.dupe_status = ctk.CTkLabel(
            config, text="Busca archivos idénticos por contenido (hash SHA-256)",
            font=ctk.CTkFont(size=11), text_color=COLOR_MUTED,
        )
        self.dupe_status.pack(side="right", padx=15, pady=10)

        self.dupe_list = ctk.CTkScrollableFrame(tab, label_text="Duplicados encontrados")
        self.dupe_list.pack(fill="both", expand=True, padx=10, pady=(5, 10))

    def _on_scan_dupes(self):
        try:
            min_mb = float(self.dupe_min_size.get())
            if min_mb < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror(APP_NAME, "Ingresa un número válido.")
            return

        self.dupe_scan_btn.configure(state="disabled", text="⏳ Buscando...")
        self.dupe_status.configure(text="Indexando archivos...")
        for w in self.dupe_list.winfo_children():
            w.destroy()

        def progress_cb(text):
            self.after(0, self.dupe_status.configure, {"text": text})

        threading.Thread(
            target=self._dupe_worker, args=(min_mb, progress_cb), daemon=True
        ).start()

    def _dupe_worker(self, min_mb, progress_cb):
        try:
            groups = scanner.scan_duplicates(min_size_mb=min_mb,
                                             progress_callback=progress_cb)
            self.after(0, self._render_dupes, groups)
        except Exception as e:
            self.after(0, self.dupe_status.configure,
                       {"text": f"Error: {e}", "text_color": COLOR_DANGER})
            self.after(0, self.dupe_scan_btn.configure,
                       {"state": "normal", "text": "🔍 Buscar duplicados"})

    def _render_dupes(self, groups: list[scanner.DuplicateGroup]):
        self.dupe_scan_btn.configure(state="normal", text="🔍 Buscar duplicados")

        if not groups:
            self.dupe_status.configure(text="No se encontraron duplicados.")
            return

        total_wasted = sum(g.wasted_bytes for g in groups)
        self.dupe_status.configure(
            text=f"{len(groups)} grupos — {scanner._size_fmt(total_wasted)} desperdiciados"
        )

        for i, group in enumerate(groups[:30]):  # max 30 grupos
            grp_frame = ctk.CTkFrame(self.dupe_list)
            grp_frame.pack(fill="x", padx=5, pady=4)

            ctk.CTkLabel(
                grp_frame,
                text=f"Grupo {i+1} — {group.size_human} × {len(group.paths)} copias "
                     f"({scanner._size_fmt(group.wasted_bytes)} desperdiciados)",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=COLOR_WARNING,
            ).pack(anchor="w", padx=10, pady=(6, 2))

            for j, path in enumerate(group.paths):
                row = ctk.CTkFrame(grp_frame)
                row.pack(fill="x", padx=15, pady=1)

                # Marcar el primero como "Original"
                if j == 0:
                    ctk.CTkLabel(
                        row, text="Original",
                        font=ctk.CTkFont(size=10, weight="bold"),
                        text_color=COLOR_SUCCESS, width=55,
                    ).pack(side="left", padx=(5, 2), pady=3)

                display = path
                if len(display) > 60:
                    display = "..." + display[-57:]

                ctk.CTkLabel(
                    row, text=display,
                    font=ctk.CTkFont(size=11), anchor="w",
                ).pack(side="left", padx=5, pady=3)

                # Botón ubicar (selecciona el archivo en Explorer)
                ctk.CTkButton(
                    row, text="📂", width=30, height=24,
                    font=ctk.CTkFont(size=11),
                    command=lambda p=path: subprocess.Popen(
                        f'explorer /select,"{p}"'),
                ).pack(side="right", padx=(5, 5), pady=3)

                # Botón eliminar solo en copias (no el original)
                if j > 0:
                    ctk.CTkButton(
                        row, text="🗑️ Eliminar", width=80, height=24,
                        font=ctk.CTkFont(size=11),
                        fg_color=COLOR_DANGER, hover_color="#c0392b",
                        command=lambda p=path, r=row: self._delete_file(p, r),
                    ).pack(side="right", padx=(5, 2), pady=3)

    # ===================================================================
    # Tab 4: Archivos grandes
    # ===================================================================

    def _build_large_tab(self):
        tab = self.tab_large

        config = ctk.CTkFrame(tab)
        config.pack(fill="x", padx=10, pady=(10, 5))

        ctk.CTkLabel(config, text="Mínimo (MB):",
                     font=ctk.CTkFont(size=13),
                     ).pack(side="left", padx=(15, 5), pady=10)

        self.large_min_size = ctk.StringVar(value="100")
        ctk.CTkEntry(config, textvariable=self.large_min_size, width=70,
                     ).pack(side="left", padx=5, pady=10)

        self.large_scan_btn = ctk.CTkButton(
            config, text="🔍 Buscar archivos grandes",
            command=self._on_scan_large, width=200, height=35,
        )
        self.large_scan_btn.pack(side="left", padx=15, pady=10)

        self.large_status = ctk.CTkLabel(config, text="",
                                          font=ctk.CTkFont(size=12))
        self.large_status.pack(side="right", padx=15, pady=10)

        self.large_list = ctk.CTkScrollableFrame(tab, label_text="Archivos encontrados")
        self.large_list.pack(fill="both", expand=True, padx=10, pady=(5, 10))

    def _on_scan_large(self):
        try:
            min_size = int(self.large_min_size.get())
            if min_size < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror(APP_NAME, "Ingresa un número válido.")
            return

        self.large_scan_btn.configure(state="disabled", text="⏳ Buscando...")
        self.large_status.configure(text="Buscando...")
        for w in self.large_list.winfo_children():
            w.destroy()

        threading.Thread(
            target=self._large_worker, args=(min_size,), daemon=True
        ).start()

    def _large_worker(self, min_size_mb):
        try:
            result = scanner.scan_large_files(min_size_mb=min_size_mb)
            self.after(0, self._render_large, result)
        except Exception as e:
            self.after(0, self.large_status.configure,
                       {"text": f"Error: {e}", "text_color": COLOR_DANGER})
            self.after(0, self.large_scan_btn.configure,
                       {"state": "normal", "text": "🔍 Buscar archivos grandes"})

    def _render_large(self, result: scanner.ScanResult):
        self.large_scan_btn.configure(state="normal",
                                       text="🔍 Buscar archivos grandes")
        if result.files_found == 0:
            self.large_status.configure(text="No se encontraron archivos grandes.")
            return

        self.large_status.configure(
            text=f"{result.files_found} archivos — {result.size_human}")

        for path in result.paths[:50]:
            size = scanner._safe_size(path)
            if size == 0:
                continue

            row = ctk.CTkFrame(self.large_list)
            row.pack(fill="x", padx=5, pady=2)

            filename = os.path.basename(path)
            if len(filename) > 35:
                filename = filename[:32] + "..."

            ctk.CTkLabel(
                row, text=filename,
                font=ctk.CTkFont(size=12, weight="bold"),
                width=220, anchor="w",
            ).pack(side="left", padx=(10, 5), pady=5)

            folder = os.path.dirname(path)
            if len(folder) > 35:
                folder = "..." + folder[-32:]
            ctk.CTkLabel(
                row, text=folder,
                font=ctk.CTkFont(size=10), text_color=COLOR_MUTED,
                width=220, anchor="w",
            ).pack(side="left", padx=5, pady=5)

            ctk.CTkLabel(
                row, text=scanner._size_fmt(size),
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=COLOR_DANGER, width=80,
            ).pack(side="left", padx=5, pady=5)

            # Botón ubicar (selecciona el archivo en Explorer)
            ctk.CTkButton(
                row, text="📂", width=30, height=24,
                font=ctk.CTkFont(size=11),
                command=lambda p=path: subprocess.Popen(
                    f'explorer /select,"{p}"'),
            ).pack(side="right", padx=(5, 10), pady=5)

            # Botón eliminar con confirmación
            ctk.CTkButton(
                row, text="🗑️ Eliminar", width=80, height=24,
                font=ctk.CTkFont(size=11),
                fg_color=COLOR_DANGER, hover_color="#c0392b",
                command=lambda p=path, r=row: self._delete_file(p, r),
            ).pack(side="right", padx=5, pady=5)

    # ===================================================================
    # Acción compartida: Eliminar archivo
    # ===================================================================

    def _delete_file(self, path: str, row_widget):
        """Elimina un archivo con confirmación y quita la fila de la lista."""
        filename = os.path.basename(path)
        size = scanner._safe_size(path)

        if not messagebox.askyesno(
            "Confirmar eliminación",
            f"¿Eliminar '{filename}'?\n"
            f"Tamaño: {scanner._size_fmt(size)}\n\n"
            f"Ruta: {path}\n\n"
            "Esta acción no se puede deshacer.",
        ):
            return

        try:
            os.remove(path)
            # Quitar la fila de la UI
            row_widget.destroy()
            messagebox.showinfo(APP_NAME,
                f"'{filename}' eliminado.\n"
                f"Espacio liberado: {scanner._size_fmt(size)}")
        except PermissionError:
            messagebox.showerror(APP_NAME,
                f"No se pudo eliminar '{filename}'.\n"
                "El archivo puede estar en uso o necesitas permisos de administrador.")
        except OSError as e:
            messagebox.showerror(APP_NAME,
                f"Error al eliminar '{filename}':\n{e}")

    # ===================================================================
    # Tab 5: Inicio (Startup)
    # ===================================================================

    def _build_startup_tab(self):
        tab = self.tab_startup

        info = ctk.CTkFrame(tab)
        info.pack(fill="x", padx=10, pady=(10, 5))
        ctk.CTkLabel(
            info,
            text="Programas que arrancan con Windows. Deshabilitar los que no necesitas acelera el inicio.",
            font=ctk.CTkFont(size=13), wraplength=750,
        ).pack(padx=15, pady=10)

        btn_frame = ctk.CTkFrame(tab)
        btn_frame.pack(fill="x", padx=10, pady=5)

        self.startup_refresh_btn = ctk.CTkButton(
            btn_frame, text="🔄 Cargar programas de inicio",
            command=self._on_load_startup, width=220, height=35,
        )
        self.startup_refresh_btn.pack(side="left", padx=10, pady=8)

        self.startup_list_frame = ctk.CTkScrollableFrame(
            tab, label_text="Programas de inicio")
        self.startup_list_frame.pack(fill="both", expand=True, padx=10, pady=5)

    def _on_load_startup(self):
        for w in self.startup_list_frame.winfo_children():
            w.destroy()
        try:
            programs = scanner.get_startup_programs()
        except Exception as e:
            ctk.CTkLabel(
                self.startup_list_frame, text=f"Error: {e}",
                text_color=COLOR_DANGER,
            ).pack(padx=10, pady=10)
            return

        if not programs:
            ctk.CTkLabel(
                self.startup_list_frame,
                text="No se encontraron programas de inicio.",
            ).pack(padx=10, pady=10)
            return

        for prog in programs:
            row = ctk.CTkFrame(self.startup_list_frame)
            row.pack(fill="x", padx=5, pady=3)

            ctk.CTkLabel(
                row, text=prog["name"],
                font=ctk.CTkFont(size=13, weight="bold"),
                width=180, anchor="w",
            ).pack(side="left", padx=(10, 5), pady=8)

            ctk.CTkLabel(
                row, text=prog["hive_name"],
                font=ctk.CTkFont(size=11), text_color=COLOR_MUTED,
                width=60,
            ).pack(side="left", padx=5, pady=8)

            cmd_text = prog["command"]
            if len(cmd_text) > 50:
                cmd_text = cmd_text[:47] + "..."
            ctk.CTkLabel(
                row, text=cmd_text,
                font=ctk.CTkFont(size=10), text_color=COLOR_MUTED,
                anchor="w",
            ).pack(side="left", padx=5, pady=8, fill="x", expand=True)

            btn = ctk.CTkButton(
                row, text="Deshabilitar", width=100, height=28,
                font=ctk.CTkFont(size=11),
                fg_color=COLOR_WARNING, hover_color="#d35400",
                command=lambda p=prog, r=row: self._toggle_startup(p, r),
            )
            btn.pack(side="right", padx=10, pady=8)

    def _toggle_startup(self, program, row_widget):
        if program.get("enabled", True):
            if scanner.disable_startup_program(program):
                program["enabled"] = False
                for w in row_widget.winfo_children():
                    if isinstance(w, ctk.CTkButton):
                        w.configure(text="Habilitar",
                                    fg_color=COLOR_SUCCESS, hover_color="#27ae60")
                messagebox.showinfo(APP_NAME,
                    f"'{program['name']}' deshabilitado.\nAplica en el próximo reinicio.")
            else:
                messagebox.showerror(APP_NAME,
                    f"No se pudo deshabilitar '{program['name']}'.\n"
                    "Intenta ejecutar como administrador.")
        else:
            if scanner.enable_startup_program(program):
                program["enabled"] = True
                for w in row_widget.winfo_children():
                    if isinstance(w, ctk.CTkButton):
                        w.configure(text="Deshabilitar",
                                    fg_color=COLOR_WARNING, hover_color="#d35400")

    # ===================================================================
    # Tab 6: Programas instalados
    # ===================================================================

    def _build_programs_tab(self):
        tab = self.tab_programs

        top = ctk.CTkFrame(tab)
        top.pack(fill="x", padx=10, pady=(10, 5))

        self.prog_load_btn = ctk.CTkButton(
            top, text="🔄 Cargar programas instalados",
            command=self._on_load_programs, width=240, height=35,
        )
        self.prog_load_btn.pack(side="left", padx=10, pady=8)

        # Buscador
        ctk.CTkLabel(top, text="Buscar:", font=ctk.CTkFont(size=12),
                     ).pack(side="left", padx=(20, 5), pady=8)

        self.prog_search_var = ctk.StringVar()
        self.prog_search_var.trace_add("write", self._on_prog_search)
        ctk.CTkEntry(top, textvariable=self.prog_search_var, width=200,
                     placeholder_text="Nombre del programa...",
                     ).pack(side="left", padx=5, pady=8)

        self.prog_count_label = ctk.CTkLabel(
            top, text="", font=ctk.CTkFont(size=12), text_color=COLOR_MUTED,
        )
        self.prog_count_label.pack(side="right", padx=15, pady=8)

        self.prog_list = ctk.CTkScrollableFrame(tab, label_text="Programas instalados")
        self.prog_list.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        self._all_programs: list[scanner.InstalledProgram] = []

    def _on_load_programs(self):
        self.prog_load_btn.configure(state="disabled", text="⏳ Cargando...")
        for w in self.prog_list.winfo_children():
            w.destroy()

        threading.Thread(target=self._programs_worker, daemon=True).start()

    def _programs_worker(self):
        try:
            programs = scanner.get_installed_programs()
            self.after(0, self._render_programs, programs)
        except Exception as e:
            self.after(0, self.prog_count_label.configure,
                       {"text": f"Error: {e}", "text_color": COLOR_DANGER})
            self.after(0, self.prog_load_btn.configure,
                       {"state": "normal", "text": "🔄 Cargar programas instalados"})

    def _render_programs(self, programs: list[scanner.InstalledProgram]):
        self.prog_load_btn.configure(state="normal",
                                      text="🔄 Cargar programas instalados")
        self._all_programs = programs
        self.prog_count_label.configure(text=f"{len(programs)} programas")
        self._display_programs(programs)

    def _display_programs(self, programs):
        for w in self.prog_list.winfo_children():
            w.destroy()

        for prog in programs[:100]:  # max 100 en lista
            row = ctk.CTkFrame(self.prog_list)
            row.pack(fill="x", padx=5, pady=2)

            ctk.CTkLabel(
                row, text=prog.name,
                font=ctk.CTkFont(size=12, weight="bold"),
                width=220, anchor="w",
            ).pack(side="left", padx=(10, 5), pady=5)

            version_text = prog.version or ""
            ctk.CTkLabel(
                row, text=version_text,
                font=ctk.CTkFont(size=11), text_color=COLOR_MUTED,
                width=80, anchor="w",
            ).pack(side="left", padx=5, pady=5)

            publisher_text = prog.publisher or ""
            if len(publisher_text) > 25:
                publisher_text = publisher_text[:22] + "..."
            ctk.CTkLabel(
                row, text=publisher_text,
                font=ctk.CTkFont(size=11), text_color=COLOR_MUTED,
                width=150, anchor="w",
            ).pack(side="left", padx=5, pady=5)

            if prog.size_human:
                ctk.CTkLabel(
                    row, text=prog.size_human,
                    font=ctk.CTkFont(size=11), text_color=COLOR_ACCENT,
                    width=70,
                ).pack(side="left", padx=5, pady=5)

            if prog.uninstall_string:
                ctk.CTkButton(
                    row, text="Desinstalar", width=90, height=26,
                    font=ctk.CTkFont(size=11),
                    fg_color=COLOR_DANGER, hover_color="#c0392b",
                    command=lambda p=prog: self._on_uninstall(p),
                ).pack(side="right", padx=10, pady=5)

    def _on_prog_search(self, *_args):
        query = self.prog_search_var.get().lower().strip()
        if not query:
            self._display_programs(self._all_programs)
            return
        filtered = [p for p in self._all_programs if query in p.name.lower()]
        self._display_programs(filtered)
        self.prog_count_label.configure(
            text=f"{len(filtered)} de {len(self._all_programs)}")

    def _on_uninstall(self, prog: scanner.InstalledProgram):
        if not messagebox.askyesno(
            "Desinstalar programa",
            f"¿Desinstalar '{prog.name}'?\n\n"
            "Se abrirá el desinstalador del programa.",
        ):
            return
        ok = scanner.uninstall_program(prog)
        if ok:
            messagebox.showinfo(APP_NAME,
                f"Se inició el desinstalador de '{prog.name}'.\n"
                "Sigue las instrucciones del desinstalador.")
        else:
            messagebox.showerror(APP_NAME,
                f"No se pudo iniciar el desinstalador de '{prog.name}'.")

    # ===================================================================
    # Tab 7: Red
    # ===================================================================

    def _build_network_tab(self):
        tab = self.tab_network

        btn_frame = ctk.CTkFrame(tab)
        btn_frame.pack(fill="x", padx=10, pady=(10, 5))

        self.net_refresh_btn = ctk.CTkButton(
            btn_frame, text="🔄 Obtener info de red",
            command=self._on_load_network, width=200, height=35,
        )
        self.net_refresh_btn.pack(side="left", padx=10, pady=8)

        self.net_report_btn = ctk.CTkButton(
            btn_frame, text="📄 Generar reporte completo",
            command=self._on_generate_report, width=220, height=35,
            fg_color="#8e44ad", hover_color="#7d3c98",
        )
        self.net_report_btn.pack(side="left", padx=10, pady=8)

        self.net_status = ctk.CTkLabel(
            btn_frame, text="", font=ctk.CTkFont(size=12), text_color=COLOR_MUTED,
        )
        self.net_status.pack(side="right", padx=15, pady=8)

        self.net_info_frame = ctk.CTkScrollableFrame(tab, label_text="Información de red")
        self.net_info_frame.pack(fill="both", expand=True, padx=10, pady=(5, 10))

    def _on_load_network(self):
        self.net_refresh_btn.configure(state="disabled", text="⏳ Obteniendo...")
        self.net_status.configure(text="Recopilando info de red...")
        for w in self.net_info_frame.winfo_children():
            w.destroy()

        threading.Thread(target=self._network_worker, daemon=True).start()

    def _network_worker(self):
        try:
            info = scanner.get_network_info()
            self.after(0, self._render_network, info)
        except Exception as e:
            self.after(0, self.net_status.configure,
                       {"text": f"Error: {e}", "text_color": COLOR_DANGER})
            self.after(0, self.net_refresh_btn.configure,
                       {"state": "normal", "text": "🔄 Obtener info de red"})

    def _render_network(self, info: scanner.NetworkInfo):
        self.net_refresh_btn.configure(state="normal", text="🔄 Obtener info de red")
        self.net_status.configure(text="Info de red actualizada")
        parent = self.net_info_frame

        def row(label, value, copyable=False):
            f = ctk.CTkFrame(parent)
            f.pack(fill="x", padx=10, pady=2)
            ctk.CTkLabel(f, text=label, font=ctk.CTkFont(size=12),
                         width=160, anchor="w", text_color=COLOR_MUTED,
                         ).pack(side="left", padx=(10, 5), pady=5)
            ctk.CTkLabel(f, text=str(value),
                         font=ctk.CTkFont(size=12, weight="bold"),
                         anchor="w",
                         ).pack(side="left", padx=5, pady=5)

        row("Hostname", info.hostname)
        row("IP Local", info.local_ip)
        row("IP Pública", info.public_ip)
        row("Gateway", info.gateway)
        row("MAC", info.mac_address)

        if info.dns_servers:
            row("DNS", ", ".join(info.dns_servers))

        if info.interfaces:
            ctk.CTkLabel(parent, text="Interfaces de red",
                         font=ctk.CTkFont(size=14, weight="bold"),
                         ).pack(anchor="w", padx=10, pady=(12, 4))
            for iface in info.interfaces:
                row(iface["name"], f"{iface['ip']} / {iface['netmask']}")

    def _on_generate_report(self):
        self.net_report_btn.configure(state="disabled", text="⏳ Generando...")
        self.net_status.configure(text="Generando reporte...")

        threading.Thread(target=self._report_worker, daemon=True).start()

    def _report_worker(self):
        try:
            path = scanner.generate_report()
            self.after(0, self._report_complete, path)
        except Exception as e:
            self.after(0, self.net_status.configure,
                       {"text": f"Error: {e}", "text_color": COLOR_DANGER})
            self.after(0, self.net_report_btn.configure,
                       {"state": "normal", "text": "📄 Generar reporte completo"})

    def _report_complete(self, path):
        self.net_report_btn.configure(state="normal",
                                       text="📄 Generar reporte completo")
        self.net_status.configure(text=f"Reporte guardado en el escritorio")
        messagebox.showinfo(
            "Reporte generado",
            f"Reporte guardado en:\n{path}\n\n"
            "Puedes enviarlo por WhatsApp o email para soporte técnico.",
        )
        # Abrir la carpeta del reporte
        try:
            os.startfile(os.path.dirname(path))
        except Exception:
            pass


# ===========================================================================
# Entry point
# ===========================================================================

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    app = VeCleanApp()
    app.mainloop()


if __name__ == "__main__":
    main()
