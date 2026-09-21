from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.enums import MessageOriginType
from core.database import db
from core.loader import reload_materials_for
from admin_bot.state import AdminState
from core.keyboards import get_cancel_keyboard, remove_reply_keyboard
from config.settings import BACKUP_CHANNEL_ID
from admin_bot.permissions import (
    ADD_MATERIALS,
    DELETE_MATERIALS,
    MATERIAL_PERMISSIONS,
    REORDER_MATERIALS,
    has_permission,
    has_any_permission,
    require_callback_menu_scope,
    require_callback_permission,
    require_message_menu_scope,
    require_message_permission,
)

router = Router()


def format_materials_text(materials: list, menu_name: str, prefix_text: str = "") -> str:
    text = f"{prefix_text}📎 <b>ملفات القائمة:</b> {menu_name}\n\n"
    if not materials:
        text += "لا توجد ملفات مربوطة بهذا الزر."
        return text
    for i, mat in enumerate(materials, start=1):
        if str(mat['channel_id']) == 'TEXT':
            content = mat['description'] or ""
            content = (content[:30] + '..') if len(content) > 30 else content
            text += f"{i}. <b>رسالة نصية:</b>\n   📝 {content}\n\n"
        else:
            desc = mat['description'] or "بدون وصف"
            text += f"{i}. <b>ملف:</b> (قناة: <code>{mat['channel_id']}</code> | رسالة: <code>{mat['message_id']}</code>)\n"
            text += f"   📝 {desc}\n\n"
    return text


