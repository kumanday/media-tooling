# Guia practica de Media Tooling y Codex

Esta guia explica el flujo de trabajo del toolkit para alguien que ya sabe producir video, trabajar con material audiovisual y usar ChatGPT para pensar ideas, pero que todavia tiene poca experiencia con terminal, Codex o agent harnesses.

El objetivo es convertir un corpus grande de audio, video e imagenes en un paquete de trabajo facil de revisar, buscar, clasificar y editar.

## Instalacion en macOS

La forma mas simple es usar el script de arranque del toolkit.

```bash
git clone <repo-del-toolkit> "$HOME/dev/media-tooling"
cd "$HOME/dev/media-tooling"
./scripts/bootstrap-macos.sh
```

Ese script instala:

- `uv`
- `ffmpeg`
- Python 3.12 con `uv`
- el entorno local del proyecto
- las funciones `extract` y `subtitle` en `~/.zshrc`

Si prefieres hacerlo a mano:

```bash
brew install uv ffmpeg
uv python install 3.12
cd "$HOME/dev/media-tooling"
uv sync
./scripts/install-shell-helpers.sh
source ~/.zshrc
```

## Para que sirve este toolkit

Media Tooling prepara material. Ordena archivos, genera transcripciones, crea subtitulos, resume videos silenciosos con contact sheets y deja una base lista para storyboard, guion y rough cut.

Sirve para muchos formatos:

- podcasts
- entrevistas
- tutoriales
- cursos
- videos de producto
- shorts
- reels
- piezas para YouTube

La edicion final sigue siendo un trabajo humano. El toolkit acelera la parte mecanica y documental.

## Como pensar el sistema

Hay dos capas.

### Toolkit reutilizable

Aqui vive el codigo reutilizable.

Ejemplo de ubicacion:

- `$HOME/dev/media-tooling`

### Workspace del proyecto

Cada proyecto necesita su propio espacio de trabajo.

Ejemplos:

- `$HOME/projects/podcast-episodio-12-media`
- `$HOME/projects/curso-python-media`
- `$HOME/projects/shorts-cliente-x`

En ese workspace van los artefactos del proyecto:

- transcripciones
- subtitulos
- inventarios
- analisis
- storyboards
- rough cuts
- notas editoriales

Regla practica:

- el toolkit contiene herramientas
- el workspace contiene resultados

## Tipos de material

### Material con voz

Si el archivo tiene dialogo, narracion o explicacion util, conviene generar:

- transcripcion
- subtitulos `.srt`

### Material silencioso

Si el archivo es una grabacion de pantalla sin voz, lo mas util es una contact sheet.

Una contact sheet es una imagen que junta varios frames del video. Permite ver rapido el recorrido visual del clip y decidir si merece revision manual.

### Imagenes fijas

Las imagenes se inventarian directamente. Suelen servir para:

- articulos
- miniaturas
- chapter cards
- referencias visuales

## Funciones de shell

Despues de instalar el toolkit, tendras estas funciones:

### `extract`

Extrae audio `.m4a` desde un video.

Ejemplo:

```bash
extract "/ruta/al/video.mp4"
```

### `subtitle`

Genera transcripcion, subtitulos y metadatos desde audio o video.

Ejemplo:

```bash
subtitle "/ruta/al/video.mp4" --output-dir "$PROJECT_DIR/transcripts"
```

## Flujo recomendado

### 1. Crear el workspace del proyecto

Usa una estructura simple:

```text
mi-proyecto-media/
  assets/
    audio/
    reference/
  transcripts/
  subtitles/
  inventory/
  analysis/
  storyboards/
  rough-cuts/
```

### 2. Juntar el corpus

Reune:

- videos hablados
- videos silenciosos
- audios
- screenshots
- notas de contexto

### 3. Separar por tipo

Haz esta division:

- hablado
- silencioso
- imagen fija

### 4. Procesar material hablado

