#!/usr/bin/env python3
"""
Bot Telegram multifunción:
- Chat y generación de scripts con Mistral (Hugging Face Inference API)
- Generación de imágenes (placeholder para integrar proveedor)
- Moderación básica por palabras y opcionalmente por admin
- Reportes de recuperación de canales (envía al RECOVERY_CHAT_ID y permite respuesta con botones)
"""

import os
import json
import logging
import tempfile
import aiohttp
import uuid
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

from telegram import InputFile, ChatMember, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters,
)

# --- Config ---
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY")
HUGGINGFACE_MODEL = os.getenv("HUGGINGFACE_MODEL", "mistralai/mistral-7b-instruct")
HUGGINGFACE_API_URL_TEMPLATE = "https://api-inference.huggingface.co/models/{}"

IMAGE_PROVIDER = os.getenv("IMAGE_PROVIDER", "none")
IMAGE_API_KEY = os.getenv("IMAGE_API_KEY", "")

STATE_FILE = os.getenv("STATE_FILE", "state.json")

RECOVERY_CHAT_ID = os.getenv("RECOVERY_CHAT_ID")
RECOVERY_ADMIN_IDS = os.getenv("RECOVERY_ADMIN_IDS", "")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN no establecido en .env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- State management (simple file) ---
DEFAULT_STATE = {"moderated_chats": [], "histories": {}, "reports": []}

def load_state():
    if not Path(STATE_FILE).exists():
        save_state(DEFAULT_STATE)
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

STATE = load_state()

# --- Utils ---
EXT_MAP = {
    "python": ".py", "py": ".py",
    "js": ".js", "javascript": ".js",
    "ts": ".ts", "typescript": ".ts",
    "sh": ".sh", "bash": ".sh",
    "go": ".go", "java": ".java", "rb": ".rb", "php": ".php",
    "txt": ".txt",
}

BANNED_WORDS = ["palabraprohibida1", "palabraprohibida2"]  # personaliza

def is_chat_moderated(chat_id: int) -> bool:
    return chat_id in STATE.get("moderated_chats", [])

def add_moderated_chat(chat_id: int):
    arr = STATE.setdefault("moderated_chats", [])
    if chat_id not in arr:
        arr.append(chat_id)
        save_state(STATE)

def remove_moderated_chat(chat_id: int):
    arr = STATE.setdefault("moderated_chats", [])
    if chat_id in arr:
        arr.remove(chat_id)
        save_state(STATE)

def push_history(chat_id: int, role: str, content: str, max_len=10):
    h = STATE.setdefault("histories", {}).setdefault(str(chat_id), [])
    h.append({"role": role, "content": content})
    if len(h) > max_len:
        STATE["histories"][str(chat_id)] = h[-max_len:]
    save_state(STATE)

def _admin_ids_set():
    s = set()
    for p in (RECOVERY_ADMIN_IDS or "").split(","):
        p = p.strip()
        if not p:
            continue
        try:
            s.add(int(p))
        except ValueError:
            continue
    return s

# --- Hugging Face (Mistral) helpers ---
async def hf_generate_text(prompt: str, max_tokens: int = 512, temperature: float = 0.7):
    """
    Llama a la Inference API de Hugging Face para generar texto con un modelo Mistral.
    Requiere HUGGINGFACE_API_KEY y HUGGINGFACE_MODEL configurados en .env.
    """
    if not HUGGINGFACE_API_KEY:
        raise RuntimeError("HUGGINGFACE_API_KEY no está configurado en .env")
    url = HUGGINGFACE_API_URL_TEMPLATE.format(HUGGINGFACE_MODEL)
    headers = {
        "Authorization": f"Bearer {HUGGINGFACE_API_KEY}",
        "Accept": "application/json",
    }
    payload = {
        "inputs": prompt,
        "parameters": {"max_new_tokens": max_tokens, "temperature": temperature},
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload, timeout=120) as resp:
            text = await resp.text()
            try:
                data = json.loads(text)
            except Exception:
                raise RuntimeError(f"Hugging Face returned non-JSON response: {text[:400]}")
            if isinstance(data, dict) and data.get("error"):
                raise RuntimeError(f"Hugging Face error: {data.get('error')}")
            if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                # formato común: [{"generated_text":"..."}]
                return data[0].get("generated_text") or ""
            if isinstance(data, dict):
                return data.get("generated_text") or data.get("text") or str(data)
            return str(data)