async def get_materials_keyboard(menu_name: str, user_id: int) -> InlineKeyboardMarkup:
    """Build keyboard for materials list."""
    buttons = []
    if await has_permission(user_id, ADD_MATERIALS):
        buttons.append([InlineKeyboardButton(text="➕ إضافة ملفات (Forward)", callback_data=f"matadd:{menu_name}")])
        buttons.append([InlineKeyboardButton(text="➕ إضافة نص (رسالة منفصلة)", callback_data=f"mataddtext:{menu_name}")])
    if await has_permission(user_id, REORDER_MATERIALS):
        buttons.append([InlineKeyboardButton(text="🔀 ترتيب العناصر", callback_data=f"matswap:{menu_name}")])
    if await has_permission(user_id, DELETE_MATERIALS):
        buttons.append([InlineKeyboardButton(text="❌ حذف عنصر", callback_data=f"matrmv:{menu_name}")])
    buttons.append([InlineKeyboardButton(text="⬅️ رجوع", callback_data=f"v:{menu_name}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@router.callback_query(F.data.startswith('mat:'))
async def cb_materials_list(callback: CallbackQuery, state: FSMContext):
    if not await has_any_permission(callback.from_user.id, MATERIAL_PERMISSIONS):
        await callback.answer("❌ لا تملك صلاحية إدارة الملفات.", show_alert=True)
        return
    menu_name = callback.data.split(':', 1)[1]
    if not await require_callback_menu_scope(callback, menu_name):
        return
    await callback.answer()
    
    materials = await db.get_materials(menu_name)
    text = format_materials_text(materials, menu_name)
            
    await callback.message.edit_text(
        text, 
        reply_markup=await get_materials_keyboard(menu_name, callback.from_user.id),
        parse_mode='HTML'
    )

# ─── Add Material ─────────────────────────────────────────────

@router.callback_query(F.data.startswith('matadd:'))
async def cb_add_material(callback: CallbackQuery, state: FSMContext):
    if not await require_callback_permission(callback, ADD_MATERIALS):
        return
    menu_name = callback.data.split(':', 1)[1]
    if not await require_callback_menu_scope(callback, menu_name):
        return
    await callback.answer()
    
    current_materials = await db.get_materials(menu_name)
    if len(current_materials) >= 10:
        await callback.answer("❌ عذراً، لقد وصلت للحد الأقصى (10 ملفات/رسائل) في هذا الزر.\nقم بإنشاء زر جديد أو حذف ملفات قديمة.", show_alert=True)
        return

    # Initialize empty list for materials in state
    await state.update_data(editing_menu=menu_name, temp_materials=[])
    
    # Send instructions with a Reply keyboard for "✅ تم"
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ تم")],
            [KeyboardButton(text="❌ إلغاء")]
        ],
        resize_keyboard=True
    )
    
    await callback.message.answer(
        "قم بعمل Forward للرسائل من القناة.\n\nيمكنك إرسال أكثر من رسالة.\n\nبعد الانتهاء اضغط: ✅ تم",
        reply_markup=keyboard
    )
    await state.set_state(AdminState.waiting_materials)

@router.message(AdminState.waiting_materials, F.text == "✅ تم")
async def on_materials_done(message: Message, state: FSMContext):
    if not await require_message_permission(message, ADD_MATERIALS):
        await state.clear()
        return
    data = await state.get_data()
    if not await require_message_menu_scope(message, data.get('editing_menu')):
        await state.clear()
        return
    temp_materials = data.get("temp_materials", [])
    
    if not temp_materials:
        await message.answer("لم يتم إرسال أي ملفات بعد. الرجاء عمل Forward لرسالة أو أكثر، ثم الضغط على ✅ تم.")
        return
        
    await message.answer(
        "أرسل وصفاً للملفات أو أرسل \".\" للتخطي",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminState.waiting_material_desc)

@router.message(AdminState.waiting_materials)
async def on_material_forward(message: Message, state: FSMContext):
    if not await require_message_permission(message, ADD_MATERIALS):
        await state.clear()
        return
    # Check if message is a forward from a channel
    if not message.forward_origin or message.forward_origin.type != MessageOriginType.CHANNEL:
        await message.answer("❌ الرجاء عمل Forward من القناة بشكل صحيح.")
        return
        
    data = await state.get_data()
    menu_name = data.get('editing_menu')
    if not await require_message_menu_scope(message, menu_name):
        await state.clear()
        return
    temp_materials = data.get("temp_materials", [])
    
    current_materials = await db.get_materials(menu_name)
    if len(current_materials) + len(temp_materials) >= 10:
        await message.answer("❌ عذراً، لقد وصلت للحد الأقصى (10 ملفات/رسائل).\nاضغط ✅ تم لحفظ ما قمت بإرساله.")
        return

    # Copy message to backup channel for permanent storage
    try:
        stored = await message.bot.copy_message(
            chat_id=BACKUP_CHANNEL_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id
        )
        store_channel_id = str(BACKUP_CHANNEL_ID)
        store_message_id = stored.message_id
    except Exception as e:
        await message.answer(f"❌ فشل حفظ الملف في قناة التخزين.\n<code>{e}</code>", parse_mode="HTML")
        return

    # Prevent duplicates in the same batch
    for m in temp_materials:
        if m["store_channel_id"] == store_channel_id and m["store_message_id"] == store_message_id:
            await message.answer("⚠️ تم إضافة هذه الرسالة مسبقاً في هذه الدفعة.")
            return
            
    temp_materials.append({
        "store_channel_id": store_channel_id,
        "store_message_id": store_message_id,
    })
    
    await state.update_data(temp_materials=temp_materials)
    await message.answer(f"✅ تمت إضافة الملف (إجمالي الملفات الآن: {len(temp_materials)})")

@router.message(AdminState.waiting_material_desc)
async def on_material_desc(message: Message, state: FSMContext):
    if not await require_message_permission(message, ADD_MATERIALS):
        await state.clear()
        return
    data = await state.get_data()
    menu_name = data.get('editing_menu')
    if not await require_message_menu_scope(message, menu_name):
        await state.clear()
        return
    temp_materials = data.get('temp_materials', [])
    desc = message.text if message.text != '.' else None
    
    await remove_reply_keyboard(message)

    # Get current max order
    existing = await db.get_materials(menu_name)
    next_order = max([m['order_index'] for m in existing] + [-1]) + 1
    
    rows = []
    for mat in temp_materials:
        rows.append((
            menu_name,
            mat['store_channel_id'],
            mat['store_message_id'],
            desc,
            next_order,
            None,
            None,
        ))
        next_order += 1
    await db.add_materials(rows)
        
    await reload_materials_for(menu_name)
    await state.clear()
    
    # Send success message
    await message.answer(f"✅ تم حفظ {len(temp_materials)} ملف/ملفات بنجاح!")
    
    # Back to materials list
    materials = await db.get_materials(menu_name)
    text = format_materials_text(materials, menu_name)
            
    await message.answer(
        text, 
        reply_markup=await get_materials_keyboard(menu_name, message.from_user.id),
        parse_mode='HTML'
    )

# ─── Add Text Message ─────────────────────────────────────────

@router.callback_query(F.data.startswith('mataddtext:'))
async def cb_add_text_message(callback: CallbackQuery, state: FSMContext):
    if not await require_callback_permission(callback, ADD_MATERIALS):
        return
    menu_name = callback.data.split(':', 1)[1]
    if not await require_callback_menu_scope(callback, menu_name):
        return
    await callback.answer()

    current_materials = await db.get_materials(menu_name)
    if len(current_materials) >= 10:
        await callback.answer("❌ عذراً، لقد وصلت للحد الأقصى (10 ملفات/رسائل) في هذا الزر.\nقم بإنشاء زر جديد أو حذف ملفات قديمة.", show_alert=True)
        return

    await state.update_data(editing_menu=menu_name)
    
    await callback.message.answer("أرسل الرسالة النصية التي تريد إضافتها:", reply_markup=get_cancel_keyboard())
    await state.set_state(AdminState.waiting_text_message)

@router.message(AdminState.waiting_text_message)
async def on_text_message(message: Message, state: FSMContext):
    if not await require_message_permission(message, ADD_MATERIALS):
        await state.clear()
        return
    data = await state.get_data()
    menu_name = data.get('editing_menu')
    if not await require_message_menu_scope(message, menu_name):
        await state.clear()
        return
    text_content = message.text
    
    await remove_reply_keyboard(message)

    existing = await db.get_materials(menu_name)
    next_order = max([m['order_index'] for m in existing] + [-1]) + 1
    
    # channel_id = 'TEXT', message_id = 0, description = actual text
    await db.add_material(menu_name, 'TEXT', 0, text_content, next_order)
    
    await reload_materials_for(menu_name)
    await state.clear()
    
    materials = await db.get_materials(menu_name)
    text = format_materials_text(materials, menu_name, "✅ <b>تم إضافة الرسالة النصية بنجاح!</b>\n\n")
            
    await message.answer(
        text, 
        reply_markup=await get_materials_keyboard(menu_name, message.from_user.id),
        parse_mode='HTML'
    )

# ─── Remove Material ──────────────────────────────────────────

@router.callback_query(F.data.startswith('matrmv:'))
async def cb_remove_material(callback: CallbackQuery, state: FSMContext):
    if not await require_callback_permission(callback, DELETE_MATERIALS):
        return
    menu_name = callback.data.split(':', 1)[1]
    if not await require_callback_menu_scope(callback, menu_name):
        return
    await callback.answer()
    
    materials = await db.get_materials(menu_name)
    if not materials:
        await callback.message.answer("لا توجد ملفات لحذفها.")
        return
        
    buttons = []
    for mat in materials:
        if mat['channel_id'] == 'TEXT':
            desc = mat['description']
            desc = (desc[:20] + '..') if len(desc) > 20 else desc
            btn_text = f"❌ نص | {desc}"
        else:
            desc = mat['description'] or f"رسالة {mat['message_id']}"
            desc = (desc[:20] + '..') if len(desc) > 20 else desc
            btn_text = f"❌ ملف | {desc}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"matdel:{mat['id']}")])
        
    buttons.append([InlineKeyboardButton(text="⬅️ إلغاء", callback_data=f"mat:{menu_name}")])
    
    await callback.message.edit_text(
        "اختر الملف المراد حذفه:", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

@router.callback_query(F.data.startswith('matdel:'))
async def cb_delete_material_confirm(callback: CallbackQuery, state: FSMContext):
    if not await require_callback_permission(callback, DELETE_MATERIALS):
        return
    mat_id = int(callback.data.split(':', 1)[1])
    
    mat = await db.get_material_by_id(mat_id)
    if not mat:
        await callback.message.edit_text("❌ الملف غير موجود أو تم حذفه مسبقاً.")
        return
        
    menu_name = mat['menu_name']
    if not await require_callback_menu_scope(callback, menu_name):
        return
    await callback.answer()
    await db.remove_material(mat_id)
    
    await reload_materials_for(menu_name)
    
    # Back to materials list
    materials = await db.get_materials(menu_name)
    text = format_materials_text(materials, menu_name, "✅ <b>تم حذف الملف بنجاح!</b>\n\n")
            
    await callback.message.edit_text(
        text, 
        reply_markup=await get_materials_keyboard(menu_name, callback.from_user.id),
        parse_mode='HTML'
    )

# ─── Reorder Materials ────────────────────────────────────────

@router.callback_query(F.data.startswith('matswap:'))
async def cb_reorder_materials(callback: CallbackQuery, state: FSMContext):
    if not await require_callback_permission(callback, REORDER_MATERIALS):
        return
    menu_name = callback.data.split(':', 1)[1]
    if not await require_callback_menu_scope(callback, menu_name):
        return
    await callback.answer()
    
    materials = await db.get_materials(menu_name)
    if len(materials) < 2:
        await callback.message.answer("يجب أن يكون هناك عنصرين على الأقل للترتيب.")
        return
        
    buttons = []
    for mat in materials:
        if mat['channel_id'] == 'TEXT':
            desc = mat['description']
            desc = (desc[:20] + '..') if len(desc) > 20 else desc
            btn_text = f"نص | {desc}"
        else:
            desc = mat['description'] or f"رسالة {mat['message_id']}"
            desc = (desc[:20] + '..') if len(desc) > 20 else desc
            btn_text = f"ملف | {desc}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"ms1:{mat['id']}")])
        
    buttons.append([InlineKeyboardButton(text="⬅️ إلغاء", callback_data=f"mat:{menu_name}")])
    
    await callback.message.edit_text(
        "اختر العنصر الأول الذي تريد تغيير مكانه:", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

@router.callback_query(F.data.startswith('ms1:'))
async def cb_swap_first(callback: CallbackQuery, state: FSMContext):
    if not await require_callback_permission(callback, REORDER_MATERIALS):
        return
    mat_id_1 = int(callback.data.split(':', 1)[1])
    
    mat1 = await db.get_material_by_id(mat_id_1)
    if not mat1:
        await callback.message.edit_text("❌ العنصر غير موجود.")
        return
        
    menu_name = mat1['menu_name']
    if not await require_callback_menu_scope(callback, menu_name):
        return
    await callback.answer()
    await state.update_data(swap_mat_first=mat_id_1, editing_menu=menu_name)
    
    materials = await db.get_materials(menu_name)
    buttons = []
    for mat in materials:
        if mat['id'] == mat_id_1:
            continue
        if mat['channel_id'] == 'TEXT':
            desc = mat['description']
            desc = (desc[:20] + '..') if len(desc) > 20 else desc
            btn_text = f"نص | {desc}"
        else:
            desc = mat['description'] or f"رسالة {mat['message_id']}"
            desc = (desc[:20] + '..') if len(desc) > 20 else desc
            btn_text = f"ملف | {desc}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"ms2:{mat['id']}")])
        
    buttons.append([InlineKeyboardButton(text="⬅️ إلغاء", callback_data=f"mat:{menu_name}")])
    
    await callback.message.edit_text(
        "اختر العنصر الثاني لتبديل الأماكن بينهما:", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

@router.callback_query(F.data.startswith('ms2:'))
async def cb_swap_second(callback: CallbackQuery, state: FSMContext):
    if not await require_callback_permission(callback, REORDER_MATERIALS):
        return
    mat_id_2 = int(callback.data.split(':', 1)[1])
    
    data = await state.get_data()
    mat_id_1 = data.get('swap_mat_first')
    menu_name = data.get('editing_menu')
    if not await require_callback_menu_scope(callback, menu_name):
        return
    await callback.answer()
    
    await db.swap_materials(mat_id_1, mat_id_2)
    
    await reload_materials_for(menu_name)
    await state.clear()
    
    materials = await db.get_materials(menu_name)
    text = format_materials_text(materials, menu_name, "✅ <b>تم تبديل الأماكن بنجاح!</b>\n\n")
            
    await callback.message.edit_text(
        text, 
        reply_markup=await get_materials_keyboard(menu_name, callback.from_user.id),
        parse_mode='HTML'
    )
