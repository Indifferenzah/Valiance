import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import re
import time
from typing import Optional

from bot_utils import owner_or_has_permissions
from json_store import load_json, save_json

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')
DATA_PATH = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')), 'data', 'reminders.json')


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
        # No DB init needed with JSON storage
        pass

    remind = app_commands.Group(name='remind', description='Sistema di reminder')

    @remind.command(name='add', description='Crea un promemoria')
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
        # JSON storage
        data = await load_json(DATA_PATH, {})
        gid = str(interaction.guild.id)
        uid = int(interaction.user.id)
        g = data.get(gid, {"last_id": 0, "items": []})
        # limit per user
        max_per_user = int(cfg.get('max_per_user', 10))
        user_count = sum(1 for it in g.get('items', []) if it.get('user_id') == uid)
        if user_count >= max_per_user:
            await interaction.response.send_message(f'Hai raggiunto il limite di {max_per_user} promemoria.', ephemeral=True)
            return
        new_id = int(g.get('last_id', 0)) + 1
        g['last_id'] = new_id
        g['items'] = g.get('items', [])
        g['items'].append({
            'id': new_id,
            'user_id': uid,
            'channel_id': int(target_channel_id) if target_channel_id else None,
            'is_dm': bool(send_dm),
            'message': message,
            'remind_at': int(due),
            'created_at': int(time.time())
        })
        data[gid] = g
        await save_json(DATA_PATH, data)
        await interaction.response.send_message(cfg['messages']['created'].format(time=when), ephemeral=True)

    @remind.command(name='list', description='Lista i tuoi promemoria')
    async def slash_reminders(self, interaction: discord.Interaction):
        cfg = self.config
        data = await load_json(DATA_PATH, {})
        gid = str(interaction.guild.id)
        uid = int(interaction.user.id)
        g = data.get(gid, {"items": []})
        rows = sorted([it for it in g.get('items', []) if it.get('user_id') == uid], key=lambda it: it.get('remind_at', 0))
        if not rows:
            await interaction.response.send_message(cfg['messages']['no_reminders'], ephemeral=True)
            return
        desc = [cfg['messages']['list_header']]
        for r in rows:
            ts = f"<t:{int(r.get('remind_at', 0))}:F>"
            dest = 'DM' if r.get('is_dm') else (f"<#{int(r.get('channel_id'))}>" if r.get('channel_id') else '#current')
            desc.append(f"`#{r.get('id')}` {ts} → {dest} — {r.get('message')}")
        await interaction.response.send_message('\n'.join(desc), ephemeral=True)

    @remind.command(name='delete', description='Elimina un tuo promemoria')
    @app_commands.describe(reminder_id='ID promemoria')
    async def slash_remind_delete(self, interaction: discord.Interaction, reminder_id: int):
        data = await load_json(DATA_PATH, {})
        gid = str(interaction.guild.id)
        uid = int(interaction.user.id)
        g = data.get(gid, {"items": []})
        items = g.get('items', [])
        found = next((it for it in items if int(it.get('id')) == int(reminder_id)), None)
        if not found:
            await interaction.response.send_message('Promemoria non trovato.', ephemeral=True)
            return
        if found.get('user_id') != uid and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('Non puoi eliminare promemoria di altri.', ephemeral=True)
            return
        items = [it for it in items if int(it.get('id')) != int(reminder_id)]
        g['items'] = items
        data[gid] = g
        await save_json(DATA_PATH, data)
        await interaction.response.send_message('🗑️ Promemoria eliminato.', ephemeral=True)

    @tasks.loop(seconds=30)
    async def dispatch_loop(self):
        await self.bot.wait_until_ready()
        try:
            now = int(time.time())
            data = await load_json(DATA_PATH, {})
            changed = False
            for gid, g in list(data.items()):
                items = g.get('items', [])
                remaining = []
                for r in items:
                    if int(r.get('remind_at', 0)) > now:
                        remaining.append(r)
                        continue
                    try:
                        guild = self.bot.get_guild(int(gid))
                        if not guild:
                            continue
                        user = guild.get_member(int(r.get('user_id')))
                        if not user:
                            continue
                        content = self.config['messages']['remind_format'].format(mention=user.mention, message=r.get('message'))
                        if r.get('is_dm'):
                            try:
                                await user.send(content)
                            except Exception:
                                pass
                        else:
                            ch_id = r.get('channel_id')
                            channel = guild.get_channel(int(ch_id)) if ch_id else None
                            if channel is None:
                                channel = guild.system_channel or next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)
                            if channel:
                                await channel.send(content)
                    finally:
                        changed = True
                if changed:
                    g['items'] = remaining
                    data[gid] = g
            if changed:
                await save_json(DATA_PATH, data)
        except Exception:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(RemindersCog(bot))