# --- Command handlers ---
async def start(update: "telegram.Update", context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hola — soy un bot multifunción (Mistral).\n"
        "Comandos:\n"
        "/generate_script <lenguaje> | <descripcion> - Genera un script/archivo\n"
        "/image <descripcion> - Genera una imagen (si está configurado proveedor)\n"
        "/chat <mensaje> - Chatea con la IA (Mistral)\n"
        "/moderate_on - Activar moderación en este chat (requiere admin)\n"
        "/moderate_off - Desactivar moderación\n"
        "/report_recovery <url_del_canal> - Reportar recuperación de canal\n"
        "/recovery_status <report_id> - Consultar estado de un reporte\n"
        "/help - Mostrar ayuda"
    )

async def help_cmd(update, context):
    await start(update, context)

# /generate_script
async def generate_script(update, context):
    text = update.message.text or ""
    args = text.split(" ", 1)
    if len(args) < 2 or not args[1].strip():
        await update.message.reply_text("Uso: /generate_script <lenguaje> | <descripcion breve>\nEj: /generate_script python | Lee un CSV y resume columnas")
        return
    body = args[1].strip()
    if "|" in body:
        lang, prompt = map(str.strip, body.split("|", 1))
    else:
        lang = "txt"
        prompt = body

    await update.message.reply_text(f"Generando script en {lang} con Mistral...")
    system_prompt = f"Genera un script en {lang} que haga lo siguiente:\n{prompt}\nEntrega solo el código, sin explicaciones adicionales."

    try:
        code = await hf_generate_text(system_prompt, max_tokens=1200, temperature=0.15)
    except Exception as e:
        logger.exception("Error generando script con Mistral")
        await update.message.reply_text(f"Error al generar el script: {e}")
        return

    ext = EXT_MAP.get(lang.lower(), ".txt")
    filename = f"script{ext}"
    try:
        await update.message.reply_text("Aquí está el código generado (también te lo adjunto como archivo):")
        with tempfile.NamedTemporaryFile("w+", suffix=ext, delete=False, encoding="utf-8") as tmp:
            tmp.write(code)
            tmp.flush()
            tmp_path = tmp.name
        await context.bot.send_document(chat_id=update.effective_chat.id, document=InputFile(tmp_path, filename=filename))
        Path(tmp_path).unlink(missing_ok=True)
    except Exception:
        logger.exception("Error enviando archivo")
        await update.message.reply_text("No se pudo adjuntar el archivo, te envío el código en texto:\n\n" + code)

# /image (placeholder)
async def image_cmd(update, context):
    text = update.message.text or ""
    args = text.split(" ", 1)
    if len(args) < 2 or not args[1].strip():
        await update.message.reply_text("Uso: /image <descripcion>")
        return
    prompt = args[1].strip()

    if IMAGE_PROVIDER == "none" or not IMAGE_API_KEY:
        await update.message.reply_text("No hay proveedor de imágenes configurado. Si quieres imágenes, dime qué proveedor usar (openai/replicate/stability) y lo configuro.")
        return

    await update.message.reply_text("Generando imagen... (proveedor configurado: {})".format(IMAGE_PROVIDER))
    # Integración de proveedor de imágenes debe añadirse aquí según IMAGE_PROVIDER.