Para videos o audios con voz:

- genera transcripcion
- genera subtitulos

El resultado base suele ir en:

- `assets/audio/`
- `transcripts/`
- `subtitles/`

### 5. Procesar material silencioso

Para screen recordings o demos sin voz:

- genera contact sheets
- crea inventario
- escribe una nota breve sobre el posible uso editorial

### 6. Analizar el corpus

Con los artefactos tecnicos listos, pasa al trabajo editorial:

- que clips merecen revision manual
- que piezas sirven para un video largo
- que piezas sirven para clips cortos
- que material sirve para un articulo o README

### 7. Armar storyboard y shot list

El storyboard organiza la narracion.

La shot list organiza el uso del material.

Una shot list util puede incluir:

- archivo
- tiempo de entrada
- tiempo de salida
- duracion
- objetivo del clip
- notas editoriales

### 8. Crear un rough cut

El rough cut ayuda a probar:

- estructura
- orden
- proporcion entre A-roll y B-roll
- huecos narrativos

### 9. Editar la version final

Aqui entra el trabajo fino del editor:

- seleccionar el mejor fragmento
- limpiar silencios
- ajustar ritmo
- tratar color y audio
- exportar la pieza final

## Ejemplos concretos de uso con Codex

### Ejemplo 1. Ingesta completa de un proyecto mixto

```text
Tengo un proyecto nuevo en $PROJECT_DIR.

Fuentes:
- videos hablados: /path/to/spoken
- screen recordings silenciosos: /path/to/silent
- screenshots: /path/to/images

Por favor:
1. inventaria el corpus
2. separa spoken, silent e images
3. crea manifests para procesamiento por lote
4. genera transcripciones y SRT para spoken media
5. genera contact sheets para silent media
6. escribe notas breves de analisis en $PROJECT_DIR/analysis

Usa procesamiento secuencial y no guardes artefactos del proyecto dentro del repo del toolkit.
```

### Ejemplo 2. Episodio de podcast

```text
Tengo un episodio de podcast con:
- una grabacion larga con voz
- un audio limpio
- tres clips cortos para promocion

Quiero:
1. transcripciones y SRT
2. una lista de momentos fuertes
3. sugerencias para:
   - episodio completo
   - clips cortos
   - quote graphics
4. un shot list con tiempos
```

### Ejemplo 3. Tutorial o curso

```text
Tengo materiales de un tutorial:
- lecciones narradas
- demos silenciosas de pantalla
- screenshots de apoyo

Quiero:
- transcripciones y subtitulos para el material narrado
- contact sheets para el material silencioso
- una propuesta de storyboard para:
  - un video largo
  - tres clips cortos
  - un articulo de apoyo
```

### Ejemplo 4. Rough cut

```text
El corpus ya esta procesado en $PROJECT_DIR.

Revisa:
- transcripts/
- subtitles/
- assets/reference/
- analysis/

Y prepara:
1. una lista corta de los mejores clips
2. una secuencia tentativa
3. una nota sobre lo que falta grabar
```

## Exportar el toolkit a otra Mac

La forma mas limpia es poner `media-tooling` en su propio repo de Git.

El repo debe incluir:

- `README.md`
- `pyproject.toml`
- `uv.lock`
- `src/`
- `shell/`
- `scripts/`
- `docs/`
- `.gitignore`

El repo no debe incluir:

- `.venv/`
- `.cache/`
- `mlx_models/`
- artefactos de proyectos concretos

La guia detallada esta en:

- `docs/EXPORTING.md`

## Resultado esperado

Un buen flujo deja el proyecto en este estado:

- corpus ordenado
- transcripciones listas
- subtitulos base
- referencias visuales para clips silenciosos
- inventarios utilizables
- notas de analisis
- storyboard claro
- rough cut inicial

Ese punto cambia mucho el trabajo diario. La energia pasa de tareas repetitivas a decisiones editoriales.
