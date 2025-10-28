import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import time
from typing import Optional, List, Tuple

from db_utils import get_db, ensure_db_ready

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')


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
        await ensure_db_ready()

    bday = app_commands.Group(name='birthday', description='Gestione compleanni')

    @bday.command(name='set', description='Imposta il tuo compleanno (DD/MM o DD/MM/YY)')
    @app_commands.describe(date='Data nel formato DD/MM o DD/MM/YY')
    async def birthday_set(self, interaction: discord.Interaction, date: str):
        parsed = parse_bday(date)
        if not parsed:
            await interaction.response.send_message('Formato non valido. Usa DD/MM o DD/MM/YY', ephemeral=True)
            return
        d, m, y = parsed
        db = await get_db()
        row = await (await db.execute('SELECT 1 FROM birthdays WHERE guild_id=? AND user_id=?', (interaction.guild.id, interaction.user.id))).fetchone()
        if row:
            await db.execute('UPDATE birthdays SET day=?, month=?, year=? WHERE guild_id=? AND user_id=?', (d, m, y, interaction.guild.id, interaction.user.id))
        else:
            await db.execute('INSERT INTO birthdays (guild_id, user_id, day, month, year) VALUES (?,?,?,?,?)', (interaction.guild.id, interaction.user.id, d, m, y))
        await db.commit()
        await interaction.response.send_message(self.config['messages']['set'].format(user=interaction.user.mention, date=date))

    @bday.command(name='remove', description='Rimuovi il tuo compleanno')
    async def birthday_remove(self, interaction: discord.Interaction):
        db = await get_db()
        await db.execute('DELETE FROM birthdays WHERE guild_id=? AND user_id=?', (interaction.guild.id, interaction.user.id))
        await db.commit()
        await interaction.response.send_message(self.config['messages']['removed'], ephemeral=True)

    @bday.command(name='when', description='Mostra il compleanno di un utente')
    @app_commands.describe(user='Utente (opzionale)')
    async def birthday_when(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        member = user or interaction.user
        db = await get_db()
        row = await (await db.execute('SELECT day, month, year FROM birthdays WHERE guild_id=? AND user_id=?', (interaction.guild.id, member.id))).fetchone()
        if not row:
            await interaction.response.send_message('Non trovato.', ephemeral=True)
            return
        d, m, y = int(row['day']), int(row['month']), row['year']
        date_str = f"{d:02d}/{m:02d}" + (f"/{str(y)[2:]}" if y else '')
        await interaction.response.send_message(self.config['messages']['when'].format(user=member.mention, date=date_str))

    @bday.command(name='next', description='Mostra i prossimi compleanni')
    async def birthday_next(self, interaction: discord.Interaction):
        db = await get_db()
        rows = await (await db.execute('SELECT user_id, day, month FROM birthdays WHERE guild_id=?', (interaction.guild.id,))).fetchall()
        if not rows:
            await interaction.response.send_message('Nessun compleanno registrato.', ephemeral=True)
            return
        import datetime
        today = datetime.date.today()
        def days_until(d, m):
            year = today.year if (m, d) >= (today.month, today.day) else today.year + 1
            try:
                target = datetime.date(year, m, d)
                return (target - today).days
            except Exception:
                return 9999
        upcoming = sorted([(r['user_id'], r['day'], r['month'], days_until(r['day'], r['month'])) for r in rows], key=lambda x: x[3])
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
                db = await get_db()
                rows = await (await db.execute('SELECT user_id FROM birthdays WHERE guild_id=? AND day=? AND month=?', (guild.id, today.day, today.month))).fetchall()
                if not rows:
                    continue
                ch_id = self.config.get('announce_channel_id')
                channel = guild.get_channel(int(ch_id)) if ch_id else (guild.system_channel or next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None))
                for r in rows:
                    user = guild.get_member(r['user_id'])
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
