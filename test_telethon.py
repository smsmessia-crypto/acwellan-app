# test_telethon.py
import asyncio
from telethon import TelegramClient
from telethon.network import ConnectionTcpMTProxyRandomizedIntermediate

# Данные твоего бота и прокси
API_ID = 0  # для ботов не нужен
API_HASH = ""  # для ботов не нужен
BOT_TOKEN = "8688719708:AAHl2o2OkYdVO7kpBgV27I_ubRxtvlqQFEA"

PROXY_SERVER = "127.0.0.1"
PROXY_PORT = 1443
PROXY_SECRET = "dddb793ea1773b66de8319f3556d955bae"
CHAT_ID = 8020145435


async def main():
    print("[Telethon] Создаю клиент...")

    client = TelegramClient(
        "bot_session",
        API_ID,
        API_HASH,
        connection=ConnectionTcpMTProxyRandomizedIntermediate,
        proxy=(PROXY_SERVER, PROXY_PORT, PROXY_SECRET),
    )

    print("[Telethon] Подключаюсь через MTProxy...")
    await client.start(bot_token=BOT_TOKEN)

    print("[Telethon] Отправляю сообщение...")
    await client.send_message(CHAT_ID, "Привет! Тест через Telethon + MTProxy.")

    print("[Telethon] Сообщение отправлено! Проверь Telegram.")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())