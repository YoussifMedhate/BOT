import asyncio
import io
import logging
import os
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from admin_bot.state import BackupStates
from config.settings import BACKUP_CHANNEL_ID, DB_PATH
from core.database import db
from core.infrastructure.blocking import run_blocking
from core.loader import reload_menus
from admin_bot.permissions import BACKUP, require_callback_permission, require_message_permission

router = Router()
_backup_lock = asyncio.Lock()
logger = logging.getLogger(__name__)

# ─── Helpers ──────────────────────────────────────────────────


def _create_backup_zip_sync() -> tuple[str, bytes]:
    """
    Snapshot the live database with SQLite's backup API and compress it.

    The backup API reads a consistent snapshot even when the live DB is in WAL
    mode, avoiding raw file copies while writes are happening.
    """
    now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    zip_filename = f"backup_{now}.zip"

    # Build a unique path in the temp directory — no file is created here.
    tmp_dir = tempfile.gettempdir()
    tmp_backup = os.path.join(tmp_dir, f"bot_backup_{uuid.uuid4().hex}.db")

    try:
        source = sqlite3.connect(DB_PATH)
        target = sqlite3.connect(tmp_backup)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()

        with open(tmp_backup, "rb") as f:
            db_bytes = f.read()

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("bot_structure.db", db_bytes)

        return zip_filename, zip_buffer.getvalue()
    finally:
        if os.path.exists(tmp_backup):
            os.remove(tmp_backup)


def _extract_db_from_zip_sync(zip_data: bytes) -> tuple[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(zip_data), "r") as zf:
        file_list = zf.namelist()
        db_file = None
        for f in file_list:
            if f.endswith(".db"):
                db_file = f
                break

        if not db_file:
            raise FileNotFoundError("الملف المضغوط لا يحتوي على ملف قاعدة بيانات (.db)")

        return db_file, zf.read(db_file)


def _restore_db_sync(db_data: bytes) -> None:
    backup_current = DB_PATH + ".before_restore"
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    shutil.copy2(DB_PATH, backup_current)

    for suffix in ("-wal", "-shm"):
        sidecar_path = DB_PATH + suffix
        if os.path.exists(sidecar_path):
            os.remove(sidecar_path)

    with open(DB_PATH, "wb") as f:
        f.write(db_data)


async def create_backup_zip() -> tuple[str, bytes]:
    """
    Create a zip backup of the database off the event loop.

    Concurrent-call guard
    ─────────────────────
    If a backup is already running (scheduler + manual trigger firing at the
    same time, for example), the second caller gets a RuntimeError immediately
    instead of queueing behind the lock and running a redundant backup.
    """
    if _backup_lock.locked():
        raise RuntimeError("عملية باك أب أخرى جارية حالياً. الرجاء الانتظار حتى تنتهي.")
    async with _backup_lock:
        return await run_blocking(_create_backup_zip_sync)


async def send_backup_to_channel(bot: Bot) -> None:
    """Create a backup and send it to the backup channel."""
    zip_filename, zip_bytes = await create_backup_zip()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    caption = f"💾 باك أب تلقائي\n📅 {now}"

    input_file = BufferedInputFile(zip_bytes, filename=zip_filename)
    await bot.send_document(
        chat_id=BACKUP_CHANNEL_ID,
        document=input_file,
        caption=caption,
    )
    logger.info("Backup sent to channel", extra={"event": "backup_sent"})


# ─── Backup Menu ──────────────────────────────────────────────


def get_backup_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💾 باك أب فوري", callback_data="backup_now")],
            [InlineKeyboardButton(text="📥 استعادة من ملف", callback_data="backup_restore")],
            [InlineKeyboardButton(text="⬅️ رجوع", callback_data="panel")],
        ]
    )


async def _callback_message(callback: CallbackQuery) -> Message | None:
    if isinstance(callback.message, Message):
        return callback.message
    await callback.answer("لا يمكن تعديل هذه الرسالة.", show_alert=True)
    return None


@router.callback_query(F.data == "backup")
async def cb_backup_menu(callback: CallbackQuery, state: FSMContext):
    if not await require_callback_permission(callback, BACKUP):
        return
    await callback.answer()
    await state.clear()
    message = await _callback_message(callback)
    if message is None:
        return
    await message.edit_text(
        "💾 <b>نظام باك أب قاعدة البيانات</b>\n\n" "اختر العملية المطلوبة:",
        reply_markup=get_backup_keyboard(),
        parse_mode="HTML",
    )


# ─── Instant Backup ──────────────────────────────────────────


