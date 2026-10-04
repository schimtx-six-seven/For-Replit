import asyncio
import os
import random
import json
import re
import sqlite3
import time
import unicodedata
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord.ext import commands, tasks

from catalog import CARS, DAILY_RARITIES, PARTS, RARITY_EMOJI
from employment_crime_config import (
    CRIME_HISTORY_LIMIT,
    CRIME_MAX_CHANCE,
    CRIME_MENU_TIMEOUT_SECONDS,
    CRIME_MIN_CHANCE,
    CRIME_MODIFIERS,
    CRIME_WANTED_DECAY_SECONDS,
    CRIME_WANTED_MAX_LEVEL,
    CRIME_XP_FAILURE,
    CRIME_XP_SUCCESS,
    CRIMES,
    DEFAULT_SALARY_TAX_RATE,
    EVENT_DURATION_SECONDS,
    EVENT_MAX_INTERVAL_SECONDS,
    EVENT_MIN_INTERVAL_SECONDS,
    EVENT_POLL_SECONDS,
    EVENTS,
    JOB_HISTORY_LIMIT,
    JOB_OFFER_COOLDOWN_SECONDS,
    JOB_OFFER_VALID_SECONDS,
    JOB_POLL_SECONDS,
    JOB_RARITIES,
    JOBS,
    LOAN_DURATION_SECONDS,
    LOAN_INTEREST_RATE,
    MAX_SALARY_TAX_RATE,
    MIN_SALARY_TAX_RATE,
)


# =========================
# CONFIGURAÇÃO
# =========================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None,
)


# =========================
# BANCO DE DADOS
# =========================

