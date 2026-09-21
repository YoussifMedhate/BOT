from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from core.keyboards import remove_reply_keyboard, get_cancel_keyboard
from core.database import db
from admin_bot.state import BroadcastStates
import asyncio
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError
from core.bot import main_bot
from admin_bot.permissions import (
    ANALYTICS,
    BACKUP,
    BROADCAST,
    MENU_AREA_PERMISSIONS,
    has_any_permission,
    has_permission,
    is_owner,
    require_callback_permission,
    require_message_permission,
)

router = Router()

# ── Broadcast tuning constants ──────────────────────────────────────────────
# Number of users processed concurrently in each asyncio.gather() call.
# Telegram's documented limit is ~30 messages/second for bots.  With
# BATCH_SIZE=25 and INTER_BATCH_DELAY=1.1 s we stay comfortably under that.
BROADCAST_BATCH_SIZE = 25
BROADCAST_USER_READ_BATCH_SIZE = 500
BROADCAST_MAX_RETRIES = 3

# Seconds to wait between consecutive batches to respect Telegram rate limits.
BROADCAST_INTER_BATCH_DELAY = 1.1

# Send a progress update to the admin after every N batches.
BROADCAST_PROGRESS_EVERY = 10
# ────────────────────────────────────────────────────────────────────────────


async def _copy_broadcast_message(user_id: int, admin_id: int, msg_id: int) -> bool:
    retries = BROADCAST_MAX_RETRIES
    while retries > 0:
        try:
            await main_bot.copy_message(chat_id=user_id, from_chat_id=admin_id, message_id=msg_id)
            return True
        except TelegramRetryAfter as e:
            retries -= 1
            await asyncio.sleep(e.retry_after)
        except TelegramForbiddenError:
            return False
        except Exception:
            retries -= 1
            if retries == 0:
                return False
            await asyncio.sleep(0.5)
    return False


async def _send_broadcast_to_user(user_id: int, admin_id: int, msg_ids: list[int]) -> bool:
    for msg_id in msg_ids:
        if not await _copy_broadcast_message(user_id, admin_id, msg_id):
            return False
    return True


async def _send_broadcast_batch(user_ids: list[int], admin_id: int, msg_ids: list[int]) -> tuple[int, int]:
    results = await asyncio.gather(
        *(_send_broadcast_to_user(user_id, admin_id, msg_ids) for user_id in user_ids),
        return_exceptions=True,
    )
    success_count = 0
    fail_count = 0
    for result in results:
        if result is True:
            success_count += 1
        else:
            fail_count += 1
    return success_count, fail_count


