# test_mtpbot.py
from mtpbot import Bot
import asyncio

BOT_TOKEN = "8688719708:AAHl2o2OkYdVO7kpBgV27I_ubRxtvlqQFEA"
CHAT_ID = 8020145435

# Прокси из твоего скриншота: 127.0.0.1:1443, secret=dddb793ea1773b66de8319f3556d955bae
PROXY = {
    "server": "127.0.0.1",
    "port": 1443,
    "secret": "dddb793ea1773b66de8319f3556d955bae",
}

async def main():
    print("[Test] Создаю бота...")
    bot = Bot(token=BOT_TOKEN, proxy=PROXY)

    print("[Test] Подключаюсь через MTProxy...")
    await bot.start()

    print("[Test] Отправляю сообщение...")
    await bot.send_message(CHAT_ID, "Привет! Это тест через MTProto-прокси.")

    print("[Test] Сообщение отправлено! Проверь Telegram.")
    await bot.stop()

if __name__ == "__main__":
    asyncio.run(main())