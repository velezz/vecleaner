# VeClean — Runbook

Guía operativa para compilar, distribuir, usar y solucionar problemas de VeClean.

---

## 1. Compilación

### Prerequisitos

```powershell
# Python 3.10+ instalado y en PATH
python --version

# Instalar dependencias
pip install customtkinter psutil pillow pyinstaller
```

### Compilar

```powershell
cd C:\ruta\al\proyecto\pclean
.\build.bat
```

**Resultado esperado**: `dist\VeClean.exe` (~25-40 MB dependiendo de las dependencias).

### Problemas comunes en compilación

| Síntoma | Causa | Solución |
|---------|-------|----------|
| `'pyinstaller' no se reconoce` | PyInstaller no está en PATH | El build.bat ya usa `python -m PyInstaller`, verificar que pip install fue exitoso |
| `ModuleNotFoundError: customtkinter` | Dependencia no instalada | `pip install customtkinter` |
| `ModuleNotFoundError: psutil` | Dependencia no instalada | `pip install psutil` |
| `ModuleNotFoundError: PIL` | Pillow no instalado | `pip install pillow` |
| `.exe no muestra ícono` | logo.ico no está en la carpeta del proyecto | Verificar que `logo.ico` está junto a `gui.py` |
| `.exe abre y se cierra inmediatamente` | Error en import o dependencia faltante | Ejecutar desde CMD para ver el traceback: `cmd /k dist\VeClean.exe` |

---

## 2. Distribución

VeClean es portable. No hay instalador.

### Cómo distribuir

1. Compilar con `build.bat`
2. Copiar `dist\VeClean.exe` a una USB, carpeta compartida o enviar por mensajería
3. El usuario final solo hace doble clic para ejecutar

### Qué decirle al usuario

> "Descarga VeClean.exe y ejecútalo cuando tu PC esté lenta. No instala nada.
> Si Windows Defender muestra una advertencia, dale a 'Más información' → 'Ejecutar de todas formas'.
> Eso pasa porque el .exe no está firmado digitalmente."

### SmartScreen / Windows Defender

Windows muestra advertencia de SmartScreen en .exe sin firma digital. Esto es normal.

**Para evitarlo** (opcional, tiene costo):
- Firmar el .exe con un certificado de code signing (~$200-400/año)
- Alternativa gratuita: distribuir por carpeta compartida interna donde ya confíen en los archivos

---

## 3. Uso por tab

### Tab: Estado

- Presionar "Actualizar estado"
- Muestra CPU, RAM, disco, uptime
- Las barras cambian de color: verde (<70%), naranja (70-90%), rojo (>90%)
- **Sin admin**: funciona completo
- **Dato**: el nombre del CPU se lee del registro de Windows, no de `platform.processor()` (más confiable)

### Tab: Limpieza

1. Presionar "Escanear" — muestra cuánto espacio se puede liberar por categoría
2. Desmarcar categorías que no se quieran limpiar
3. Presionar "Limpiar seleccionados" — pide confirmación antes de borrar
4. **Sin admin**: limpia temp del usuario, caché de navegadores, papelera
5. **Con admin**: además limpia Prefetch y caché de Windows Update

**Qué se borra:**
- `%TEMP%` y `C:\Windows\Temp` — archivos temporales de apps y sistema
- `C:\Windows\Prefetch` — caché de inicio de programas (se regenera sola)
- Caché de Chrome, Edge, Firefox, Brave — no borra contraseñas, historial ni cookies
- Papelera de reciclaje — usa la API `SHEmptyRecycleBinW`
- `C:\Windows\SoftwareDistribution\Download` — descargas de Windows Update ya aplicadas

### Tab: Duplicados

1. Configurar tamaño mínimo (default 1 MB, subir si hay muchos archivos)
2. Presionar "Buscar duplicados"
3. **Fase 1**: indexa archivos por tamaño (rápido)
4. **Fase 2**: hashea SHA-256 solo archivos que comparten tamaño (más lento)
5. Muestra grupos de duplicados con espacio desperdiciado
6. El botón 📂 abre la carpeta del archivo para que el usuario decida cuál borrar manualmente

**Directorios escaneados**: Descargas, Escritorio, Documentos del usuario actual.

**No borra automáticamente** — solo muestra los duplicados. El usuario decide.

### Tab: Grandes

1. Configurar tamaño mínimo en MB (default 100)
2. Presionar "Buscar archivos grandes"
3. Muestra archivos ordenados por tamaño (máximo 50 resultados)
4. Botón "Abrir" abre la carpeta contenedora en Explorer

**Directorios**: Descargas, Escritorio, Documentos. Ignora `.git`, `node_modules`, `__pycache__`.