async def get_panel_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Return the main admin panel inline keyboard."""
    rows = []
    if await has_any_permission(user_id, MENU_AREA_PERMISSIONS):
        rows.append([
            InlineKeyboardButton(text='📋 كل القوائم', callback_data='list'),
            InlineKeyboardButton(text='🌳 الشجرة', callback_data='tree'),
        ])
    if await has_permission(user_id, BROADCAST):
        rows.append([InlineKeyboardButton(text='📢 إذاعة للجميع', callback_data='broadcast')])
    if await has_permission(user_id, BACKUP):
        rows.append([InlineKeyboardButton(text='💾 باك أب', callback_data='backup')])
    if await has_permission(user_id, ANALYTICS):
        rows.append([InlineKeyboardButton(text='📊 الإحصائيات', callback_data='analytics')])
    if is_owner(user_id):
        rows.append([InlineKeyboardButton(text='👥 المشرفين', callback_data='admins')])
    if not rows:
        rows.append([InlineKeyboardButton(text='لا توجد صلاحيات مفعلة', callback_data='panel')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer('🛠 لوحة تحكم الأدمن', reply_markup=await get_panel_keyboard(message.from_user.id))


@router.callback_query(F.data == 'panel')
async def cb_panel(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        '🛠 لوحة تحكم الأدمن',
        reply_markup=await get_panel_keyboard(callback.from_user.id),
    )

@router.message(F.text == "❌ إلغاء")
async def cancel_handler(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        return
    await state.clear()
    await remove_reply_keyboard(message)
    await message.answer(
        "✅ تم الإلغاء ورجوعك للقائمة الرئيسية.",
        reply_markup=await get_panel_keyboard(message.from_user.id),
    )

@router.callback_query(F.data == 'broadcast')
async def cb_start_broadcast(callback: CallbackQuery, state: FSMContext):
    if not await require_callback_permission(callback, BROADCAST):
        return
    await callback.answer()
    user_count = await db.count_users()
    if not user_count:
        await callback.message.answer("❌ لا يوجد أي مستخدمين مسجلين في البوت بعد.")
        return
        
    await state.update_data(broadcast_messages=[])
    
    from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ تم (إرسال للجميع)")],
            [KeyboardButton(text="❌ إلغاء العملية")]
        ],
        resize_keyboard=True
    )
    
    await callback.message.answer(
        f"👥 عدد المستخدمين الحاليين: {user_count}\n\n"
        "أرسل الآن رسائلك (نص، صورة، فيديو، أو ملف).\n"
        "يمكنك إرسال أكثر من رسالة وسيتم تجميعها.\n"
        "عند الانتهاء اضغط على الزر أسفل الشاشة لإرسالها للجميع.",
        reply_markup=kb
    )
    await state.set_state(BroadcastStates.collecting_messages)

@router.message(BroadcastStates.collecting_messages, F.text == "❌ إلغاء العملية")
async def cancel_broadcast(message: Message, state: FSMContext):
    if not await require_message_permission(message, BROADCAST):
        await state.clear()
        return
    await state.clear()
    await remove_reply_keyboard(message)
    await message.answer(
        "✅ تم إلغاء الإذاعة.",
        reply_markup=await get_panel_keyboard(message.from_user.id),
    )

@router.message(BroadcastStates.collecting_messages, ~F.text.in_({"✅ تم (إرسال للجميع)", "❌ إلغاء العملية"}))
async def collect_broadcast_message(message: Message, state: FSMContext):
    if not await require_message_permission(message, BROADCAST):
        await state.clear()
        return
    data = await state.get_data()
    msgs = data.get("broadcast_messages", [])
    

    admin_id = message.from_user.id
    text_to_send = message.html_text if message.text or message.caption else None
    
    main_msg_id = None
    try:
        if message.text:
            main_message = await main_bot.send_message(chat_id=admin_id, text=message.html_text)
            main_msg_id = main_message.message_id
        elif message.photo:
            file = await message.bot.get_file(message.photo[-1].file_id)
            file_bytes = await message.bot.download_file(file.file_path)
            from aiogram.types import BufferedInputFile
            input_file = BufferedInputFile(file_bytes.read(), filename="photo.jpg")
            main_message = await main_bot.send_photo(chat_id=admin_id, photo=input_file, caption=text_to_send)
            main_msg_id = main_message.message_id
        elif message.video:
            file = await message.bot.get_file(message.video.file_id)
            file_bytes = await message.bot.download_file(file.file_path)
            from aiogram.types import BufferedInputFile
            input_file = BufferedInputFile(file_bytes.read(), filename="video.mp4")
            main_message = await main_bot.send_video(chat_id=admin_id, video=input_file, caption=text_to_send)
            main_msg_id = main_message.message_id
        elif message.document:
            file = await message.bot.get_file(message.document.file_id)
            file_bytes = await message.bot.download_file(file.file_path)
            from aiogram.types import BufferedInputFile
            input_file = BufferedInputFile(file_bytes.read(), filename=message.document.file_name or "document")
            main_message = await main_bot.send_document(chat_id=admin_id, document=input_file, caption=text_to_send)
            main_msg_id = main_message.message_id
        else:
            await message.answer("❌ نوع الرسالة هذا غير مدعوم للإذاعة حالياً.")
            return
    except Exception as e:
        await message.answer(f"❌ حدث خطأ أثناء تجهيز الرسالة للبوت الأساسي. تأكد أنك قمت ببدء البوت الأساسي أولاً!\nالخطأ: {e}")
        return
        


        
    msgs.append(main_msg_id)
    await state.update_data(broadcast_messages=msgs)
    await message.answer(f"✅ تم حفظ الرسالة رقم {len(msgs)}. (أرسل المزيد أو اضغط تم)")

@router.message(BroadcastStates.collecting_messages, F.text == "✅ تم (إرسال للجميع)")
async def execute_broadcast(message: Message, state: FSMContext):
    if not await require_message_permission(message, BROADCAST):
        await state.clear()
        return
    data = await state.get_data()
    msgs = data.get("broadcast_messages", [])
    
    await state.clear()
    await remove_reply_keyboard(message)
    
    if not msgs:
        await message.answer(
            "❌ لم تقم بإرسال أي رسائل لجمعها.",
            reply_markup=await get_panel_keyboard(message.from_user.id),
        )
        return

    total_users = await db.count_users()
    await message.answer(
        f"⏳ جاري الإرسال لـ {total_users} مستخدم...\n"
        f"📝 عدد الرسائل: {len(msgs)}\n"
        f"📦 حجم الدفعة: {BROADCAST_BATCH_SIZE} مستخدم\n"
        "سيتم إرسال تحديثات دورية أثناء الإرسال."
    )

    admin_id = message.from_user.id
    success_count = 0
    fail_count = 0
    batch_number = 0

    batch: list[int] = []
    async for user_id in db.iter_user_ids(BROADCAST_USER_READ_BATCH_SIZE):
        # Skip the admin — they already have the message
        if user_id == admin_id:
            continue

        batch.append(user_id)
        if len(batch) >= BROADCAST_BATCH_SIZE:
            batch_success, batch_fail = await _send_broadcast_batch(batch, admin_id, msgs)
            success_count += batch_success
            fail_count += batch_fail
            batch_number += 1
            batch = []

            # ── Rate limit: pause between batches ──────────────────────────
            # BROADCAST_INTER_BATCH_DELAY keeps us safely under Telegram's
            # ~30 messages/second per-bot ceiling across concurrent sends.
            await asyncio.sleep(BROADCAST_INTER_BATCH_DELAY)

            # ── Progress update every N batches ────────────────────────────
            if batch_number % BROADCAST_PROGRESS_EVERY == 0:
                processed = (success_count + fail_count)
                try:
                    await message.answer(
                        f"📊 تقدم الإذاعة:\n"
                        f"✅ نجح: {success_count}\n"
                        f"❌ فشل: {fail_count}\n"
                        f"🔄 المُعالَج: {processed} من أصل ~{total_users}"
                    )
                except Exception:
                    pass  # never let a progress message abort the broadcast

    # Flush the last partial batch
    if batch:
        batch_success, batch_fail = await _send_broadcast_batch(batch, admin_id, msgs)
        success_count += batch_success
        fail_count += batch_fail

    await message.answer(
        f"✅ **اكتملت الإذاعة المجمعة!**\n\n"
        f"📝 عدد الرسائل في هذه الدفعة: {len(msgs)}\n"
        f"📬 وصلت الدفعة بنجاح إلى: {success_count} مستخدم\n"
        f"❌ فشل الإرسال إلى: {fail_count} مستخدم",
        reply_markup=await get_panel_keyboard(message.from_user.id)
    )
