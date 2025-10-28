import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import time
from typing import Optional, List, Tuple

from json_store import load_json, save_json

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')
DATA_PATH = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')), 'data', 'birthdays.json')


def load_config():
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {
            "enabled": True,
            "announce_channel_id": None,
            "timezone": "Europe/Rome",
            "messages": {
                "set": "🎂 Compleanno impostato per {user}: {date}",
                "removed": "🗑️ Compleanno rimosso.",
                "when": "🎉 Il compleanno di {user} è il {date}",
                "next_header": "📅 Prossimi compleanni:",
                "wish": "🎉 Buon compleanno {mention}! 🥳"
            }
        }


def parse_bday(text: str) -> Optional[Tuple[int, int, Optional[int]]]:
    # DD/MM/YY or DD/MM
    parts = text.strip().split('/')
    if len(parts) not in (2, 3):
        return None
    try:
        d = int(parts[0])
        m = int(parts[1])
        y = None
        if len(parts) == 3:
            y2 = int(parts[2])
            y = 2000 + y2
        if not (1 <= d <= 31 and 1 <= m <= 12):
            return None
        return d, m, y
    except Exception:
        return None


class BirthdaysCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config = load_config()
        self._last_announced_day: Optional[str] = None
        self.wish_loop.start()

    def cog_unload(self):
        try:
            self.wish_loop.cancel()
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_ready(self):
        # No DB init needed when using JSON storage
        pass

    bday = app_commands.Group(name='birthday', description='Gestione compleanni')

    @bday.command(name='set', description='Imposta il tuo compleanno (DD/MM o DD/MM/YY)')
    @app_commands.describe(date='Data nel formato DD/MM o DD/MM/YY')
    async def birthday_set(self, interaction: discord.Interaction, date: str):
        parsed = parse_bday(date)
        if not parsed:
            await interaction.response.send_message('Formato non valido. Usa DD/MM o DD/MM/YY', ephemeral=True)
            return
        d, m, y = parsed
        data = await load_json(DATA_PATH, {})
        gid = str(interaction.guild.id)
        uid = str(interaction.user.id)
        guild_data = data.get(gid, {})
        users = guild_data.get('users', {})
        users[uid] = {"day": d, "month": m, "year": y}
        guild_data['users'] = users
        data[gid] = guild_data
        await save_json(DATA_PATH, data)
        await interaction.response.send_message(self.config['messages']['set'].format(user=interaction.user.mention, date=date))

    @bday.command(name='remove', description='Rimuovi il tuo compleanno')
    async def birthday_remove(self, interaction: discord.Interaction):
        data = await load_json(DATA_PATH, {})
        gid = str(interaction.guild.id)
        uid = str(interaction.user.id)
        guild_data = data.get(gid, {})
        users = guild_data.get('users', {})
        if uid in users:
            users.pop(uid, None)
            guild_data['users'] = users
            data[gid] = guild_data
            await save_json(DATA_PATH, data)
        await interaction.response.send_message(self.config['messages']['removed'], ephemeral=True)

    @bday.command(name='when', description='Mostra il compleanno di un utente')
    @app_commands.describe(user='Utente (opzionale)')
    async def birthday_when(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        member = user or interaction.user
        data = await load_json(DATA_PATH, {})
        gid = str(interaction.guild.id)
        uid = str(member.id)
        users = data.get(gid, {}).get('users', {})
        info = users.get(uid)
        if not info:
            await interaction.response.send_message('Non trovato.', ephemeral=True)
            return
        d, m, y = int(info['day']), int(info['month']), info.get('year')
        date_str = f"{d:02d}/{m:02d}" + (f"/{str(y)[2:]}" if y else '')
        await interaction.response.send_message(self.config['messages']['when'].format(user=member.mention, date=date_str))

    @bday.command(name='next', description='Mostra i prossimi compleanni')
    async def birthday_next(self, interaction: discord.Interaction):
        import datetime
        data = await load_json(DATA_PATH, {})
        gid = str(interaction.guild.id)
        users = data.get(gid, {}).get('users', {})
        if not users:
            await interaction.response.send_message('Nessun compleanno registrato.', ephemeral=True)
            return
        today = datetime.date.today()
        def days_until(d, m):
            year = today.year if (m, d) >= (today.month, today.day) else today.year + 1
            try:
                target = datetime.date(year, m, d)
                return (target - today).days
            except Exception:
                return 9999
        upcoming = []
        for uid, info in users.items():
            d = int(info.get('day', 0))
            m = int(info.get('month', 0))
            if d and m:
                upcoming.append((int(uid), d, m, days_until(d, m)))
        upcoming.sort(key=lambda x: x[3])
        desc = [self.config['messages']['next_header']]
        for user_id, d, m, left in upcoming[:10]:
            member = interaction.guild.get_member(user_id)
            desc.append(f"{member.mention if member else user_id} — {d:02d}/{m:02d} (tra {left} giorni)")
        await interaction.response.send_message('\n'.join(desc))

    @tasks.loop(minutes=10)
    async def wish_loop(self):
        await self.bot.wait_until_ready()
        try:
            import datetime
            today = datetime.date.today()
            day_key = today.strftime('%Y-%m-%d')
            if self._last_announced_day == day_key:
                return
            # Send wishes once
            for guild in self.bot.guilds:
                data = await load_json(DATA_PATH, {})
                gid = str(guild.id)
                users = data.get(gid, {}).get('users', {})
                todays = [int(uid) for uid, info in users.items() if int(info.get('day', 0)) == today.day and int(info.get('month', 0)) == today.month]
                if not todays:
                    continue
                ch_id = self.config.get('announce_channel_id')
                channel = guild.get_channel(int(ch_id)) if ch_id else (guild.system_channel or next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None))
                for uid in todays:
                    user = guild.get_member(uid)
                    if channel and user:
                        try:
                            await channel.send(self.config['messages']['wish'].format(mention=user.mention))
                        except Exception:
                            pass
            self._last_announced_day = day_key
        except Exception:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(BirthdaysCog(bot))
