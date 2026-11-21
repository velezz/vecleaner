# VeClean v2.0.0

Herramienta portable de optimización para Windows. Diseñada para usuarios no técnicos que necesitan mantener su PC limpia sin saber ejecutar comandos.

## Qué hace

| Tab | Función |
|-----|---------|
| **Estado** | Dashboard del sistema: CPU, RAM, disco, uptime, versión de Windows |
| **Limpieza** | Escanea y elimina archivos temporales, caché de navegadores, prefetch, papelera, caché de Windows Update |
| **Duplicados** | Encuentra archivos duplicados por contenido (hash SHA-256) en Descargas, Escritorio y Documentos |
| **Grandes** | Localiza archivos grandes (>100 MB por defecto) para que el usuario decida si borrarlos |
| **Inicio** | Muestra y permite deshabilitar/habilitar programas que arrancan con Windows |
| **Programas** | Lista programas instalados con buscador y lanza el desinstalador nativo |
| **Red** | Muestra IP local/pública, DNS, gateway, MAC. Genera reporte .txt para soporte técnico |

## Requisitos para compilar

- Python 3.10+
- Windows 10/11

```
pip install -r requirements.txt
```

Dependencias: `customtkinter`, `psutil`, `pillow`, `pyinstaller`.

## Compilar el .exe

```
build.bat
```

Genera `dist\VeClean.exe` — un solo archivo portable, sin instalador. El usuario solo lo ejecuta cuando quiera.

## Estructura del proyecto

```
pclean/
├── gui.py              # Interfaz gráfica (7 tabs, CustomTkinter)
├── scanner.py          # Backend: escaneo, limpieza, info del sistema
├── logo.ico            # Ícono de la aplicación (mapache con escoba)
├── build.bat           # Script de empaquetado con PyInstaller
├── requirements.txt    # Dependencias de Python
└── README.md
```

## Notas técnicas

- **Portable**: no instala nada, no escribe en el registro, no deja rastro. Solo el reporte se guarda en el escritorio del usuario si lo genera.
- **Privilegios**: funciona sin admin, pero con admin puede limpiar Prefetch y caché de Windows Update.
- **Threading**: toda operación pesada corre en hilos daemon para no congelar la UI.
- **Duplicados**: usa detección en 2 fases — agrupa por tamaño primero, hashea SHA-256 solo los candidatos. Eficiente incluso con miles de archivos.
- **Desinstalador**: no borra nada directamente, lanza el desinstalador nativo del programa.
- **Sin anti-patrones**: no limpia registro (snake oil), no "optimiza" RAM (placebo), no actualiza drivers (riesgo de BSOD).

## Qué NO hace (y por qué)

- **Limpiar registro**: no tiene impacto real en rendimiento, puede romper cosas.
- **Optimizar RAM**: liberar RAM no sirve de nada, Windows la gestiona mejor solo.
- **Actualizar drivers**: causa BSODs. Windows Update ya maneja drivers estables.
- **Gestionar extensiones del navegador**: cada navegador tiene su propio sistema, es frágil y de bajo valor.

## Licencia

Proyecto personal. Uso interno.
