from __future__ import annotations

import os

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config.settings import ANALYTICS_DEAD_LETTER_PATH
from core.application.analytics_service import analytics_service, analytics_writer
from core.monitoring.health import get_health_report
from core.workers.analytics_writer import replay_dead_letters
from admin_bot.permissions import ANALYTICS, require_callback_permission

router = Router()


def _dead_letter_count() -> int:
    """Return the number of pending entries in the dead-letter file."""
    if not os.path.exists(ANALYTICS_DEAD_LETTER_PATH):
        return 0
    try:
        with open(ANALYTICS_DEAD_LETTER_PATH, encoding="utf-8") as fh:
            return sum(1 for line in fh if line.strip())
    except OSError:
        return 0


def _analytics_keyboard() -> InlineKeyboardMarkup:
    dl_count = _dead_letter_count()
    dl_label = f"♻️ Replay Dead Letters ({dl_count})" if dl_count else "♻️ Replay Dead Letters (فارغ)"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="تحديث", callback_data="analytics")],
            [InlineKeyboardButton(text="Health", callback_data="analytics_health")],
            [InlineKeyboardButton(text=dl_label, callback_data="analytics_replay_dl")],
            [InlineKeyboardButton(text="رجوع", callback_data="panel")],
        ]
    )


async def _editable_message(callback: CallbackQuery) -> Message | None:
    if isinstance(callback.message, Message):
        return callback.message
    await callback.answer("لا يمكن تعديل هذه الرسالة.", show_alert=True)
    return None


@router.callback_query(F.data == "analytics")
async def cb_analytics(callback: CallbackQuery) -> None:
    if not await require_callback_permission(callback, ANALYTICS):
        return
    await callback.answer()
    message = await _editable_message(callback)
    if message is None:
        return

    summary = await analytics_service.dashboard_summary(top_limit=5)
    top_lines = []
    for index, stat in enumerate(summary.top_materials, start=1):
        menu = stat.menu_name or "-"
        top_lines.append(
            f"{index}. material #{stat.material_id} | {menu} | views: {stat.view_count}"
        )
    if not top_lines:
        top_lines.append("لا توجد مشاهدات مواد بعد.")

    dl_count = _dead_letter_count()
    dl_note = f"\n⚠️ Dead letters: <code>{dl_count}</code>" if dl_count else ""

    await message.edit_text(
        "<b>Analytics Dashboard</b>\n\n"
        f"Active users 24h: <code>{summary.active_users_24h}</code>\n"
        f"Events 24h: <code>{summary.total_events_24h}</code>\n"
        f"Menu views 24h: <code>{summary.menu_views_24h}</code>\n"
        f"Material views 24h: <code>{summary.material_views_24h}</code>"
        f"{dl_note}\n\n"
        "<b>Top materials</b>\n" + "\n".join(top_lines),
        reply_markup=_analytics_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "analytics_health")
async def cb_analytics_health(callback: CallbackQuery) -> None:
    if not await require_callback_permission(callback, ANALYTICS):
        return
    await callback.answer()
    message = await _editable_message(callback)
    if message is None:
        return

    report = get_health_report()
    violations = report["slo_violations"] or ["none"]
    await message.edit_text(
        "<b>Health Monitor</b>\n\n"
        f"Status: <code>{report['status']}</code>\n"
        f"Queue length: <code>{report['queue_length']}</code>\n"
        f"Bot P95: <code>{report['bot_response_p95_ms']:.1f}ms</code>\n"
        f"DB write P95: <code>{report['queue_write_p95_ms']:.1f}ms</code>\n"
        f"Dashboard P95: <code>{report['dashboard_query_p95_ms']:.1f}ms</code>\n"
        f"Memory: <code>{report['memory_mb']:.1f}MB</code>\n"
        f"Memory P99: <code>{report['memory_p99_mb']:.1f}MB</code>\n"
        f"Violations: <code>{', '.join(violations)}</code>",
        reply_markup=_analytics_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "analytics_replay_dl")
async def cb_replay_dead_letters(callback: CallbackQuery) -> None:
    """Re-enqueue all events from the dead-letter file back into the analytics queue."""
    if not await require_callback_permission(callback, ANALYTICS):
        return
    await callback.answer("⏳ جاري إعادة تشغيل الأحداث الفاشلة...")
    message = await _editable_message(callback)
    if message is None:
        return

    count_before = _dead_letter_count()
    if count_before == 0:
        await message.edit_text(
            "✅ <b>Dead Letter Queue فارغة</b>\n\nلا توجد أحداث تحتاج إعادة تشغيل.",
            reply_markup=_analytics_keyboard(),
            parse_mode="HTML",
        )
        return

    result = await replay_dead_letters(analytics_writer)

    lines = [
        "<b>♻️ نتيجة إعادة تشغيل Dead Letters</b>\n",
        f"✅ تم إعادة تشغيل: <code>{result.replayed}</code> حدث",
        f"⏭ تم تخطي (تعذر تحليلها): <code>{result.skipped}</code>",
        f"⚠️ Queue ممتلئة (متبقية): <code>{result.dropped}</code>",
    ]
    await message.edit_text(
        "\n".join(lines),
        reply_markup=_analytics_keyboard(),
        parse_mode="HTML",
    )
