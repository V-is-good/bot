```markdown
# Bot Telegram multifunción (Mistral + recuperación de canales)

Qué hace
- Chat conversacional y generación de scripts usando Mistral vía Hugging Face Inference API.
- Moderación básica por lista de palabras y eliminación de mensajes (si el bot es admin).
- Reportes de recuperación de canales: los usuarios envían `/report_recovery <url>`, los admins responden en un chat (bot notifica al usuario).
- Placeholder para integración de generación de imágenes (configurable).

Requisitos
- Python 3.10+
- Claves en `.env`:
  - TELEGRAM_BOT_TOKEN (BotFather)
  - HUGGINGFACE_API_KEY (Hugging Face)
  - HUGGINGFACE_MODEL (por defecto: mistralai/mistral-7b-instruct)
  - Opcional: IMAGE_PROVIDER, IMAGE_API_KEY
  - Opcional: RECOVERY_CHAT_ID, RECOVERY_ADMIN_IDS

Instalación local
1. Copia `.env.example` (si existe) o crea `.env` con el contenido necesario.
2. Protege el archivo:
   chmod 600 .env
3. Instala dependencias:
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
4. Ejecuta:
   python bot.py

Comandos principales
- /start, /help
- /chat <mensaje> — chatea con Mistral
- /generate_script <lenguaje> | <descripcion> — genera código
- /image <descripcion> — genera imagen (si configuras proveedor)
- /moderate_on, /moderate_off — activar/desactivar moderación en grupos (requiere admin)
- /report_recovery <url_del_canal> — crear reporte para recuperar canal
- /recovery_status <report_id> — verificar estado de reporte

Despliegue con Docker
- Construir:
  docker build -t my-telegram-bot .
- Ejecutar (ejemplo pasando variables):
  docker run --env-file .env my-telegram-bot

Seguridad
- No subas `.env` a repositorios públicos.
- Si alguna clave fue expuesta, regénérala:
  - Telegram: BotFather → revoke/regenerate token.
  - Hugging Face: https://huggingface.co/settings/tokens → revoke/create.
- Para producción usa secret managers del proveedor (Heroku, Render, AWS Secrets Manager, etc.)

Mejoras sugeridas
- Persistencia en Postgres/Redis en lugar de state.json.
- Flujo para que admin deje comentario al responder reportes.
- Integración de proveedor de imágenes (OpenAI/Replicate/Stability).
- Pruebas unitarias y contenedorización con supervisión (systemd / process manager).

Si quieres que:
1) Integre generación de imágenes con OpenAI/Replicate/Stability ahora, dime cuál.  
2) Añada la opción de que el admin escriba una nota al responder reportes.  
3) Cambie la persistencia a Postgres / Redis y te dé docker-compose.

Elige qué hago a continuación y lo implemento.
```