# /chat usando Mistral (via HF)
async def chat_cmd(update, context):
    chat_id = str(update.effective_chat.id)
    text = update.message.text or ""
    args = text.split(" ", 1)
    if len(args) < 2 or not args[1].strip():
        await update.message.reply_text("Uso: /chat <mensaje>")
        return
    user_msg = args[1].strip()
    push_history(chat_id, "user", user_msg)

    history = STATE.get("histories", {}).get(chat_id, [])
    accumulated = ""
    for item in history:
        prefix = "Usuario: " if item["role"] == "user" else "Asistente: "
        accumulated += prefix + item["content"] + "\n"
    prompt = "Eres un asistente conversacional útil y conciso.\n\n" + accumulated + "\nUsuario: " + user_msg + "\nAsistente:"

    try:
        assistant_msg = await hf_generate_text(prompt, max_tokens=512, temperature=0.6)
        push_history(chat_id, "assistant", assistant_msg)
        await update.message.reply_text(assistant_msg)
    except Exception as e:
        logger.exception("Error en chat Mistral")
        await update.message.reply_text(f"Error en la IA: {e}")

# Moderation helpers
async def _is_user_admin(update, context):
    member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
    return member.status in (ChatMember.ADMINISTRATOR, ChatMember.OWNER)

async def moderate_on(update, context):
    if update.effective_chat.type == "private":
        await update.message.reply_text("La moderación por chat no se aplica en chats privados.")
        return
    try:
        if not await _is_user_admin(update, context):
            await update.message.reply_text("Solo administradores pueden activar la moderación.")
            return
    except Exception:
        await update.message.reply_text("No pude comprobar tus permisos. Asegúrate de que el bot puede ver administradores.")
        return
    add_moderated_chat(update.effective_chat.id)
    await update.message.reply_text("Moderación activada en este chat. El bot intentará eliminar mensajes con contenido no permitido.")

async def moderate_off(update, context):
    try:
        if not await _is_user_admin(update, context):
            await update.message.reply_text("Solo administradores pueden desactivar la moderación.")
            return
    except Exception:
        await update.message.reply_text("No pude comprobar tus permisos.")
        return
    remove_moderated_chat(update.effective_chat.id)
    await update.message.reply_text("Moderación desactivada en este chat.")

async def message_handler(update, context):
    msg = update.message
    if not msg or not msg.text:
        return
    chat_id = update.effective_chat.id
    text = msg.text.lower()

    if is_chat_moderated(chat_id):
        for w in BANNED_WORDS:
            if w in text:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=msg.message_id)
                except Exception:
                    logger.exception("No pude eliminar el mensaje")
                return

# --- Recuperación de canales ---
def _create_report(user, channel_url: str):
    report_id = uuid.uuid4().hex[:8]
    report = {
        "id": report_id,
        "user_id": user.id,
        "user_name": user.username or f"{user.first_name} {getattr(user, 'last_name', '')}".strip(),
        "channel_url": channel_url,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "status": "pending",
        "response_by": None,
        "response_at": None,
    }
    STATE.setdefault("reports", []).append(report)
    save_state(STATE)
    return report

async def report_recovery(update, context):
    text = update.message.text or ""
    args = text.split(" ", 1)
    if len(args) < 2 or not args[1].strip():
        await update.message.reply_text("Uso: /report_recovery <url_del_canal>\nEj: /report_recovery https://t.me/mi_canal")
        return
    channel_url = args[1].strip()
    report = _create_report(update.effective_user, channel_url)
    await update.message.reply_text(f"Reporte creado (ID: {report['id']}). Tu solicitud será revisada por el equipo de recuperación.")

    if not RECOVERY_CHAT_ID:
        await update.message.reply_text("RECOVERY_CHAT_ID no está configurado. No se puede notificar al equipo.")
        return
    try:
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Proveer ✅", callback_data=f"recovery:{report['id']}:approve"),
                    InlineKeyboardButton("No proveer ❌", callback_data=f"recovery:{report['id']}:deny"),
                ]
            ]
        )
        text_to_admin = (
            f"🔔 Nuevo reporte de recuperación\n"
            f"Report ID: {report['id']}\n"
            f"Usuario: @{report['user_name']} (id: {report['user_id']})\n"
            f"Canal/URL: {report['channel_url']}\n"
            f"Creado: {report['created_at']}\n\n"
            f"Usa los botones para marcar si el canal fue recuperado o no."
        )
        await context.bot.send_message(chat_id=int(RECOVERY_CHAT_ID), text=text_to_admin, reply_markup=keyboard)
    except Exception as e:
        logger.exception("Error enviando reporte al chat de recuperación")
        await update.message.reply_text(f"No pude notificar al equipo de recuperación: {e}")

