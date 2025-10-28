import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import time
from typing import Optional

from json_store import load_json, save_json

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')
DATA_PATH = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')), 'data', 'reputation.json')


def load_config():
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {
            "enabled": True,
            "allow_negative": True,
            "cooldown_seconds": 43200,
            "daily_limit": 5,
            "log_channel_id": None,
            "messages": {
                "given": "✅ {from_user} ha assegnato {delta} rep a {to_user} ({reason}). Totale: {total}.",
                "cooldown": "⏳ Devi attendere prima di poter assegnare rep di nuovo a {to_user}.",
                "daily_limit": "🚫 Hai raggiunto il limite giornaliero di rep.",
                "show": "⭐ Reputation di {user}: {total}",
                "negative_disabled": "❌ Il -rep è disabilitato."
            }
        }


class ReputationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config = load_config()

    @commands.Cog.listener()
    async def on_ready(self):
        # No DB init needed with JSON storage
        pass

    rep = app_commands.Group(name='rep', description='Sistema di reputation')

    @rep.command(name='add', description='Dai +rep a un utente')
    @app_commands.describe(user='Utente', reason='Motivo (opzionale)')
    async def rep_add(self, interaction: discord.Interaction, user: discord.Member, reason: Optional[str] = None):
        await self._give_rep(interaction, user, +1, reason)

    @rep.command(name='remove', description='Dai -rep a un utente')
    @app_commands.describe(user='Utente', reason='Motivo (opzionale)')
    async def rep_remove(self, interaction: discord.Interaction, user: discord.Member, reason: Optional[str] = None):
        if not self.config.get('allow_negative', True):
            await interaction.response.send_message(self.config['messages']['negative_disabled'], ephemeral=True)
            return
        await self._give_rep(interaction, user, -1, reason)

    @rep.command(name='show', description='Mostra la reputation di un utente')
    @app_commands.describe(user='Utente (opzionale)')
    async def rep_show(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        member = user or interaction.user
        data = await load_json(DATA_PATH, {})
        gid = str(interaction.guild.id)
        totals = data.get(gid, {}).get('totals', {})
        total = int(totals.get(str(member.id), 0))
        await interaction.response.send_message(self.config['messages']['show'].format(user=member.mention, total=total))

    async def _give_rep(self, interaction: discord.Interaction, user: discord.Member, delta: int, reason: Optional[str]):
        if user.id == interaction.user.id or user.bot:
            await interaction.response.send_message('Non puoi assegnare rep a te stesso o a un bot.', ephemeral=True)
            return
        now = int(time.time())
        cfg = self.config
        data = await load_json(DATA_PATH, {})
        gid = str(interaction.guild.id)
        g = data.get(gid, {"totals": {}, "logs": []})
        logs = g.get('logs', [])
        # cooldown per coppia (from -> to)
        cooldown = int(cfg.get('cooldown_seconds', 43200))
        last_entry = next((log for log in reversed(logs) if log.get('from') == int(interaction.user.id) and log.get('to') == int(user.id)), None)
        if last_entry and now - int(last_entry.get('created_at', 0)) < cooldown:
            await interaction.response.send_message(cfg['messages']['cooldown'].format(to_user=user.mention), ephemeral=True)
            return
        # daily limit per utente (from)
        day_ago = now - 86400
        given_today = sum(1 for log in logs if log.get('from') == int(interaction.user.id) and int(log.get('created_at', 0)) >= day_ago)
        if given_today >= int(cfg.get('daily_limit', 5)):
            await interaction.response.send_message(cfg['messages']['daily_limit'], ephemeral=True)
            return
        # apply
        totals = g.get('totals', {})
        cur = int(totals.get(str(user.id), 0))
        new_total = cur + int(delta)
        totals[str(user.id)] = new_total
        g['totals'] = totals
        logs.append({
            'from': int(interaction.user.id),
            'to': int(user.id),
            'delta': int(delta),
            'reason': reason,
            'created_at': now
        })
        g['logs'] = logs
        data[gid] = g
        await save_json(DATA_PATH, data)
        msg = cfg['messages']['given'].format(from_user=interaction.user.mention, delta=('+' if delta>0 else '')+str(delta), to_user=user.mention, reason=(reason or 'nessun motivo'), total=new_total)
        await interaction.response.send_message(msg)
        # log channel
        ch_id = cfg.get('log_channel_id')
        if ch_id:
            try:
                ch = interaction.guild.get_channel(int(ch_id))
                if ch and ch.id != interaction.channel.id:
                    await ch.send(msg)
            except Exception:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(ReputationCog(bot))