db = sqlite3.connect("valkyrie.db")
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    xp INTEGER DEFAULT 0,
    coins INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
)
""")


def ensure_column(table_name, column_name, column_definition):
    cursor.execute(f"PRAGMA table_info({table_name})")
    existing_columns = {row[1] for row in cursor.fetchall()}
    if column_name not in existing_columns:
        cursor.execute(
            f"ALTER TABLE {table_name} ADD COLUMN "
            f"{column_name} {column_definition}"
        )


for column_name, column_definition in (
    ("last_job_offer", "INTEGER NOT NULL DEFAULT 0"),
    ("job_offer_expires", "INTEGER NOT NULL DEFAULT 0"),
    ("active_job", "INTEGER DEFAULT NULL"),
    ("job_completion_time", "INTEGER NOT NULL DEFAULT 0"),
    ("last_crime", "INTEGER NOT NULL DEFAULT 0"),
    ("crime_cooldown", "INTEGER NOT NULL DEFAULT 0"),
    ("last_crime_key", "TEXT DEFAULT NULL"),
    ("wanted_level", "INTEGER NOT NULL DEFAULT 0"),
    ("wanted_until", "INTEGER NOT NULL DEFAULT 0"),
    ("crime_blocked_until", "INTEGER NOT NULL DEFAULT 0"),
    ("job_blocked_until", "INTEGER NOT NULL DEFAULT 0"),
    ("prison_until", "INTEGER NOT NULL DEFAULT 0"),
    ("crime_xp", "INTEGER NOT NULL DEFAULT 0"),
):
    ensure_column("users", column_name, column_definition)

cursor.execute("""
CREATE TABLE IF NOT EXISTS daily_claims (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    claim_type TEXT NOT NULL,
    claim_date TEXT NOT NULL,
    PRIMARY KEY (guild_id, user_id, claim_type)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS inventory (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    part_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, part_id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS garage (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    car_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    is_active INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, car_id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS race_challenges (
    challenge_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    challenger_id INTEGER NOT NULL,
    opponent_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS race_stats (
    user_id INTEGER PRIMARY KEY,
    races INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS daily_shop (
    shop_date TEXT PRIMARY KEY,
    car_ids TEXT NOT NULL,
    part_ids TEXT NOT NULL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS shop_purchases (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    shop_date TEXT NOT NULL,
    item_type TEXT NOT NULL,
    item_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id, shop_date, item_type, item_id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS trades (
    trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    initiator_id INTEGER NOT NULL,
    recipient_id INTEGER NOT NULL,
    offered_items TEXT NOT NULL,
    requested_items TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS market_listings (
    listing_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    seller_id INTEGER NOT NULL,
    item_type TEXT NOT NULL,
    item_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    price INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    buyer_id INTEGER,
    sold_at INTEGER,
    status TEXT NOT NULL DEFAULT 'active'
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS jobs (
    job_key TEXT PRIMARY KEY,
    rarity TEXT NOT NULL,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    payment_min INTEGER NOT NULL,
    payment_max INTEGER NOT NULL,
    xp_min INTEGER NOT NULL,
    xp_max INTEGER NOT NULL,
    duration_seconds INTEGER NOT NULL,
    bonus_min INTEGER NOT NULL,
    bonus_max INTEGER NOT NULL,
    bonus_chance REAL NOT NULL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS job_offers (
    offer_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    job_key TEXT NOT NULL,
    payment INTEGER NOT NULL,
    xp INTEGER NOT NULL,
    duration_seconds INTEGER NOT NULL,
    bonus_min INTEGER NOT NULL,
    bonus_max INTEGER NOT NULL,
    bonus_chance REAL NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    accepted_at INTEGER,
    completed_at INTEGER,
    bonus_awarded INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending'
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS active_jobs (
    offer_id INTEGER PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    job_key TEXT NOT NULL,
    job_completion_time INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS job_history (
    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    offer_id INTEGER NOT NULL,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    job_key TEXT NOT NULL,
    payment INTEGER NOT NULL,
    bonus INTEGER NOT NULL DEFAULT 0,
    total_paid INTEGER NOT NULL,
    xp INTEGER NOT NULL,
    completed_at INTEGER NOT NULL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS crimes (
    crime_key TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    base_success REAL NOT NULL,
    cooldown_seconds INTEGER NOT NULL,
    reward_min INTEGER NOT NULL,
    reward_max INTEGER NOT NULL,
    fine_min INTEGER NOT NULL,
    fine_max INTEGER NOT NULL,
    required_crime_xp INTEGER NOT NULL,
    requires_target INTEGER NOT NULL,
    requires_car INTEGER NOT NULL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS crime_history (
    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    criminal_id INTEGER NOT NULL,
    victim_id INTEGER,
    crime_key TEXT NOT NULL,
    target_car_id INTEGER,
    success INTEGER NOT NULL,
    reward INTEGER NOT NULL DEFAULT 0,
    fine INTEGER NOT NULL DEFAULT 0,
    car_transferred INTEGER NOT NULL DEFAULT 0,
    car_recovered INTEGER NOT NULL DEFAULT 0,
    wanted_before INTEGER NOT NULL DEFAULT 0,
    wanted_after INTEGER NOT NULL DEFAULT 0,
    imprisoned INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    details TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS wanted_players (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    wanted_level INTEGER NOT NULL DEFAULT 0,
    wanted_until INTEGER NOT NULL DEFAULT 0,
    crime_blocked_until INTEGER NOT NULL DEFAULT 0,
    job_blocked_until INTEGER NOT NULL DEFAULT 0,
    prison_until INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS guild_economy (
    guild_id INTEGER PRIMARY KEY,
    salary_tax_rate REAL NOT NULL DEFAULT 0.5,
    treasury INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS treasury_ledger (
    ledger_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    amount INTEGER NOT NULL,
    tax_rate REAL NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    details TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS political_office (
    guild_id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    office TEXT NOT NULL DEFAULT 'politico',
    started_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS admin_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    admin_id INTEGER NOT NULL,
    target_id INTEGER,
    action TEXT NOT NULL,
    amount INTEGER NOT NULL DEFAULT 0,
    item TEXT,
    details TEXT,
    created_at INTEGER NOT NULL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS event_cycles (
    guild_id INTEGER PRIMARY KEY,
    last_generated_at INTEGER NOT NULL DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS news_cycles (
    guild_id INTEGER PRIMARY KEY,
    last_posted_at INTEGER NOT NULL DEFAULT 0,
    next_post_at INTEGER NOT NULL DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS news (
    news_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    headline TEXT NOT NULL,
    body TEXT NOT NULL,
    reference TEXT NOT NULL,
    created_at INTEGER NOT NULL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS catalog_images (
    item_type TEXT NOT NULL,
    item_id INTEGER NOT NULL,
    image_url TEXT NOT NULL,
    source TEXT NOT NULL,
    source_title TEXT,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (item_type, item_id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    scope TEXT NOT NULL,
    user_id INTEGER,
    event_key TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    effects_json TEXT NOT NULL,
    started_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS loans (
    loan_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    principal INTEGER NOT NULL,
    interest_rate REAL NOT NULL,
    total_due INTEGER NOT NULL,
    due_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    paid_at INTEGER,
    status TEXT NOT NULL DEFAULT 'active'
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS investment_positions (
    position_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    asset_key TEXT NOT NULL,
    invested_amount INTEGER NOT NULL DEFAULT 0,
    current_value INTEGER NOT NULL DEFAULT 0,
    volatility REAL NOT NULL,
    last_updated INTEGER NOT NULL,
    UNIQUE(guild_id, user_id, asset_key)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS investment_transactions (
    transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    asset_key TEXT NOT NULL,
    action TEXT NOT NULL,
    amount INTEGER NOT NULL,
    value INTEGER NOT NULL,
    created_at INTEGER NOT NULL
)
""")

INVESTMENT_ASSETS = {
    "acoes": {
        "title": "📈 Ações",
        "aliases": ("acoes", "acao", "ações", "stocks"),
        "volatility": 0.08,
    },
    "empresas": {
        "title": "🏢 Empresas",
        "aliases": ("empresas", "empresa", "corporativo"),
        "volatility": 0.06,
    },
    "bancos": {
        "title": "🏦 Bancos",
        "aliases": ("bancos", "banco", "bank"),
        "volatility": 0.05,
    },
    "automotiva": {
        "title": "🚗 Indústria automotiva",
        "aliases": ("automotiva", "automotivo", "carros", "auto"),
        "volatility": 0.1,
    },
    "petroleo": {
        "title": "⛽ Petróleo",
        "aliases": ("petroleo", "petróleo", "oil"),
        "volatility": 0.12,
    },
    "commodities": {
        "title": "💎 Commodities",
        "aliases": ("commodities", "commodity"),
        "volatility": 0.09,
    },
    "imoveis": {
        "title": "🏠 Imóveis",
        "aliases": ("imoveis", "imóvel", "imoveis", "realestate"),
        "volatility": 0.035,
    },
    "especiais": {
        "title": "🪙 Ativos especiais",
        "aliases": ("especiais", "especial", "ativos"),
        "volatility": 0.16,
    },
}

ensure_column("event_cycles", "next_generated_at", "INTEGER NOT NULL DEFAULT 0")
ensure_column("job_offers", "job_mode", "TEXT NOT NULL DEFAULT 'normal'")
ensure_column("job_history", "gross_payment", "INTEGER NOT NULL DEFAULT 0")
ensure_column("job_history", "tax_paid", "INTEGER NOT NULL DEFAULT 0")
ensure_column("job_history", "mode", "TEXT NOT NULL DEFAULT 'normal'")
ensure_column("job_history", "outcome", "TEXT NOT NULL DEFAULT 'completed'")
ensure_column("job_history", "fine", "INTEGER NOT NULL DEFAULT 0")

for job in JOBS:
    payment_min, payment_max = job["payment"]
    xp_min, xp_max = job["xp"]
    bonus_min, bonus_max = job["bonus"]
    cursor.execute("""
    INSERT INTO jobs (
        job_key, rarity, company, title, payment_min, payment_max,
        xp_min, xp_max, duration_seconds, bonus_min, bonus_max, bonus_chance
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(job_key) DO UPDATE SET
        rarity = excluded.rarity,
        company = excluded.company,
        title = excluded.title,
        payment_min = excluded.payment_min,
        payment_max = excluded.payment_max,
        xp_min = excluded.xp_min,
        xp_max = excluded.xp_max,
        duration_seconds = excluded.duration_seconds,
        bonus_min = excluded.bonus_min,
        bonus_max = excluded.bonus_max,
        bonus_chance = excluded.bonus_chance
    """, (
        job["key"],
        job["rarity"],
        job["company"],
        job["title"],
        payment_min,
        payment_max,
        xp_min,
        xp_max,
        job["duration_minutes"] * 60,
        bonus_min,
        bonus_max,
        job["bonus_chance"],
    ))

for crime in CRIMES:
    reward_min, reward_max = crime["reward"]
    fine_min, fine_max = crime["fine"]
    cursor.execute("""
    INSERT INTO crimes (
        crime_key, label, base_success, cooldown_seconds,
        reward_min, reward_max, fine_min, fine_max,
        required_crime_xp, requires_target, requires_car
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(crime_key) DO UPDATE SET
        label = excluded.label,
        base_success = excluded.base_success,
        cooldown_seconds = excluded.cooldown_seconds,
        reward_min = excluded.reward_min,
        reward_max = excluded.reward_max,
        fine_min = excluded.fine_min,
        fine_max = excluded.fine_max,
        required_crime_xp = excluded.required_crime_xp,
        requires_target = excluded.requires_target,
        requires_car = excluded.requires_car
    """, (
        crime["key"],
        crime["label"],
        crime["base_success"],
        crime["cooldown_seconds"],
        reward_min,
        reward_max,
        fine_min,
        fine_max,
        crime["required_crime_xp"],
        int(crime["requires_target"]),
        int(crime["requires_car"]),
    ))

db.commit()


# =========================
# COOLDOWN DE XP
# =========================

xp_cooldowns = {}
XP_COOLDOWN = 60


# =========================
# RECOMPENSAS DIÁRIAS
# =========================

SAO_PAULO_TZ = ZoneInfo("America/Sao_Paulo")
DAILY_COINS_MIN = 1000
DAILY_COINS_MAX = 3000
PARTS_BY_ID = {part[0]: part for part in PARTS}
CARS_BY_ID = {car_id: car for car_id, car in enumerate(CARS, start=1)}
CAR_ATTRIBUTE_NAMES = (
    "Velocidade Máxima",
    "Aceleração",
    "Controle",
    "Curvas",
    "Frenagem",
    "Resistência",
    "Economia",
    "Luxo",
    "TUN",
)
CAR_ATTRIBUTE_SHORT_NAMES = (
    "VMAX",
    "ACC",
    "CTRL",
    "CUR",
    "FRE",
    "RES",
    "ECO",
    "LUX",
    "TUN",
)

CAR_IMAGE_URLS = (
    "https://images.unsplash.com/photo-1492144534655-ae79c964c9d7"
    "?auto=format&fit=crop&w=1200&q=85",
    "https://images.unsplash.com/photo-1503376780353-7e6692767b70"
    "?auto=format&fit=crop&w=1200&q=85",
    "https://images.unsplash.com/photo-1552519507-da3b142c6e3d"
    "?auto=format&fit=crop&w=1200&q=85",
    "https://images.unsplash.com/photo-1542282088-72c9c27ed0cd"
    "?auto=format&fit=crop&w=1200&q=85",
    "https://images.unsplash.com/photo-1583121274602-3e2820c69888"
    "?auto=format&fit=crop&w=1200&q=85",
    "https://images.unsplash.com/photo-1503736334956-4c8f8e92946d"
    "?auto=format&fit=crop&w=1200&q=85",
)

PART_IMAGE_URLS = {
    "motor": "https://images.unsplash.com/photo-1486262715619-67b85e0b08d3"
    "?auto=format&fit=crop&w=1200&q=85",
    "turbo": "https://images.unsplash.com/photo-1517524008697-84bbe3c3fd98"
    "?auto=format&fit=crop&w=1200&q=85",
    "pneus": "https://images.unsplash.com/photo-1558981806-ec527fa84c39"
    "?auto=format&fit=crop&w=1200&q=85",
    "freios": "https://images.unsplash.com/photo-1487754180451-c456f719a1fc"
    "?auto=format&fit=crop&w=1200&q=85",
    "suspensao": "https://images.unsplash.com/photo-1492144534655-ae79c964c9d7"
    "?auto=format&fit=crop&w=1200&q=85",
    "transmissao": "https://images.unsplash.com/photo-1489824904134-891ab64532f1"
    "?auto=format&fit=crop&w=1200&q=85",
    "default": "https://images.unsplash.com/photo-1511919884226-fd3cad34687c"
    "?auto=format&fit=crop&w=1200&q=85",
}

MARKET_LISTING_SECONDS = 3 * 24 * 60 * 60
NEWS_POLL_SECONDS = 300
NEWS_MIN_INTERVAL_SECONDS = 3 * 60 * 60
NEWS_MAX_INTERVAL_SECONDS = 12 * 60 * 60
NEWS_STORIES = (
    {
        "headline": "Bebê aprende a voar e se anuncia como novo super-herói de Xique-Xique, Bahia",
        "body": (
            "Testemunhas dizem que o pequeno herói sobrevoou a praça, "
            "pediu um suco de caju e já abriu inscrições para sua primeira "
            "equipe de resgate."
        ),
        "reference": "Rádio Asa de Papel · boletim satírico local",
    },
    {
        "headline": "Pombo de Itaquera é eleito consultor oficial de trânsito",
        "body": (
            "A ave ganhou o cargo depois de organizar uma fila de carros "
            "usando apenas dois pombos-correio e um olhar severo."
        ),
        "reference": "Instituto Valkyrie de Estatísticas Improváveis",
    },
    {
        "headline": "Mecânico instala turbo em carrinho de supermercado e vence racha no estacionamento",
        "body": (
            "O veículo, batizado de Foguetinho do Hortifruti, alcançou uma "
            "velocidade que ninguém conseguiu medir sem perder o carrinho."
        ),
        "reference": "Jornal Pista Molhada · reportagem fictícia",
    },
    {
        "headline": "Prefeitura anuncia feriado municipal para comemorar o primeiro drift de uma capivara",
        "body": (
            "A capivara teria feito a manobra em uma poça, recebido aplausos "
            "e recusado entrevistas por motivos de privacidade."
        ),
        "reference": "Gazeta do Asfalto · coluna de humor",
    },
    {
        "headline": "Empresa lança combustível feito de cafezinho e promete autonomia de três reuniões",
        "body": (
            "O protótipo funciona melhor às segundas-feiras e ainda não foi "
            "aprovado por nenhuma agência real ou imaginária."
        ),
        "reference": "Boletim Valkyrie · conteúdo 100% fictício",
    },
)

RACE_CHALLENGE_SECONDS = 90
RACE_TRACKS = (
    (
        "Circuito de Interlagos",
        {
            "Velocidade": 0.28,
            "Aceleração": 0.22,
            "Controle": 0.18,
            "Curvas": 0.17,
            "Frenagem": 0.15,
        },
    ),
    (
        "Serra da Mantiqueira",
        {
            "Controle": 0.22,
            "Curvas": 0.34,
            "Frenagem": 0.24,
            "Resistência": 0.20,
        },
    ),
    (
        "Drag Strip Valkyrie",
        {
            "Velocidade": 0.45,
            "Aceleração": 0.40,
            "Controle": 0.10,
            "Frenagem": 0.05,
        },
    ),
    (
        "Circuito Urbano Neon",
        {
            "Aceleração": 0.24,
            "Controle": 0.25,
            "Curvas": 0.21,
            "Frenagem": 0.18,
            "Prestígio": 0.12,
        },
    ),
)
RACE_WEATHERS = (
    ("Ensolarado", {}),
    (
        "Chuva",
        {
            "Controle": 0.25,
            "Curvas": 0.20,
            "Frenagem": 0.25,
            "Resistência": 0.15,
            "Velocidade": -0.15,
        },
    ),
    (
        "Neblina",
        {
            "Controle": 0.30,
            "Frenagem": 0.20,
            "Velocidade": -0.15,
            "Aceleração": -0.05,
        },
    ),
    (
        "Calor intenso",
        {
            "Resistência": 0.30,
            "Economia": 0.15,
            "Velocidade": 0.08,
        },
    ),
)

JOB_BY_KEY = {job["key"]: job for job in JOBS}
JOB_RARITY_BY_KEY = {rarity["key"]: rarity for rarity in JOB_RARITIES}
JOB_RARITY_WEIGHTS = [rarity["weight"] for rarity in JOB_RARITIES]
CRIME_BY_KEY = {crime["key"]: crime for crime in CRIMES}
CRIME_ALIASES = {
    "carro": "roubar_carro",
    "roubarcarro": "roubar_carro",
    "roubar": "roubar_jogador",
    "jogador": "roubar_jogador",
    "roubarjogador": "roubar_jogador",
    "loja": "assaltar_loja",
    "assaltarloja": "assaltar_loja",
    "posto": "assaltar_posto",
    "assaltarposto": "assaltar_posto",
    "carga": "roubar_carga",
    "roubarcarga": "roubar_carga",
    "joalheria": "roubar_joalheria",
    "roubarjoalheria": "roubar_joalheria",
    "propriedade": "invadir_propriedade",
    "invadirpropriedade": "invadir_propriedade",
    "digital": "crime_digital",
    "crimedigital": "crime_digital",
    "raro": "roubar_carro_raro",
    "carro_raro": "roubar_carro_raro",
    "roubarcarro raro": "roubar_carro_raro",
    "golpe": "golpes_especiais",
    "golpes": "golpes_especiais",
    "especiais": "golpes_especiais",
    "banco": "assaltar_banco",
    "assaltarbanco": "assaltar_banco",
}


# =========================
# PATENTES
# =========================

RANKS = [
    (5, "🌾 Camponês"),
    (10, "🔨 Artesão"),
    (15, "🛡️ Soldado"),
    (20, "⚔️ Guerreiro"),
    (25, "🏹 Caçador"),
    (30, "🏰 Cavaleiro"),
    (35, "🎖️ Comandante"),
    (40, "👑 Nobre"),
]


# =========================
# CRIAR USUÁRIO
# =========================

def create_user(guild_id, user_id):
    cursor.execute("""
    INSERT OR IGNORE INTO users
    (guild_id, user_id, xp, coins)
    VALUES (?, ?, 0, 0)
    """, (guild_id, user_id))

    db.commit()


# =========================
# PEGAR DADOS
# =========================

def get_user(guild_id, user_id):
    create_user(guild_id, user_id)

    cursor.execute("""
    SELECT xp, coins
    FROM users
    WHERE guild_id = ? AND user_id = ?
    """, (guild_id, user_id))

    return cursor.fetchone()


# =========================
# ADICIONAR XP
# =========================

def add_xp(guild_id, user_id, amount):
    create_user(guild_id, user_id)

    cursor.execute("""
    UPDATE users
    SET xp = xp + ?
    WHERE guild_id = ? AND user_id = ?
    """, (amount, guild_id, user_id))

    db.commit()


def add_coins(guild_id, user_id, amount):
    create_user(guild_id, user_id)

    cursor.execute("""
    UPDATE users
    SET coins = coins + ?
    WHERE guild_id = ? AND user_id = ?
    """, (amount, guild_id, user_id))

    db.commit()


def today_in_game_timezone():
    return datetime.now(SAO_PAULO_TZ).date().isoformat()


def claim_daily_reward(guild_id, user_id, claim_type):
    claim_date = today_in_game_timezone()

    cursor.execute("""
    SELECT claim_date
    FROM daily_claims
    WHERE guild_id = ? AND user_id = ? AND claim_type = ?
    """, (guild_id, user_id, claim_type))
    previous_claim = cursor.fetchone()

    if previous_claim and previous_claim[0] == claim_date:
        return False

    cursor.execute("""
    INSERT INTO daily_claims (guild_id, user_id, claim_type, claim_date)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(guild_id, user_id, claim_type)
    DO UPDATE SET claim_date = excluded.claim_date
    """, (guild_id, user_id, claim_type, claim_date))
    db.commit()
    return True


def time_until_next_daily():
    now = datetime.now(SAO_PAULO_TZ)
    tomorrow = (now + timedelta(days=1)).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    seconds = max(1, int((tomorrow - now).total_seconds()))
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60

    if hours:
        return f"{hours}h e {minutes}min"
    return f"{minutes}min"


def normalize_text(value):
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value.lower())
        if not unicodedata.combining(character)
    )


def choose_daily_part():
    rarities = [rarity for rarity, _weight in DAILY_RARITIES]
    weights = [weight for _rarity, weight in DAILY_RARITIES]
    selected_rarity = random.choices(rarities, weights=weights, k=1)[0]
    candidates = [
        part for part in PARTS
        if part[3] == selected_rarity
    ]
    return random.choice(candidates)


def add_part_to_inventory(guild_id, user_id, part_id, quantity=1):
    cursor.execute("""
    INSERT INTO inventory (guild_id, user_id, part_id, quantity)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(guild_id, user_id, part_id)
    DO UPDATE SET quantity = inventory.quantity + excluded.quantity
    """, (guild_id, user_id, part_id, quantity))
    db.commit()


def get_inventory(guild_id, user_id):
    cursor.execute("""
    SELECT part_id, quantity
    FROM inventory
    WHERE guild_id = ? AND user_id = ? AND quantity > 0
    ORDER BY quantity DESC, part_id ASC
    """, (guild_id, user_id))
    return cursor.fetchall()


def get_car(car_id):
    return CARS_BY_ID.get(car_id)


def get_car_details(car_id):
    car = get_car(car_id)
    if car is None:
        return None

    attributes = dict(zip(CAR_ATTRIBUTE_NAMES, car[1:-1]))
    # Compatibilidade com mensagens e dados antigos que chamavam TUN de prestígio.
    attributes["Prestígio"] = attributes["TUN"]
    return {
        "name": car[0],
        "attributes": attributes,
        "price": car[-1] * 1000,
    }


def get_part_details(part_id):
    part = PARTS_BY_ID.get(part_id)
    if part is None:
        return None
    return {
        "part_id": part[0],
        "name": part[1],
        "category": part[2],
        "rarity": part[3],
        "price": part[4],
    }


def catalog_image_url(item_type, item_id):
    if item_type == "car":
        details = get_car_details(item_id)
        label = details["name"] if details else f"Carro #{item_id}"
    else:
        details = get_part_details(item_id)
        label = details["name"] if details else f"Peça #{item_id}"
    from urllib.parse import quote
    return (
        "https://placehold.co/1200x675/0b1220/ffd166/png?text="
        + quote(label)
    )


def catalog_image_query(item_type, item_id):
    if item_type == "car":
        details = get_car_details(item_id)
        return details["name"].split(" — ", 1)[0] if details else None
    details = get_part_details(item_id)
    if details is None:
        return None
    category_terms = {
        "intake": "air filter",
        "exhaust": "exhaust",
        "escape": "exhaust",
        "ignition": "spark plug",
        "brakes": "brake",
        "freios": "brake",
        "suspension": "suspension",
        "suspensao": "suspension",
        "tires": "tire",
        "pneus": "tire",
        "wheels": "wheel",
        "clutch": "clutch",
        "cooling": "radiator",
        "ecu": "engine control unit",
        "differential": "differential",
        "transmission": "gearbox",
        "transmissao": "gearbox",
        "turbo": "turbocharger",
        "engine": "engine",
        "motor": "engine",
        "electric": "electric motor",
        "combustivel": "fuel injector",
        "eletrica": "battery",
        "aero": "spoiler",
        "aerodinamica": "spoiler",
        "blindagem": "armored vehicle",
        "visual": "car interior",
        "weight": "carbon fiber",
        "drivetrain": "drivetrain",
        "nitrous": "nitrous oxide",
        "launch": "launch control",
        "traction": "traction control",
        "telemetry": "telemetry",
    }
    return category_terms.get(normalize_text(details["category"]))


def catalog_image_is_relevant(item_type, query, title):
    if not query or not title:
        return False
    query_text = normalize_text(query).strip()
    title_text = normalize_text(title.split(":", 1)[-1]).strip()
    if item_type == "car":
        if not title_text.startswith(query_text):
            return False
        remainder = title_text[len(query_text):].strip()
        if not remainder:
            return True
        first_suffix = re.split(r"[\s,()–—-]+", remainder, maxsplit=1)[0]
        if first_suffix in {
            "cross", "hybrid", "gr", "gti", "type", "r", "rs", "amg", "m",
            "gt", "gtr", "turbo", "evo", "evolution", "sport", "coupe",
            "convertible", "spider", "spyder", "roadster", "avant",
        }:
            return False
        return True

    category_terms = [
        term for term in query_text.split()
        if term not in {"automotive", "car", "vehicle", "racing", "performance"}
    ]
    title_words = set(re.findall(r"[a-z0-9]+", title_text))
    return bool(category_terms) and all(
        term in title_words or f"{term}s" in title_words
        for term in category_terms
    )


async def resolve_catalog_image_url(item_type, item_id):
    fallback = catalog_image_url(item_type, item_id)
    cursor.execute("""
    SELECT image_url
    FROM catalog_images
    WHERE item_type = ? AND item_id = ?
    """, (item_type, item_id))
    cached = cursor.fetchone()
    if cached:
        return cached[0]

    query = catalog_image_query(item_type, item_id)
    image_url = None
    source = "catalog-card"
    source_title = None
    if query:
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": "6",
            "gsrlimit": "5",
            "prop": "imageinfo",
            "iiprop": "url|mime",
            "iiurlwidth": "1200",
            "format": "json",
        }
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            headers = {
                "User-Agent": "ValkyrieCatalog/1.0 (Discord catalog preview)",
            }
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(
                    "https://commons.wikimedia.org/w/api.php",
                    params=params,
                ) as response:
                    if response.status == 200:
                        payload = await response.json()
                        pages = payload.get("query", {}).get("pages", {})
                        for page in pages.values():
                            title = page.get("title", "")
                            info = (page.get("imageinfo") or [{}])[0]
                            mime = info.get("mime", "")
                            if (
                                mime.startswith("image/")
                                and catalog_image_is_relevant(item_type, query, title)
                            ):
                                image_url = info.get("thumburl") or info.get("url")
                                source = "Wikimedia Commons"
                                source_title = title
                                break
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            pass

    if not image_url:
        image_url = fallback
    cursor.execute("""
    INSERT INTO catalog_images (
        item_type, item_id, image_url, source, source_title, updated_at
    )
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        item_type, item_id, image_url, source, source_title, int(time.time()),
    ))
    db.commit()
    return image_url


def format_money(amount):
    return f"{amount:,}".replace(",", ".")


def format_car_attributes(car_id, compact=False):
    details = get_car_details(car_id)
    if details is None:
        return "Carro inválido."

    if compact:
        return " · ".join(
            f"{short}: {details['attributes'][name]}"
            for short, name in zip(CAR_ATTRIBUTE_SHORT_NAMES, CAR_ATTRIBUTE_NAMES)
        )

    return "\n".join(
        f"**{name}:** {value}"
        for name, value in details["attributes"].items()
    )


def get_car_quantity(guild_id, user_id, car_id):
    cursor.execute("""
    SELECT quantity
    FROM garage
    WHERE guild_id = ? AND user_id = ? AND car_id = ?
    """, (guild_id, user_id, car_id))
    row = cursor.fetchone()
    return row[0] if row else 0


def get_garage(guild_id, user_id):
    cursor.execute("""
    SELECT car_id, quantity, is_active
    FROM garage
    WHERE guild_id = ? AND user_id = ? AND quantity > 0
    ORDER BY car_id ASC
    """, (guild_id, user_id))
    return cursor.fetchall()


def get_active_car(guild_id, user_id):
    cursor.execute("""
    SELECT car_id
    FROM garage
    WHERE guild_id = ? AND user_id = ? AND is_active = 1 AND quantity > 0
    LIMIT 1
    """, (guild_id, user_id))
    row = cursor.fetchone()
    if row is None:
        return None
    return get_car(row[0])


def adjusted_market_price(guild_id, user_id, base_price, item_type):
    effects = get_active_event_effects(guild_id, user_id)
    multiplier = (
        effects["price_multiplier"]
        if item_type == "car"
        else effects["part_price_multiplier"]
    )
    return max(1, round(base_price * multiplier))


def buy_car(guild_id, user_id, car_id):
    details = get_car_details(car_id)
    if details is None:
        return "invalid", None
    create_user(guild_id, user_id)
    price = adjusted_market_price(guild_id, user_id, details["price"], "car")
    details = {**details, "price": price}
    cursor.execute("BEGIN IMMEDIATE")
    try:
        cursor.execute("""
        SELECT quantity
        FROM garage
        WHERE guild_id = ? AND user_id = ? AND car_id = ?
        """, (guild_id, user_id, car_id))
        if cursor.fetchone() is not None:
            db.rollback()
            return "owned", details
        cursor.execute("""
        SELECT coins
        FROM users
        WHERE guild_id = ? AND user_id = ? AND coins >= ?
        """, (guild_id, user_id, price))
        if cursor.fetchone() is None:
            coins = cursor.execute(
                "SELECT coins FROM users WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ).fetchone()[0]
            db.rollback()
            return "funds", {
                **details,
                "missing": price - coins,
            }
        has_active_car = cursor.execute("""
            SELECT 1 FROM garage
            WHERE guild_id = ? AND user_id = ? AND is_active = 1 AND quantity > 0
        """, (guild_id, user_id)).fetchone() is not None
        cursor.execute("""
        UPDATE users
        SET coins = coins - ?
        WHERE guild_id = ? AND user_id = ? AND coins >= ?
        """, (price, guild_id, user_id, price))
        if cursor.rowcount != 1:
            db.rollback()
            return "funds", {**details, "missing": price}
        cursor.execute("""
        INSERT INTO garage (guild_id, user_id, car_id, quantity, is_active)
        VALUES (?, ?, ?, 1, ?)
        """, (guild_id, user_id, car_id, 0 if has_active_car else 1))
        db.commit()
        return "bought", details
    except Exception:
        db.rollback()
        raise


def get_daily_shop():
    shop_date = today_in_game_timezone()
    cursor.execute("""
    SELECT car_ids, part_ids
    FROM daily_shop
    WHERE shop_date = ?
    """, (shop_date,))
    row = cursor.fetchone()
    if row is None:
        generator = random.Random(f"valkyrie-daily-shop:{shop_date}")
        car_ids = sorted(generator.sample(list(CARS_BY_ID), 3))
        part_ids = sorted(generator.sample(list(PARTS_BY_ID), 3))
        cursor.execute("""
        INSERT OR IGNORE INTO daily_shop (shop_date, car_ids, part_ids)
        VALUES (?, ?, ?)
        """, (
            shop_date,
            json.dumps(car_ids),
            json.dumps(part_ids),
        ))
        db.commit()
        return shop_date, car_ids, part_ids

    return shop_date, json.loads(row[0]), json.loads(row[1])


def is_daily_shop_item(shop_date, item_type, item_id):
    current_date, car_ids, part_ids = get_daily_shop()
    if current_date != shop_date:
        return False
    if item_type == "car":
        return item_id in car_ids
    return item_id in part_ids


def has_shop_purchase(guild_id, user_id, shop_date, item_type, item_id):
    cursor.execute("""
    SELECT 1
    FROM shop_purchases
    WHERE guild_id = ? AND user_id = ? AND shop_date = ?
      AND item_type = ? AND item_id = ?
    """, (guild_id, user_id, shop_date, item_type, item_id))
    return cursor.fetchone() is not None


def buy_daily_item(guild_id, user_id, item_type, item_id):
    shop_date, car_ids, part_ids = get_daily_shop()
    valid_ids = car_ids if item_type == "car" else part_ids
    if item_id not in valid_ids:
        return "unavailable", None

    if item_type == "car":
        details = get_car_details(item_id)
        price = details["price"]
    else:
        part = PARTS_BY_ID.get(item_id)
        if part is None:
            return "invalid", None
        details = {
            "name": part[1],
            "price": part[4],
            "rarity": part[3],
        }
        price = details["price"]

    create_user(guild_id, user_id)
    price = adjusted_market_price(guild_id, user_id, price, item_type)
    details = {**details, "price": price}
    cursor.execute("BEGIN IMMEDIATE")
    try:
        if has_shop_purchase(guild_id, user_id, shop_date, item_type, item_id):
            db.rollback()
            return "purchased", details
        if item_type == "car":
            cursor.execute("""
            SELECT quantity
            FROM garage
            WHERE guild_id = ? AND user_id = ? AND car_id = ?
            """, (guild_id, user_id, item_id))
            if cursor.fetchone() is not None:
                db.rollback()
                return "owned", details
        cursor.execute("""
        UPDATE users
        SET coins = coins - ?
        WHERE guild_id = ? AND user_id = ? AND coins >= ?
        """, (price, guild_id, user_id, price))
        if cursor.rowcount != 1:
            coins = cursor.execute(
                "SELECT coins FROM users WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ).fetchone()[0]
            db.rollback()
            return "funds", {**details, "missing": price - coins}

        if item_type == "car":
            has_active_car = cursor.execute("""
                SELECT 1 FROM garage
                WHERE guild_id = ? AND user_id = ? AND is_active = 1 AND quantity > 0
            """, (guild_id, user_id)).fetchone() is not None
            cursor.execute("""
            INSERT INTO garage (guild_id, user_id, car_id, quantity, is_active)
            VALUES (?, ?, ?, 1, ?)
            """, (
                guild_id, user_id, item_id, 0 if has_active_car else 1,
            ))
        else:
            cursor.execute("""
            INSERT INTO inventory (guild_id, user_id, part_id, quantity)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(guild_id, user_id, part_id)
            DO UPDATE SET quantity = inventory.quantity + 1
            """, (guild_id, user_id, item_id))

        cursor.execute("""
        INSERT INTO shop_purchases (
            guild_id, user_id, shop_date, item_type, item_id
        )
        VALUES (?, ?, ?, ?, ?)
        """, (guild_id, user_id, shop_date, item_type, item_id))
        db.commit()
        return "bought", details
    except Exception:
        db.rollback()
        raise


def set_active_car(guild_id, user_id, car_id):
    if get_car_quantity(guild_id, user_id, car_id) < 1:
        return False

    cursor.execute("""
    UPDATE garage
    SET is_active = 0
    WHERE guild_id = ? AND user_id = ?
    """, (guild_id, user_id))
    cursor.execute("""
    UPDATE garage
    SET is_active = 1
    WHERE guild_id = ? AND user_id = ? AND car_id = ?
    """, (guild_id, user_id, car_id))
    db.commit()
    return True


def record_race_stats(challenge):
    participants = (
        challenge["challenger_id"],
        challenge["opponent_id"],
    )
    winner_id = challenge["winner_id"]
    for user_id in participants:
        cursor.execute("""
        INSERT INTO race_stats (user_id, races, wins)
        VALUES (?, 1, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET
            races = race_stats.races + 1,
            wins = race_stats.wins + excluded.wins
        """, (user_id, 1 if user_id == winner_id else 0))
    db.commit()


RANKING_CATEGORIES = {
    "vitorias": (
        "Vitórias em rachas",
        "wins",
        "SELECT user_id, wins AS score FROM race_stats "
        "WHERE wins > 0 ORDER BY wins DESC, user_id ASC LIMIT ?",
    ),
    "corridas": (
        "Corridas disputadas",
        "races",
        "SELECT user_id, races AS score FROM race_stats "
        "WHERE races > 0 ORDER BY races DESC, user_id ASC LIMIT ?",
    ),
    "carros": (
        "Carros na garagem",
        "cars",
        "SELECT user_id, SUM(quantity) AS score FROM garage "
        "GROUP BY user_id ORDER BY score DESC, user_id ASC LIMIT ?",
    ),
    "pecas": (
        "Peças no inventário",
        "parts",
        "SELECT user_id, SUM(quantity) AS score FROM inventory "
        "GROUP BY user_id ORDER BY score DESC, user_id ASC LIMIT ?",
    ),
    "coins": (
        "Lost Coins acumulados",
        "coins",
        "SELECT user_id, SUM(coins) AS score FROM users "
        "GROUP BY user_id ORDER BY score DESC, user_id ASC LIMIT ?",
    ),
    "xp": (
        "XP acumulado",
        "xp",
        "SELECT user_id, SUM(xp) AS score FROM users "
        "GROUP BY user_id ORDER BY score DESC, user_id ASC LIMIT ?",
    ),
}


def get_ranking_category(value):
    normalized = normalize_text(value or "vitorias")
    aliases = {
        "vitoria": "vitorias",
        "wins": "vitorias",
        "win": "vitorias",
        "corrida": "corridas",
        "race": "corridas",
        "carro": "carros",
        "car": "carros",
        "peca": "pecas",
        "part": "pecas",
        "moedas": "coins",
        "moeda": "coins",
        "coin": "coins",
    }
    return aliases.get(normalized, normalized)


def get_global_ranking(category, limit=10):
    category_data = RANKING_CATEGORIES.get(category)
    if category_data is None:
        return None, []

    title, _score_name, query = category_data
    cursor.execute(query, (limit,))
    return title, cursor.fetchall()


# =========================
# EVENTOS, TESOURO E ADMINISTRAÇÃO
# =========================

ADMIN_ID = 1483990772368801893


def ensure_guild_economy(guild_id):
    cursor.execute("""
    INSERT OR IGNORE INTO guild_economy (guild_id, salary_tax_rate, treasury, updated_at)
    VALUES (?, ?, 0, ?)
    """, (guild_id, DEFAULT_SALARY_TAX_RATE, int(time.time())))


def get_active_event_effects(guild_id, user_id=None):
    now = int(time.time())
    cursor.execute("""
    SELECT effects_json
    FROM events
    WHERE guild_id = ? AND status = 'active' AND expires_at > ?
      AND (
          scope = 'global'
          OR ((scope = 'individual' OR scope = 'targeted') AND user_id = ?)
      )
    ORDER BY started_at ASC
    """, (guild_id, now, user_id))
    effects = {
        "salary_multiplier": 1.0,
        "price_multiplier": 1.0,
        "part_price_multiplier": 1.0,
        "crime_reward_multiplier": 1.0,
        "xp_multiplier": 1.0,
        "investment_multiplier": 1.0,
        "tax_rate": None,
        "corruption_chance_add": 0.0,
    }
    for (effects_json,) in cursor.fetchall():
        event_effects = json.loads(effects_json)
        for key in (
            "salary_multiplier",
            "price_multiplier",
            "part_price_multiplier",
            "crime_reward_multiplier",
            "xp_multiplier",
            "investment_multiplier",
        ):
            if key in event_effects:
                effects[key] *= float(event_effects[key])
        if "tax_rate" in event_effects:
            effects["tax_rate"] = float(event_effects["tax_rate"])
        if "corruption_chance_add" in event_effects:
            effects["corruption_chance_add"] += float(
                event_effects["corruption_chance_add"]
            )
    return effects


def get_salary_tax_rate(guild_id, user_id=None):
    ensure_guild_economy(guild_id)
    cursor.execute(
        "SELECT salary_tax_rate FROM guild_economy WHERE guild_id = ?",
        (guild_id,),
    )
    stored_rate = cursor.fetchone()[0]
    event_rate = get_active_event_effects(guild_id, user_id).get("tax_rate")
    if event_rate is not None:
        return min(MAX_SALARY_TAX_RATE, max(MIN_SALARY_TAX_RATE, event_rate))
    return min(MAX_SALARY_TAX_RATE, max(MIN_SALARY_TAX_RATE, stored_rate))


def settle_salary(guild_id, user_id, gross_amount, source):
    effects = get_active_event_effects(guild_id, user_id)
    adjusted_gross = max(0, round(gross_amount * effects["salary_multiplier"]))
    tax_rate = get_salary_tax_rate(guild_id, user_id)
    tax = min(adjusted_gross, round(adjusted_gross * tax_rate / 100))
    net_amount = adjusted_gross - tax
    ensure_guild_economy(guild_id)
    cursor.execute("""
    UPDATE guild_economy
    SET treasury = treasury + ?, updated_at = ?
    WHERE guild_id = ?
    """, (tax, int(time.time()), guild_id))
    cursor.execute("""
    INSERT INTO treasury_ledger (
        guild_id, source, amount, tax_rate, created_at, details
    )
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        guild_id,
        source,
        tax,
        tax_rate,
        int(time.time()),
        f"Salário bruto: {adjusted_gross} LC; líquido: {net_amount} LC",
    ))
    return adjusted_gross, tax, net_amount, tax_rate


def maybe_generate_event(guild_id):
    now = int(time.time())
    cursor.execute("""
    SELECT last_generated_at, next_generated_at
    FROM event_cycles
    WHERE guild_id = ?
    """, (guild_id,))
    row = cursor.fetchone()
    if row and row[1] and now < row[1]:
        return None

    cursor.execute("BEGIN IMMEDIATE")
    try:
        cursor.execute("""
        SELECT last_generated_at, next_generated_at
        FROM event_cycles
        WHERE guild_id = ?
        """, (guild_id,))
        row = cursor.fetchone()
        if row and row[1] and now < row[1]:
            db.rollback()
            return None

        event = random.choice(EVENTS)
        cursor.execute(
            "SELECT user_id FROM users WHERE guild_id = ? ORDER BY RANDOM() LIMIT 1",
            (guild_id,),
        )
        selected_user = cursor.fetchone()
        directed = event["effects"].get("directed", False)
        individual = selected_user is not None and random.random() < 0.35
        scope = (
            "targeted" if directed and selected_user is not None
            else "individual" if individual
            else "global"
        )
        user_id = selected_user[0] if scope != "global" else None
        event_effects = dict(event["effects"])

        if user_id is not None and "individual_coins" in event_effects:
            minimum, maximum = event_effects["individual_coins"]
            amount = random.randint(minimum, maximum)
            cursor.execute("""
            UPDATE users
            SET coins = coins + ?
            WHERE guild_id = ? AND user_id = ?
            """, (amount, guild_id, user_id))
            event_effects["awarded_coins"] = amount

        if user_id is not None and "individual_prison_seconds" in event_effects:
            prison_until = now + int(event_effects["individual_prison_seconds"])
            cursor.execute("""
            UPDATE users
            SET prison_until = MAX(prison_until, ?),
                crime_blocked_until = MAX(crime_blocked_until, ?),
                job_blocked_until = MAX(job_blocked_until, ?)
            WHERE guild_id = ? AND user_id = ?
            """, (prison_until, prison_until, prison_until, guild_id, user_id))

        cursor.execute("""
        INSERT INTO events (
            guild_id, scope, user_id, event_key, title, description,
            effects_json, started_at, expires_at, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
        """, (
            guild_id,
            scope,
            user_id,
            event["key"],
            event["title"],
            event["description"],
            json.dumps(event_effects),
            now,
            now + EVENT_DURATION_SECONDS,
        ))
        event_id = cursor.lastrowid
        cursor.execute("""
        INSERT INTO event_cycles (guild_id, last_generated_at)
        VALUES (?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET last_generated_at = excluded.last_generated_at
        """, (guild_id, now))
        next_generated_at = now + random.randint(
            EVENT_MIN_INTERVAL_SECONDS,
            EVENT_MAX_INTERVAL_SECONDS,
        )
        cursor.execute("""
        UPDATE event_cycles
        SET next_generated_at = ?
        WHERE guild_id = ?
        """, (next_generated_at, guild_id))
        db.commit()
        return {
            "event_id": event_id,
            "guild_id": guild_id,
            "scope": scope,
            "user_id": user_id,
            **event,
            "effects": event_effects,
        }
    except Exception:
        db.rollback()
        raise


def get_event_status(guild_id, user_id=None, limit=5):
    now = int(time.time())
    parameters = [guild_id, now]
    scope_filter = ""
    if user_id is not None:
        scope_filter = "AND (scope = 'global' OR user_id = ?)"
        parameters.append(user_id)
    parameters.append(limit)
    cursor.execute(f"""
    SELECT event_id, scope, user_id, title, description, started_at, expires_at
    FROM events
    WHERE guild_id = ? AND status = 'active' AND expires_at > ?
      {scope_filter}
    ORDER BY started_at DESC
    LIMIT ?
    """, parameters)
    return cursor.fetchall()


def resolve_investment_asset(value):
    normalized = normalize_text(value)
    for asset_key, asset in INVESTMENT_ASSETS.items():
        if normalized == normalize_text(asset_key):
            return asset_key
        if normalized in {normalize_text(alias) for alias in asset["aliases"]}:
            return asset_key
    return None


def refresh_investment_position(position):
    now = int(time.time())
    if now - position["last_updated"] < 15 * 60:
        return position
    event_effects = get_active_event_effects(
        position["guild_id"],
        position["user_id"],
    )
    change = random.uniform(-position["volatility"], position["volatility"])
    event_multiplier = event_effects.get("investment_multiplier", 1.0)
    position["current_value"] = max(
        0,
        round(position["current_value"] * (1 + change) * event_multiplier),
    )
    position["last_updated"] = now
    cursor.execute("""
    UPDATE investment_positions
    SET current_value = ?, last_updated = ?
    WHERE position_id = ?
    """, (
        position["current_value"],
        position["last_updated"],
        position["position_id"],
    ))
    return position


def read_investment_position(row):
    keys = (
        "position_id",
        "guild_id",
        "user_id",
        "asset_key",
        "invested_amount",
        "current_value",
        "volatility",
        "last_updated",
    )
    return dict(zip(keys, row))


def get_investment_positions(guild_id, user_id):
    cursor.execute("""
    SELECT position_id, guild_id, user_id, asset_key, invested_amount,
           current_value, volatility, last_updated
    FROM investment_positions
    WHERE guild_id = ? AND user_id = ?
    ORDER BY asset_key
    """, (guild_id, user_id))
    positions = [
        refresh_investment_position(read_investment_position(row))
        for row in cursor.fetchall()
    ]
    db.commit()
    return positions


def buy_investment(guild_id, user_id, asset_key, amount):
    asset = INVESTMENT_ASSETS.get(asset_key)
    if asset is None:
        return "error", "Ativo inválido."
    if amount < 100:
        return "error", "O investimento mínimo é de 100 LC."
    create_user(guild_id, user_id)
    cursor.execute("BEGIN IMMEDIATE")
    try:
        cursor.execute("""
        UPDATE users
        SET coins = coins - ?
        WHERE guild_id = ? AND user_id = ? AND coins >= ?
        """, (amount, guild_id, user_id, amount))
        if cursor.rowcount != 1:
            db.rollback()
            return "error", "Saldo disponível insuficiente."
        cursor.execute("""
        SELECT position_id, guild_id, user_id, asset_key, invested_amount,
               current_value, volatility, last_updated
        FROM investment_positions
        WHERE guild_id = ? AND user_id = ? AND asset_key = ?
        """, (guild_id, user_id, asset_key))
        row = cursor.fetchone()
        if row is None:
            cursor.execute("""
            INSERT INTO investment_positions (
                guild_id, user_id, asset_key, invested_amount,
                current_value, volatility, last_updated
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                guild_id,
                user_id,
                asset_key,
                amount,
                amount,
                asset["volatility"],
                int(time.time()),
            ))
        else:
            position = refresh_investment_position(read_investment_position(row))
            cursor.execute("""
            UPDATE investment_positions
            SET invested_amount = invested_amount + ?,
                current_value = current_value + ?
            WHERE position_id = ?
            """, (amount, amount, position["position_id"]))
        cursor.execute("""
        INSERT INTO investment_transactions (
            guild_id, user_id, asset_key, action, amount, value, created_at
        )
        VALUES (?, ?, ?, 'buy', ?, ?, ?)
        """, (guild_id, user_id, asset_key, amount, amount, int(time.time())))
        db.commit()
        return "ok", amount
    except Exception:
        db.rollback()
        raise


def sell_investment(guild_id, user_id, asset_key, requested_amount=None):
    if asset_key not in INVESTMENT_ASSETS:
        return "error", "Ativo inválido."
    cursor.execute("BEGIN IMMEDIATE")
    try:
        cursor.execute("""
        SELECT position_id, guild_id, user_id, asset_key, invested_amount,
               current_value, volatility, last_updated
        FROM investment_positions
        WHERE guild_id = ? AND user_id = ? AND asset_key = ?
        """, (guild_id, user_id, asset_key))
        row = cursor.fetchone()
        if row is None:
            db.rollback()
            return "error", "Você não possui posição nesse ativo."
        position = refresh_investment_position(read_investment_position(row))
        current_value = position["current_value"]
        if current_value <= 0:
            db.rollback()
            return "error", "Essa posição está sem valor para venda."
        sell_value = current_value if requested_amount is None else requested_amount
        if sell_value <= 0 or sell_value > current_value:
            db.rollback()
            return "error", f"Informe um valor entre 1 e {format_money(current_value)} LC."
        sold_cost = round(
            position["invested_amount"] * sell_value / current_value
        )
        if sell_value == current_value:
            cursor.execute(
                "DELETE FROM investment_positions WHERE position_id = ?",
                (position["position_id"],),
            )
        else:
            cursor.execute("""
            UPDATE investment_positions
            SET invested_amount = invested_amount - ?,
                current_value = current_value - ?
            WHERE position_id = ?
            """, (sold_cost, sell_value, position["position_id"]))
        cursor.execute("""
        UPDATE users
        SET coins = coins + ?
        WHERE guild_id = ? AND user_id = ?
        """, (sell_value, guild_id, user_id))
        cursor.execute("""
        INSERT INTO investment_transactions (
            guild_id, user_id, asset_key, action, amount, value, created_at
        )
        VALUES (?, ?, ?, 'sell', ?, ?, ?)
        """, (
            guild_id,
            user_id,
            asset_key,
            sold_cost,
            sell_value,
            int(time.time()),
        ))
        db.commit()
        return "ok", {
            "received": sell_value,
            "cost": sold_cost,
            "profit": sell_value - sold_cost,
        }
    except Exception:
        db.rollback()
        raise


def get_investment_transactions(guild_id, user_id, limit=10):
    cursor.execute("""
    SELECT asset_key, action, amount, value, created_at
    FROM investment_transactions
    WHERE guild_id = ? AND user_id = ?
    ORDER BY created_at DESC
    LIMIT ?
    """, (guild_id, user_id, limit))
    return cursor.fetchall()


def log_admin_action(guild_id, admin_id, action, target_id=None, amount=0,
                     item=None, details=None):
    cursor.execute("""
    INSERT INTO admin_logs (
        guild_id, admin_id, target_id, action, amount, item, details, created_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        guild_id,
        admin_id,
        target_id,
        action,
        amount,
        item,
        details,
        int(time.time()),
    ))
    db.commit()


def resolve_catalog_car(value):
    if value is None:
        return None
    try:
        car_id = int(value)
        return car_id if get_car(car_id) is not None else None
    except (TypeError, ValueError):
        normalized = normalize_text(str(value))
        for car_id, car in CARS_BY_ID.items():
            if normalize_text(car[0]) == normalized:
                return car_id
        for car_id, car in CARS_BY_ID.items():
            if normalized and normalized in normalize_text(car[0]):
                return car_id
    return None


def resolve_catalog_part(value):
    if value is None:
        return None
    try:
        part_id = int(value)
        return part_id if part_id in PARTS_BY_ID else None
    except (TypeError, ValueError):
        normalized = normalize_text(str(value))
        for part_id, part in PARTS_BY_ID.items():
            if normalize_text(part[1]) == normalized:
                return part_id
        for part_id, part in PARTS_BY_ID.items():
            if normalized and normalized in normalize_text(part[1]):
                return part_id
    return None


def admin_adjust_coins(guild_id, target_id, amount):
    cursor.execute("BEGIN IMMEDIATE")
    try:
        cursor.execute("""
        INSERT OR IGNORE INTO users (guild_id, user_id, xp, coins)
        VALUES (?, ?, 0, 0)
        """, (guild_id, target_id))
        cursor.execute("""
        UPDATE users
        SET coins = coins + ?
        WHERE guild_id = ? AND user_id = ?
          AND coins + ? >= 0
        """, (amount, guild_id, target_id, amount))
        if cursor.rowcount != 1:
            db.rollback()
            return False
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise


def admin_adjust_xp(guild_id, target_id, amount):
    cursor.execute("BEGIN IMMEDIATE")
    try:
        cursor.execute("""
        INSERT OR IGNORE INTO users (guild_id, user_id, xp, coins)
        VALUES (?, ?, 0, 0)
        """, (guild_id, target_id))
        cursor.execute("""
        UPDATE users
        SET xp = MAX(0, xp + ?)
        WHERE guild_id = ? AND user_id = ?
        """, (amount, guild_id, target_id))
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise


def admin_adjust_car(guild_id, target_id, car_id, quantity):
    if get_car(car_id) is None:
        return False
    cursor.execute("BEGIN IMMEDIATE")
    try:
        cursor.execute("""
        INSERT OR IGNORE INTO users (guild_id, user_id, xp, coins)
        VALUES (?, ?, 0, 0)
        """, (guild_id, target_id))
        if quantity > 0:
            cursor.execute("""
            INSERT INTO garage (guild_id, user_id, car_id, quantity, is_active)
            VALUES (?, ?, ?, ?, 0)
            ON CONFLICT(guild_id, user_id, car_id)
            DO UPDATE SET quantity = garage.quantity + excluded.quantity
            """, (guild_id, target_id, car_id, quantity))
        else:
            cursor.execute("""
            UPDATE garage
            SET quantity = quantity - ?
            WHERE guild_id = ? AND user_id = ? AND car_id = ? AND quantity >= ?
            """, (-quantity, guild_id, target_id, car_id, -quantity))
            if cursor.rowcount != 1:
                db.rollback()
                return False
            cursor.execute("""
            DELETE FROM garage
            WHERE guild_id = ? AND user_id = ? AND car_id = ? AND quantity <= 0
            """, (guild_id, target_id, car_id))
        ensure_active_car(guild_id, target_id)
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise


def admin_adjust_item(guild_id, target_id, part_id, quantity):
    if part_id not in PARTS_BY_ID:
        return False
    cursor.execute("BEGIN IMMEDIATE")
    try:
        cursor.execute("""
        INSERT OR IGNORE INTO users (guild_id, user_id, xp, coins)
        VALUES (?, ?, 0, 0)
        """, (guild_id, target_id))
        if quantity > 0:
            cursor.execute("""
            INSERT INTO inventory (guild_id, user_id, part_id, quantity)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id, part_id)
            DO UPDATE SET quantity = inventory.quantity + excluded.quantity
            """, (guild_id, target_id, part_id, quantity))
        else:
            cursor.execute("""
            UPDATE inventory
            SET quantity = quantity - ?
            WHERE guild_id = ? AND user_id = ? AND part_id = ? AND quantity >= ?
            """, (-quantity, guild_id, target_id, part_id, -quantity))
            if cursor.rowcount != 1:
                db.rollback()
                return False
            cursor.execute("""
            DELETE FROM inventory
            WHERE guild_id = ? AND user_id = ? AND part_id = ? AND quantity <= 0
            """, (guild_id, target_id, part_id))
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise


def reset_user_data(guild_id, target_id):
    cursor.execute("BEGIN IMMEDIATE")
    try:
        for table, condition in (
            ("daily_claims", "guild_id = ? AND user_id = ?"),
            ("inventory", "guild_id = ? AND user_id = ?"),
            ("garage", "guild_id = ? AND user_id = ?"),
            ("job_offers", "guild_id = ? AND user_id = ?"),
            ("active_jobs", "guild_id = ? AND user_id = ?"),
            ("job_history", "guild_id = ? AND user_id = ?"),
            ("crime_history", "guild_id = ? AND criminal_id = ?"),
            ("wanted_players", "guild_id = ? AND user_id = ?"),
            ("loans", "guild_id = ? AND user_id = ?"),
            ("events", "guild_id = ? AND user_id = ?"),
            ("investment_positions", "guild_id = ? AND user_id = ?"),
            ("investment_transactions", "guild_id = ? AND user_id = ?"),
        ):
            cursor.execute(f"DELETE FROM {table} WHERE {condition}", (guild_id, target_id))
        cursor.execute("""
        DELETE FROM race_challenges
        WHERE guild_id = ? AND (challenger_id = ? OR opponent_id = ?)
        """, (guild_id, target_id, target_id))
        cursor.execute("""
        DELETE FROM trades
        WHERE guild_id = ? AND (initiator_id = ? OR recipient_id = ?)
        """, (guild_id, target_id, target_id))
        cursor.execute("DELETE FROM race_stats WHERE user_id = ?", (target_id,))
        cursor.execute(
            "DELETE FROM political_office WHERE guild_id = ? AND user_id = ?",
            (guild_id, target_id),
        )
        cursor.execute(
            "DELETE FROM users WHERE guild_id = ? AND user_id = ?",
            (guild_id, target_id),
        )
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise


# =========================
# EMPREGOS
# =========================

def format_duration(seconds):
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours and minutes:
        return f"{hours}h {minutes}min"
    if hours:
        return f"{hours}h"
    return f"{max(1, minutes)}min"


def job_offer_from_row(row):
    if row is None:
        return None
    keys = (
        "offer_id",
        "guild_id",
        "user_id",
        "job_key",
        "payment",
        "xp",
        "duration_seconds",
        "bonus_min",
        "bonus_max",
        "bonus_chance",
        "created_at",
        "expires_at",
        "accepted_at",
        "completed_at",
        "bonus_awarded",
        "status",
        "job_mode",
    )
    offer = dict(zip(keys, row))
    job = JOB_BY_KEY.get(offer["job_key"])
    if job is None:
        cursor.execute(
            "SELECT rarity, company, title FROM jobs WHERE job_key = ?",
            (offer["job_key"],),
        )
        job_row = cursor.fetchone()
        if job_row is None:
            return offer
        job = {
            "rarity": job_row[0],
            "company": job_row[1],
            "title": job_row[2],
        }
    offer.update({
        key: job[key]
        for key in ("rarity", "company", "title")
        if key in job
    })
    offer["rarity_info"] = JOB_RARITY_BY_KEY.get(
        offer["rarity"],
        {"label": offer["rarity"], "emoji": "⭐"},
    )
    return offer


def get_job_offer(offer_id):
    cursor.execute("""
    SELECT offer_id, guild_id, user_id, job_key, payment, xp,
           duration_seconds, bonus_min, bonus_max, bonus_chance,
           created_at, expires_at, accepted_at, completed_at,
           bonus_awarded, status, job_mode
    FROM job_offers
    WHERE offer_id = ?
    """, (offer_id,))
    return job_offer_from_row(cursor.fetchone())


def expire_job_offers():
    now = int(time.time())
    cursor.execute("""
    UPDATE job_offers
    SET status = 'expired'
    WHERE status = 'pending' AND expires_at <= ?
    """, (now,))
    cursor.execute("""
    UPDATE users
    SET job_offer_expires = 0
    WHERE job_offer_expires > 0 AND job_offer_expires <= ?
      AND (active_job IS NULL OR active_job = 0)
    """, (now,))
    db.commit()


def complete_due_jobs(guild_id=None, user_id=None):
    expire_job_offers()
    now = int(time.time())
    filters = ["a.status = 'active'", "a.job_completion_time <= ?"]
    parameters = [now]
    if guild_id is not None:
        filters.append("a.guild_id = ?")
        parameters.append(guild_id)
    if user_id is not None:
        filters.append("a.user_id = ?")
        parameters.append(user_id)

    cursor.execute(f"""
    SELECT a.offer_id, a.guild_id, a.user_id, a.job_key,
           o.payment, o.xp, o.bonus_min, o.bonus_max, o.bonus_chance,
           o.job_mode
    FROM active_jobs a
    JOIN job_offers o ON o.offer_id = a.offer_id
    WHERE {' AND '.join(filters)}
    ORDER BY a.job_completion_time ASC
    """, parameters)
    due_jobs = cursor.fetchall()
    if not due_jobs:
        return []

    completed = []
    cursor.execute("BEGIN IMMEDIATE")
    try:
        for row in due_jobs:
            (
                offer_id,
                current_guild_id,
                current_user_id,
                job_key,
                payment,
                xp_amount,
                bonus_min,
                bonus_max,
                bonus_chance,
                job_mode,
            ) = row
            cursor.execute("""
            UPDATE active_jobs
            SET status = 'completed'
            WHERE offer_id = ? AND status = 'active'
            """, (offer_id,))
            if cursor.rowcount != 1:
                continue

            bonus = (
                random.randint(bonus_min, bonus_max)
                if random.random() < bonus_chance
                else 0
            )
            job = JOB_BY_KEY.get(job_key, {})
            if job.get("special_action") == "police":
                cursor.execute("""
                SELECT COUNT(*)
                FROM users
                WHERE guild_id = ? AND wanted_level > 0
                """, (current_guild_id,))
                bonus += min(1000, cursor.fetchone()[0] * 250)

            mode = job_mode or "normal"
            outcome = "completed"
            fine = 0
            imprisoned = 0
            wanted_after = 0
            gross_payment = payment + bonus
            if job.get("political") and mode == "corruption":
                effects = get_active_event_effects(
                    current_guild_id,
                    current_user_id,
                )
                discovery_chance = min(
                    0.95,
                    job.get("corruption_chance", 0.3)
                    + effects["corruption_chance_add"],
                )
                if random.random() < discovery_chance:
                    outcome = "corruption_discovered"
                    fine = min(
                        cursor.execute(
                            "SELECT coins FROM users WHERE guild_id = ? AND user_id = ?",
                            (current_guild_id, current_user_id),
                        ).fetchone()[0],
                        random.randint(*job["corruption_fine"]),
                    )
                    wanted_before = cursor.execute(
                        "SELECT wanted_level FROM users WHERE guild_id = ? AND user_id = ?",
                        (current_guild_id, current_user_id),
                    ).fetchone()[0]
                    wanted_after = min(
                        CRIME_WANTED_MAX_LEVEL,
                        wanted_before + 2,
                    )
                    wanted_until = now + 8 * 60 * 60
                    prison_until = 0
                    if random.random() < job.get("corruption_prison_chance", 0.3):
                        imprisoned = 1
                        prison_until = now + job.get(
                            "corruption_prison_seconds",
                            90 * 60,
                        )
                    cursor.execute("""
                    UPDATE users
                    SET coins = MAX(0, coins - ?),
                        wanted_level = ?,
                        wanted_until = ?,
                        crime_blocked_until = MAX(crime_blocked_until, ?),
                        job_blocked_until = MAX(job_blocked_until, ?),
                        prison_until = MAX(prison_until, ?)
                    WHERE guild_id = ? AND user_id = ?
                    """, (
                        fine,
                        wanted_after,
                        wanted_until,
                        prison_until,
                        prison_until,
                        prison_until,
                        current_guild_id,
                        current_user_id,
                    ))
                    cursor.execute("""
                    DELETE FROM political_office
                    WHERE guild_id = ? AND user_id = ?
                    """, (current_guild_id, current_user_id))
                    total_paid = 0
                    tax_paid = 0
                    gross_payment = 0
                    xp_amount = max(1, xp_amount // 2)
                else:
                    gross_payment = round(
                        gross_payment * job.get("corruption_multiplier", 3.0)
                    )

            if outcome == "completed":
                gross_payment, tax_paid, total_paid, _tax_rate = settle_salary(
                    current_guild_id,
                    current_user_id,
                    gross_payment,
                    f"job:{job_key}:{mode}",
                )
                xp_amount = round(
                    xp_amount * get_active_event_effects(
                        current_guild_id,
                        current_user_id,
                    )["xp_multiplier"]
                )
                cursor.execute("""
                UPDATE users
                SET coins = coins + ?,
                    xp = xp + ?,
                    active_job = CASE WHEN active_job = ? THEN NULL ELSE active_job END,
                    job_completion_time = CASE
                        WHEN active_job = ? THEN 0
                        ELSE job_completion_time
                    END,
                    job_offer_expires = 0
                WHERE guild_id = ? AND user_id = ?
                """, (
                    total_paid,
                    xp_amount,
                    offer_id,
                    offer_id,
                    current_guild_id,
                    current_user_id,
                ))
            else:
                tax_paid = 0
                cursor.execute("""
                UPDATE users
                SET xp = xp + ?,
                    active_job = CASE WHEN active_job = ? THEN NULL ELSE active_job END,
                    job_completion_time = CASE
                        WHEN active_job = ? THEN 0
                        ELSE job_completion_time
                    END,
                    job_offer_expires = 0
                WHERE guild_id = ? AND user_id = ?
                """, (
                    xp_amount,
                    offer_id,
                    offer_id,
                    current_guild_id,
                    current_user_id,
                ))
            cursor.execute("""
            UPDATE job_offers
            SET status = 'completed', completed_at = ?, bonus_awarded = ?
            WHERE offer_id = ? AND status = 'accepted'
            """, (now, bonus, offer_id))
            cursor.execute("""
            INSERT INTO job_history (
                offer_id, guild_id, user_id, job_key, payment, bonus,
                total_paid, xp, completed_at, gross_payment, tax_paid,
                mode, outcome, fine
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                offer_id,
                current_guild_id,
                current_user_id,
                job_key,
                payment,
                bonus,
                total_paid,
                xp_amount,
                now,
                gross_payment,
                tax_paid,
                mode,
                outcome,
                fine,
            ))
            completed.append({
                "offer_id": offer_id,
                "guild_id": current_guild_id,
                "user_id": current_user_id,
                "job_key": job_key,
                "payment": payment,
                "bonus": bonus,
                "total_paid": total_paid,
                "xp": xp_amount,
                "gross_payment": gross_payment,
                "tax_paid": tax_paid,
                "mode": mode,
                "outcome": outcome,
                "fine": fine,
                "imprisoned": imprisoned,
                "wanted_after": wanted_after,
            })
        db.commit()
    except Exception:
        db.rollback()
        raise
    return completed


def get_active_job(guild_id, user_id):
    complete_due_jobs(guild_id, user_id)
    cursor.execute("""
    SELECT o.offer_id, o.guild_id, o.user_id, o.job_key, o.payment, o.xp,
           o.duration_seconds, o.bonus_min, o.bonus_max, o.bonus_chance,
           o.created_at, o.expires_at, o.accepted_at, o.completed_at,
           o.bonus_awarded, o.status, o.job_mode
    FROM active_jobs a
    JOIN job_offers o ON o.offer_id = a.offer_id
    WHERE a.guild_id = ? AND a.user_id = ? AND a.status = 'active'
    LIMIT 1
    """, (guild_id, user_id))
    active = job_offer_from_row(cursor.fetchone())
    if active is not None:
        cursor.execute(
            "SELECT job_completion_time FROM active_jobs WHERE offer_id = ?",
            (active["offer_id"],),
        )
        completion_row = cursor.fetchone()
        active["completion_time"] = completion_row[0] if completion_row else 0
    return active


def create_job_offer(guild_id, user_id):
    complete_due_jobs(guild_id, user_id)
    expire_job_offers()
    create_user(guild_id, user_id)
    now = int(time.time())

    cursor.execute("BEGIN IMMEDIATE")
    try:
        cursor.execute("""
        SELECT last_job_offer, job_offer_expires, active_job,
               job_completion_time, job_blocked_until, prison_until
        FROM users
        WHERE guild_id = ? AND user_id = ?
        """, (guild_id, user_id))
        state = cursor.fetchone()
        last_offer, offer_expires, active_job, completion_time, job_blocked, prison_until = state
        if active_job:
            active = get_active_job(guild_id, user_id)
            db.rollback()
            return "active", active
        if max(job_blocked, prison_until) > now:
            db.rollback()
            return "blocked", max(job_blocked, prison_until)

        cursor.execute("""
        SELECT offer_id
        FROM job_offers
        WHERE guild_id = ? AND user_id = ? AND status = 'pending'
          AND expires_at > ?
        ORDER BY offer_id DESC
        LIMIT 1
        """, (guild_id, user_id, now))
        pending_row = cursor.fetchone()
        if pending_row:
            pending = get_job_offer(pending_row[0])
            db.rollback()
            return "pending", pending

        if last_offer and now < last_offer + JOB_OFFER_COOLDOWN_SECONDS:
            db.rollback()
            return "cooldown", last_offer + JOB_OFFER_COOLDOWN_SECONDS

        rarity = random.choices(
            JOB_RARITIES,
            weights=JOB_RARITY_WEIGHTS,
            k=1,
        )[0]
        candidates = [
            job for job in JOBS
            if job["rarity"] == rarity["key"]
        ]
        job = random.choice(candidates)
        payment = random.randint(*job["payment"])
        xp_amount = random.randint(*job["xp"])
        bonus_min, bonus_max = job["bonus"]
        expires_at = now + JOB_OFFER_VALID_SECONDS
        duration_seconds = job["duration_minutes"] * 60

        cursor.execute("""
        INSERT INTO job_offers (
            guild_id, user_id, job_key, payment, xp, duration_seconds,
            bonus_min, bonus_max, bonus_chance, created_at, expires_at,
            status, job_mode
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 'normal')
        """, (
            guild_id,
            user_id,
            job["key"],
            payment,
            xp_amount,
            duration_seconds,
            bonus_min,
            bonus_max,
            job["bonus_chance"],
            now,
            expires_at,
        ))
        offer_id = cursor.lastrowid
        cursor.execute("""
        UPDATE users
        SET last_job_offer = ?, job_offer_expires = ?
        WHERE guild_id = ? AND user_id = ?
        """, (now, expires_at, guild_id, user_id))
        db.commit()
        return "new", get_job_offer(offer_id)
    except Exception:
        db.rollback()
        raise


def accept_job(guild_id, user_id, offer_id, mode="normal"):
    complete_due_jobs(guild_id, user_id)
    expire_job_offers()
    now = int(time.time())
    create_user(guild_id, user_id)
    if mode not in {"normal", "corruption"}:
        mode = "normal"
    cursor.execute("BEGIN IMMEDIATE")
    try:
        cursor.execute("""
        SELECT job_blocked_until, prison_until, active_job
        FROM users
        WHERE guild_id = ? AND user_id = ?
        """, (guild_id, user_id))
        state = cursor.fetchone()
        if state is None:
            db.rollback()
            return "error", "Não foi possível carregar seu perfil."
        job_blocked, prison_until, active_job = state
        if max(job_blocked, prison_until) > now:
            db.rollback()
            return "error", f"Você está bloqueado para trabalhos por {format_duration(max(job_blocked, prison_until) - now)}."
        if active_job:
            db.rollback()
            return "error", "Você já está trabalhando em um emprego ativo."

        cursor.execute("""
        SELECT offer_id, job_key, duration_seconds
        FROM job_offers
        WHERE offer_id = ? AND guild_id = ? AND user_id = ?
          AND status = 'pending' AND expires_at > ?
        """, (offer_id, guild_id, user_id, now))
        offer_row = cursor.fetchone()
        if offer_row is None:
            db.rollback()
            return "error", "Essa oferta não existe, já expirou ou não pertence a você."
        _offer_id, job_key, duration_seconds = offer_row
        job = JOB_BY_KEY.get(job_key, {})
        if not job.get("political") and mode == "corruption":
            db.rollback()
            return "error", "Somente uma oferta política pode usar corrupção."
        if job.get("political") and mode == "corruption":
            cursor.execute("""
            SELECT 1
            FROM political_office
            WHERE guild_id = ? AND status = 'active' AND expires_at > ?
              AND user_id != ?
            LIMIT 1
            """, (guild_id, now, user_id))
            if cursor.fetchone() is not None:
                db.rollback()
                return "error", "Já existe outro político em mandato neste servidor."

        cursor.execute("""
        UPDATE job_offers
        SET status = 'accepted', accepted_at = ?, job_mode = ?
        WHERE offer_id = ? AND status = 'pending' AND expires_at > ?
        """, (now, mode, offer_id, now))
        if cursor.rowcount != 1:
            db.rollback()
            return "error", "Essa oferta já foi respondida ou expirou."

        completion_time = now + duration_seconds
        cursor.execute("""
        INSERT INTO active_jobs (
            offer_id, guild_id, user_id, job_key, job_completion_time, status
        )
        VALUES (?, ?, ?, ?, ?, 'active')
        """, (offer_id, guild_id, user_id, job_key, completion_time))
        cursor.execute("""
        UPDATE users
        SET active_job = ?, job_completion_time = ?
        WHERE guild_id = ? AND user_id = ? AND active_job IS NULL
        """, (offer_id, completion_time, guild_id, user_id))
        if cursor.rowcount != 1:
            db.rollback()
            return "error", "Você já começou outro trabalho ao mesmo tempo."
        if job.get("political"):
            cursor.execute("""
            INSERT INTO political_office (
                guild_id, user_id, office, started_at, expires_at, status
            )
            VALUES (?, ?, 'politico', ?, ?, 'active')
            ON CONFLICT(guild_id) DO UPDATE SET
                user_id = excluded.user_id,
                office = excluded.office,
                started_at = excluded.started_at,
                expires_at = excluded.expires_at,
                status = excluded.status
            """, (guild_id, user_id, now, completion_time))
        db.commit()
        return "accepted", get_job_offer(offer_id)
    except Exception:
        db.rollback()
        raise


def reject_job(guild_id, user_id, offer_id):
    now = int(time.time())
    cursor.execute("""
    UPDATE job_offers
    SET status = 'rejected'
    WHERE offer_id = ? AND guild_id = ? AND user_id = ?
      AND status = 'pending' AND expires_at > ?
    """, (offer_id, guild_id, user_id, now))
    if cursor.rowcount != 1:
        return False
    cursor.execute("""
    UPDATE users
    SET job_offer_expires = 0
    WHERE guild_id = ? AND user_id = ?
    """, (guild_id, user_id))
    db.commit()
    return True


def get_wanted_state(guild_id, user_id):
    create_user(guild_id, user_id)
    now = int(time.time())
    cursor.execute("""
    SELECT wanted_level, wanted_until, crime_blocked_until,
           job_blocked_until, prison_until
    FROM users
    WHERE guild_id = ? AND user_id = ?
    """, (guild_id, user_id))
    row = cursor.fetchone()
    if row is None:
        return {
            "wanted_level": 0,
            "wanted_until": 0,
            "crime_blocked_until": 0,
            "job_blocked_until": 0,
            "prison_until": 0,
        }

    wanted_level, wanted_until, crime_blocked, job_blocked, prison_until = row
    if wanted_level > 0 and wanted_until <= now:
        wanted_level = 0
        wanted_until = 0
        cursor.execute("""
        UPDATE users
        SET wanted_level = 0, wanted_until = 0
        WHERE guild_id = ? AND user_id = ?
        """, (guild_id, user_id))
        db.commit()

    cursor.execute("""
    INSERT INTO wanted_players (
        guild_id, user_id, wanted_level, wanted_until,
        crime_blocked_until, job_blocked_until, prison_until
    )
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(guild_id, user_id) DO UPDATE SET
        wanted_level = excluded.wanted_level,
        wanted_until = excluded.wanted_until,
        crime_blocked_until = excluded.crime_blocked_until,
        job_blocked_until = excluded.job_blocked_until,
        prison_until = excluded.prison_until
    """, (
        guild_id,
        user_id,
        wanted_level,
        wanted_until,
        crime_blocked,
        job_blocked,
        prison_until,
    ))
    db.commit()
    return {
        "wanted_level": wanted_level,
        "wanted_until": wanted_until,
        "crime_blocked_until": crime_blocked,
        "job_blocked_until": job_blocked,
        "prison_until": prison_until,
    }


def get_crime_key(value):
    normalized = normalize_text(value or "").replace(" ", "")
    if normalized in CRIME_BY_KEY:
        return normalized
    return CRIME_ALIASES.get(normalized)


def get_stealable_cars(guild_id, excluded_user_id=None, target_user_id=None):
    parameters = [guild_id]
    filters = ["quantity > 0", "guild_id = ?"]
    if excluded_user_id is not None:
        filters.append("user_id != ?")
        parameters.append(excluded_user_id)
    if target_user_id is not None:
        filters.append("user_id = ?")
        parameters.append(target_user_id)
    cursor.execute(f"""
    SELECT user_id, car_id, quantity, is_active
    FROM garage
    WHERE {' AND '.join(filters)}
    ORDER BY user_id ASC, is_active DESC, car_id ASC
    """, parameters)
    return cursor.fetchall()


def crime_chance(guild_id, user_id, crime_key):
    crime = CRIME_BY_KEY[crime_key]
    _xp, _coins = get_user(guild_id, user_id)
    cursor.execute("""
    SELECT crime_xp, wanted_level
    FROM users
    WHERE guild_id = ? AND user_id = ?
    """, (guild_id, user_id))
    crime_xp, wanted_level = cursor.fetchone()
    experience_modifier = min(
        CRIME_MODIFIERS["experience_cap"],
        crime_xp / CRIME_MODIFIERS["crime_xp_per_point"],
    )
    car_modifier = 0
    active_car = get_active_car(guild_id, user_id)
    if active_car is not None:
        car_details = get_car_details(
            next(
                car_id for car_id, car in CARS_BY_ID.items()
                if car == active_car
            )
        )
        attributes = car_details["attributes"]
        car_score = (
            attributes.get("Velocidade Máxima", 0)
            + attributes.get("Controle", 0)
        ) / 2
        car_modifier = min(
            CRIME_MODIFIERS["car_attribute_cap"],
            car_score / CRIME_MODIFIERS["car_attribute_per_point"],
        )
    wanted_modifier = wanted_level * CRIME_MODIFIERS["wanted_penalty_per_level"]
    return round(max(
        CRIME_MIN_CHANCE,
        min(
            CRIME_MAX_CHANCE,
            crime["base_success"] + experience_modifier
            + car_modifier - wanted_modifier,
        ),
    ), 1)


def crime_preview(guild_id, user_id, crime_key, victim_id=None, target_car_id=None):
    crime = CRIME_BY_KEY.get(crime_key)
    if crime is None:
        return "error", "Crime inválido."
    create_user(guild_id, user_id)
    cursor.execute(
        "SELECT crime_xp FROM users WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    )
    crime_xp = cursor.fetchone()[0]
    if crime_xp < crime["required_crime_xp"]:
        return (
            "error",
            f"Você precisa de {crime['required_crime_xp']} XP criminal para esse crime.",
        )
    if crime["requires_target"] and victim_id is None:
        return "target_required", None
    if victim_id is not None and victim_id == user_id:
        return "error", "Você não pode escolher a si mesmo como alvo."

    result = {
        "crime_key": crime_key,
        "crime": crime,
        "chance": crime_chance(guild_id, user_id, crime_key),
        "victim_id": victim_id,
        "target_car_id": target_car_id,
        "target_car": None,
        "target_coins": 0,
    }
    if crime["requires_car"]:
        cars = get_stealable_cars(
            guild_id,
            excluded_user_id=user_id,
            target_user_id=victim_id,
        )
        if target_car_id is not None:
            cars = [row for row in cars if row[1] == target_car_id]
        if crime.get("rare_car_min_price"):
            cars = [
                row for row in cars
                if get_car_details(row[1])["price"] >= crime["rare_car_min_price"]
            ]
        if not cars:
            return "error", "Esse alvo não possui um carro elegível para esse roubo."
        victim_id, selected_car_id = cars[0][0], cars[0][1]
        result["victim_id"] = victim_id
        result["target_car_id"] = selected_car_id
        result["target_car"] = get_car_details(selected_car_id)
    elif crime["requires_target"]:
        get_user(guild_id, victim_id)
        cursor.execute(
            "SELECT coins FROM users WHERE guild_id = ? AND user_id = ?",
            (guild_id, victim_id),
        )
        target_row = cursor.fetchone()
        if target_row is None or target_row[0] <= 0:
            return "error", "Esse jogador não possui Lost Coins para roubar."
        result["target_coins"] = target_row[0]
    return "ok", result


def execute_crime(guild_id, user_id, crime_key, victim_id=None, target_car_id=None):
    complete_due_jobs(guild_id, user_id)
    preview_type, preview = crime_preview(
        guild_id,
        user_id,
        crime_key,
        victim_id,
        target_car_id,
    )
    if preview_type != "ok":
        return preview_type, preview

    crime = preview["crime"]
    now = int(time.time())
    cursor.execute("BEGIN IMMEDIATE")
    try:
        cursor.execute("""
        SELECT coins, crime_xp, wanted_level, wanted_until,
               crime_blocked_until, job_blocked_until, prison_until,
               crime_cooldown
        FROM users
        WHERE guild_id = ? AND user_id = ?
        """, (guild_id, user_id))
        actor_row = cursor.fetchone()
        if actor_row is None:
            db.rollback()
            return "error", "Não foi possível carregar seu perfil."
        (
            actor_coins,
            actor_crime_xp,
            wanted_before,
            wanted_until_before,
            crime_blocked_before,
            job_blocked_before,
            prison_until_before,
            crime_cooldown,
        ) = actor_row
        if max(crime_blocked_before, prison_until_before) > now:
            db.rollback()
            return "error", f"Crimes bloqueados por {format_duration(max(crime_blocked_before, prison_until_before) - now)}."
        if crime_cooldown > now:
            db.rollback()
            return "cooldown", crime_cooldown
        if actor_crime_xp < crime["required_crime_xp"]:
            db.rollback()
            return "error", f"Você precisa de {crime['required_crime_xp']} XP criminal para esse crime."

        if crime["requires_car"]:
            cursor.execute("""
            SELECT quantity
            FROM garage
            WHERE guild_id = ? AND user_id = ? AND car_id = ? AND quantity > 0
            """, (guild_id, victim_id, target_car_id))
            if cursor.fetchone() is None:
                db.rollback()
                return "error", "Esse carro já não está disponível para roubo."
        elif crime["requires_target"]:
            cursor.execute(
                "SELECT coins FROM users WHERE guild_id = ? AND user_id = ?",
                (guild_id, victim_id),
            )
            target_row = cursor.fetchone()
            if target_row is None or target_row[0] <= 0:
                db.rollback()
                return "error", "Esse jogador não possui saldo disponível para roubo."

        success = random.random() < (preview["chance"] / 100)
        reward = 0
        fine = 0
        car_transferred = 0
        imprisoned = 0
        details = crime["label"]

        if success:
            if crime["key"] == "roubar_carro":
                cursor.execute("""
                UPDATE garage
                SET quantity = quantity - 1, is_active = 0
                WHERE guild_id = ? AND user_id = ? AND car_id = ? AND quantity > 0
                """, (guild_id, victim_id, target_car_id))
                if cursor.rowcount != 1:
                    db.rollback()
                    return "error", "O carro foi alterado antes da transferência; tente novamente."
                cursor.execute("""
                DELETE FROM garage
                WHERE guild_id = ? AND user_id = ? AND car_id = ? AND quantity <= 0
                """, (guild_id, victim_id, target_car_id))
                cursor.execute("""
                SELECT 1 FROM garage
                WHERE guild_id = ? AND user_id = ? AND quantity > 0
                LIMIT 1
                """, (guild_id, user_id))
                thief_has_car = cursor.fetchone() is not None
                cursor.execute("""
                INSERT INTO garage (guild_id, user_id, car_id, quantity, is_active)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(guild_id, user_id, car_id)
                DO UPDATE SET quantity = garage.quantity + 1
                """, (
                    guild_id,
                    user_id,
                    target_car_id,
                    0 if thief_has_car else 1,
                ))
                ensure_active_car(guild_id, victim_id)
                ensure_active_car(guild_id, user_id)
                car_transferred = 1
                details = f"{crime['label']}: {preview['target_car']['name']}"
            elif crime["key"] == "roubar_jogador":
                cursor.execute(
                    "SELECT coins FROM users WHERE guild_id = ? AND user_id = ?",
                    (guild_id, victim_id),
                )
                victim_coins = cursor.fetchone()[0]
                max_stolen = min(
                    int(victim_coins * crime["victim_loss_percent"]),
                    crime["victim_loss_cap"],
                )
                if max_stolen <= 0:
                    db.rollback()
                    return "error", "O alvo não possui saldo suficiente para esse roubo."
                reward = min(
                    max_stolen,
                    max(
                        1,
                        round(
                            random.randint(1, max_stolen)
                            * get_active_event_effects(
                                guild_id,
                                user_id,
                            )["crime_reward_multiplier"]
                        ),
                    ),
                )
                cursor.execute("""
                UPDATE users
                SET coins = coins - ?
                WHERE guild_id = ? AND user_id = ? AND coins >= ?
                """, (reward, guild_id, victim_id, reward))
                if cursor.rowcount != 1:
                    db.rollback()
                    return "error", "O saldo do alvo mudou antes da transferência."
                details = f"{crime['label']}: {reward} Lost Coins"
            else:
                reward = round(
                    random.randint(*crime["reward"])
                    * get_active_event_effects(
                        guild_id,
                        user_id,
                    )["crime_reward_multiplier"]
                )
            wanted_after = wanted_before
            wanted_until_after = wanted_until_before
            crime_blocked_after = crime_blocked_before
            job_blocked_after = job_blocked_before
            prison_until_after = prison_until_before
            crime_cooldown_after = now + crime["cooldown_seconds"]
            crime_xp_after = actor_crime_xp + CRIME_XP_SUCCESS
        else:
            requested_fine = random.randint(*crime["fine"])
            fine = min(actor_coins, requested_fine)
            wanted_after = min(
                CRIME_WANTED_MAX_LEVEL,
                wanted_before + crime["wanted_on_failure"],
            )
            wanted_until_after = max(
                wanted_until_before,
                now + crime["wanted_duration_seconds"],
            )
            crime_blocked_after = max(
                crime_blocked_before,
                now + crime["failure_crime_block_seconds"],
            )
            job_blocked_after = max(
                job_blocked_before,
                now + crime["failure_job_block_seconds"],
            )
            prison_until_after = prison_until_before
            if random.random() < crime["prison_chance"]:
                imprisoned = 1
                prison_until_after = max(
                    prison_until_before,
                    now + crime["prison_seconds"],
                )
                crime_blocked_after = max(crime_blocked_after, prison_until_after)
                job_blocked_after = max(job_blocked_after, prison_until_after)
            crime_cooldown_after = max(
                now + crime["cooldown_seconds"],
                crime_blocked_after,
            )
            crime_xp_after = actor_crime_xp + CRIME_XP_FAILURE

        net_coins = reward - fine
        cursor.execute("""
        UPDATE users
        SET coins = MAX(0, coins + ?),
            last_crime = ?,
            last_crime_key = ?,
            crime_cooldown = ?,
            wanted_level = ?,
            wanted_until = ?,
            crime_blocked_until = ?,
            job_blocked_until = ?,
            prison_until = ?,
            crime_xp = ?
        WHERE guild_id = ? AND user_id = ?
        """, (
            net_coins,
            now,
            crime_key,
            crime_cooldown_after,
            wanted_after,
            wanted_until_after,
            crime_blocked_after,
            job_blocked_after,
            prison_until_after,
            crime_xp_after,
            guild_id,
            user_id,
        ))
        cursor.execute("""
        INSERT INTO wanted_players (
            guild_id, user_id, wanted_level, wanted_until,
            crime_blocked_until, job_blocked_until, prison_until
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(guild_id, user_id) DO UPDATE SET
            wanted_level = excluded.wanted_level,
            wanted_until = excluded.wanted_until,
            crime_blocked_until = excluded.crime_blocked_until,
            job_blocked_until = excluded.job_blocked_until,
            prison_until = excluded.prison_until
        """, (
            guild_id,
            user_id,
            wanted_after,
            wanted_until_after,
            crime_blocked_after,
            job_blocked_after,
            prison_until_after,
        ))
        cursor.execute("""
        INSERT INTO crime_history (
            guild_id, criminal_id, victim_id, crime_key, target_car_id,
            success, reward, fine, car_transferred, car_recovered,
            wanted_before, wanted_after, imprisoned, created_at, details
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
        """, (
            guild_id,
            user_id,
            victim_id,
            crime_key,
            target_car_id,
            int(success),
            reward,
            fine,
            car_transferred,
            wanted_before,
            wanted_after,
            imprisoned,
            now,
            details,
        ))
        db.commit()
    except Exception:
        db.rollback()
        raise

    return "success" if success else "failure", {
        "crime_key": crime_key,
        "crime": crime,
        "criminal_id": user_id,
        "success": success,
        "chance": preview["chance"],
        "victim_id": victim_id,
        "target_car_id": target_car_id,
        "target_car": preview["target_car"],
        "reward": reward,
        "fine": fine,
        "car_transferred": car_transferred,
        "wanted_before": wanted_before,
        "wanted_after": wanted_after,
        "imprisoned": imprisoned,
        "details": details,
        "crime_cooldown": crime_cooldown_after,
        "job_blocked_until": job_blocked_after,
        "crime_blocked_until": crime_blocked_after,
        "prison_until": prison_until_after,
    }


def get_recent_job_history(guild_id, user_id):
    cursor.execute("""
    SELECT job_key, payment, bonus, total_paid, xp, completed_at,
           gross_payment, tax_paid, mode, outcome, fine
    FROM job_history
    WHERE guild_id = ? AND user_id = ?
    ORDER BY completed_at DESC
    LIMIT ?
    """, (guild_id, user_id, JOB_HISTORY_LIMIT))
    return cursor.fetchall()


def get_recent_crime_history(guild_id, user_id):
    cursor.execute("""
    SELECT crime_key, success, reward, fine, wanted_after,
           imprisoned, created_at, details
    FROM crime_history
    WHERE guild_id = ? AND criminal_id = ?
    ORDER BY created_at DESC
    LIMIT ?
    """, (guild_id, user_id, CRIME_HISTORY_LIMIT))
    return cursor.fetchall()


def expire_trades():
    cursor.execute("""
    UPDATE trades
    SET status = 'expired'
    WHERE status = 'pending' AND expires_at <= ?
    """, (int(time.time()),))
    db.commit()


def parse_trade_items(value):
    if not value:
        return None

    normalized = normalize_text(value)
    sides = re.split(r"\s+por\s+", normalized, maxsplit=1)
    if len(sides) != 2:
        return None

    item_pattern = re.compile(r"\b(carro|car|peca|part|parts)\s*[:#]?\s*(\d+)\b")
    parsed = []
    for side in sides:
        matches = item_pattern.findall(side)
        if not matches:
            return None
        side_items = []
        for item_type, item_id_text in matches:
            item_id = int(item_id_text)
            normalized_type = "car" if item_type in {"carro", "car"} else "part"
            if normalized_type == "car" and get_car(item_id) is None:
                return None
            if normalized_type == "part" and item_id not in PARTS_BY_ID:
                return None
            side_items.append({"type": normalized_type, "id": item_id})
        parsed.append(side_items)

    return parsed[0], parsed[1]


def has_trade_items(guild_id, user_id, items):
    required_cars = {}
    required_parts = {}
    for item in items:
        target = required_cars if item["type"] == "car" else required_parts
        target[item["id"]] = target.get(item["id"], 0) + 1

    for car_id, quantity in required_cars.items():
        if get_car_quantity(guild_id, user_id, car_id) < quantity:
            return False
    for part_id, quantity in required_parts.items():
        cursor.execute("""
        SELECT quantity
        FROM inventory
        WHERE guild_id = ? AND user_id = ? AND part_id = ?
        """, (guild_id, user_id, part_id))
        row = cursor.fetchone()
        if row is None or row[0] < quantity:
            return False
    return True


def remove_trade_item(guild_id, user_id, item):
    if item["type"] == "car":
        cursor.execute("""
        UPDATE garage
        SET quantity = quantity - 1, is_active = 0
        WHERE guild_id = ? AND user_id = ? AND car_id = ?
        """, (guild_id, user_id, item["id"]))
        cursor.execute("""
        DELETE FROM garage
        WHERE guild_id = ? AND user_id = ? AND car_id = ? AND quantity <= 0
        """, (guild_id, user_id, item["id"]))
        return

    cursor.execute("""
    UPDATE inventory
    SET quantity = quantity - 1
    WHERE guild_id = ? AND user_id = ? AND part_id = ?
    """, (guild_id, user_id, item["id"]))
    cursor.execute("""
    DELETE FROM inventory
    WHERE guild_id = ? AND user_id = ? AND part_id = ? AND quantity <= 0
    """, (guild_id, user_id, item["id"]))


def add_trade_item(guild_id, user_id, item):
    if item["type"] == "car":
        cursor.execute("""
        INSERT INTO garage (guild_id, user_id, car_id, quantity, is_active)
        VALUES (?, ?, ?, 1, 0)
        ON CONFLICT(guild_id, user_id, car_id)
        DO UPDATE SET quantity = garage.quantity + 1
        """, (guild_id, user_id, item["id"]))
        return

    cursor.execute("""
    INSERT INTO inventory (guild_id, user_id, part_id, quantity)
    VALUES (?, ?, ?, 1)
    ON CONFLICT(guild_id, user_id, part_id)
    DO UPDATE SET quantity = inventory.quantity + 1
    """, (guild_id, user_id, item["id"]))


def ensure_active_car(guild_id, user_id):
    if get_active_car(guild_id, user_id) is not None:
        return
    cursor.execute("""
    SELECT car_id
    FROM garage
    WHERE guild_id = ? AND user_id = ? AND quantity > 0
    ORDER BY car_id ASC
    LIMIT 1
    """, (guild_id, user_id))
    row = cursor.fetchone()
    if row is not None:
        cursor.execute("""
        UPDATE garage
        SET is_active = 1
        WHERE guild_id = ? AND user_id = ? AND car_id = ?
        """, (guild_id, user_id, row[0]))


def market_item_details(item_type, item_id):
    if item_type == "car":
        details = get_car_details(item_id)
        if details is None:
            return None
        return {
            "name": details["name"],
            "rarity": "Veículo",
            "category": "carro",
            "price": details["price"],
        }
    return get_part_details(item_id)


def market_item_label(item_type, item_id, quantity=1):
    details = market_item_details(item_type, item_id)
    if details is None:
        return f"{item_type} #{item_id}"
    unit = "carro" if item_type == "car" else "peça"
    quantity_text = f" ×{quantity}" if quantity > 1 else ""
    return f"{unit} #{item_id} · {details['name']}{quantity_text}"


def add_market_item(guild_id, user_id, item_type, item_id, quantity):
    if item_type == "car":
        cursor.execute("""
        INSERT INTO garage (guild_id, user_id, car_id, quantity, is_active)
        VALUES (?, ?, ?, ?, 0)
        ON CONFLICT(guild_id, user_id, car_id)
        DO UPDATE SET quantity = garage.quantity + excluded.quantity
        """, (guild_id, user_id, item_id, quantity))
        ensure_active_car(guild_id, user_id)
        return
    cursor.execute("""
    INSERT INTO inventory (guild_id, user_id, part_id, quantity)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(guild_id, user_id, part_id)
    DO UPDATE SET quantity = inventory.quantity + excluded.quantity
    """, (guild_id, user_id, item_id, quantity))


def expire_market_listings():
    now = int(time.time())
    cursor.execute("BEGIN IMMEDIATE")
    try:
        cursor.execute("""
        SELECT listing_id, guild_id, seller_id, item_type, item_id, quantity
        FROM market_listings
        WHERE status = 'active' AND expires_at <= ?
        """, (now,))
        expired = cursor.fetchall()
        for listing_id, guild_id, seller_id, item_type, item_id, quantity in expired:
            add_market_item(guild_id, seller_id, item_type, item_id, quantity)
            cursor.execute("""
            UPDATE market_listings
            SET status = 'expired'
            WHERE listing_id = ? AND status = 'active'
            """, (listing_id,))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return len(expired)


def create_market_listing(
    guild_id,
    seller_id,
    item_type,
    item_id,
    quantity,
    price,
):
    details = market_item_details(item_type, item_id)
    if details is None:
        return "invalid", None
    if item_type not in {"car", "part"}:
        return "invalid", None
    if price < 1 or quantity < 1 or (item_type == "car" and quantity != 1):
        return "amount", None

    expire_market_listings()
    create_user(guild_id, seller_id)
    cursor.execute("BEGIN IMMEDIATE")
    try:
        if item_type == "car":
            cursor.execute("""
            SELECT quantity, is_active
            FROM garage
            WHERE guild_id = ? AND user_id = ? AND car_id = ? AND quantity >= 1
            """, (guild_id, seller_id, item_id))
            row = cursor.fetchone()
            if row is None:
                db.rollback()
                return "missing", details
            remaining = row[0] - 1
            if remaining:
                cursor.execute("""
                UPDATE garage
                SET quantity = ?
                WHERE guild_id = ? AND user_id = ? AND car_id = ?
                """, (remaining, guild_id, seller_id, item_id))
            else:
                cursor.execute("""
                DELETE FROM garage
                WHERE guild_id = ? AND user_id = ? AND car_id = ?
                """, (guild_id, seller_id, item_id))
                ensure_active_car(guild_id, seller_id)
        else:
            cursor.execute("""
            UPDATE inventory
            SET quantity = quantity - ?
            WHERE guild_id = ? AND user_id = ? AND part_id = ? AND quantity >= ?
            """, (quantity, guild_id, seller_id, item_id, quantity))
            if cursor.rowcount != 1:
                db.rollback()
                return "missing", details
            cursor.execute("""
            DELETE FROM inventory
            WHERE guild_id = ? AND user_id = ? AND part_id = ? AND quantity <= 0
            """, (guild_id, seller_id, item_id))

        now = int(time.time())
        cursor.execute("""
        INSERT INTO market_listings (
            guild_id, seller_id, item_type, item_id, quantity, price,
            created_at, expires_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            guild_id, seller_id, item_type, item_id, quantity, price,
            now, now + MARKET_LISTING_SECONDS,
        ))
        listing_id = cursor.lastrowid
        db.commit()
        return "listed", {
            "listing_id": listing_id,
            "item_type": item_type,
            "item_id": item_id,
            "quantity": quantity,
            **details,
            "price": price,
        }
    except Exception:
        db.rollback()
        raise


def get_market_listings(guild_id, limit=15):
    expire_market_listings()
    cursor.execute("""
    SELECT listing_id, seller_id, item_type, item_id, quantity, price,
           created_at, expires_at
    FROM market_listings
    WHERE guild_id = ? AND status = 'active'
    ORDER BY listing_id DESC
    LIMIT ?
    """, (guild_id, limit))
    rows = cursor.fetchall()
    keys = (
        "listing_id", "seller_id", "item_type", "item_id", "quantity",
        "price", "created_at", "expires_at",
    )
    return [dict(zip(keys, row)) for row in rows]


def buy_market_listing(guild_id, buyer_id, listing_id):
    expire_market_listings()
    create_user(guild_id, buyer_id)
    cursor.execute("BEGIN IMMEDIATE")
    try:
        cursor.execute("""
        SELECT seller_id, item_type, item_id, quantity, price, expires_at
        FROM market_listings
        WHERE listing_id = ? AND guild_id = ? AND status = 'active'
        """, (listing_id, guild_id))
        row = cursor.fetchone()
        if row is None:
            db.rollback()
            return "unavailable", None
        seller_id, item_type, item_id, quantity, price, expires_at = row
        if expires_at <= int(time.time()):
            db.rollback()
            expire_market_listings()
            return "unavailable", None
        if seller_id == buyer_id:
            db.rollback()
            return "self", None
        details = market_item_details(item_type, item_id)
        cursor.execute("""
        UPDATE users
        SET coins = coins - ?
        WHERE guild_id = ? AND user_id = ? AND coins >= ?
        """, (price, guild_id, buyer_id, price))
        if cursor.rowcount != 1:
            coins = cursor.execute(
                "SELECT coins FROM users WHERE guild_id = ? AND user_id = ?",
                (guild_id, buyer_id),
            ).fetchone()[0]
            db.rollback()
            return "funds", {"missing": price - coins, "price": price}
        cursor.execute("""
        UPDATE users
        SET coins = coins + ?
        WHERE guild_id = ? AND user_id = ?
        """, (price, guild_id, seller_id))
        cursor.execute("""
        UPDATE market_listings
        SET status = 'sold', buyer_id = ?, sold_at = ?
        WHERE listing_id = ? AND status = 'active'
        """, (buyer_id, int(time.time()), listing_id))
        if cursor.rowcount != 1:
            db.rollback()
            return "unavailable", None
        add_market_item(guild_id, buyer_id, item_type, item_id, quantity)
        db.commit()
        return "bought", {
            "listing_id": listing_id,
            "seller_id": seller_id,
            "item_type": item_type,
            "item_id": item_id,
            "quantity": quantity,
            **(details or {}),
            "price": price,
        }
    except Exception:
        db.rollback()
        raise


def cancel_market_listing(guild_id, seller_id, listing_id):
    expire_market_listings()
    cursor.execute("BEGIN IMMEDIATE")
    try:
        cursor.execute("""
        SELECT item_type, item_id, quantity
        FROM market_listings
        WHERE listing_id = ? AND guild_id = ? AND seller_id = ? AND status = 'active'
        """, (listing_id, guild_id, seller_id))
        row = cursor.fetchone()
        if row is None:
            db.rollback()
            return "unavailable", None
        item_type, item_id, quantity = row
        cursor.execute("""
        UPDATE market_listings
        SET status = 'cancelled'
        WHERE listing_id = ? AND status = 'active'
        """, (listing_id,))
        if cursor.rowcount != 1:
            db.rollback()
            return "unavailable", None
        add_market_item(guild_id, seller_id, item_type, item_id, quantity)
        db.commit()
        return "cancelled", {
            "listing_id": listing_id,
            "item_type": item_type,
            "item_id": item_id,
            "quantity": quantity,
        }
    except Exception:
        db.rollback()
        raise


def create_trade(guild_id, initiator_id, recipient_id, offered_items, requested_items):
    expire_trades()
    now = int(time.time())
    cursor.execute("""
    SELECT trade_id
    FROM trades
    WHERE guild_id = ?
      AND status = 'pending'
      AND expires_at > ?
      AND (
          initiator_id IN (?, ?) OR recipient_id IN (?, ?)
      )
    LIMIT 1
    """, (
        guild_id,
        now,
        initiator_id,
        recipient_id,
        initiator_id,
        recipient_id,
    ))
    if cursor.fetchone() is not None:
        return None

    cursor.execute("""
    INSERT INTO trades (
        guild_id, initiator_id, recipient_id, offered_items,
        requested_items, status, created_at, expires_at
    )
    VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
    """, (
        guild_id,
        initiator_id,
        recipient_id,
        json.dumps(offered_items),
        json.dumps(requested_items),
        now,
        now + RACE_CHALLENGE_SECONDS,
    ))
    db.commit()
    return cursor.lastrowid


def get_trade(trade_id):
    cursor.execute("""
    SELECT trade_id, guild_id, initiator_id, recipient_id,
           offered_items, requested_items, status, created_at, expires_at
    FROM trades
    WHERE trade_id = ?
    """, (trade_id,))
    row = cursor.fetchone()
    if row is None:
        return None
    keys = (
        "trade_id",
        "guild_id",
        "initiator_id",
        "recipient_id",
        "offered_items",
        "requested_items",
        "status",
        "created_at",
        "expires_at",
    )
    result = dict(zip(keys, row))
    result["offered_items"] = json.loads(result["offered_items"])
    result["requested_items"] = json.loads(result["requested_items"])
    return result


def resolve_trade(trade_id, user_id, accepted):
    expire_trades()
    trade = get_trade(trade_id)
    if trade is None:
        return "error", "Essa troca não existe."
    if trade["status"] != "pending":
        return "error", "Essa troca já foi respondida ou expirou."
    if trade["recipient_id"] != user_id:
        return "error", "Somente a pessoa convidada pode responder esta troca."

    if not accepted:
        cursor.execute("""
        UPDATE trades
        SET status = 'declined'
        WHERE trade_id = ? AND status = 'pending'
        """, (trade_id,))
        db.commit()
        return "declined", trade

    if not has_trade_items(
        trade["guild_id"],
        trade["initiator_id"],
        trade["offered_items"],
    ) or not has_trade_items(
        trade["guild_id"],
        trade["recipient_id"],
        trade["requested_items"],
    ):
        cursor.execute("""
        UPDATE trades
        SET status = 'cancelled'
        WHERE trade_id = ? AND status = 'pending'
        """, (trade_id,))
        db.commit()
        return (
            "error",
            "A troca foi cancelada porque um dos itens não está mais disponível.",
        )

    for item in trade["offered_items"]:
        remove_trade_item(trade["guild_id"], trade["initiator_id"], item)
        add_trade_item(trade["guild_id"], trade["recipient_id"], item)
    for item in trade["requested_items"]:
        remove_trade_item(trade["guild_id"], trade["recipient_id"], item)
        add_trade_item(trade["guild_id"], trade["initiator_id"], item)

    ensure_active_car(trade["guild_id"], trade["initiator_id"])
    ensure_active_car(trade["guild_id"], trade["recipient_id"])
    cursor.execute("""
    UPDATE trades
    SET status = 'completed'
    WHERE trade_id = ? AND status = 'pending'
    """, (trade_id,))
    db.commit()
    return "completed", trade


def format_trade_items(items):
    labels = []
    for item in items:
        if item["type"] == "car":
            label = f"🚗 carro #{item['id']} ({get_car_details(item['id'])['name']})"
        else:
            label = f"🔧 peça #{item['id']} ({PARTS_BY_ID[item['id']][1]})"
        labels.append(label)
    return "\n".join(labels)


def expire_race_challenges():
    cursor.execute("""
    UPDATE race_challenges
    SET status = 'expired'
    WHERE status = 'pending' AND expires_at <= ?
    """, (int(time.time()),))
    db.commit()


def create_race_challenge(guild_id, challenger_id, opponent_id):
    expire_race_challenges()
    now = int(time.time())
    cursor.execute("""
    SELECT challenge_id
    FROM race_challenges
    WHERE guild_id = ?
      AND status = 'pending'
      AND expires_at > ?
      AND (
          challenger_id IN (?, ?) OR opponent_id IN (?, ?)
      )
    LIMIT 1
    """, (
        guild_id,
        now,
        challenger_id,
        opponent_id,
        challenger_id,
        opponent_id,
    ))
    if cursor.fetchone() is not None:
        return None

    cursor.execute("""
    INSERT INTO race_challenges (
        guild_id, challenger_id, opponent_id, status, created_at, expires_at
    )
    VALUES (?, ?, ?, 'pending', ?, ?)
    """, (
        guild_id,
        challenger_id,
        opponent_id,
        now,
        now + RACE_CHALLENGE_SECONDS,
    ))
    db.commit()
    return cursor.lastrowid


def get_race_challenge(challenge_id):
    cursor.execute("""
    SELECT challenge_id, guild_id, challenger_id, opponent_id,
           status, created_at, expires_at
    FROM race_challenges
    WHERE challenge_id = ?
    """, (challenge_id,))
    row = cursor.fetchone()
    if row is None:
        return None

    keys = (
        "challenge_id",
        "guild_id",
        "challenger_id",
        "opponent_id",
        "status",
        "created_at",
        "expires_at",
    )
    return dict(zip(keys, row))


def calculate_race_score(car_id, track_weights, weather_weights):
    details = get_car_details(car_id)
    attributes = details["attributes"]
    track_score = sum(
        attributes.get(attribute, 0) * weight
        for attribute, weight in track_weights.items()
    )
    weather_score = sum(
        attributes.get(attribute, 0) * weight
        for attribute, weight in weather_weights.items()
    )
    dice_roll = random.randint(1, 20)
    total = track_score + weather_score + dice_roll
    return {
        "base": round(track_score + weather_score, 1),
        "roll": dice_roll,
        "total": round(total, 1),
    }


def resolve_race_challenge(challenge_id, user_id, accepted):
    expire_race_challenges()
    challenge = get_race_challenge(challenge_id)
    if challenge is None:
        return "error", "Esse racha não existe."
    if challenge["status"] != "pending":
        return "error", "Esse racha já foi respondido ou expirou."
    if challenge["opponent_id"] != user_id:
        return "error", "Somente a pessoa desafiada pode responder este racha."

    if not accepted:
        cursor.execute("""
        UPDATE race_challenges
        SET status = 'declined'
        WHERE challenge_id = ? AND status = 'pending'
        """, (challenge_id,))
        db.commit()
        return "declined", challenge

    challenger_car = get_active_car(
        challenge["guild_id"],
        challenge["challenger_id"],
    )
    opponent_car = get_active_car(
        challenge["guild_id"],
        challenge["opponent_id"],
    )
    if challenger_car is None or opponent_car is None:
        cursor.execute("""
        UPDATE race_challenges
        SET status = 'cancelled'
        WHERE challenge_id = ? AND status = 'pending'
        """, (challenge_id,))
        db.commit()
        return (
            "error",
            "O racha foi cancelado: os dois participantes precisam ter "
            "um carro ativo na garagem.",
        )

    track_name, track_weights = random.choice(RACE_TRACKS)
    weather_name, weather_weights = random.choice(RACE_WEATHERS)
    challenger_car_id = next(
        car_id for car_id, car in CARS_BY_ID.items() if car == challenger_car
    )
    opponent_car_id = next(
        car_id for car_id, car in CARS_BY_ID.items() if car == opponent_car
    )
    challenger_score = calculate_race_score(
        challenger_car_id,
        track_weights,
        weather_weights,
    )
    opponent_score = calculate_race_score(
        opponent_car_id,
        track_weights,
        weather_weights,
    )

    cursor.execute("""
    UPDATE race_challenges
    SET status = 'completed'
    WHERE challenge_id = ? AND status = 'pending'
    """, (challenge_id,))
    db.commit()

    if challenger_score["total"] > opponent_score["total"]:
        winner_id = challenge["challenger_id"]
    elif opponent_score["total"] > challenger_score["total"]:
        winner_id = challenge["opponent_id"]
    else:
        winner_id = None

    result = {
        **challenge,
        "track": track_name,
        "weather": weather_name,
        "challenger_car_id": challenger_car_id,
        "opponent_car_id": opponent_car_id,
        "challenger_score": challenger_score,
        "opponent_score": opponent_score,
        "winner_id": winner_id,
    }
    record_race_stats(result)

    return "completed", result


def race_embed(result, guild):
    challenger = guild.get_member(result["challenger_id"])
    opponent = guild.get_member(result["opponent_id"])
    challenger_name = challenger.mention if challenger else f"<@{result['challenger_id']}>"
    opponent_name = opponent.mention if opponent else f"<@{result['opponent_id']}>"
    challenger_car = get_car_details(result["challenger_car_id"])
    opponent_car = get_car_details(result["opponent_car_id"])
    winner_id = result["winner_id"]

    if winner_id is None:
        title = "🏁 Racha empatado!"
        color = discord.Color.gold()
        outcome = "Os dois chegaram praticamente juntos."
    else:
        winner_name = challenger_name if winner_id == result["challenger_id"] else opponent_name
        title = f"🏆 {winner_name} venceu o racha!"
        color = discord.Color.green()
        outcome = "O resultado combinou os atributos dos carros, as condições e o dado."

    embed = discord.Embed(
        title=title,
        description=outcome,
        color=color,
    )
    embed.add_field(
        name="Condições da corrida",
        value=(
            f"**Pista:** {result['track']}\n"
            f"**Clima:** {result['weather']}\n"
            "Cada piloto recebeu um dado **D20**."
        ),
        inline=False,
    )
    embed.add_field(
        name=f"🚗 {challenger_name} · {challenger_car['name']}",
        value=(
            f"Atributos + condições: **{result['challenger_score']['base']}**\n"
            f"Dado: **{result['challenger_score']['roll']}**\n"
            f"Total: **{result['challenger_score']['total']}**"
        ),
        inline=True,
    )
    embed.add_field(
        name=f"🚗 {opponent_name} · {opponent_car['name']}",
        value=(
            f"Atributos + condições: **{result['opponent_score']['base']}**\n"
            f"Dado: **{result['opponent_score']['roll']}**\n"
            f"Total: **{result['opponent_score']['total']}**"
        ),
        inline=True,
    )
    embed.set_footer(text=f"Racha #{result['challenge_id']}")
    return embed


class RaceChallengeView(discord.ui.View):
    def __init__(self, challenge_id, opponent_id):
        super().__init__(timeout=RACE_CHALLENGE_SECONDS)
        self.challenge_id = challenge_id
        self.opponent_id = opponent_id
        self.message = None

    async def finish_interaction(self, interaction, accepted):
        if interaction.user.id != self.opponent_id:
            await interaction.response.send_message(
                "Essa opção só pode ser usada pela pessoa desafiada.",
                ephemeral=True,
            )
            return

        result_type, result = resolve_race_challenge(
            self.challenge_id,
            interaction.user.id,
            accepted,
        )
        if result_type == "error":
            await interaction.response.send_message(result, ephemeral=True)
            return

        if result_type == "declined":
            await interaction.response.edit_message(
                content=f"❌ <@{self.opponent_id}> recusou o racha #{self.challenge_id}.",
                embed=None,
                view=None,
            )
            self.stop()
            return

        await interaction.response.edit_message(
            content="",
            embed=race_embed(result, interaction.guild),
            view=None,
        )
        self.stop()

    @discord.ui.button(
        label="Aceitar racha",
        style=discord.ButtonStyle.success,
        emoji="🏁",
    )
    async def accept_button(self, interaction, _button):
        await self.finish_interaction(interaction, accepted=True)

    @discord.ui.button(
        label="Recusar",
        style=discord.ButtonStyle.danger,
        emoji="✖️",
    )
    async def decline_button(self, interaction, _button):
        await self.finish_interaction(interaction, accepted=False)

    async def on_timeout(self):
        expire_race_challenges()
        if self.message is None:
            return

        challenge = get_race_challenge(self.challenge_id)
        if challenge and challenge["status"] == "pending":
            for child in self.children:
                child.disabled = True
            try:
                await self.message.edit(
                    content=f"⌛ O racha #{self.challenge_id} expirou.",
                    view=self,
                )
            except discord.HTTPException:
                pass


def trade_embed(trade, guild):
    initiator = guild.get_member(trade["initiator_id"])
    recipient = guild.get_member(trade["recipient_id"])
    initiator_name = initiator.mention if initiator else f"<@{trade['initiator_id']}>"
    recipient_name = recipient.mention if recipient else f"<@{trade['recipient_id']}>"

    embed = discord.Embed(
        title=f"🤝 Troca #{trade['trade_id']}",
        description=(
            f"{initiator_name} propôs uma troca para {recipient_name}.\n"
            "A oferta expira em 90 segundos."
        ),
        color=discord.Color.purple(),
    )
    embed.add_field(
        name=f"{initiator_name} oferece",
        value=format_trade_items(trade["offered_items"]),
        inline=True,
    )
    embed.add_field(
        name=f"{initiator_name} receberá",
        value=format_trade_items(trade["requested_items"]),
        inline=True,
    )
    embed.set_footer(text="Somente a pessoa convidada pode aceitar ou recusar.")
    return embed


class TradeView(discord.ui.View):
    def __init__(self, trade_id, recipient_id):
        super().__init__(timeout=RACE_CHALLENGE_SECONDS)
        self.trade_id = trade_id
        self.recipient_id = recipient_id
        self.message = None

    async def finish_interaction(self, interaction, accepted):
        if interaction.user.id != self.recipient_id:
            await interaction.response.send_message(
                "Essa opção só pode ser usada pela pessoa convidada.",
                ephemeral=True,
            )
            return

        result_type, result = resolve_trade(
            self.trade_id,
            interaction.user.id,
            accepted,
        )
        if result_type == "error":
            await interaction.response.send_message(result, ephemeral=True)
            return
        if result_type == "declined":
            await interaction.response.edit_message(
                content=f"❌ <@{self.recipient_id}> recusou a troca #{self.trade_id}.",
                embed=None,
                view=None,
            )
            self.stop()
            return

        await interaction.response.edit_message(
            content="✅ Troca concluída.",
            embed=trade_embed(result, interaction.guild),
            view=None,
        )
        self.stop()

    @discord.ui.button(
        label="Aceitar troca",
        style=discord.ButtonStyle.success,
        emoji="🤝",
    )
    async def accept_button(self, interaction, _button):
        await self.finish_interaction(interaction, accepted=True)

    @discord.ui.button(
        label="Recusar",
        style=discord.ButtonStyle.danger,
        emoji="✖️",
    )
    async def decline_button(self, interaction, _button):
        await self.finish_interaction(interaction, accepted=False)

    async def on_timeout(self):
        expire_trades()
        if self.message is None:
            return

        trade = get_trade(self.trade_id)
        if trade and trade["status"] == "pending":
            for child in self.children:
                child.disabled = True
            try:
                await self.message.edit(
                    content=f"⌛ A troca #{self.trade_id} expirou.",
                    view=self,
                )
            except discord.HTTPException:
                pass


def job_offer_embed(offer):
    rarity = offer["rarity_info"]
    job = JOB_BY_KEY.get(offer["job_key"], {})
    bonus_text = (
        f"{format_money(offer['bonus_min'])}–{format_money(offer['bonus_max'])} LC "
        f"({offer['bonus_chance'] * 100:.0f}% de chance)"
    )
    embed = discord.Embed(
        title="💼 OFERTA DE EMPREGO",
        description=(
            "Aceite a oferta para iniciar o trabalho. "
            "O pagamento só acontece ao concluir."
            + (
                "\n🏛️ Como político, escolha entre trabalho normal ou corrupção."
                if job.get("political")
                else ""
            )
        ),
        color=discord.Color.green(),
    )
    embed.add_field(name="🏢 Empresa", value=offer["company"], inline=True)
    embed.add_field(name="💼 Cargo", value=offer["title"], inline=True)
    embed.add_field(
        name="⭐ Raridade",
        value=f"{rarity['emoji']} {rarity['label']}"
        + (" · 🔒 secreto" if job.get("secret") else ""),
        inline=True,
    )
    embed.add_field(
        name="💰 Pagamento",
        value=f"{format_money(offer['payment'])} LC",
        inline=True,
    )
    embed.add_field(name="⭐ XP", value=f"+{offer['xp']}", inline=True)
    embed.add_field(
        name="⏱️ Duração",
        value=format_duration(offer["duration_seconds"]),
        inline=True,
    )
    embed.add_field(name="🎁 Bônus possível", value=bonus_text, inline=False)
    embed.set_footer(
        text=(
            f"Oferta #{offer['offer_id']} · válida por "
            f"{format_duration(JOB_OFFER_VALID_SECONDS)}"
        )
    )
    return embed


def job_completed_embed(completion):
    job = JOB_BY_KEY.get(completion["job_key"], {})
    if completion.get("outcome") == "corruption_discovered":
        embed = discord.Embed(
            title="🚨 CORRUPÇÃO DESCOBERTA!",
            description=(
                "O escândalo político foi revelado. Você perdeu o cargo, "
                "recebeu uma multa e foi marcado como procurado."
            ),
            color=discord.Color.red(),
        )
        embed.add_field(
            name="💸 Multa",
            value=f"{format_money(completion['fine'])} LC",
            inline=True,
        )
        embed.add_field(
            name="🚨 Procurado",
            value=f"Nível {completion.get('wanted_after', 0)}/{CRIME_WANTED_MAX_LEVEL}",
            inline=True,
        )
        if completion.get("imprisoned"):
            embed.add_field(name="⛓️ Prisão", value="Aplicada", inline=True)
        embed.add_field(
            name="⭐ XP de trabalho",
            value=f"+{completion['xp']}",
            inline=True,
        )
        return embed
    embed = discord.Embed(
        title="✅ EMPREGO CONCLUÍDO!",
        description=f"Você concluiu o cargo **{job.get('title', completion['job_key'])}**.",
        color=discord.Color.green(),
    )
    embed.add_field(
        name="💰 Pagamento",
        value=f"{format_money(completion['payment'])} LC",
        inline=True,
    )
    embed.add_field(
        name="🎁 Bônus",
        value=f"{format_money(completion['bonus'])} LC",
        inline=True,
    )
    embed.add_field(
        name="💵 Total recebido",
        value=f"{format_money(completion['total_paid'])} LC",
        inline=True,
    )
    if completion.get("tax_paid"):
        embed.add_field(
            name="🏛️ Imposto",
            value=f"{format_money(completion['tax_paid'])} LC ao Tesouro",
            inline=True,
        )
    if completion.get("mode") == "corruption":
        embed.add_field(
            name="🏛️ Modalidade",
            value="Corrupção descoberta não ocorreu",
            inline=False,
        )
    embed.add_field(name="⭐ XP de trabalho", value=f"+{completion['xp']}", inline=True)
    return embed


class JobOfferView(discord.ui.View):
    def __init__(self, offer_id, user_id):
        super().__init__(timeout=JOB_OFFER_VALID_SECONDS)
        self.offer_id = offer_id
        self.user_id = user_id
        self.message = None
        offer = get_job_offer(offer_id)
        if offer and JOB_BY_KEY.get(offer["job_key"], {}).get("political"):
            self.accept_button.label = "Trabalho normal"
            corruption_button = discord.ui.Button(
                label="Corrupção",
                style=discord.ButtonStyle.danger,
                emoji="🔴",
            )
            corruption_button.callback = self.accept_corruption
            self.add_item(corruption_button)

    async def accept_corruption(self, interaction):
        await self.finish_interaction(interaction, accepted=True, mode="corruption")

    async def finish_interaction(self, interaction, accepted, mode="normal"):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Essa oferta pertence a outro piloto.",
                ephemeral=True,
            )
            return

        if accepted:
            result_type, result = accept_job(
                interaction.guild.id,
                interaction.user.id,
                self.offer_id,
                mode=mode,
            )
            if result_type == "error":
                await interaction.response.send_message(result, ephemeral=True)
                return
            await interaction.response.edit_message(
                content=(
                    f"✅ {interaction.user.mention} aceitou o emprego. "
                    f"Volte em {format_duration(result['duration_seconds'])}."
                ),
                embed=job_offer_embed(result),
                view=None,
            )
        else:
            if not reject_job(
                interaction.guild.id,
                interaction.user.id,
                self.offer_id,
            ):
                await interaction.response.send_message(
                    "Essa oferta já foi respondida ou expirou.",
                    ephemeral=True,
                )
                return
            await interaction.response.edit_message(
                content="❌ Oferta de emprego recusada.",
                embed=None,
                view=None,
            )
        self.stop()

    @discord.ui.button(
        label="Aceitar emprego",
        style=discord.ButtonStyle.success,
        emoji="✅",
    )
    async def accept_button(self, interaction, _button):
        await self.finish_interaction(interaction, accepted=True)

    @discord.ui.button(
        label="Recusar",
        style=discord.ButtonStyle.danger,
        emoji="✖️",
    )
    async def decline_button(self, interaction, _button):
        await self.finish_interaction(interaction, accepted=False)

    async def on_timeout(self):
        expire_job_offers()
        if self.message is None:
            return
        offer = get_job_offer(self.offer_id)
        if offer and offer["status"] == "pending":
            for child in self.children:
                child.disabled = True
            try:
                await self.message.edit(
                    content=f"⌛ A oferta de emprego #{self.offer_id} expirou.",
                    view=self,
                )
            except discord.HTTPException:
                pass


def crime_preview_embed(preview):
    crime = preview["crime"]
    embed = discord.Embed(
        title=f"{crime['emoji']} {crime['label'].upper()}",
        description=crime["description"],
        color=discord.Color.red(),
    )
    if preview["victim_id"] is not None:
        embed.add_field(
            name="🎯 Alvo",
            value=f"<@{preview['victim_id']}>",
            inline=True,
        )
    if preview["target_car"] is not None:
        car = preview["target_car"]
        embed.add_field(
            name="🚗 Veículo",
            value=f"{car['name']}\nValor: {format_money(car['price'])} LC",
            inline=False,
        )
    elif crime["key"] == "roubar_jogador":
        max_stolen = min(
            int(preview["target_coins"] * crime["victim_loss_percent"]),
            crime["victim_loss_cap"],
        )
        embed.add_field(
            name="💰 Limite do roubo",
            value=f"Até {format_money(max_stolen)} LC",
            inline=True,
        )
    else:
        embed.add_field(
            name="💰 Recompensa possível",
            value=(
                f"{format_money(crime['reward'][0])}–"
                f"{format_money(crime['reward'][1])} LC"
            ),
            inline=True,
        )
    embed.add_field(
        name="🎲 Chance de sucesso",
        value=f"**{preview['chance']:.1f}%**",
        inline=True,
    )
    embed.add_field(
        name="⏱️ Cooldown",
        value=format_duration(crime["cooldown_seconds"]),
        inline=True,
    )
    embed.add_field(
        name="🚨 Risco",
        value=(
            f"Falha: multa de {format_money(crime['fine'][0])}–"
            f"{format_money(crime['fine'][1])} LC\n"
            f"Procurado: +{crime['wanted_on_failure']} nível(is)"
        ),
        inline=False,
    )
    if crime["required_crime_xp"]:
        embed.add_field(
            name="🔑 Requisito",
            value=f"{crime['required_crime_xp']} XP criminal",
            inline=False,
        )
    embed.set_footer(text="A chance usa RNG real e nunca garante 100% de sucesso.")
    return embed


def crime_result_embed(result, guild):
    crime = result["crime"]
    if result["success"]:
        embed = discord.Embed(
            title=f"🟢 {crime['label'].upper()} BEM-SUCEDIDO!",
            color=discord.Color.green(),
        )
        if result["car_transferred"]:
            car_name = result["target_car"]["name"]
            embed.description = (
                f"Você roubou **{car_name}** de <@{result['victim_id']}>!\n"
                "🚗 O veículo foi transferido para sua garagem."
            )
        elif crime["key"] == "roubar_jogador":
            embed.description = (
                f"Você roubou **{format_money(result['reward'])} LC** "
                f"de <@{result['victim_id']}>."
            )
        else:
            embed.description = f"A operação rendeu **{format_money(result['reward'])} LC**."
        if result["reward"]:
            embed.add_field(
                name="💰 Dinheiro ganho",
                value=f"{format_money(result['reward'])} LC",
                inline=True,
            )
    else:
        embed = discord.Embed(
            title="🔴 OPERAÇÃO FRACASSOU!",
            description="🚨 Você foi descoberto!",
            color=discord.Color.red(),
        )
        embed.add_field(
            name="💸 Multa",
            value=f"{format_money(result['fine'])} LC",
            inline=True,
        )
        embed.add_field(
            name="🚨 Procurado",
            value=f"Nível {result['wanted_after']}/{CRIME_WANTED_MAX_LEVEL}",
            inline=True,
        )
        embed.add_field(
            name="⏳ Crimes bloqueados",
            value=format_duration(max(
                0,
                result["crime_blocked_until"] - int(time.time()),
            )),
            inline=True,
        )
        embed.add_field(
            name="💼 Trabalhos bloqueados",
            value=format_duration(max(
                0,
                result["job_blocked_until"] - int(time.time()),
            )),
            inline=True,
        )
        if result["imprisoned"]:
            embed.add_field(
                name="⛓️ Prisão",
                value=format_duration(max(
                    0,
                    result["prison_until"] - int(time.time()),
                )),
                inline=False,
            )
    embed.add_field(
        name="⭐ XP criminal",
        value=f"+{CRIME_XP_SUCCESS if result['success'] else CRIME_XP_FAILURE}",
        inline=True,
    )
    embed.set_footer(
        text=f"Chance calculada: {result['chance']:.1f}% · cooldown persistente"
    )
    return embed


class CrimeConfirmView(discord.ui.View):
    def __init__(self, preview, user_id):
        super().__init__(timeout=CRIME_MENU_TIMEOUT_SECONDS)
        self.preview = preview
        self.user_id = user_id
        self.message = None

    async def execute(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Esse menu pertence a outro piloto.",
                ephemeral=True,
            )
            return
        result_type, result = execute_crime(
            interaction.guild.id,
            interaction.user.id,
            self.preview["crime_key"],
            self.preview["victim_id"],
            self.preview["target_car_id"],
        )
        if result_type == "cooldown":
            await interaction.response.send_message(
                f"Crime bloqueado por {format_duration(result - int(time.time()))}.",
                ephemeral=True,
            )
            return
        if result_type not in {"success", "failure"}:
            await interaction.response.send_message(result, ephemeral=True)
            return

        await interaction.response.edit_message(
            content="",
            embed=crime_result_embed(result, interaction.guild),
            view=None,
        )
        await notify_crime_victim(result, interaction.guild)
        self.stop()

    @discord.ui.button(
        label="Executar crime",
        style=discord.ButtonStyle.danger,
        emoji="🚨",
    )
    async def execute_button(self, interaction, _button):
        await self.execute(interaction)

    @discord.ui.button(
        label="Cancelar",
        style=discord.ButtonStyle.secondary,
        emoji="✖️",
    )
    async def cancel_button(self, interaction, _button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Esse menu pertence a outro piloto.",
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(
            content="❌ Crime cancelado.",
            embed=None,
            view=None,
        )
        self.stop()

    async def on_timeout(self):
        if self.message is not None:
            for child in self.children:
                child.disabled = True
            try:
                await self.message.edit(
                    content="⌛ A confirmação do crime expirou.",
                    view=self,
                )
            except discord.HTTPException:
                pass


class CrimeTypeSelect(discord.ui.Select):
    def __init__(self, parent_view):
        options = [
            discord.SelectOption(
                label=crime["label"],
                value=crime["key"],
                description=crime["description"][:100],
                emoji=crime["emoji"],
            )
            for crime in CRIMES
        ]
        super().__init__(
            placeholder="Escolha um crime...",
            min_values=1,
            max_values=1,
            options=options,
        )
        self.parent_view = parent_view

    async def callback(self, interaction):
        await self.parent_view.select_crime(interaction, self.values[0])


class CrimeMenuView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=CRIME_MENU_TIMEOUT_SECONDS)
        self.user_id = user_id
        self.message = None
        self.add_item(CrimeTypeSelect(self))

    async def select_crime(self, interaction, crime_key):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Esse menu pertence a outro piloto.",
                ephemeral=True,
            )
            return
        crime = CRIME_BY_KEY[crime_key]
        if crime["requires_target"]:
            target_view = CrimeTargetView(
                crime_key,
                self.user_id,
                interaction.guild,
            )
            if not target_view.options:
                await interaction.response.send_message(
                    "Não há alvos elegíveis para esse crime no momento.",
                    ephemeral=True,
                )
                return
            target_view.message = self.message
            await interaction.response.edit_message(
                content="Escolha o alvo do crime:",
                embed=None,
                view=target_view,
            )
            self.stop()
            return

        preview_type, preview = crime_preview(
            interaction.guild.id,
            self.user_id,
            crime_key,
        )
        if preview_type != "ok":
            await interaction.response.send_message(preview, ephemeral=True)
            return
        confirm_view = CrimeConfirmView(preview, self.user_id)
        confirm_view.message = self.message
        await interaction.response.edit_message(
            content="Confira os detalhes antes de executar:",
            embed=crime_preview_embed(preview),
            view=confirm_view,
        )
        self.stop()

    async def on_timeout(self):
        if self.message is not None:
            for child in self.children:
                child.disabled = True
            try:
                await self.message.edit(content="⌛ Menu de crimes expirou.", view=self)
            except discord.HTTPException:
                pass


class CrimeTargetSelect(discord.ui.Select):
    def __init__(self, parent_view, options):
        super().__init__(
            placeholder="Escolha o alvo...",
            min_values=1,
            max_values=1,
            options=options[:25],
        )
        self.parent_view = parent_view

    async def callback(self, interaction):
        await self.parent_view.select_target(interaction, self.values[0])


class CrimeTargetView(discord.ui.View):
    def __init__(self, crime_key, user_id, guild):
        super().__init__(timeout=CRIME_MENU_TIMEOUT_SECONDS)
        self.crime_key = crime_key
        self.user_id = user_id
        self.message = None
        self.options = self.build_options(guild)
        if self.options:
            self.add_item(CrimeTargetSelect(self, self.options))

    def build_options(self, guild):
        crime = CRIME_BY_KEY[self.crime_key]
        options = []
        if crime["requires_car"]:
            rows = get_stealable_cars(
                guild.id,
                excluded_user_id=self.user_id,
            )
            for victim_id, car_id, _quantity, is_active in rows:
                member = guild.get_member(victim_id)
                if member is None or member.bot:
                    continue
                car = get_car_details(car_id)
                active_label = " · ativo" if is_active else ""
                options.append(discord.SelectOption(
                    label=f"{member.display_name[:55]} · {car['name'][:35]}",
                    value=f"{victim_id}:{car_id}",
                    description=f"Carro #{car_id}{active_label}",
                    emoji="🚗",
                ))
        else:
            cursor.execute("""
            SELECT user_id, coins
            FROM users
            WHERE guild_id = ? AND user_id != ? AND coins > 0
            ORDER BY coins DESC
            LIMIT 25
            """, (guild.id, self.user_id))
            for victim_id, coins in cursor.fetchall():
                member = guild.get_member(victim_id)
                if member is None or member.bot:
                    continue
                options.append(discord.SelectOption(
                    label=member.display_name[:100],
                    value=str(victim_id),
                    description=f"Saldo detectado: {format_money(coins)} LC",
                    emoji="💰",
                ))
        return options

    async def select_target(self, interaction, value):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Esse menu pertence a outro piloto.",
                ephemeral=True,
            )
            return
        victim_id = None
        target_car_id = None
        if CRIME_BY_KEY[self.crime_key]["requires_car"]:
            victim_id_text, target_car_text = value.split(":", maxsplit=1)
            victim_id = int(victim_id_text)
            target_car_id = int(target_car_text)
        else:
            victim_id = int(value)
        preview_type, preview = crime_preview(
            interaction.guild.id,
            self.user_id,
            self.crime_key,
            victim_id,
            target_car_id,
        )
        if preview_type != "ok":
            await interaction.response.send_message(preview, ephemeral=True)
            return
        confirm_view = CrimeConfirmView(preview, self.user_id)
        confirm_view.message = self.message
        await interaction.response.edit_message(
            content="Confira os detalhes antes de executar:",
            embed=crime_preview_embed(preview),
            view=confirm_view,
        )
        self.stop()

    async def on_timeout(self):
        if self.message is not None:
            for child in self.children:
                child.disabled = True
            try:
                await self.message.edit(
                    content="⌛ Seleção de alvo expirou.",
                    view=self,
                )
            except discord.HTTPException:
                pass


async def notify_crime_victim(result, guild):
    victim_id = result.get("victim_id")
    if victim_id is None:
        return
    try:
        victim = guild.get_member(victim_id) or await bot.fetch_user(victim_id)
        if result["success"] and result["car_transferred"]:
            embed = discord.Embed(
                title="🚨 SEU CARRO FOI ROUBADO!",
                description=(
                    f"{guild.get_member(result['criminal_id']).mention if guild.get_member(result['criminal_id']) else 'Outro piloto'} "
                    f"roubou **{result['target_car']['name']}** da sua garagem."
                ),
                color=discord.Color.red(),
            )
        elif result["success"]:
            embed = discord.Embed(
                title="🚨 SEU DINHEIRO FOI ROUBADO!",
                description=(
                    f"Um piloto conseguiu roubar **{format_money(result['reward'])} LC** de você."
                ),
                color=discord.Color.red(),
            )
        else:
            embed = discord.Embed(
                title="🛡️ TENTATIVA DE CRIME DETECTADA!",
                description="Uma tentativa de crime contra você foi registrada.",
                color=discord.Color.orange(),
            )
        await victim.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException, AttributeError):
        pass


def get_active_loan(guild_id, user_id):
    cursor.execute("""
    SELECT loan_id, principal, interest_rate, total_due, due_at, created_at, status
    FROM loans
    WHERE guild_id = ? AND user_id = ? AND status = 'active'
    ORDER BY loan_id DESC
    LIMIT 1
    """, (guild_id, user_id))
    row = cursor.fetchone()
    if row is None:
        return None
    keys = ("loan_id", "principal", "interest_rate", "total_due", "due_at", "created_at", "status")
    return dict(zip(keys, row))


def request_loan(guild_id, user_id, principal):
    active = get_active_job(guild_id, user_id)
    if active is None or active["job_key"] != "agiota":
        return "error", "Você precisa estar trabalhando como 🦈 Agiota para emprestar dinheiro."
    if principal < 100 or principal > 10000:
        return "error", "O empréstimo deve ficar entre 100 e 10.000 LC."
    if get_active_loan(guild_id, user_id) is not None:
        return "error", "Você já possui um empréstimo ativo."
    now = int(time.time())
    total_due = principal + round(principal * LOAN_INTEREST_RATE)
    cursor.execute("BEGIN IMMEDIATE")
    try:
        cursor.execute("""
        INSERT INTO loans (
            guild_id, user_id, principal, interest_rate, total_due,
            due_at, created_at, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
        """, (
            guild_id,
            user_id,
            principal,
            LOAN_INTEREST_RATE,
            total_due,
            now + LOAN_DURATION_SECONDS,
            now,
        ))
        cursor.execute("""
        UPDATE users
        SET coins = coins + ?
        WHERE guild_id = ? AND user_id = ?
        """, (principal, guild_id, user_id))
        loan_id = cursor.lastrowid
        db.commit()
        return "ok", {
            "loan_id": loan_id,
            "principal": principal,
            "total_due": total_due,
            "due_at": now + LOAN_DURATION_SECONDS,
        }
    except Exception:
        db.rollback()
        raise


def repay_loan(guild_id, user_id, loan_id):
    try:
        loan_id = int(loan_id)
    except (TypeError, ValueError):
        return "error", "Informe o ID do empréstimo."
    cursor.execute("BEGIN IMMEDIATE")
    try:
        cursor.execute("""
        SELECT total_due
        FROM loans
        WHERE loan_id = ? AND guild_id = ? AND user_id = ? AND status = 'active'
        """, (loan_id, guild_id, user_id))
        row = cursor.fetchone()
        if row is None:
            db.rollback()
            return "error", "Empréstimo ativo não encontrado."
        total_due = row[0]
        cursor.execute("""
        UPDATE users
        SET coins = coins - ?
        WHERE guild_id = ? AND user_id = ? AND coins >= ?
        """, (total_due, guild_id, user_id, total_due))
        if cursor.rowcount != 1:
            db.rollback()
            return "error", f"Você precisa de {format_money(total_due)} LC para pagar."
        cursor.execute("""
        UPDATE loans
        SET status = 'paid', paid_at = ?
        WHERE loan_id = ? AND status = 'active'
        """, (int(time.time()), loan_id))
        if cursor.rowcount != 1:
            db.rollback()
            return "error", "O empréstimo já foi pago."
        db.commit()
        return "paid", total_due
    except Exception:
        db.rollback()
        raise


def set_salary_tax(guild_id, user_id, tax_rate):
    active = get_active_job(guild_id, user_id)
    if active is None or active["job_key"] != "politico":
        return "error", "Somente o político em mandato pode alterar o imposto."
    try:
        tax_rate = float(str(tax_rate).replace(",", "."))
    except (TypeError, ValueError):
        return "error", "Informe uma porcentagem válida entre 0,5 e 15."
    if not MIN_SALARY_TAX_RATE <= tax_rate <= MAX_SALARY_TAX_RATE:
        return "error", "O imposto deve ficar entre 0,5% e 15%."
    now = int(time.time())
    ensure_guild_economy(guild_id)
    cursor.execute("""
    UPDATE guild_economy
    SET salary_tax_rate = ?, updated_at = ?
    WHERE guild_id = ?
    """, (tax_rate, now, guild_id))
    cursor.execute("""
    INSERT INTO treasury_ledger (
        guild_id, source, amount, tax_rate, created_at, details
    )
    VALUES (?, 'political_tax_change', 0, ?, ?, ?)
    """, (
        guild_id,
        tax_rate,
        now,
        f"Imposto alterado pelo político {user_id} para {tax_rate:.2f}%",
    ))
    db.commit()
    return "ok", tax_rate


def get_treasury_status(guild_id):
    ensure_guild_economy(guild_id)
    cursor.execute("""
    SELECT salary_tax_rate, treasury, updated_at
    FROM guild_economy
    WHERE guild_id = ?
    """, (guild_id,))
    return cursor.fetchone()


def is_admin_user(user_id):
    return int(user_id) == ADMIN_ID


async def require_admin(ctx):
    if ctx.guild is None:
        await ctx.send("A administração só pode ser usada dentro de um servidor.")
        return False
    if not is_admin_user(ctx.author.id):
        log_admin_action(
            ctx.guild.id,
            ctx.author.id,
            f"denied:{ctx.command.qualified_name if ctx.command else 'admin'}",
            details="Tentativa de usar administração sem autorização",
        )
        await ctx.send("🚫 Você não tem permissão para usar a administração.")
        return False
    return True


def parse_positive_integer(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def admin_user_summary(guild_id, target_id):
    create_user(guild_id, target_id)
    cursor.execute("""
    SELECT xp, coins, crime_xp, wanted_level, wanted_until,
           crime_blocked_until, job_blocked_until, prison_until
    FROM users
    WHERE guild_id = ? AND user_id = ?
    """, (guild_id, target_id))
    user_row = cursor.fetchone()
    cursor.execute(
        "SELECT COALESCE(SUM(quantity), 0) FROM garage WHERE guild_id = ? AND user_id = ?",
        (guild_id, target_id),
    )
    cars = cursor.fetchone()[0]
    cursor.execute(
        "SELECT COALESCE(SUM(quantity), 0) FROM inventory WHERE guild_id = ? AND user_id = ?",
        (guild_id, target_id),
    )
    parts = cursor.fetchone()[0]
    return user_row, cars, parts


class AdminPanelView(discord.ui.View):
    def __init__(self, admin_id):
        super().__init__(timeout=180)
        self.admin_id = admin_id

    async def guard(self, interaction):
        if interaction.user.id != self.admin_id or not is_admin_user(interaction.user.id):
            await interaction.response.send_message(
                "Este painel pertence somente ao administrador autorizado.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Comandos", style=discord.ButtonStyle.primary, emoji="📖")
    async def commands_button(self, interaction, _button):
        if not await self.guard(interaction):
            return
        log_admin_action(
            interaction.guild.id,
            interaction.user.id,
            "panel_commands",
        )
        await interaction.response.send_message(
            "Use: `!give_money`, `!remove_money`, `!give_xp`, `!remove_xp`, "
            "`!give_car`, `!remove_car`, `!give_item`, `!remove_item`, "
            "`!ban`, `!unban`, `!userinfo`, `!reset_user`.",
            ephemeral=True,
        )

    @discord.ui.button(label="Logs recentes", style=discord.ButtonStyle.secondary, emoji="🧾")
    async def logs_button(self, interaction, _button):
        if not await self.guard(interaction):
            return
        cursor.execute("""
        SELECT action, target_id, amount, item, details, created_at
        FROM admin_logs
        WHERE guild_id = ?
        ORDER BY log_id DESC
        LIMIT 10
        """, (interaction.guild.id,))
        rows = cursor.fetchall()
        lines = [
            f"`{created_at}` · {action}"
            + (f" · alvo {target_id}" if target_id else "")
            + (f" · {amount}" if amount else "")
            + (f" · {item}" if item else "")
            for action, target_id, amount, item, _details, created_at in rows
        ]
        log_admin_action(
            interaction.guild.id,
            interaction.user.id,
            "panel_logs",
        )
        await interaction.response.send_message(
            "\n".join(lines) or "Nenhuma ação administrativa registrada.",
            ephemeral=True,
        )

    @discord.ui.button(label="Fechar", style=discord.ButtonStyle.danger, emoji="✖️")
    async def close_button(self, interaction, _button):
        if not await self.guard(interaction):
            return
        log_admin_action(
            interaction.guild.id,
            interaction.user.id,
            "panel_close",
        )
        await interaction.response.edit_message(
            content="Painel administrativo fechado.",
            embed=None,
            view=None,
        )
        self.stop()


# =========================
# COMANDOS DE EMPREGOS E CRIMES
# =========================

async def send_job_completions(ctx, completions):
    for completion in completions:
        await ctx.send(embed=job_completed_embed(completion))
        try:
            await update_ranks(ctx.author)
        except discord.HTTPException:
            pass


@bot.command(
    name="emprego",
    aliases=["trabalho", "jobs"],
)
async def emprego(ctx):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return

    completions = complete_due_jobs(ctx.guild.id, ctx.author.id)
    if completions:
        await send_job_completions(ctx, completions)

    result_type, result = create_job_offer(ctx.guild.id, ctx.author.id)
    if result_type in {"new", "pending"}:
        view = JobOfferView(result["offer_id"], ctx.author.id)
        message = await ctx.send(
            embed=job_offer_embed(result),
            view=view,
        )
        view.message = message
        return
    if result_type == "active":
        remaining = max(0, result["completion_time"] - int(time.time()))
        await ctx.send(
            f"💼 Você já está trabalhando como **{result['title']}**.\n"
            f"⏱️ Conclusão em aproximadamente **{format_duration(remaining)}**."
        )
        return
    if result_type == "blocked":
        await ctx.send(
            f"🚫 Trabalhos bloqueados por "
            f"**{format_duration(result - int(time.time()))}**."
        )
        return
    await ctx.send(
        f"⏳ Você poderá solicitar uma nova oferta em "
        f"**{format_duration(result - int(time.time()))}**."
    )


async def answer_job_command(ctx, offer_id, accepted, mode="normal"):
    try:
        parsed_offer_id = int(offer_id)
    except (TypeError, ValueError):
        await ctx.send("Informe o ID da oferta. Exemplo: `!aceitar_emprego 12`.")
        return

    if accepted:
        result_type, result = accept_job(
            ctx.guild.id,
            ctx.author.id,
            parsed_offer_id,
            mode=mode,
        )
        if result_type == "error":
            await ctx.send(result)
            return
        await ctx.send(
            f"✅ Você aceitou **{result['title']}**. "
            f"Pagamento em {format_duration(result['duration_seconds'])}.",
            embed=job_offer_embed(result),
        )
        return

    if not reject_job(ctx.guild.id, ctx.author.id, parsed_offer_id):
        await ctx.send("Essa oferta já foi respondida, expirou ou não pertence a você.")
        return
    await ctx.send(f"❌ Oferta de emprego #{parsed_offer_id} recusada.")


@bot.command(
    name="aceitar_emprego",
    aliases=["aceitaremprego", "aceitar_trabalho"],
)
async def aceitar_emprego(ctx, offer_id=None, modo=None):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return
    mode = "corruption" if normalize_text(modo) in {
        "corrupcao",
        "corrupcao",
        "corrupção",
    } else "normal"
    await answer_job_command(ctx, offer_id, accepted=True, mode=mode)


@bot.command(
    name="recusar_emprego",
    aliases=["recusaremprego", "recusar_trabalho"],
)
async def recusar_emprego(ctx, offer_id=None):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return
    await answer_job_command(ctx, offer_id, accepted=False)


def crime_menu_embed(guild_id, user_id):
    status = get_wanted_state(guild_id, user_id)
    wanted_text = (
        f"🚨 Procurado: nível {status['wanted_level']}/{CRIME_WANTED_MAX_LEVEL}"
        if status["wanted_level"]
        else "✅ Status: não procurado"
    )
    embed = discord.Embed(
        title="🚨 CENTRAL DE CRIMES",
        description=(
            "Escolha uma operação no menu abaixo.\n"
            f"{wanted_text}\n\n"
            "As chances são calculadas com RNG real e nunca são garantidas."
        ),
        color=discord.Color.dark_red(),
    )
    for crime in CRIMES:
        requirement = (
            f" · requer {crime['required_crime_xp']} XP criminal"
            if crime["required_crime_xp"]
            else ""
        )
        embed.add_field(
            name=f"{crime['emoji']} {crime['label']}",
            value=(
                f"Chance base: {crime['base_success']}% · "
                f"cooldown: {format_duration(crime['cooldown_seconds'])}"
                f"{requirement}"
            ),
            inline=False,
        )
    return embed


async def send_crime_flow(ctx, crime_key=None, target=None):
    if crime_key is None:
        view = CrimeMenuView(ctx.author.id)
        message = await ctx.send(
            embed=crime_menu_embed(ctx.guild.id, ctx.author.id),
            view=view,
        )
        view.message = message
        return

    crime = CRIME_BY_KEY.get(crime_key)
    if crime is None:
        await ctx.send(
            "Crime inválido. Use `!crime` para abrir o menu ou escolha: "
            "`carro`, `jogador`, `loja`, `carga` ou `banco`."
        )
        return
    if target is not None and not crime["requires_target"]:
        await ctx.send("Esse crime não usa um jogador como alvo.")
        return
    if target is not None and target.bot:
        await ctx.send("Você só pode escolher outro jogador como alvo.")
        return

    if crime["requires_target"] and target is None:
        view = CrimeTargetView(crime_key, ctx.author.id, ctx.guild)
        if not view.options:
            await ctx.send("Não há alvos elegíveis para esse crime no momento.")
            return
        message = await ctx.send(
            content="Escolha o alvo do crime:",
            view=view,
        )
        view.message = message
        return

    target_car_id = None
    if crime["requires_car"]:
        target_cars = get_stealable_cars(
            ctx.guild.id,
            excluded_user_id=ctx.author.id,
            target_user_id=target.id,
        )
        if not target_cars:
            await ctx.send("Esse jogador não possui carro disponível para roubo.")
            return
        target_car_id = target_cars[0][1]

    preview_type, preview = crime_preview(
        ctx.guild.id,
        ctx.author.id,
        crime_key,
        target.id if target else None,
        target_car_id,
    )
    if preview_type != "ok":
        await ctx.send(preview)
        return
    view = CrimeConfirmView(preview, ctx.author.id)
    message = await ctx.send(
        content="Confira os detalhes antes de executar:",
        embed=crime_preview_embed(preview),
        view=view,
    )
    view.message = message


@bot.command(
    name="crime",
    aliases=["crimes", "criminalidade"],
)
async def crime(ctx, tipo=None, target: discord.Member = None):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return
    await send_crime_flow(ctx, get_crime_key(tipo) if tipo else None, target)


@bot.command(
    name="executar_crime",
    aliases=["executarcrime", "crime_exec"],
)
async def executar_crime(ctx, tipo=None, target: discord.Member = None):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return
    if not tipo:
        await ctx.send(
            "Use `!executar_crime banco` ou abra o menu com `!crime`."
        )
        return
    await send_crime_flow(ctx, get_crime_key(tipo), target)


@bot.command(
    name="procurado",
    aliases=["wanted", "status_criminal"],
)
async def procurado(ctx):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return
    status = get_wanted_state(ctx.guild.id, ctx.author.id)
    now = int(time.time())
    embed = discord.Embed(
        title=f"🚨 Status criminal de {ctx.author.display_name}",
        color=discord.Color.red() if status["wanted_level"] else discord.Color.green(),
    )
    embed.add_field(
        name="Nível de procurado",
        value=f"{status['wanted_level']}/{CRIME_WANTED_MAX_LEVEL}",
        inline=True,
    )
    embed.add_field(
        name="Duração do status",
        value=(
            format_duration(status["wanted_until"] - now)
            if status["wanted_until"] > now
            else "Normal"
        ),
        inline=True,
    )
    crime_lock = max(status["crime_blocked_until"], status["prison_until"])
    job_lock = max(status["job_blocked_until"], status["prison_until"])
    embed.add_field(
        name="Crimes",
        value=(
            f"Bloqueados por {format_duration(crime_lock - now)}"
            if crime_lock > now
            else "Liberados"
        ),
        inline=False,
    )
    embed.add_field(
        name="Trabalhos",
        value=(
            f"Bloqueados por {format_duration(job_lock - now)}"
            if job_lock > now
            else "Liberados"
        ),
        inline=False,
    )
    if status["prison_until"] > now:
        embed.add_field(
            name="⛓️ Prisão",
            value=f"Libertação em {format_duration(status['prison_until'] - now)}",
            inline=False,
        )
    await ctx.send(embed=embed)


@bot.command(
    name="historico",
    aliases=["history", "histórico"],
)
async def historico(ctx):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return
    complete_due_jobs(ctx.guild.id, ctx.author.id)
    job_rows = get_recent_job_history(ctx.guild.id, ctx.author.id)
    crime_rows = get_recent_crime_history(ctx.guild.id, ctx.author.id)
    embed = discord.Embed(
        title=f"📊 Histórico de {ctx.author.display_name}",
        color=discord.Color.blurple(),
    )
    job_lines = []
    for row in job_rows:
        (
            job_key,
            payment,
            bonus,
            total_paid,
            xp_amount,
            _completed_at,
            gross_payment,
            tax_paid,
            mode,
            outcome,
            fine,
        ) = row
        job = JOB_BY_KEY.get(job_key, {"title": job_key})
        if outcome == "corruption_discovered":
            job_lines.append(
                f"🚨 {job['title']} · corrupção descoberta · "
                f"multa {format_money(fine)} LC"
            )
            continue
        job_lines.append(
            f"💼 {job['title']} · +{format_money(total_paid)} LC · +{xp_amount} XP"
            + (f" · bônus {format_money(bonus)}" if bonus else "")
            + (f" · imposto {format_money(tax_paid)}" if tax_paid else "")
            + (" · corrupção" if mode == "corruption" else "")
        )
    crime_lines = []
    for (
        crime_key,
        success,
        reward,
        fine,
        wanted_after,
        imprisoned,
        _created_at,
        details,
    ) in crime_rows:
        label = CRIME_BY_KEY.get(crime_key, {"label": crime_key})["label"]
        marker = "🟢" if success else "🔴"
        money_text = (
            f"+{format_money(reward)} LC"
            if success and reward
            else f"-{format_money(fine)} LC"
        )
        prison_text = " · prisão" if imprisoned else ""
        crime_lines.append(
            f"{marker} {label} · {money_text} · procurado {wanted_after}/"
            f"{CRIME_WANTED_MAX_LEVEL}{prison_text}"
            + (f"\n  {details}" if details else "")
        )
    embed.add_field(
        name="💼 Empregos realizados",
        value="\n".join(job_lines) or "Nenhum emprego concluído ainda.",
        inline=False,
    )
    embed.add_field(
        name="🚨 Crimes realizados",
        value="\n".join(crime_lines) or "Nenhum crime registrado ainda.",
        inline=False,
    )
    investment_rows = get_investment_transactions(ctx.guild.id, ctx.author.id, limit=5)
    investment_lines = []
    for asset_key, action, amount, value, _created_at in investment_rows:
        asset = INVESTMENT_ASSETS[asset_key]
        marker = "🟢 compra" if action == "buy" else "🔵 venda"
        investment_lines.append(
            f"{marker} {asset['title']} · {format_money(value)} LC"
        )
    embed.add_field(
        name="📈 Investimentos",
        value="\n".join(investment_lines) or "Nenhuma movimentação de investimento.",
        inline=False,
    )
    await ctx.send(embed=embed)


def portfolio_embed(guild_id, user_id, display_name):
    positions = get_investment_positions(guild_id, user_id)
    embed = discord.Embed(
        title=f"📈 Carteira de {display_name}",
        description="Os valores são atualizados por RNG; lucro nunca é garantido.",
        color=discord.Color.teal(),
    )
    total_invested = 0
    total_current = 0
    for position in positions:
        asset = INVESTMENT_ASSETS[position["asset_key"]]
        profit = position["current_value"] - position["invested_amount"]
        marker = "📈" if profit >= 0 else "📉"
        embed.add_field(
            name=f"{asset['title']} {marker}",
            value=(
                f"Investido: **{format_money(position['invested_amount'])} LC**\n"
                f"Valor atual: **{format_money(position['current_value'])} LC**\n"
                f"{'Lucro' if profit >= 0 else 'Prejuízo'}: "
                f"**{'+' if profit >= 0 else ''}{format_money(profit)} LC**\n"
                f"Volatilidade: **±{position['volatility'] * 100:.1f}%**"
            ),
            inline=False,
        )
        total_invested += position["invested_amount"]
        total_current += position["current_value"]
    embed.add_field(
        name="Total da carteira",
        value=(
            f"Investido: **{format_money(total_invested)} LC**\n"
            f"Atual: **{format_money(total_current)} LC**\n"
            f"Resultado: **{'+' if total_current >= total_invested else ''}"
            f"{format_money(total_current - total_invested)} LC**"
        ),
        inline=False,
    )
    if not positions:
        embed.description += "\nSua carteira ainda está vazia."
    return embed


@bot.command(name="saldo", aliases=["balance"])
async def saldo(ctx):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return
    _xp_value, coins = get_user(ctx.guild.id, ctx.author.id)
    positions = get_investment_positions(ctx.guild.id, ctx.author.id)
    invested = sum(position["current_value"] for position in positions)
    await ctx.send(
        f"💳 **Saldo disponível:** {format_money(coins)} LC\n"
        f"📈 **Dinheiro investido:** {format_money(invested)} LC\n"
        f"💰 **Patrimônio total:** {format_money(coins + invested)} LC"
    )


@bot.command(name="carteira", aliases=["portfolio"])
async def carteira(ctx):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return
    await ctx.send(
        embed=portfolio_embed(
            ctx.guild.id,
            ctx.author.id,
            ctx.author.display_name,
        )
    )


@bot.command(name="investimentos", aliases=["investimento", "investir"])
async def investimentos(ctx, acao=None, ativo=None, valor=None):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return
    normalized_action = normalize_text(acao)
    if normalized_action in {"comprar", "buy"}:
        asset_key = resolve_investment_asset(ativo)
        amount = parse_positive_integer(valor)
        if asset_key is None or amount is None:
            await ctx.send("Use `!investimentos comprar açoes 1000`.")
            return
        result_type, result = buy_investment(
            ctx.guild.id,
            ctx.author.id,
            asset_key,
            amount,
        )
        if result_type == "error":
            await ctx.send(result)
            return
        await ctx.send(
            f"✅ Você investiu **{format_money(result)} LC** em "
            f"**{INVESTMENT_ASSETS[asset_key]['title']}**."
        )
        return
    if normalized_action in {"vender", "sell"}:
        asset_key = resolve_investment_asset(ativo)
        amount = parse_positive_integer(valor) if valor else None
        if asset_key is None or (valor and amount is None):
            await ctx.send("Use `!investimentos vender açoes [valor opcional]`.")
            return
        result_type, result = sell_investment(
            ctx.guild.id,
            ctx.author.id,
            asset_key,
            amount,
        )
        if result_type == "error":
            await ctx.send(result)
            return
        await ctx.send(
            f"✅ Venda concluída por **{format_money(result['received'])} LC**. "
            f"Resultado: **{'+' if result['profit'] >= 0 else ''}"
            f"{format_money(result['profit'])} LC**."
        )
        return
    await ctx.send(embed=portfolio_embed(ctx.guild.id, ctx.author.id, ctx.author.display_name))


@tasks.loop(seconds=JOB_POLL_SECONDS)
async def job_completion_loop():
    completions = complete_due_jobs()
    for completion in completions:
        guild = bot.get_guild(completion["guild_id"])
        if guild is None:
            continue
        member = guild.get_member(completion["user_id"])
        if member is None:
            continue
        try:
            await member.send(embed=job_completed_embed(completion))
            await update_ranks(member)
        except (discord.Forbidden, discord.HTTPException):
            pass


@job_completion_loop.before_loop
async def before_job_completion_loop():
    await bot.wait_until_ready()


def event_embed(event):
    scope_text = (
        f"para <@{event['user_id']}>"
        if event.get("scope") in {"individual", "targeted"} and event.get("user_id")
        else "global"
    )
    effects = event.get("effects", {})
    details = []
    if effects.get("awarded_coins"):
        details.append(f"Prêmio imediato: **{format_money(effects['awarded_coins'])} LC**")
    if effects.get("salary_multiplier", 1) != 1:
        details.append(f"Salários: ×{effects['salary_multiplier']:.2f}")
    if effects.get("crime_reward_multiplier", 1) != 1:
        details.append(f"Crimes: ×{effects['crime_reward_multiplier']:.2f}")
    if effects.get("price_multiplier", 1) != 1:
        details.append(f"Carros: ×{effects['price_multiplier']:.2f}")
    if effects.get("part_price_multiplier", 1) != 1:
        details.append(f"Peças: ×{effects['part_price_multiplier']:.2f}")
    if effects.get("tax_rate") is not None:
        details.append(f"Imposto temporário: {effects['tax_rate']:.1f}%")
    embed = discord.Embed(
        title=f"🌎 EVENTO VALKYRIE · {event['title']}",
        description=f"{event['description']}\n\nEscopo: **{scope_text}**",
        color=discord.Color.gold(),
    )
    if details:
        embed.add_field(name="Efeitos", value="\n".join(details), inline=False)
    embed.set_footer(text=f"Evento #{event['event_id']} · dura aproximadamente 24h")
    return embed


def news_embed(news):
    embed = discord.Embed(
        title="📰 Jornal Valkyrie · NOTÍCIA FICTÍCIA",
        description=f"**{news['headline']}**\n\n{news['body']}",
        color=discord.Color.orange(),
    )
    embed.add_field(
        name="Referência",
        value=news["reference"],
        inline=False,
    )
    embed.set_footer(
        text="Sátira e ficção: não é uma notícia real nem fonte jornalística."
    )
    return embed


def maybe_generate_news(guild_id, force=False):
    now = int(time.time())
    cursor.execute("BEGIN IMMEDIATE")
    try:
        cursor.execute("""
        SELECT next_post_at
        FROM news_cycles
        WHERE guild_id = ?
        """, (guild_id,))
        cycle = cursor.fetchone()
        if not force and cycle is not None and cycle[0] > now:
            db.rollback()
            return None

        story = random.choice(NEWS_STORIES)
        cursor.execute("""
        INSERT INTO news (guild_id, headline, body, reference, created_at)
        VALUES (?, ?, ?, ?, ?)
        """, (
            guild_id,
            story["headline"],
            story["body"],
            story["reference"],
            now,
        ))
        news_id = cursor.lastrowid
        next_post_at = now + random.randint(
            NEWS_MIN_INTERVAL_SECONDS,
            NEWS_MAX_INTERVAL_SECONDS,
        )
        cursor.execute("""
        INSERT INTO news_cycles (guild_id, last_posted_at, next_post_at)
        VALUES (?, ?, ?)
        ON CONFLICT(guild_id)
        DO UPDATE SET
            last_posted_at = excluded.last_posted_at,
            next_post_at = excluded.next_post_at
        """, (guild_id, now, next_post_at))
        db.commit()
        return {
            "news_id": news_id,
            "guild_id": guild_id,
            **story,
            "created_at": now,
        }
    except Exception:
        db.rollback()
        raise


def get_recent_news(guild_id, limit=5):
    cursor.execute("""
    SELECT news_id, headline, body, reference, created_at
    FROM news
    WHERE guild_id = ?
    ORDER BY news_id DESC
    LIMIT ?
    """, (guild_id, limit))
    keys = ("news_id", "headline", "body", "reference", "created_at")
    return [dict(zip(keys, row)) for row in cursor.fetchall()]


def announcement_channel(guild):
    me = guild.me
    if guild.system_channel is not None:
        permissions = (
            guild.system_channel.permissions_for(me)
            if me is not None
            else None
        )
        if permissions is None or permissions.send_messages:
            return guild.system_channel
    for candidate in guild.text_channels:
        permissions = candidate.permissions_for(me) if me is not None else None
        if permissions is None or permissions.send_messages:
            return candidate
    return None


async def announce_event(event):
    guild = bot.get_guild(event["guild_id"])
    if guild is None:
        return
    embed = event_embed(event)
    if event.get("scope") == "individual" and event.get("user_id"):
        member = guild.get_member(event["user_id"])
        if member is not None:
            try:
                await member.send(embed=embed)
                return
            except (discord.Forbidden, discord.HTTPException):
                pass
    channel = announcement_channel(guild)
    if channel is not None:
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            pass


@tasks.loop(seconds=EVENT_POLL_SECONDS)
async def event_loop():
    cursor.execute("SELECT DISTINCT guild_id FROM users")
    guild_ids = [row[0] for row in cursor.fetchall()]
    for guild_id in guild_ids:
        event = maybe_generate_event(guild_id)
        if event is not None:
            await announce_event(event)


@event_loop.before_loop
async def before_event_loop():
    await bot.wait_until_ready()


async def announce_news(news):
    guild = bot.get_guild(news["guild_id"])
    if guild is None:
        return
    channel = announcement_channel(guild)
    if channel is None:
        return
    try:
        await channel.send(
            embed=news_embed(news),
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except (discord.Forbidden, discord.HTTPException, AttributeError):
        pass


@tasks.loop(seconds=NEWS_POLL_SECONDS)
async def news_loop():
    cursor.execute("SELECT DISTINCT guild_id FROM users")
    guild_ids = [row[0] for row in cursor.fetchall()]
    for guild_id in guild_ids:
        news = maybe_generate_news(guild_id)
        if news is not None:
            await announce_news(news)


@news_loop.before_loop
async def before_news_loop():
    await bot.wait_until_ready()


def get_rank_name(xp_value):
    current_rank = "Novato"
    for required_xp, role_name in RANKS:
        if xp_value >= required_xp:
            current_rank = role_name
    return current_rank


# =========================
# CRIAR CARGO DE PATENTE
# =========================

async def create_rank_role(guild, role_name):
    role = discord.utils.get(guild.roles, name=role_name)

    if role:
        return role

    try:
        role = await guild.create_role(
            name=role_name,
            permissions=discord.Permissions.none(),
            hoist=False,
            mentionable=False,
            reason="Valkyrie - Cargo de XP",
        )

        print(f"🏅 Cargo criado: {role_name}")
        return role

    except discord.Forbidden:
        print(f"❌ Sem permissão para criar: {role_name}")
        return None


# =========================
# ATUALIZAR PATENTES
# =========================

async def update_ranks(member):
    xp_value, coins = get_user(
        member.guild.id,
        member.id,
    )

    for required_xp, role_name in RANKS:
        if xp_value < required_xp:
            continue

        role = await create_rank_role(
            member.guild,
            role_name,
        )

        if role is None or role in member.roles:
            continue

        try:
            await member.add_roles(
                role,
                reason=f"Valkyrie - {xp_value} XP",
            )

            print(f"🏅 {member} recebeu {role_name}")

        except discord.Forbidden:
            print(f"❌ Não consegui dar {role_name}")


async def claim_daily_coins(ctx):
    if not claim_daily_reward(ctx.guild.id, ctx.author.id, "coins"):
        await ctx.send(
            f"🪙 {ctx.author.mention}, você já coletou seu daily de Lost Coins hoje. "
            f"Volte em {time_until_next_daily()}."
        )
        return

    amount = random.randint(DAILY_COINS_MIN, DAILY_COINS_MAX)
    add_coins(ctx.guild.id, ctx.author.id, amount)
    await ctx.send(
        f"🪙 {ctx.author.mention}, você recebeu **{amount:,} Lost Coins** no daily!"
        .replace(",", ".")
    )


async def claim_daily_part(ctx):
    if not claim_daily_reward(ctx.guild.id, ctx.author.id, "parts"):
        await ctx.send(
            f"🔧 {ctx.author.mention}, você já coletou seu daily de peças hoje. "
            f"Volte em {time_until_next_daily()}."
        )
        return

    part = choose_daily_part()
    part_id, part_name, _category, rarity, price = part[:5]
    add_part_to_inventory(ctx.guild.id, ctx.author.id, part_id)
    rarity_icon = RARITY_EMOJI.get(rarity, "🔧")
    embed = discord.Embed(
        title=f"{rarity_icon} Daily de peças · {part_name}",
        description=(
            f"{ctx.author.mention}, sua recompensa foi adicionada ao inventário.\n"
            f"Valor de catálogo: **{format_money(price)} LC**"
        ),
        color=discord.Color.orange(),
    )
    embed.set_image(url=await resolve_catalog_image_url("part", part_id))
    await ctx.send(embed=embed)


# =========================
# BOT ONLINE
# =========================

@bot.event
async def on_disconnect():
    print("⚠️ Valkyrie perdeu a conexão; o Discord.py tentará reconectar automaticamente.")


@bot.event
async def on_resumed():
    print("🔄 Valkyrie reconectada ao Discord.")


@bot.event
async def on_ready():
    if not job_completion_loop.is_running():
        job_completion_loop.start()
    if not event_loop.is_running():
        event_loop.start()
    if not news_loop.is_running():
        news_loop.start()
    print("=" * 40)
    print(f"🤖 Valkyrie online como {bot.user}")
    print(f"🏠 Servidores: {len(bot.guilds)}")
    print("=" * 40)


# =========================
# XP POR MENSAGEM
# =========================

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.guild is None:
        return

    guild_id = message.guild.id
    user_id = message.author.id

    create_user(guild_id, user_id)

    now = time.time()
    last_xp = xp_cooldowns.get((guild_id, user_id), 0)

    if now - last_xp >= XP_COOLDOWN:
        amount = random.randint(1, 3)
        add_xp(guild_id, user_id, amount)
        xp_cooldowns[(guild_id, user_id)] = now

        print(f"🆙 {message.author} recebeu {amount} XP")
        await update_ranks(message.author)

    await bot.process_commands(message)


# =========================
# COMANDO !XP
# =========================

@bot.command()
async def xp(ctx):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return

    xp_value, coins = get_user(ctx.guild.id, ctx.author.id)

    await ctx.send(
        f"🆙 {ctx.author.mention}, "
        f"você possui **{xp_value} XP**."
    )


# =========================
# COMANDO !DAILY
# =========================

@bot.command(
    name="daily",
    aliases=["diario", "diaria", "diária", "daily_coins"],
)
async def daily(ctx, categoria=None):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return

    if categoria is None or normalize_text(categoria) in {
        "coin",
        "coins",
        "moeda",
        "moedas",
        "lostcoin",
        "lostcoins",
    }:
        await claim_daily_coins(ctx)
        return

    if normalize_text(categoria) in {
        "peca",
        "pecas",
        "part",
        "parts",
    }:
        await claim_daily_part(ctx)
        return

    await ctx.send(
        "Use `!daily` para Lost Coins ou `!daily peças` para receber uma peça."
    )


@bot.command(
    name="daily_pecas",
    aliases=["dailypecas", "daily_peca", "pecasdaily"],
)
async def daily_pecas(ctx):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return

    await claim_daily_part(ctx)


# =========================
# LOJA E GARAGEM DE CARROS
# =========================

@bot.command(
    name="loja",
    aliases=["loja_carros", "carros"],
)
async def loja(ctx):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return

    shop_date, car_ids, part_ids = get_daily_shop()
    embed = discord.Embed(
        title="🏪 Loja diária Valkyrie",
        description=(
            f"Ofertas de **{shop_date}** · a loja troca à meia-noite "
            "no horário de São Paulo.\n"
            "Use `!comprar carro ID` ou `!comprar peça ID`."
        ),
        color=discord.Color.gold(),
    )
    if car_ids:
        embed.set_thumbnail(
            url=await resolve_catalog_image_url("car", car_ids[0])
        )

    car_lines = []
    for car_id in car_ids:
        details = get_car_details(car_id)
        purchased = has_shop_purchase(
            ctx.guild.id,
            ctx.author.id,
            shop_date,
            "car",
            car_id,
        )
        status = " · **COMPRADO**" if purchased else ""
        car_lines.append(
            f"**#{car_id} · {details['name']}**{status}\n"
            f"💰 {format_money(details['price'])} LC\n"
            f"`{format_car_attributes(car_id, compact=True)}`"
        )
    embed.add_field(
        name="🚗 3 carros em oferta",
        value="\n\n".join(car_lines),
        inline=False,
    )

    part_lines = []
    for part_id in part_ids:
        part = PARTS_BY_ID[part_id]
        purchased = has_shop_purchase(
            ctx.guild.id,
            ctx.author.id,
            shop_date,
            "part",
            part_id,
        )
        status = " · **COMPRADA**" if purchased else ""
        rarity_icon = RARITY_EMOJI.get(part[3], "🔧")
        part_lines.append(
            f"{rarity_icon} **#{part_id} · {part[1]}**{status}\n"
            f"💰 {format_money(part[4])} LC · {part[3]}"
        )
    embed.add_field(
        name="🔧 3 peças em oferta",
        value="\n\n".join(part_lines),
        inline=False,
    )
    embed.set_footer(text="Os atributos completos ficam disponíveis em !carro ID.")

    await ctx.send(embed=embed)


@bot.command(
    name="carro",
    aliases=["detalhes", "carro_info"],
)
async def carro(ctx, car_id=None):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return

    try:
        parsed_car_id = int(car_id)
    except (TypeError, ValueError):
        await ctx.send("Use `!carro ID`. Exemplo: `!carro 1`.")
        return

    details = get_car_details(parsed_car_id)
    if details is None:
        await ctx.send(f"Não encontrei o carro #{parsed_car_id}.")
        return

    quantity = get_car_quantity(ctx.guild.id, ctx.author.id, parsed_car_id)
    active_car = get_active_car(ctx.guild.id, ctx.author.id)
    is_active = active_car == CARS_BY_ID[parsed_car_id]
    status = "Carro ativo" if is_active else (
        f"Você possui ×{quantity}" if quantity else "Ainda não está na sua garagem"
    )

    embed = discord.Embed(
        title=f"🚗 #{parsed_car_id} · {details['name']}",
        color=discord.Color.blue(),
    )
    embed.add_field(
        name="Preço",
        value=f"💰 {format_money(details['price'])} LC",
        inline=True,
    )
    embed.add_field(name="Status", value=status, inline=True)
    embed.add_field(
        name="Atributos",
        value=format_car_attributes(parsed_car_id),
        inline=False,
    )
    embed.set_image(
        url=await resolve_catalog_image_url("car", parsed_car_id)
    )
    await ctx.send(embed=embed)


@bot.command(
    name="peca",
    aliases=["peça", "peca_info", "item"],
)
async def peca(ctx, part_id=None):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return

    try:
        parsed_part_id = int(part_id)
    except (TypeError, ValueError):
        await ctx.send("Use `!peca ID`. Exemplo: `!peca 101`.")
        return

    details = get_part_details(parsed_part_id)
    if details is None:
        await ctx.send(f"Não encontrei a peça #{parsed_part_id}.")
        return
    cursor.execute("""
    SELECT quantity
    FROM inventory
    WHERE guild_id = ? AND user_id = ? AND part_id = ?
    """, (ctx.guild.id, ctx.author.id, parsed_part_id))
    row = cursor.fetchone()
    quantity = row[0] if row else 0
    rarity_icon = RARITY_EMOJI.get(details["rarity"], "🔧")
    embed = discord.Embed(
        title=f"{rarity_icon} #{parsed_part_id} · {details['name']}",
        color=discord.Color.orange(),
    )
    embed.add_field(name="Categoria", value=details["category"].title(), inline=True)
    embed.add_field(name="Raridade", value=details["rarity"], inline=True)
    embed.add_field(
        name="Preço de catálogo",
        value=f"💰 {format_money(details['price'])} LC",
        inline=True,
    )
    embed.add_field(
        name="Seu inventário",
        value=f"×{quantity}" if quantity else "Você ainda não possui",
        inline=False,
    )
    embed.set_image(
        url=await resolve_catalog_image_url("part", parsed_part_id)
    )
    embed.set_footer(text="Use !mercado para comprar ou vender itens de jogadores.")
    await ctx.send(embed=embed)


@bot.command(
    name="comprar",
    aliases=["comprar_carro", "comprarcarro"],
)
async def comprar(ctx, tipo=None, item_id=None):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return

    if item_id is None:
        item_id = tipo
        tipo = "carro"

    try:
        parsed_item_id = int(item_id)
    except (TypeError, ValueError):
        await ctx.send(
            "Use `!comprar carro ID` ou `!comprar peça ID`. "
            "Exemplo: `!comprar carro 1`."
        )
        return

    normalized_type = normalize_text(tipo or "")
    if normalized_type in {"carro", "car", "cars", "carros"}:
        item_type = "car"
    elif normalized_type in {"peca", "part", "parts", "pecas"}:
        item_type = "part"
    else:
        await ctx.send(
            "Escolha `carro` ou `peça`. Exemplo: `!comprar peça 31`."
        )
        return

    result_type, result = buy_daily_item(
        ctx.guild.id,
        ctx.author.id,
        item_type,
        parsed_item_id,
    )
    if result_type == "invalid":
        await ctx.send(f"Não encontrei o item #{parsed_item_id}.")
        return
    if result_type == "unavailable":
        await ctx.send(
            f"O item #{parsed_item_id} não está na loja diária de hoje. "
            "Use `!loja` para ver as ofertas atuais."
        )
        return
    if result_type == "owned":
        await ctx.send(
            f"Você já possui **{result['name']}**. "
            "Use `!garagem` para ver seus carros."
        )
        return
    if result_type == "purchased":
        await ctx.send(
            f"Você já comprou **{result['name']}** na loja diária de hoje."
        )
        return
    if result_type == "funds":
        _xp, coins = get_user(ctx.guild.id, ctx.author.id)
        await ctx.send(
            f"Você precisa de **{format_money(result['missing'])} LC** a mais "
            f"para comprar **{result['name']}**.\n"
            f"Saldo atual: **{format_money(coins)} LC**."
        )
        return

    item_label = "carro" if item_type == "car" else "peça"
    embed = discord.Embed(
        title=f"✅ Compra concluída · {result['name']}",
        description=(
            f"{ctx.author.mention} comprou a {item_label} por "
            f"**{format_money(result['price'])} LC**.\n"
            + (
                "A peça foi adicionada ao seu inventário."
                if item_type == "part"
                else "O carro foi colocado na sua garagem e selecionado como ativo."
            )
        ),
        color=discord.Color.green(),
    )
    embed.set_image(
        url=await resolve_catalog_image_url(item_type, parsed_item_id)
    )
    await ctx.send(embed=embed)


@bot.command(
    name="garagem",
    aliases=["garage", "meuscarros"],
)
async def garagem(ctx):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return

    owned_cars = get_garage(ctx.guild.id, ctx.author.id)
    if not owned_cars:
        await ctx.send(
            f"🚗 {ctx.author.mention}, sua garagem está vazia. "
            "Veja `!loja` e compre seu primeiro carro."
        )
        return

    lines = []
    for car_id, quantity, is_active in owned_cars:
        details = get_car_details(car_id)
        active_label = " · **ATIVO**" if is_active else ""
        lines.append(
            f"**#{car_id} · {details['name']}** ×{quantity}{active_label}\n"
            f"`{format_car_attributes(car_id, compact=True)}`"
        )

    embed = discord.Embed(
        title=f"🚗 Garagem de {ctx.author.display_name}",
        description="\n\n".join(lines),
        color=discord.Color.dark_blue(),
    )
    embed.set_footer(text="Use !usarcarro ID para trocar o carro ativo.")
    await ctx.send(embed=embed)


@bot.command(
    name="usar_carro",
    aliases=["usarcarro", "carroativo"],
)
async def usar_carro(ctx, car_id=None):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return

    try:
        parsed_car_id = int(car_id)
    except (TypeError, ValueError):
        await ctx.send("Use `!usarcarro ID`. Exemplo: `!usarcarro 1`.")
        return

    details = get_car_details(parsed_car_id)
    if details is None:
        await ctx.send(f"Não encontrei o carro #{parsed_car_id}.")
        return
    if not set_active_car(ctx.guild.id, ctx.author.id, parsed_car_id):
        await ctx.send(
            f"Você não possui **{details['name']}**. "
            "Compre o carro ou confira sua `!garagem`."
        )
        return

    await ctx.send(
        f"✅ **{details['name']}** agora é seu carro ativo para os rachas."
    )


# =========================
# MERCADO ENTRE JOGADORES
# =========================

def parse_market_integer(value):
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    if not digits:
        return None
    try:
        parsed = int(digits)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def market_listings_embed(guild, listings):
    embed = discord.Embed(
        title="🛒 Mercado Valkyrie",
        description=(
            "Compre itens de outros pilotos com Lost Coins. "
            "As ofertas duram 3 dias e ficam reservadas até vender, cancelar ou expirar."
        ),
        color=discord.Color.green(),
    )
    if not listings:
        embed.description += "\n\nAinda não há ofertas ativas neste servidor."
        embed.set_footer(
            text="Anuncie com !mercado vender carro ID PREÇO ou !mercado vender peça ID PREÇO QUANTIDADE."
        )
        return embed

    for listing in listings:
        seller = guild.get_member(listing["seller_id"])
        seller_name = seller.display_name if seller else f"Piloto {listing['seller_id']}"
        remaining = max(0, listing["expires_at"] - int(time.time()))
        embed.add_field(
            name=(
                f"#{listing['listing_id']} · "
                f"{market_item_label(listing['item_type'], listing['item_id'], listing['quantity'])}"
            ),
            value=(
                f"Vendedor: **{seller_name}**\n"
                f"Preço total: **{format_money(listing['price'])} LC**\n"
                f"Expira em: **{format_duration(remaining)}**\n"
                f"Comprar: `!mercado comprar {listing['listing_id']}`"
            ),
            inline=False,
        )
    first = listings[0]
    embed.set_thumbnail(
        url=catalog_image_url(first["item_type"], first["item_id"])
    )
    embed.set_footer(
        text="Itens anunciados ficam em custódia até a conclusão da negociação."
    )
    return embed


@bot.command(
    name="mercado",
    aliases=["market", "feira", "loja_jogadores"],
)
async def mercado(ctx, acao=None, *, detalhes=None):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return

    action = normalize_text(acao or "listar")
    tokens = detalhes.split() if detalhes else []
    if action in {"listar", "lista", "ver", "ofertas", "market"}:
        await ctx.send(embed=market_listings_embed(
            ctx.guild,
            get_market_listings(ctx.guild.id),
        ))
        return

    if action in {"vender", "anunciar", "sell"}:
        if len(tokens) < 3:
            await ctx.send(
                "Use `!mercado vender carro ID PREÇO` ou "
                "`!mercado vender peça ID PREÇO QUANTIDADE`."
            )
            return
        normalized_type = normalize_text(tokens[0])
        if normalized_type in {"carro", "car", "cars"}:
            item_type = "car"
        elif normalized_type in {"peca", "part", "parts", "item"}:
            item_type = "part"
        else:
            await ctx.send("O tipo precisa ser `carro` ou `peça`.")
            return
        item_id = parse_market_integer(tokens[1])
        price = parse_market_integer(tokens[2])
        quantity = parse_market_integer(tokens[3]) if len(tokens) >= 4 else 1
        if item_id is None or price is None or quantity is None:
            await ctx.send("ID, preço e quantidade precisam ser números positivos.")
            return
        result_type, result = create_market_listing(
            ctx.guild.id,
            ctx.author.id,
            item_type,
            item_id,
            quantity,
            price,
        )
        if result_type == "invalid":
            await ctx.send("Não encontrei esse carro ou peça no catálogo.")
        elif result_type == "amount":
            await ctx.send(
                "Preço e quantidade devem ser positivos. Para carros, anuncie apenas 1 por oferta."
            )
        elif result_type == "missing":
            await ctx.send("Você não possui essa quantidade disponível para anunciar.")
        else:
            embed = discord.Embed(
                title=f"📌 Oferta #{result['listing_id']} publicada",
                description=(
                    f"{market_item_label(item_type, item_id, quantity)}\n"
                    f"Preço total: **{format_money(price)} LC**\n\n"
                    "O item foi colocado em custódia e voltou para você se a oferta expirar ou for cancelada."
                ),
                color=discord.Color.green(),
            )
            embed.set_image(
                url=await resolve_catalog_image_url(item_type, item_id)
            )
            await ctx.send(embed=embed)
        return

    if action in {"comprar", "buy"}:
        listing_id = parse_market_integer(tokens[0] if tokens else None)
        if listing_id is None:
            await ctx.send("Use `!mercado comprar ID_DA_OFERTA`.")
            return
        result_type, result = buy_market_listing(
            ctx.guild.id,
            ctx.author.id,
            listing_id,
        )
        if result_type == "unavailable":
            await ctx.send("Essa oferta não está mais disponível.")
        elif result_type == "self":
            await ctx.send("Você não pode comprar a própria oferta.")
        elif result_type == "funds":
            await ctx.send(
                f"Faltam **{format_money(result['missing'])} LC** para comprar essa oferta."
            )
        else:
            embed = discord.Embed(
                title="✅ Compra no mercado concluída",
                description=(
                    f"Você comprou {market_item_label(result['item_type'], result['item_id'], result['quantity'])} "
                    f"por **{format_money(result['price'])} LC**.\n"
                    "O pagamento foi enviado ao vendedor."
                ),
                color=discord.Color.green(),
            )
            embed.set_image(
                url=await resolve_catalog_image_url(
                    result["item_type"],
                    result["item_id"],
                )
            )
            await ctx.send(embed=embed)
        return

    if action in {"cancelar", "cancel", "retirar"}:
        listing_id = parse_market_integer(tokens[0] if tokens else None)
        if listing_id is None:
            await ctx.send("Use `!mercado cancelar ID_DA_OFERTA`.")
            return
        result_type, result = cancel_market_listing(
            ctx.guild.id,
            ctx.author.id,
            listing_id,
        )
        if result_type == "unavailable":
            await ctx.send("Essa oferta não existe, já terminou ou não é sua.")
        else:
            await ctx.send(
                f"✅ Oferta #{listing_id} cancelada. "
                f"{market_item_label(result['item_type'], result['item_id'], result['quantity'])} "
                "foi devolvido ao seu inventário."
            )
        return

    await ctx.send(
        "Use `!mercado` para listar ofertas, `!mercado vender ...`, "
        "`!mercado comprar ID` ou `!mercado cancelar ID`."
    )


# =========================
# DESAFIOS E CORRIDAS
# =========================

@bot.command(
    name="racha",
    aliases=["corrida", "desafiar"],
)
async def racha(ctx, opponent: discord.Member = None):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return
    if opponent is None:
        await ctx.send("Marque alguém para desafiar. Exemplo: `!racha @piloto`.")
        return
    if opponent.id == ctx.author.id:
        await ctx.send("Você não pode desafiar a si mesmo.")
        return
    if opponent.bot:
        await ctx.send("Você só pode desafiar outro piloto.")
        return
    if get_active_car(ctx.guild.id, ctx.author.id) is None:
        await ctx.send(
            "Você precisa ter um carro ativo. Use `!loja`, `!comprar ID` "
            "e depois `!usarcarro ID`."
        )
        return

    challenge_id = create_race_challenge(
        ctx.guild.id,
        ctx.author.id,
        opponent.id,
    )
    if challenge_id is None:
        await ctx.send(
            "Você ou a pessoa marcada já está envolvida em um racha pendente."
        )
        return

    active_car = get_active_car(ctx.guild.id, ctx.author.id)
    challenger_car_id = next(
        car_id for car_id, car in CARS_BY_ID.items() if car == active_car
    )
    view = RaceChallengeView(challenge_id, opponent.id)
    embed = discord.Embed(
        title=f"🏁 Racha #{challenge_id}",
        description=(
            f"{ctx.author.mention} desafiou {opponent.mention}!\n\n"
            f"Carro do desafiante: **{get_car_details(challenger_car_id)['name']}**\n"
            f"A pista, o clima e o dado serão sorteados quando o desafio for aceito."
        ),
        color=discord.Color.orange(),
    )
    embed.set_footer(text=f"{opponent.display_name}, você tem 90 segundos para responder.")
    message = await ctx.send(
        content=opponent.mention,
        embed=embed,
        view=view,
        allowed_mentions=discord.AllowedMentions(users=[opponent]),
    )
    view.message = message


async def answer_race_command(ctx, challenge_id, accepted):
    try:
        parsed_challenge_id = int(challenge_id)
    except (TypeError, ValueError):
        await ctx.send(
            "Informe o ID do racha. Exemplo: `!aceitar 12`."
        )
        return

    result_type, result = resolve_race_challenge(
        parsed_challenge_id,
        ctx.author.id,
        accepted,
    )
    if result_type == "error":
        await ctx.send(result)
        return
    if result_type == "declined":
        await ctx.send(f"❌ <@{ctx.author.id}> recusou o racha #{parsed_challenge_id}.")
        return

    await ctx.send(embed=race_embed(result, ctx.guild))


@bot.command(
    name="aceitar",
    aliases=["aceitarracha", "aceitar_racha"],
)
async def aceitar(ctx, challenge_id=None):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return
    await answer_race_command(ctx, challenge_id, accepted=True)


@bot.command(
    name="recusar",
    aliases=["recusarracha", "recusar_racha"],
)
async def recusar(ctx, challenge_id=None):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return
    await answer_race_command(ctx, challenge_id, accepted=False)


# =========================
# TROCAS ENTRE MEMBROS
# =========================

@bot.command(
    name="troca",
    aliases=["trade", "trocar"],
)
async def troca(ctx, opponent: discord.Member = None, *, offer=None):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return
    if opponent is None or not offer:
        await ctx.send(
            "Use `!troca @pessoa carro 1 peça 2 por carro 3 peça 4`.\n"
            "Carro e peça são opcionais; você pode trocar um ou os dois."
        )
        return
    if opponent.id == ctx.author.id:
        await ctx.send("Você não pode fazer uma troca consigo mesmo.")
        return
    if opponent.bot:
        await ctx.send("Você só pode negociar com outro membro.")
        return

    parsed_items = parse_trade_items(offer)
    if parsed_items is None:
        await ctx.send(
            "Não entendi a oferta. Use, por exemplo: "
            "`!troca @pessoa carro 1 peça 2 por carro 3 peça 4`."
        )
        return

    offered_items, requested_items = parsed_items
    offered_keys = [(item["type"], item["id"]) for item in offered_items]
    requested_keys = [(item["type"], item["id"]) for item in requested_items]
    if len(set(offered_keys)) != len(offered_keys) or (
        len(set(requested_keys)) != len(requested_keys)
    ):
        await ctx.send("Não repita o mesmo item dentro de uma oferta.")
        return
    if not has_trade_items(ctx.guild.id, ctx.author.id, offered_items):
        await ctx.send("Você não possui todos os itens que está oferecendo.")
        return
    if not has_trade_items(ctx.guild.id, opponent.id, requested_items):
        await ctx.send("A pessoa marcada não possui todos os itens pedidos.")
        return

    trade_id = create_trade(
        ctx.guild.id,
        ctx.author.id,
        opponent.id,
        offered_items,
        requested_items,
    )
    if trade_id is None:
        await ctx.send(
            "Você ou a pessoa marcada já está envolvida em uma troca pendente."
        )
        return

    trade = get_trade(trade_id)
    view = TradeView(trade_id, opponent.id)
    message = await ctx.send(
        content=opponent.mention,
        embed=trade_embed(trade, ctx.guild),
        view=view,
        allowed_mentions=discord.AllowedMentions(users=[opponent]),
    )
    view.message = message


async def answer_trade_command(ctx, trade_id, accepted):
    try:
        parsed_trade_id = int(trade_id)
    except (TypeError, ValueError):
        await ctx.send("Informe o ID da troca. Exemplo: `!aceitar_troca 12`.")
        return

    result_type, result = resolve_trade(
        parsed_trade_id,
        ctx.author.id,
        accepted,
    )
    if result_type == "error":
        await ctx.send(result)
        return
    if result_type == "declined":
        await ctx.send(f"❌ <@{ctx.author.id}> recusou a troca #{parsed_trade_id}.")
        return

    await ctx.send(
        f"✅ Troca #{parsed_trade_id} concluída.",
        embed=trade_embed(result, ctx.guild),
    )


@bot.command(
    name="aceitar_troca",
    aliases=["aceitartroca"],
)
async def aceitar_troca(ctx, trade_id=None):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return
    await answer_trade_command(ctx, trade_id, accepted=True)


@bot.command(
    name="recusar_troca",
    aliases=["recusartroca"],
)
async def recusar_troca(ctx, trade_id=None):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return
    await answer_trade_command(ctx, trade_id, accepted=False)


# =========================
# ADMINISTRAÇÃO E RECURSOS ESPECIAIS
# =========================

@bot.command(name="admin")
async def admin(ctx):
    if not await require_admin(ctx):
        return
    log_admin_action(ctx.guild.id, ctx.author.id, "panel_open")
    embed = discord.Embed(
        title="🔐 Painel administrativo Valkyrie",
        description=(
            "Somente o administrador autorizado pode usar este painel.\n"
            "As alterações são persistidas no SQLite e todas as ações são registradas."
        ),
        color=discord.Color.dark_gold(),
    )
    embed.add_field(
        name="Economia e XP",
        value="`!give_money`, `!remove_money`, `!give_xp`, `!remove_xp`",
        inline=False,
    )
    embed.add_field(
        name="Itens",
        value="`!give_car`, `!remove_car`, `!give_item`, `!remove_item`",
        inline=False,
    )
    embed.add_field(
        name="Moderação",
        value="`!ban`, `!unban`, `!userinfo`, `!reset_user`",
        inline=False,
    )
    await ctx.send(embed=embed, view=AdminPanelView(ctx.author.id))


@bot.command(name="give_money")
async def give_money(ctx, target: discord.Member = None, valor=None):
    if not await require_admin(ctx):
        return
    amount = parse_positive_integer(valor)
    if target is None or amount is None:
        await ctx.send("Use `!give_money @user valor` com um valor positivo.")
        return
    admin_adjust_coins(ctx.guild.id, target.id, amount)
    log_admin_action(
        ctx.guild.id, ctx.author.id, "give_money",
        target.id, amount, details=f"Saldo de {target}",
    )
    await ctx.send(f"✅ {format_money(amount)} LC adicionados a {target.mention}.")


@bot.command(name="remove_money")
async def remove_money(ctx, target: discord.Member = None, valor=None):
    if not await require_admin(ctx):
        return
    amount = parse_positive_integer(valor)
    if target is None or amount is None:
        await ctx.send("Use `!remove_money @user valor` com um valor positivo.")
        return
    if not admin_adjust_coins(ctx.guild.id, target.id, -amount):
        await ctx.send("❌ O usuário não possui saldo suficiente para remover esse valor.")
        return
    log_admin_action(
        ctx.guild.id, ctx.author.id, "remove_money",
        target.id, -amount, details=f"Saldo de {target}",
    )
    await ctx.send(f"✅ {format_money(amount)} LC removidos de {target.mention}.")


@bot.command(name="give_xp")
async def give_xp(ctx, target: discord.Member = None, valor=None):
    if not await require_admin(ctx):
        return
    amount = parse_positive_integer(valor)
    if target is None or amount is None:
        await ctx.send("Use `!give_xp @user valor` com um valor positivo.")
        return
    admin_adjust_xp(ctx.guild.id, target.id, amount)
    log_admin_action(
        ctx.guild.id, ctx.author.id, "give_xp",
        target.id, amount, details=f"XP de {target}",
    )
    await ctx.send(f"✅ {amount} XP adicionados a {target.mention}.")
    await update_ranks(target)


@bot.command(name="remove_xp")
async def remove_xp(ctx, target: discord.Member = None, valor=None):
    if not await require_admin(ctx):
        return
    amount = parse_positive_integer(valor)
    if target is None or amount is None:
        await ctx.send("Use `!remove_xp @user valor` com um valor positivo.")
        return
    admin_adjust_xp(ctx.guild.id, target.id, -amount)
    log_admin_action(
        ctx.guild.id, ctx.author.id, "remove_xp",
        target.id, -amount, details=f"XP de {target}",
    )
    await ctx.send(f"✅ {amount} XP removidos de {target.mention}.")


@bot.command(name="give_car")
async def give_car(ctx, target: discord.Member = None, *, carro=None):
    if not await require_admin(ctx):
        return
    car_id = resolve_catalog_car(carro)
    if target is None or car_id is None:
        await ctx.send("Use `!give_car @user ID ou nome do carro`.")
        return
    admin_adjust_car(ctx.guild.id, target.id, car_id, 1)
    details = get_car_details(car_id)
    log_admin_action(
        ctx.guild.id, ctx.author.id, "give_car",
        target.id, 1, item=f"#{car_id} {details['name']}",
    )
    await ctx.send(f"✅ **{details['name']}** adicionado à garagem de {target.mention}.")


@bot.command(name="remove_car")
async def remove_car(ctx, target: discord.Member = None, *, carro=None):
    if not await require_admin(ctx):
        return
    car_id = resolve_catalog_car(carro)
    if target is None or car_id is None:
        await ctx.send("Use `!remove_car @user ID ou nome do carro`.")
        return
    if not admin_adjust_car(ctx.guild.id, target.id, car_id, -1):
        await ctx.send("❌ O usuário não possui esse carro disponível.")
        return
    details = get_car_details(car_id)
    log_admin_action(
        ctx.guild.id, ctx.author.id, "remove_car",
        target.id, -1, item=f"#{car_id} {details['name']}",
    )
    await ctx.send(f"✅ **{details['name']}** removido da garagem de {target.mention}.")


def parse_item_quantity(value):
    if not value:
        return None, None
    pieces = value.rsplit(maxsplit=1)
    if len(pieces) != 2:
        return None, None
    quantity = parse_positive_integer(pieces[1])
    return pieces[0], quantity


@bot.command(name="give_item")
async def give_item(ctx, target: discord.Member = None, *, item_quantidade=None):
    if not await require_admin(ctx):
        return
    item_name, quantity = parse_item_quantity(item_quantidade)
    part_id = resolve_catalog_part(item_name)
    if target is None or part_id is None or quantity is None:
        await ctx.send("Use `!give_item @user item quantidade`.")
        return
    admin_adjust_item(ctx.guild.id, target.id, part_id, quantity)
    part = PARTS_BY_ID[part_id]
    log_admin_action(
        ctx.guild.id, ctx.author.id, "give_item",
        target.id, quantity, item=f"#{part_id} {part[1]}",
    )
    await ctx.send(f"✅ {quantity}× **{part[1]}** adicionadas ao inventário de {target.mention}.")


@bot.command(name="remove_item")
async def remove_item(ctx, target: discord.Member = None, *, item_quantidade=None):
    if not await require_admin(ctx):
        return
    item_name, quantity = parse_item_quantity(item_quantidade)
    part_id = resolve_catalog_part(item_name)
    if target is None or part_id is None or quantity is None:
        await ctx.send("Use `!remove_item @user item quantidade`.")
        return
    if not admin_adjust_item(ctx.guild.id, target.id, part_id, -quantity):
        await ctx.send("❌ O usuário não possui essa quantidade da peça.")
        return
    part = PARTS_BY_ID[part_id]
    log_admin_action(
        ctx.guild.id, ctx.author.id, "remove_item",
        target.id, -quantity, item=f"#{part_id} {part[1]}",
    )
    await ctx.send(f"✅ {quantity}× **{part[1]}** removidas de {target.mention}.")


@bot.command(name="ban")
async def ban(ctx, target: discord.Member = None, *, motivo=None):
    if not await require_admin(ctx):
        return
    if target is None:
        await ctx.send("Use `!ban @user motivo`.")
        return
    if target.id == ctx.author.id:
        await ctx.send("❌ O administrador não pode banir a si mesmo.")
        return
    reason = motivo or "Banimento administrativo Valkyrie"
    try:
        await ctx.guild.ban(target, reason=reason, delete_message_seconds=0)
    except discord.Forbidden:
        await ctx.send("❌ O Discord recusou o banimento. Verifique a hierarquia de cargos.")
        return
    except discord.HTTPException:
        await ctx.send("❌ Não foi possível concluir o banimento.")
        return
    log_admin_action(
        ctx.guild.id, ctx.author.id, "ban",
        target.id, details=reason,
    )
    await ctx.send(f"✅ {target} banido. Motivo: {reason}")


@bot.command(name="unban")
async def unban(ctx, user_id=None):
    if not await require_admin(ctx):
        return
    try:
        target_id = int(user_id)
    except (TypeError, ValueError):
        await ctx.send("Use `!unban ID`.")
        return
    try:
        await ctx.guild.unban(discord.Object(id=target_id), reason="Valkyrie admin")
    except discord.NotFound:
        await ctx.send("❌ Esse ID não está banido neste servidor.")
        return
    except (discord.Forbidden, discord.HTTPException):
        await ctx.send("❌ Não foi possível remover o banimento.")
        return
    log_admin_action(ctx.guild.id, ctx.author.id, "unban", target_id=target_id)
    await ctx.send(f"✅ Banimento removido para o ID `{target_id}`.")


@bot.command(name="userinfo")
async def userinfo(ctx, target: discord.Member = None):
    if not await require_admin(ctx):
        return
    target = target or ctx.author
    summary, car_count, part_count = admin_user_summary(ctx.guild.id, target.id)
    xp_value, coins, crime_xp, wanted, wanted_until, crime_lock, job_lock, prison = summary
    active_job = get_active_job(ctx.guild.id, target.id)
    embed = discord.Embed(
        title=f"🔎 Informações administrativas · {target}",
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="Economia",
        value=f"XP: **{xp_value}**\nLC: **{format_money(coins)}**\nXP criminal: **{crime_xp}**",
        inline=True,
    )
    embed.add_field(
        name="Inventário",
        value=f"Carros: **{car_count}**\nPeças: **{part_count}**",
        inline=True,
    )
    embed.add_field(
        name="Criminalidade",
        value=f"Procurado: **{wanted}/{CRIME_WANTED_MAX_LEVEL}**\n"
              f"Prisâo ativa: **{'sim' if prison > int(time.time()) else 'não'}**",
        inline=False,
    )
    embed.add_field(
        name="Emprego",
        value=active_job["title"] if active_job else "Nenhum emprego ativo",
        inline=False,
    )
    log_admin_action(ctx.guild.id, ctx.author.id, "userinfo", target.id)
    await ctx.send(embed=embed)


@bot.command(name="reset_user")
async def reset_user(ctx, target: discord.Member = None):
    if not await require_admin(ctx):
        return
    if target is None:
        await ctx.send("Use `!reset_user @user`.")
        return
    reset_user_data(ctx.guild.id, target.id)
    log_admin_action(
        ctx.guild.id, ctx.author.id, "reset_user",
        target.id, details="Dados do usuário resetados; logs administrativos preservados",
    )
    await ctx.send(f"✅ Dados de {target.mention} resetados.")


@bot.command(name="set_wanted", aliases=["alterar_procurado", "procurado_admin"])
async def set_wanted(ctx, target: discord.Member = None, nivel=None):
    if not await require_admin(ctx):
        return
    try:
        wanted_level = int(nivel)
    except (TypeError, ValueError):
        wanted_level = -1
    if target is None or not 0 <= wanted_level <= CRIME_WANTED_MAX_LEVEL:
        await ctx.send(
            f"Use `!set_wanted @user nível` com nível entre 0 e {CRIME_WANTED_MAX_LEVEL}."
        )
        return
    now = int(time.time())
    wanted_until = now + CRIME_WANTED_DECAY_SECONDS if wanted_level else 0
    create_user(ctx.guild.id, target.id)
    cursor.execute("""
    UPDATE users
    SET wanted_level = ?, wanted_until = ?
    WHERE guild_id = ? AND user_id = ?
    """, (wanted_level, wanted_until, ctx.guild.id, target.id))
    cursor.execute("""
    INSERT INTO wanted_players (
        guild_id, user_id, wanted_level, wanted_until,
        crime_blocked_until, job_blocked_until, prison_until
    )
    VALUES (?, ?, ?, ?, 0, 0, 0)
    ON CONFLICT(guild_id, user_id) DO UPDATE SET
        wanted_level = excluded.wanted_level,
        wanted_until = excluded.wanted_until
    """, (ctx.guild.id, target.id, wanted_level, wanted_until))
    db.commit()
    log_admin_action(
        ctx.guild.id,
        ctx.author.id,
        "set_wanted",
        target.id,
        wanted_level,
        details=f"Procurado definido para {wanted_level}",
    )
    await ctx.send(
        f"✅ Nível de procurado de {target.mention} definido para "
        f"**{wanted_level}/{CRIME_WANTED_MAX_LEVEL}**."
    )


@bot.command(name="definir_imposto", aliases=["imposto", "taxa"])
async def definir_imposto(ctx, percentual=None):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return
    result_type, result = set_salary_tax(ctx.guild.id, ctx.author.id, percentual)
    if result_type == "error":
        await ctx.send(result)
        return
    await ctx.send(
        f"🏛️ O imposto sobre salários agora é **{result:.2f}%**. "
        "A arrecadação futura irá para o Tesouro Público."
    )


@bot.command(name="tesouro", aliases=["tesouro_publico"])
async def tesouro(ctx):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return
    tax_rate, treasury, _updated_at = get_treasury_status(ctx.guild.id)
    office = cursor.execute("""
    SELECT user_id, expires_at
    FROM political_office
    WHERE guild_id = ? AND status = 'active' AND expires_at > ?
    """, (ctx.guild.id, int(time.time()))).fetchone()
    embed = discord.Embed(
        title=f"🏛️ Tesouro Público · {ctx.guild.name}",
        color=discord.Color.gold(),
    )
    embed.add_field(name="Saldo", value=f"**{format_money(treasury)} LC**", inline=True)
    embed.add_field(name="Imposto atual", value=f"**{tax_rate:.2f}%**", inline=True)
    embed.add_field(
        name="Governo",
        value=f"<@{office[0]}>" if office else "Sem político em mandato",
        inline=False,
    )
    await ctx.send(embed=embed)


@bot.command(name="eventos", aliases=["evento"])
async def eventos(ctx):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return
    rows = get_event_status(ctx.guild.id, ctx.author.id, limit=10)
    embed = discord.Embed(
        title="🌎 Eventos ativos",
        description="Eventos são sorteados aproximadamente a cada 3 dias e duram cerca de 24h.",
        color=discord.Color.gold(),
    )
    now = int(time.time())
    for _event_id, scope, user_id, title, description, _started, expires in rows:
        scope_text = "global" if scope == "global" else "individual"
        embed.add_field(
            name=title,
            value=f"{description}\nEscopo: {scope_text} · resta {format_duration(expires - now)}",
            inline=False,
        )
    if not rows:
        embed.description += "\nNenhum evento ativo para você neste momento."
    await ctx.send(embed=embed)


@bot.command(name="emprestimo", aliases=["agiota"])
async def emprestimo(ctx, valor=None):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return
    amount = parse_positive_integer(valor)
    if amount is None:
        await ctx.send("Use `!emprestimo valor` enquanto trabalha como Agiota.")
        return
    result_type, result = request_loan(ctx.guild.id, ctx.author.id, amount)
    if result_type == "error":
        await ctx.send(result)
        return
    await ctx.send(
        f"🦈 Empréstimo **#{result['loan_id']}** liberado: "
        f"+{format_money(result['principal'])} LC.\n"
        f"Total para pagar em 24h: **{format_money(result['total_due'])} LC**.\n"
        f"Use `!pagar_emprestimo {result['loan_id']}`."
    )


@bot.command(name="pagar_emprestimo", aliases=["pagar_loan"])
async def pagar_emprestimo(ctx, loan_id=None):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return
    result_type, result = repay_loan(ctx.guild.id, ctx.author.id, loan_id)
    if result_type == "error":
        await ctx.send(result)
        return
    await ctx.send(f"✅ Empréstimo pago: **{format_money(result)} LC**.")


def police_hunt(guild_id, police_id, target_id):
    active = get_active_job(guild_id, police_id)
    if active is None or active["job_key"] != "policial":
        return "error", "Você precisa estar trabalhando como 👮 Policial."
    if police_id == target_id:
        return "error", "Você não pode caçar a si mesmo."
    cursor.execute("BEGIN IMMEDIATE")
    try:
        cursor.execute("""
        SELECT wanted_level
        FROM users
        WHERE guild_id = ? AND user_id = ? AND wanted_level > 0
        """, (guild_id, target_id))
        row = cursor.fetchone()
        if row is None:
            db.rollback()
            return "error", "Esse jogador não está procurado."
        wanted_before = row[0]
        reward = wanted_before * 300
        cursor.execute("""
        UPDATE users
        SET wanted_level = MAX(0, wanted_level - 1),
            wanted_until = CASE WHEN wanted_level <= 1 THEN 0 ELSE wanted_until END,
            crime_blocked_until = CASE WHEN wanted_level <= 1 THEN 0 ELSE crime_blocked_until END
        WHERE guild_id = ? AND user_id = ? AND wanted_level > 0
        """, (guild_id, target_id))
        if cursor.rowcount != 1:
            db.rollback()
            return "error", "O alvo deixou de estar disponível."
        cursor.execute("""
        UPDATE users
        SET coins = coins + ?
        WHERE guild_id = ? AND user_id = ?
        """, (reward, guild_id, police_id))
        db.commit()
        return "ok", reward
    except Exception:
        db.rollback()
        raise


@bot.command(name="cacar", aliases=["caçar", "caçar_criminoso", "caçarcriminoso"])
async def cacar(ctx, target: discord.Member = None):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return
    if target is None or target.bot:
        await ctx.send("Use `!cacar @criminoso`.")
        return
    result_type, result = police_hunt(ctx.guild.id, ctx.author.id, target.id)
    if result_type == "error":
        await ctx.send(result)
        return
    await ctx.send(
        f"👮 Você capturou parte da ficha de {target.mention} e recebeu "
        f"**{format_money(result)} LC**."
    )


# =========================
# RANKING GLOBAL
# =========================

@bot.command(
    name="noticias",
    aliases=["noticia", "news", "jornal"],
)
async def noticias(ctx, acao=None):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return

    force = normalize_text(acao or "") in {
        "nova",
        "novas",
        "gerar",
        "random",
        "aleatoria",
    }
    latest = get_recent_news(ctx.guild.id)
    if force or not latest:
        generated = maybe_generate_news(ctx.guild.id, force=True)
        if generated is not None:
            latest = get_recent_news(ctx.guild.id, limit=5)

    if not latest:
        await ctx.send("Ainda não há notícias disponíveis.")
        return

    embed = news_embed(latest[0])
    if len(latest) > 1:
        embed.add_field(
            name="🗞️ Edições anteriores",
            value="\n".join(
                f"• **#{item['news_id']}** {item['headline'][:160]}"
                for item in latest[1:]
            ),
            inline=False,
        )
    await ctx.send(embed=embed)


def ranking_lines(rows, guild):
    medals = ("🥇", "🥈", "🥉")
    lines = []
    for position, (user_id, score) in enumerate(rows, start=1):
        member = guild.get_member(user_id) if guild else None
        name = member.display_name if member else f"Piloto {user_id}"
        medal = medals[position - 1] if position <= len(medals) else f"**{position}.**"
        lines.append(f"{medal} {name} — **{format_money(score)}**")
    return "\n".join(lines) or "Ainda não há dados nessa categoria."


@bot.command(
    name="ranking",
    aliases=["rank", "leaderboard"],
)
async def ranking(ctx, categoria=None):
    category = get_ranking_category(categoria)
    if categoria and category not in RANKING_CATEGORIES:
        await ctx.send(
            "Categoria inválida. Use: `vitorias`, `corridas`, `carros`, "
            "`pecas`, `coins` ou `xp`."
        )
        return

    if categoria:
        title, rows = get_global_ranking(category, limit=10)
        embed = discord.Embed(
            title=f"🌎 Ranking global · {title}",
            description=ranking_lines(rows, ctx.guild),
            color=discord.Color.gold(),
        )
        embed.set_footer(text="Os dados são somados entre todos os servidores.")
        await ctx.send(embed=embed)
        return

    embed = discord.Embed(
        title="🌎 Ranking global Valkyrie",
        description=(
            "Escolha uma categoria com `!ranking categoria`.\n"
            "Exemplo: `!ranking vitorias`."
        ),
        color=discord.Color.gold(),
    )
    for category in ("vitorias", "carros", "corridas", "pecas", "coins", "xp"):
        title, rows = get_global_ranking(category, limit=5)
        embed.add_field(
            name=title,
            value=ranking_lines(rows, ctx.guild),
            inline=False,
        )
    await ctx.send(embed=embed)


# =========================
# AJUDA
# =========================

@bot.command(
    name="ajuda",
    aliases=["help", "comandos"],
)
async def ajuda(ctx):
    embed = discord.Embed(
        title="📖 Central de ajuda da Valkyrie",
        description=(
            "Use os comandos abaixo para começar. Os IDs de carros e peças "
            "aparecem em `!loja`."
        ),
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="Economia",
        value=(
            "`!daily` — recebe Lost Coins uma vez por dia.\n"
            "`!daily peças` — recebe uma peça automotiva por dia.\n"
            "`!loja` — mostra 3 carros e 3 peças em oferta hoje.\n"
            "`!comprar carro ID` — compra um carro da oferta diária.\n"
            "`!comprar peça ID` — compra uma peça da oferta diária.\n"
            "`!carro ID` / `!peca ID` — vê detalhes e imagem do item.\n"
            "`!mercado` — compra e vende carros e peças entre jogadores.\n"
            "`!saldo` — separa saldo disponível, investimentos e patrimônio.\n"
            "`!carteira` — mostra o valor atual dos investimentos.\n"
            "`!investimentos comprar ATIVO VALOR` — investe LC.\n"
            "`!investimentos vender ATIVO [VALOR]` — vende uma posição.\n"
            "`!historico` — consulta movimentações financeiras, empregos e crimes."
        ),
        inline=False,
    )
    embed.add_field(
        name="Carros",
        value=(
            "`!carro ID` — vê preço e todos os atributos.\n"
            "`!garagem` — vê seus carros.\n"
            "`!usarcarro ID` — escolhe o carro ativo.\n"
            "Atributos: velocidade máxima, aceleração, controle, curvas, "
            "frenagem, resistência, economia, luxo e TUN."
        ),
        inline=False,
    )
    embed.add_field(
        name="Corridas",
        value=(
            "`!racha @pessoa` — envia um desafio de corrida.\n"
            "`!aceitar ID` / `!recusar ID` — responde por comando.\n"
            "O racha sorteia pista, clima e um dado D20 além dos atributos."
        ),
        inline=False,
    )
    embed.add_field(
        name="Trocas e rankings",
        value=(
            "`!troca @pessoa carro 1 peça 2 por carro 3 peça 4` — propõe uma troca.\n"
            "`!aceitar_troca ID` / `!recusar_troca ID` — responde por comando.\n"
            "`!ranking` — mostra todas as categorias.\n"
            "`!ranking vitorias` — mostra uma categoria específica."
        ),
        inline=False,
    )
    embed.add_field(
        name="Empregos e crimes",
        value=(
            "`!emprego` — recebe uma oferta a cada 6 horas.\n"
            "`!aceitar_emprego ID` / `!recusar_emprego ID` — responde à oferta.\n"
            "`!crime` — abre o menu de crimes e alvos.\n"
            "`!crime banco|posto|joalheria|digital|raro|golpe` — escolhe uma operação.\n"
            "`!procurado` — mostra bloqueios, prisão e nível de procurado.\n"
            "`!historico` — mostra empregos, crimes e investimentos realizados.\n"
            "Os crimes usam chance, cooldown e penalidades próprias; falhas podem gerar multa, prisão e bloqueios."
        ),
        inline=False,
    )
    embed.add_field(
        name="Perfil",
        value=(
            "`!perfil` — vê XP, Lost Coins e patente.\n"
            "`!xp` — consulta seu XP.\n"
            "`!inventario` — vê suas peças.\n"
            "`!eventos` — consulta eventos globais e direcionados ativos.\n"
            "`!noticias` / `!noticias nova` — jornal aleatório satírico do servidor.\n"
            "`!tesouro` — consulta o Tesouro Público e imposto.\n"
            "`!definir_imposto 0,5-15` — político define a taxa salarial.\n"
            "`!emprestimo VALOR` / `!pagar_emprestimo ID` — recursos do Agiota.\n"
            "`!cacar @procurado` — Policial caça um criminoso."
        ),
        inline=False,
    )
    if ctx.guild is not None and ctx.author.id == ADMIN_ID:
        embed.add_field(
            name="Administração exclusiva",
            value=(
                "`!admin` — abre o painel.\n"
                "`!give_money/remove_money @user valor` · "
                "`!give_xp/remove_xp @user valor`\n"
                "`!give_car/remove_car @user ID/nome` · "
                "`!give_item/remove_item @user peça quantidade`\n"
                "`!ban @user motivo` · `!unban ID` · `!userinfo @user` · "
                "`!reset_user @user` · `!set_wanted @user nível`"
            ),
            inline=False,
        )
    await ctx.send(embed=embed)


# =========================
# COMANDO !INVENTARIO
# =========================

@bot.command(
    name="inventario",
    aliases=["inventory", "inv", "pecas"],
)
async def inventario(ctx):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return

    rows = get_inventory(ctx.guild.id, ctx.author.id)
    if not rows:
        await ctx.send(
            f"🔧 {ctx.author.mention}, seu inventário de peças está vazio. "
            "Use `!daily peças` para começar."
        )
        return

    lines = []
    for part_id, quantity in rows[:30]:
        part = PARTS_BY_ID.get(part_id)
        if part is None:
            continue
        rarity = part[3]
        rarity_icon = RARITY_EMOJI.get(rarity, "🔧")
        lines.append(f"{rarity_icon} **{part[1]}** ×{quantity} · {rarity}")

    if len(rows) > 30:
        lines.append(f"\n… e mais {len(rows) - 30} peça(s).")

    embed = discord.Embed(
        title=f"🔧 Inventário de {ctx.author.display_name}",
        description="\n".join(lines),
        color=discord.Color.orange(),
    )
    await ctx.send(embed=embed)


# =========================
# COMANDO !PERFIL
# =========================

@bot.command()
async def perfil(ctx):
    if ctx.guild is None:
        await ctx.send("Este comando só pode ser usado em um servidor.")
        return

    xp_value, coins = get_user(ctx.guild.id, ctx.author.id)

    embed = discord.Embed(
        title=f"👤 Perfil de {ctx.author.display_name}",
        color=discord.Color.blurple(),
    )

    embed.set_thumbnail(url=ctx.author.display_avatar.url)

    embed.add_field(
        name="🆙 XP",
        value=str(xp_value),
        inline=True,
    )

    embed.add_field(
        name="🪙 Lost Coin",
        value=f"{coins:,} LC".replace(",", "."),
        inline=True,
    )

    embed.add_field(
        name="🏅 Patente",
        value=get_rank_name(xp_value),
        inline=False,
    )

    await ctx.send(embed=embed)


# =========================
# TOKEN
# =========================

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError("❌ DISCORD_TOKEN não foi configurado.")


# =========================
# INICIAR
# =========================

try:
    bot.run(TOKEN)
except discord.LoginFailure:
    print(
        "❌ O Discord rejeitou DISCORD_TOKEN (401). "
        "Atualize o segredo no Replit e reinicie o workflow.",
        flush=True,
    )
    raise SystemExit(78)