async def recovery_callback_handler(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "recovery":
        return
    report_id = parts[1]
    action = parts[2]

    clicker_id = query.from_user.id
    admins = _admin_ids_set()
    if admins and clicker_id not in admins:
        await query.edit_message_text(query.message.text + f"\n\n⚠️ Usuario @{query.from_user.username or query.from_user.id} intentó interactuar pero no está autorizado.")
        await query.answer("No estás autorizado para responder este reporte.", show_alert=True)
        return

    reports = STATE.setdefault("reports", [])
    report = next((r for r in reports if r["id"] == report_id), None)
    if not report:
        await query.answer("Reporte no encontrado.", show_alert=True)
        return

    if report.get("status") != "pending":
        await query.answer("Este reporte ya fue respondido.", show_alert=True)
        return

    if action == "approve":
        report["status"] = "provided"
    else:
        report["status"] = "denied"
    report["response_by"] = clicker_id
    report["response_at"] = datetime.utcnow().isoformat() + "Z"
    save_state(STATE)

    responder = query.from_user.username or f"{query.from_user.first_name}"
    try:
        await query.edit_message_text(
            query.message.text + f"\n\n✅ Respondido por {responder} - Resultado: {report['status']}"
        )
    except Exception:
        pass

    try:
        user_id = report["user_id"]
        if report["status"] == "provided":
            await context.bot.send_message(chat_id=user_id, text=f"Tu reporte (ID: {report_id}) para {report['channel_url']} ha sido RESPONDIDO: ✅ Se indicó que se PROVEE la recuperación.")
        else:
            await context.bot.send_message(chat_id=user_id, text=f"Tu reporte (ID: {report_id}) para {report['channel_url']} ha sido RESPONDIDO: ❌ No se provee la recuperación.")
    except Exception:
        logger.exception("No pude notificar al usuario sobre la respuesta al reporte")

async def recovery_status(update, context):
    text = update.message.text or ""
    args = text.split(" ", 1)
    if len(args) < 2 or not args[1].strip():
        await update.message.reply_text("Uso: /recovery_status <report_id>\nEj: /recovery_status a1b2c3d4")
        return
    report_id = args[1].strip()
    reports = STATE.setdefault("reports", [])
    report = next((r for r in reports if r["id"] == report_id), None)
    if not report:
        await update.message.reply_text("Reporte no encontrado.")
        return
    reply = (
        f"Report ID: {report['id']}\n"
        f"Usuario: @{report['user_name']} (id: {report['user_id']})\n"
        f"Canal: {report['channel_url']}\n"
        f"Creado: {report['created_at']}\n"
        f"Estado: {report['status']}\n"
    )
    if report.get("response_by"):
        reply += f"Respondido por: {report['response_by']} a las {report.get('response_at')}\n"
    await update.message.reply_text(reply)

# --- Main ---
def main():
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("generate_script", generate_script))
    application.add_handler(CommandHandler("image", image_cmd))
    application.add_handler(CommandHandler("chat", chat_cmd))
    application.add_handler(CommandHandler("moderate_on", moderate_on))
    application.add_handler(CommandHandler("moderate_off", moderate_off))

    application.add_handler(CommandHandler("report_recovery", report_recovery))
    application.add_handler(CommandHandler("recovery_status", recovery_status))
    application.add_handler(CallbackQueryHandler(recovery_callback_handler, pattern=r"^recovery:"))

    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), message_handler))

    logger.info("Bot iniciado")
    application.run_polling()

if __name__ == "__main__":
    main()