@router.callback_query(F.data == "backup_now")
async def cb_backup_now(callback: CallbackQuery):
    if not await require_callback_permission(callback, BACKUP):
        return
    await callback.answer("⏳ جاري عمل الباك أب...")
    message = await _callback_message(callback)
    if message is None:
        return

    try:
        zip_filename, zip_bytes = await create_backup_zip()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        input_file = BufferedInputFile(zip_bytes, filename=zip_filename)

        # Send to admin in chat
        await message.answer_document(
            document=input_file,
            caption=f"💾 <b>باك أب فوري</b>\n📅 {now}\n📦 الحجم: {len(zip_bytes) / 1024:.1f} KB",
            parse_mode="HTML",
        )

        # Send to backup channel
        try:
            if callback.bot is None:
                raise RuntimeError("Telegram bot is not attached to callback.")
            input_file_channel = BufferedInputFile(zip_bytes, filename=zip_filename)
            await callback.bot.send_document(
                chat_id=BACKUP_CHANNEL_ID,
                document=input_file_channel,
                caption=f"💾 باك أب يدوي\n📅 {now}",
            )
            channel_msg = "✅ تم الإرسال للقناة"
        except Exception as e:
            channel_msg = f"⚠️ فشل الإرسال للقناة: {e}"

        await message.answer(
            f"✅ <b>تم عمل الباك أب بنجاح!</b>\n\n"
            f"📄 الملف: <code>{zip_filename}</code>\n"
            f"📦 الحجم: {len(zip_bytes) / 1024:.1f} KB\n"
            f"📢 القناة: {channel_msg}",
            reply_markup=get_backup_keyboard(),
            parse_mode="HTML",
        )
    except Exception as e:
        await message.answer(
            f"❌ حدث خطأ أثناء عمل الباك أب:\n<code>{e}</code>",
            reply_markup=get_backup_keyboard(),
            parse_mode="HTML",
        )


# ─── Restore Backup ──────────────────────────────────────────


@router.callback_query(F.data == "backup_restore")
async def cb_backup_restore(callback: CallbackQuery, state: FSMContext):
    if not await require_callback_permission(callback, BACKUP):
        return
    await callback.answer()
    message = await _callback_message(callback)
    if message is None:
        return
    await message.edit_text(
        "📥 <b>استعادة باك أب</b>\n\n"
        "أرسل ملف الباك أب (.zip) الآن.\n\n"
        "⚠️ <b>تحذير:</b> سيتم استبدال قاعدة البيانات الحالية بالكامل!",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ إلغاء", callback_data="backup")]]
        ),
        parse_mode="HTML",
    )
    await state.set_state(BackupStates.waiting_restore_file)


@router.message(BackupStates.waiting_restore_file, F.document)
async def on_restore_file(message: Message, state: FSMContext):
    if not await require_message_permission(message, BACKUP):
        await state.clear()
        return
    doc = message.document
    if doc is None:
        await message.answer("❌ الرجاء إرسال ملف (.zip) فقط.")
        return

    # Validate file extension
    if not doc.file_name or not doc.file_name.endswith(".zip"):
        await message.answer(
            "❌ الملف يجب أن يكون بصيغة <code>.zip</code>\nأرسل ملف zip صحيح أو اضغط إلغاء.",
            parse_mode="HTML",
        )
        return

    await message.answer("⏳ جاري استعادة الباك أب...")

    try:
        # Download the file
        if message.bot is None:
            raise RuntimeError("Telegram bot is not attached to message.")
        file = await message.bot.get_file(doc.file_id)
        if file.file_path is None:
            raise FileNotFoundError("Telegram did not return a downloadable file path.")
        file_bytes = await message.bot.download_file(file.file_path)
        if file_bytes is None:
            raise FileNotFoundError("Telegram did not return file bytes.")
        zip_data = file_bytes.read()

        try:
            db_file, db_data = await run_blocking(_extract_db_from_zip_sync, zip_data)
        except FileNotFoundError:
            await message.answer(
                "❌ الملف المضغوط لا يحتوي على ملف قاعدة بيانات (.db)",
                reply_markup=get_backup_keyboard(),
            )
            await state.clear()
            return

        async with _backup_lock:
            await db.close()
            try:
                await run_blocking(_restore_db_sync, db_data)
            finally:
                await db.init_db()
            await reload_menus()

        await state.clear()
        await message.answer(
            "✅ <b>تم استعادة الباك أب بنجاح!</b>\n\n"
            f"📄 الملف المُستعاد: <code>{db_file}</code>\n"
            f"📦 الحجم: {len(db_data) / 1024:.1f} KB\n\n"
            "💡 تم حفظ نسخة احتياطية من القاعدة القديمة تلقائياً.",
            reply_markup=get_backup_keyboard(),
            parse_mode="HTML",
        )

    except zipfile.BadZipFile:
        await message.answer(
            "❌ الملف المرسل ليس ملف zip صالح.", reply_markup=get_backup_keyboard()
        )
        await state.clear()
    except Exception as e:
        await message.answer(
            f"❌ حدث خطأ أثناء الاستعادة:\n<code>{e}</code>",
            reply_markup=get_backup_keyboard(),
            parse_mode="HTML",
        )
        await state.clear()


@router.message(BackupStates.waiting_restore_file)
async def on_restore_invalid(message: Message, state: FSMContext):
    if not await require_message_permission(message, BACKUP):
        await state.clear()
        return
    await message.answer("❌ الرجاء إرسال ملف (.zip) فقط.")
