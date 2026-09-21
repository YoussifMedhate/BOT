from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from config.settings import MAIN_BOT_TOKEN, ADMIN_BOT_TOKEN, DEV_BOT_TOKEN

default_props = DefaultBotProperties(parse_mode='HTML')

main_bot = Bot(token=MAIN_BOT_TOKEN, default=default_props)
admin_bot = Bot(token=ADMIN_BOT_TOKEN, default=default_props)
dev_bot = Bot(token=DEV_BOT_TOKEN, default=default_props)

async def close_bots():
    await main_bot.session.close()
    await admin_bot.session.close()
    await dev_bot.session.close()
