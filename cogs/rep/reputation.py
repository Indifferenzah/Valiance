import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import time
from typing import Optional

from db_utils import get_db, ensure_db_ready

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')


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
        await ensure_db_ready()

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
        db = await get_db()
        row = await (await db.execute('SELECT rep FROM reputation WHERE guild_id=? AND user_id=?', (interaction.guild.id, member.id))).fetchone()
        total = int(row['rep']) if row else 0
        await interaction.response.send_message(self.config['messages']['show'].format(user=member.mention, total=total))

    async def _give_rep(self, interaction: discord.Interaction, user: discord.Member, delta: int, reason: Optional[str]):
        if user.id == interaction.user.id or user.bot:
            await interaction.response.send_message('Non puoi assegnare rep a te stesso o a un bot.', ephemeral=True)
            return
        db = await get_db()
        now = int(time.time())
        # cooldown per coppia
        cooldown = int(self.config.get('cooldown_seconds', 43200))
        last = await (await db.execute('SELECT created_at FROM reputation_logs WHERE guild_id=? AND from_user_id=? AND to_user_id=? ORDER BY created_at DESC LIMIT 1', (interaction.guild.id, interaction.user.id, user.id))).fetchone()
        if last and now - int(last['created_at']) < cooldown:
            await interaction.response.send_message(self.config['messages']['cooldown'].format(to_user=user.mention), ephemeral=True)
            return
        # daily limit per utente
        day_ago = now - 86400
        cnt_row = await (await db.execute('SELECT COUNT(*) as c FROM reputation_logs WHERE guild_id=? AND from_user_id=? AND created_at>=?', (interaction.guild.id, interaction.user.id, day_ago))).fetchone()
        if int(cnt_row['c']) >= int(self.config.get('daily_limit', 5)):
            await interaction.response.send_message(self.config['messages']['daily_limit'], ephemeral=True)
            return
        # apply
        cur = await (await db.execute('SELECT rep FROM reputation WHERE guild_id=? AND user_id=?', (interaction.guild.id, user.id))).fetchone()
        new_total = (int(cur['rep']) if cur else 0) + delta
        if cur:
            await db.execute('UPDATE reputation SET rep=? WHERE guild_id=? AND user_id=?', (new_total, interaction.guild.id, user.id))
        else:
            await db.execute('INSERT INTO reputation (guild_id, user_id, rep) VALUES (?,?,?)', (interaction.guild.id, user.id, new_total))
        await db.execute('INSERT INTO reputation_logs (guild_id, from_user_id, to_user_id, delta, reason, created_at) VALUES (?,?,?,?,?,?)', (interaction.guild.id, interaction.user.id, user.id, delta, reason, now))
        await db.commit()
        msg = self.config['messages']['given'].format(from_user=interaction.user.mention, delta=('+' if delta>0 else '')+str(delta), to_user=user.mention, reason=(reason or 'nessun motivo'), total=new_total)
        await interaction.response.send_message(msg)
        # log channel
        ch_id = self.config.get('log_channel_id')
        if ch_id:
            try:
                ch = interaction.guild.get_channel(int(ch_id))
                if ch and ch.id != interaction.channel.id:
                    await ch.send(msg)
            except Exception:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(ReputationCog(bot))
