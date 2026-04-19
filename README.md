# LectorIA

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)
![PySide6](https://img.shields.io/badge/PySide6-Qt6-green?logo=qt&logoColor=white)
![Gemini](https://img.shields.io/badge/Google_Gemini-AI-orange?logo=google&logoColor=white)

Aplicación de escritorio para **lectura accesible** orientada a estudiantes con discapacidad visual. LectorIA transcribe documentos (PDF, imágenes, texto) usando Google Gemini AI y los reproduce en voz alta, con resaltado de palabras y un asistente de preguntas y respuestas.

---

## Capturas de pantalla

> Agrega tus capturas en la carpeta `screenshots/` y actualiza las rutas aquí.

```
test/
├── App_Test.png
```

---

## Funciones principales

### Lectura en voz alta
- Carga documentos PDF, imágenes y archivos de texto
- Transcripción inteligente con Google Gemini AI (describe imágenes y diagramas)
- Reproducción de audio con gTTS y resaltado de palabra activa
- Controles de reproducción: play/pausa, avance/retroceso por oración
- Modo lento y control de velocidad
- Sistema de marcadores (10 por sesión)

### Asistente de preguntas
- Pregunta sobre el documento cargado en lenguaje natural
- Entrada por texto o por voz (micrófono)
- Respuestas narradas en voz alta
- Historial de respuestas navegable

### Gestión de sesiones
- Múltiples sesiones nombradas con persistencia
- Renombrar y eliminar sesiones
- Historial de documentos por sesión

---

## Requisitos

- Python **3.11** o superior
- Una **API Key de Google Gemini** (obtenla en [Google AI Studio](https://aistudio.google.com/))
- Windows (la app compila a .exe con PyInstaller)

**Dependencias opcionales** (para entrada por voz):
- `sounddevice`
- `SpeechRecognition`
- `numpy`

---

## Instalación

```bash
# 1. Clona el repositorio
git clone https://github.com/tu-usuario/lector-ia.git
cd lector-ia

# 2. Crea un entorno virtual (recomendado)
python -m venv venv
venv\Scripts\activate

# 3. Instala las dependencias
pip install -r requirements.txt

# 4. Configura tu API Key
```

Edita el archivo `config.json` y reemplaza el valor de `api_key`:

```json
{
  "api_key": "TU_API_KEY_AQUI",
  "model": "gemini-2.5-flash"
}
```

---

## Uso

```bash
python main.py
```

### Atajos de teclado

| Acción | Atajo |
|---|---|
| Abrir archivo | `Ctrl+O` |
| Nueva sesión | `Ctrl+Space` |
| Play / Pausa | `Space` |
| Oración anterior / siguiente | `← / →` |
| Cambiar de pestaña | `Ctrl+← / →` |
| Navegar sesiones | `Ctrl+↑ / ↓` |
| Guardar marcador | `Ctrl+1…9, Ctrl+0` |
| Ir a marcador | `Alt+1…9, Alt+0` |
| Iniciar/detener grabación | `Enter` (pestaña Q&A) |
| Renombrar sesión | `F2` |

---

## Compilar el ejecutable (.exe)

Para generar un instalable de Windows sin necesidad de Python:

```bat
build.bat
```

El ejecutable quedará en `dist/LectorIA/`.

---

## Estructura del proyecto

```
App Clean/
├── main.py           # Punto de entrada
├── app.py            # Ventana principal y lógica de UI (PySide6)
├── config.py         # Gestión de configuración (config.json)
├── session.py        # Modelo de sesiones y persistencia
├── gemini_client.py  # Integración con Google Gemini API
├── tts_engine.py     # Motor de voz (gTTS + pygame)
├── requirements.txt  # Dependencias de Python
├── config.json       # Configuración del usuario (API key, prompts)
├── LectorIA.spec     # Especificación de PyInstaller
├── build.bat         # Script de compilación
└── sessions/         # Sesiones guardadas (JSON)
```

---

## Licencia

Este proyecto está bajo la licencia [MIT](LICENSE).
