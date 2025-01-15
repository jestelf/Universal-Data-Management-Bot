import logging
import json
import random
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ContentTypes
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.utils.executor import start_polling
from aiogram.dispatcher import FSMContext
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters.state import State, StatesGroup
from config import API_TOKEN, ADMIN_ID, STORAGE_CHAT_ID
import os

# Логирование
logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
dp.middleware.setup(LoggingMiddleware())

# Словарь для хранения модов
mods = {}
current_page = 1
mods_per_page = 5
sort_mode = "default"  # Сортировка по умолчанию
query = None  # Запрос для поиска

# Хранение сообщений для очистки
user_message_ids = {}

# Путь к файлу с данными
MODS_FILE = 'mods.json'

# Состояния для загрузки
class ModUpload(StatesGroup):
    waiting_for_template_and_archive = State()

# Загрузка данных из JSON
def load_mods():
    if os.path.exists(MODS_FILE):
        with open(MODS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

# Сохранение данных в JSON
def save_mods():
    with open(MODS_FILE, 'w', encoding='utf-8') as f:
        json.dump(mods, f, ensure_ascii=False, indent=4)

# Очистка сообщений
async def clear_user_messages(chat_id):
    if chat_id in user_message_ids:
        for msg_id in user_message_ids[chat_id]:
            try:
                await bot.delete_message(chat_id, msg_id)
            except:
                pass
        user_message_ids[chat_id] = []

# Генерация кнопок
def generate_reply_keyboard(is_admin=False):
    keyboard = [[types.KeyboardButton("/start")]]
    if is_admin:
        keyboard.append([types.KeyboardButton("/upload")])
    return types.ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

# Команда /start
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    global query
    query = None  # Сброс поиска
    await clear_user_messages(message.chat.id)  # Очищаем предыдущие сообщения

    # Определяем, админ ли пользователь
    is_admin = message.from_user.id == ADMIN_ID

    # Генерируем соответствующую клавиатуру
    reply_markup = generate_reply_keyboard(is_admin=is_admin)

    # Отправляем приветствие
    msg = await message.answer(
        "🦇|Добро пожаловать в русский Baldur Gate 3! \n\n💾|Это большая база данных \n🛠|русифицированных модификаций. \n\n🇷🇺|Мы рады дарить вам ру-моды, \n🛠|которых на сегодня так мало.",
        reply_markup=reply_markup,
    )
    user_message_ids[message.chat.id] = [msg.message_id, message.message_id]
    await list_mods(message)

async def list_mods(message: types.Message):
    global current_page, query
    query = None  # Сброс поиска
    await send_mods_page(message, current_page)

# Новый класс состояний для поиска
class SearchState(StatesGroup):
    waiting_for_query = State()

# Отправка страницы с модами
async def send_mods_page(message_or_callback, page, search_query=None):
    global mods_per_page, sort_mode, query
    query = search_query or query
    mod_list = list(mods.values())

    # Сортировка
    if sort_mode == "downloads":
        mod_list = sorted(mod_list, key=lambda x: x.get("downloads", 0), reverse=True)
    elif sort_mode == "newest":
        mod_list = sorted(mod_list, key=lambda x: x.get("created_at", ""), reverse=True)
    elif sort_mode == "random":
        random.shuffle(mod_list)

    # Поиск
    if query:
        mod_list = [mod for mod in mod_list if query.lower() in mod['name'].lower() or 
                    query.lower() in mod['description'].lower() or
                    query.lower() in mod['author'].lower()]

    total_pages = max(1, (len(mod_list) + mods_per_page - 1) // mods_per_page)
    if page < 1 or page > total_pages:
        return

    start_index = (page - 1) * mods_per_page
    end_index = start_index + mods_per_page
    page_mods = mod_list[start_index:end_index]

    mod_text = f"♻️Сортировка: {sort_mode.capitalize()} | 📌Страница {page}/{total_pages}\n\n"
    if page_mods:
        mod_text += "\n\n".join([
            f"🏷Название: {mod['name']}\n💽Описание: {mod['description']}🇷🇺\n👤Автор: {mod['author']} (Скачивания: {mod.get('downloads', 0)})"
            for mod in page_mods
        ])
    else:
        mod_text += "Нет модов для отображения."

    markup = InlineKeyboardMarkup(row_width=3)
    for mod in page_mods:
        markup.add(InlineKeyboardButton(mod['name'], callback_data=f"mod_{mod['name']}"))

    if page > 1:
        markup.add(InlineKeyboardButton("⬅️ Назад", callback_data=f"page_{page - 1}"))
    if page < total_pages:
        markup.add(InlineKeyboardButton("➡️ Вперед", callback_data=f"page_{page + 1}"))

    markup.row(
        InlineKeyboardButton("🔍 Поиск", callback_data="search_query"),
        InlineKeyboardButton("⬇️ Скачивания", callback_data="sort_downloads"),
        InlineKeyboardButton("🆕 Новизна", callback_data="sort_newest"),
        InlineKeyboardButton("🎲 Рандом", callback_data="sort_random")
    )

    if isinstance(message_or_callback, types.Message):
        msg = await message_or_callback.answer(mod_text, reply_markup=markup)
        user_message_ids[message_or_callback.chat.id].append(msg.message_id)
    elif isinstance(message_or_callback, types.CallbackQuery):
        await message_or_callback.message.edit_text(mod_text, reply_markup=markup)

# Админская загрузка
@dp.message_handler(commands=['upload'], user_id=ADMIN_ID)
async def upload_mod(message: types.Message):
    await ModUpload.waiting_for_template_and_archive.set()
    await message.answer(
        "Отправьте текст с шаблоном мода и архив с модом в одном сообщении.\n\n"
        "Пример формата:\n"
        "Название: MyMod\n"
        "Описание: Мод для игры\n"
        "Автор: Иван Иванов\n\n"
    )

# Обработка нажатия кнопки "🔍 Поиск"
@dp.callback_query_handler(lambda c: c.data == "search_query")
async def start_search(callback_query: types.CallbackQuery):
    await callback_query.message.answer("🔎 Введите текст для поиска (🏷название, 💽описание или 👤автор):")
    await SearchState.waiting_for_query.set()
    await callback_query.answer()

# Обработка текста, введенного пользователем для поиска
@dp.message_handler(state=SearchState.waiting_for_query, content_types=ContentTypes.TEXT)
async def handle_search_query(message: types.Message, state: FSMContext):
    global query
    query = message.text.strip()
    if not query:
        await message.answer("Поиск не может быть пустым. Пожалуйста, введите текст для поиска.")
        return

    await state.finish()  # Завершаем состояние
    await send_mods_page(message, 1, search_query=query)

# Обработка пагинации
@dp.callback_query_handler(lambda c: c.data.startswith("page_"))
async def change_page(callback_query: types.CallbackQuery):
    page = int(callback_query.data.split("_")[1])
    await send_mods_page(callback_query, page)
    await callback_query.answer()

# Обработка сортировки
@dp.callback_query_handler(lambda c: c.data.startswith("sort_"))
async def sort_mods_callback(callback_query: types.CallbackQuery):
    global sort_mode, current_page
    sort_mode = callback_query.data.split("_")[1]
    current_page = 1
    await send_mods_page(callback_query, current_page)
    await callback_query.answer("Сортировка обновлена!")


# Поиск по имени мода
@dp.message_handler(commands=['search'])
async def search_mods(message: types.Message):
    global query
    query = message.get_args()
    if not query:
        await message.answer("🔎Введите текст для поиска. Например:\n`/search MyMod`")
        return
    await send_mods_page(message, 1, search_query=query)

# Отображение деталей мода
@dp.callback_query_handler(lambda c: c.data.startswith("mod_"))
async def show_mod_details(callback_query: types.CallbackQuery):
    mod_name = callback_query.data[4:]
    mod_info = mods.get(mod_name)
    if mod_info:
        mod_info['downloads'] = mod_info.get('downloads', 0) + 1
        save_mods()
        file_id = mod_info['file_id']
        caption = (f"Мод: {mod_info['name']}\n"
                   f"Описание: {mod_info['description']}\n"
                   f"Автор: {mod_info['author']}\n"
                   f"Скачиваний: {mod_info['downloads']}")
        await bot.send_document(chat_id=callback_query.message.chat.id, document=file_id, caption=caption)
    else:
        await callback_query.message.answer("Мод не найден.")
    await callback_query.answer()

# Админская загрузка
@dp.message_handler(commands=['upload'], user_id=ADMIN_ID)
async def upload_mod(message: types.Message):
    await ModUpload.waiting_for_template_and_archive.set()
    await message.answer("Отправьте текст с шаблоном мода (Название, Описание, Автор) и архив с модом в одном сообщении.")

@dp.message_handler(state=ModUpload.waiting_for_template_and_archive, content_types=ContentTypes.DOCUMENT)
async def process_archive_with_caption(message: types.Message, state: FSMContext):
    if not message.caption:
        await message.answer("Добавьте подпись:\nНазвание: ...\nОписание: ...\nАвтор: ...")
        return
    caption = message.caption.split("\n")
    try:
        name = caption[0].split(":")[1].strip()
        description = caption[1].split(":")[1].strip()
        author = caption[2].split(":")[1].strip()
    except IndexError:
        await message.answer("Неверный формат подписи.")
        return

    file_id = message.document.file_id
    mod_info = {
        'name': name,
        'description': description,
        'author': author,
        'file_id': file_id,
        'created_at': datetime.now().isoformat(),
        'downloads': 0
    }
    mods[name] = mod_info
    save_mods()
    await state.finish()
    await message.answer(f"Мод '{name}' успешно загружен!")

if __name__ == '__main__':
    mods = load_mods()
    start_polling(dp, skip_updates=True)
