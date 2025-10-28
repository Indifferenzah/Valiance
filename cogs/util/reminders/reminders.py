import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import re
import time
from typing import Optional

from bot_utils import owner_or_has_permissions
from db_utils import get_db, ensure_db_ready

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')


def load_config():
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {
            "enabled": True,
            "default_send_in_dm": True,
            "default_channel_id": None,
            "cooldown_seconds": 10,
            "max_per_user": 10,
            "timezone": "Europe/Rome",
            "messages": {
                "created": "✅ Promemoria creato per {time}.",
                "deleted": "🗑️ Promemoria eliminato.",
                "list_header": "📋 I tuoi promemoria:",
                "remind_format": "⏰ {mention} Promemoria: {message}",
                "no_reminders": "Non hai promemoria."
            }
        }


def parse_when(when: str) -> Optional[int]:
    when = when.strip()
    now = int(time.time())
    # Relative: 10m, 2h, 1d
    m = re.fullmatch(r"(\d+)\s*([smhd])", when, flags=re.I)
    if m:
        val = int(m.group(1))
        unit = m.group(2).lower()
        mult = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}[unit]
        return now + val * mult
    # Absolute: DD/MM/YY HH:MM
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2})\s+(\d{1,2}):(\d{2})", when)
    if m:
        import datetime
        d, mo, yy, hh, mm = map(int, m.groups())
        year = 2000 + yy
        try:
            dt = datetime.datetime(year, mo, d, hh, mm)
            return int(dt.timestamp())
        except Exception:
            return None
    return None


class RemindersCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config = load_config()
        self.dispatch_loop.start()

    def cog_unload(self):
        try:
            self.dispatch_loop.cancel()
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_ready(self):
        await ensure_db_ready()

    @app_commands.command(name='remind', description='Crea un promemoria')
    @app_commands.describe(when='Quando (es. 10m, 2h, 1d o DD/MM/YY HH:MM)', message='Messaggio del promemoria', send_in_dm='Se inviare in DM', channel='Canale dove ricordarti (se non in DM)')
    async def slash_remind(self, interaction: discord.Interaction, when: str, message: str, send_in_dm: Optional[bool] = None, channel: Optional[discord.TextChannel] = None):
        cfg = self.config
        due = parse_when(when)
        if not due or due <= int(time.time()):
            await interaction.response.send_message('Formato tempo non valido o nel passato.', ephemeral=True)
            return
        send_dm = cfg.get('default_send_in_dm', True) if send_in_dm is None else send_in_dm
        target_channel_id = None
        if not send_dm:
            if channel:
                target_channel_id = channel.id
            elif cfg.get('default_channel_id'):
                target_channel_id = int(cfg.get('default_channel_id'))
            else:
                target_channel_id = interaction.channel.id
        db = await get_db()
        # limit per user
        max_per_user = int(cfg.get('max_per_user', 10))
        c = await (await db.execute('SELECT COUNT(*) as c FROM reminders WHERE guild_id=? AND user_id=?', (interaction.guild.id, interaction.user.id))).fetchone()
        if c['c'] >= max_per_user:
            await interaction.response.send_message(f'Hai raggiunto il limite di {max_per_user} promemoria.', ephemeral=True)
            return
        await db.execute('INSERT INTO reminders (guild_id, user_id, channel_id, is_dm, message, remind_at, recurrence, created_at) VALUES (?,?,?,?,?,?,?,?)', (
            interaction.guild.id, interaction.user.id, target_channel_id, 1 if send_dm else 0, message, due, None, int(time.time())
        ))
        await db.commit()
        await interaction.response.send_message(cfg['messages']['created'].format(time=when), ephemeral=True)

    @app_commands.command(name='reminders', description='Lista i tuoi promemoria')
    async def slash_reminders(self, interaction: discord.Interaction):
        cfg = self.config
        db = await get_db()
        rows = await (await db.execute('SELECT id, channel_id, is_dm, message, remind_at FROM reminders WHERE guild_id=? AND user_id=? ORDER BY remind_at', (interaction.guild.id, interaction.user.id))).fetchall()
        if not rows:
            await interaction.response.send_message(cfg['messages']['no_reminders'], ephemeral=True)
            return
        desc = [cfg['messages']['list_header']]
        for r in rows:
            ts = f"<t:{r['remind_at']}:F>"
            dest = 'DM' if r['is_dm'] else (f"<#${r['channel_id']}>" if r['channel_id'] else '#current')
            desc.append(f"`#{r['id']}` {ts} → {dest} — {r['message']}")
        await interaction.response.send_message('\n'.join(desc), ephemeral=True)

    @app_commands.command(name='remind_delete', description='Elimina un tuo promemoria')
    @app_commands.describe(reminder_id='ID promemoria')
    async def slash_remind_delete(self, interaction: discord.Interaction, reminder_id: int):
        db = await get_db()
        row = await (await db.execute('SELECT user_id FROM reminders WHERE id=? AND guild_id=?', (reminder_id, interaction.guild.id))).fetchone()
        if not row:
            await interaction.response.send_message('Promemoria non trovato.', ephemeral=True)
            return
        if row['user_id'] != interaction.user.id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('Non puoi eliminare promemoria di altri.', ephemeral=True)
            return
        await db.execute('DELETE FROM reminders WHERE id=?', (reminder_id,))
        await db.commit()
        await interaction.response.send_message('🗑️ Promemoria eliminato.', ephemeral=True)

    @tasks.loop(seconds=30)
    async def dispatch_loop(self):
        await self.bot.wait_until_ready()
        try:
            db = await get_db()
            now = int(time.time())
            rows = await (await db.execute('SELECT id, guild_id, user_id, channel_id, is_dm, message FROM reminders WHERE remind_at <= ?', (now,))).fetchall()
            if not rows:
                return
            for r in rows:
                try:
                    guild = self.bot.get_guild(r['guild_id'])
                    if not guild:
                        continue
                    user = guild.get_member(r['user_id'])
                    if not user:
                        continue
                    content = self.config['messages']['remind_format'].format(mention=user.mention, message=r['message'])
                    if r['is_dm']:
                        try:
                            await user.send(content)
                        except Exception:
                            pass
                    else:
                        channel = guild.get_channel(r['channel_id']) if r['channel_id'] else None
                        if channel is None:
                            channel = guild.system_channel or next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)
                        if channel:
                            await channel.send(content)
                finally:
                    await db.execute('DELETE FROM reminders WHERE id=?', (r['id'],))
            await db.commit()
        except Exception:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(RemindersCog(bot))