### Tab: Inicio

1. Presionar "Cargar programas de inicio"
2. Muestra nombre, ubicación (HKCU/HKLM/Carpeta) y comando
3. "Deshabilitar" mueve la entrada del registro a `Run_VeClean_Disabled`
4. "Habilitar" la restaura a su ubicación original
5. **Los cambios aplican en el siguiente reinicio**

**Sin admin**: solo puede modificar HKCU (programas del usuario actual).
**Con admin**: también puede modificar HKLM (programas de todos los usuarios).

### Tab: Programas

1. Presionar "Cargar programas instalados"
2. Usar el buscador para filtrar en tiempo real
3. "Desinstalar" lanza el desinstalador nativo del programa — VeClean no borra nada directamente
4. Lee de 3 ubicaciones del registro: HKLM 64-bit, HKLM 32-bit (WOW6432Node), HKCU

### Tab: Red

1. "Obtener info de red" — muestra IP local/pública, DNS, gateway, MAC, interfaces
2. "Generar reporte completo" — crea un .txt en el escritorio con toda la info del sistema
3. El reporte incluye: OS, CPU, RAM, discos, red — útil para soporte remoto

**IP pública**: se obtiene de `api.ipify.org`. Si no hay internet, muestra "No disponible".

---

## 4. Troubleshooting

### La app no abre

```powershell
# Ejecutar desde CMD para ver errores
cmd /k C:\ruta\VeClean.exe
```

Causas comunes:
- Antivirus bloqueando el .exe → agregar excepción
- .NET Framework faltante → no aplica, VeClean usa Python embebido
- DLL faltante → recompilar en la misma versión de Windows del usuario final

### "No se pudo limpiar X"

- **Prefetch / Windows Update**: necesita ejecutar como admin → clic derecho → "Ejecutar como administrador"
- **Archivos en uso**: algunos archivos temporales están bloqueados por procesos activos. Es normal, se limpian en el siguiente intento.

### El escaneo de duplicados es muy lento

- Subir el tamaño mínimo (de 1 MB a 5-10 MB)
- Es normal en carpetas con miles de archivos — la fase 2 hashea cada candidato

### El desinstalador no hace nada

- Algunos programas tienen `UninstallString` inválido o vacío
- Programas de Microsoft Store no aparecen (usan otro sistema de registro)

### El reporte no se genera

- Verificar permisos de escritura en el escritorio del usuario
- Si falla, se puede especificar otra ruta en el código

### IP pública muestra "No disponible"

- Sin conexión a internet
- Firewall corporativo bloqueando `api.ipify.org`
- Proxy que requiere autenticación

---

## 5. Seguridad

- VeClean **no envía datos** a ningún servidor (excepto la consulta a `api.ipify.org` para IP pública)
- **No modifica el registro** excepto para mover entradas de startup (y guarda backup en `Run_VeClean_Disabled`)
- **No borra archivos del sistema** — solo temporales, caché y papelera
- El desinstalador **lanza el proceso nativo** del programa, no borra carpetas directamente
- El reporte se guarda **localmente** en el escritorio, no se envía a ningún lado

---

## 6. Actualización

No hay actualización automática. Para distribuir una nueva versión:

1. Modificar `APP_VERSION` en `gui.py`
2. Recompilar con `build.bat`
3. Reemplazar el .exe anterior en el medio de distribución

---

## 7. Arquitectura

```
VeClean.exe (PyInstaller --onefile)
├── gui.py          → UI thread (CustomTkinter, main loop)
│   ├── Tab Estado      → llama scanner.get_system_info()
│   ├── Tab Limpieza    → llama scanner.scan_*/clean_* en daemon thread
│   ├── Tab Duplicados  → llama scanner.scan_duplicates() en daemon thread
│   ├── Tab Grandes     → llama scanner.scan_large_files() en daemon thread
│   ├── Tab Inicio      → llama scanner.get/disable/enable_startup_program()
│   ├── Tab Programas   → llama scanner.get_installed_programs/uninstall()
│   └── Tab Red         → llama scanner.get_network_info/generate_report()
│
├── scanner.py      → Backend (sin dependencia de UI)
│   ├── psutil      → CPU, RAM, disco, red
│   ├── winreg      → registro de Windows
│   ├── ctypes      → APIs Win32 (papelera, admin check)
│   ├── hashlib     → SHA-256 para duplicados
│   └── subprocess  → ipconfig, desinstaladores
│
└── logo.ico        → empaquetado como recurso
```

**Principio de diseño**: `scanner.py` no importa nada de GUI. Se puede usar como librería desde un script sin interfaz gráfica.
