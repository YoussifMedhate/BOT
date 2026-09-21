from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from config.settings import DEV_IDS
from core.database import db
from core.loader import reload_custom_buttons

router = Router()

def is_dev(user_id: int) -> bool:
    return user_id in DEV_IDS

@router.message(CommandStart())
async def cmd_start(message: Message):
    if not is_dev(message.from_user.id):
        await message.answer("❌ عذراً، هذا البوت مخصص للمطورين فقط.")
        return

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 عرض الطلبات المعلقة")]
        ],
        resize_keyboard=True
    )
    await message.answer("👋 مرحباً بك في لوحة المطورين!\nاختر ما تريد القيام به من القائمة أدناه:", reply_markup=kb)


@router.message(F.text == "📋 عرض الطلبات المعلقة")
async def show_pending_requests(message: Message):
    if not is_dev(message.from_user.id):
        return

    pending_buttons = await db.get_pending_buttons()
    
    if not pending_buttons:
        await message.answer("✅ لا توجد أي طلبات برمجة معلقة حالياً. عمل رائع!")
        return

    await message.answer(f"🔍 تم العثور على {len(pending_buttons)} طلب معلق:")

    for btn in pending_buttons:
        name = btn['button_name']
        desc = btn['description']
        menu_name = btn.get('menu_name') or 'غير محدد'
        
        text = (
            f"🔹 <b>اسم الزر:</b> {name}\n"
            f"📍 <b>القائمة:</b> {menu_name}\n"
            f"📝 <b>الوصف/المطلوب:</b>\n{desc}"
        )
        
        ikb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ تم الإنجاز", callback_data=f"dev_done:{name}")]
        ])
        
        await message.answer(text, reply_markup=ikb, parse_mode='HTML')


@router.callback_query(F.data.startswith("dev_done:"))
async def cb_mark_done(callback: CallbackQuery):
    if not is_dev(callback.from_user.id):
        await callback.answer("غير مصرح", show_alert=True)
        return

    button_name = callback.data.split(":", 1)[1]
    
    await db.mark_button_done(button_name)
    await reload_custom_buttons()
    
    await callback.message.edit_text(
        f"{callback.message.html_text}\n\n"
        f"✅ <b>تم إنجاز هذا الطلب وتفعيله في البوت الأساسي.</b>",
        parse_mode='HTML'
    )
    await callback.answer("تم تحديث حالة الزر بنجاح!")
