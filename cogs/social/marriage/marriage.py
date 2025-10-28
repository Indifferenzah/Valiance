import discord
from discord.ext import commands
from discord import app_commands
import json
import os
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
            "announce_channel_id": None,
            "messages": {
                "proposal": "💍 {proposer} ha chiesto di sposare {target}!",
                "accepted": "🎉 {proposer} e {target} ora sono sposati!",
                "declined": "❌ {target} ha rifiutato la proposta di {proposer}.",
                "already_married": "❌ Uno dei due è già in una relazione.",
                "not_married": "❌ Non sei in una relazione.",
                "divorced": "💔 {a} e {b} hanno divorziato.",
                "status": "💞 {a} è in relazione con {b} dal {date}."
            }
        }


async def is_user_married(db, guild_id: int, user_id: int) -> Optional[int]:
    r = await (await db.execute('SELECT user_id_a, user_id_b, started_at FROM marriages WHERE guild_id=? AND (user_id_a=? OR user_id_b=?)', (guild_id, user_id, user_id))).fetchone()
    return r


class ConsentView(discord.ui.View):
    def __init__(self, proposer_id: int, target: discord.Member, timeout: int = 60):
        super().__init__(timeout=timeout)
        self.proposer_id = proposer_id
        self.target_id = target.id
        self.result: Optional[bool] = None

    @discord.ui.button(label='Accetta', style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target_id:
            await interaction.response.send_message('Solo il destinatario può rispondere.', ephemeral=True)
            return
        self.result = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label='Rifiuta', style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target_id:
            await interaction.response.send_message('Solo il destinatario può rispondere.', ephemeral=True)
            return
        self.result = False
        self.stop()
        await interaction.response.defer()


class MarriageCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config = load_config()

    @commands.Cog.listener()
    async def on_ready(self):
        await ensure_db_ready()

    @app_commands.command(name='marry', description='Chiedi di sposare un utente')
    @app_commands.describe(user='Utente da sposare')
    async def slash_marry(self, interaction: discord.Interaction, user: discord.Member):
        if user.id == interaction.user.id or user.bot:
            await interaction.response.send_message('Non puoi sposarti da solo o con un bot.', ephemeral=True)
            return
        db = await get_db()
        # Check already married
        if await is_user_married(db, interaction.guild.id, interaction.user.id) or await is_user_married(db, interaction.guild.id, user.id):
            await interaction.response.send_message(self.config['messages']['already_married'], ephemeral=True)
            return
        msg = self.config['messages']['proposal'].format(proposer=interaction.user.mention, target=user.mention)
        view = ConsentView(interaction.user.id, user)
        await interaction.response.send_message(msg, view=view)
        await view.wait()
        if view.result is True:
            started = int(time.time())
            a, b = sorted((interaction.user.id, user.id))
            await db.execute('INSERT INTO marriages (guild_id, user_id_a, user_id_b, started_at) VALUES (?,?,?,?)', (interaction.guild.id, a, b, started))
            await db.commit()
            text = self.config['messages']['accepted'].format(proposer=interaction.user.mention, target=user.mention)
            # Announce
            ch_id = self.config.get('announce_channel_id')
            channel = interaction.guild.get_channel(int(ch_id)) if ch_id else interaction.channel
            await interaction.followup.send(text)
            if channel and channel.id != interaction.channel.id:
                await channel.send(text)
        else:
            await interaction.followup.send(self.config['messages']['declined'].format(proposer=interaction.user.mention, target=user.mention))

    @app_commands.command(name='divorce', description='Divorzia dalla tua relazione attuale')
    async def slash_divorce(self, interaction: discord.Interaction):
        db = await get_db()
        r = await is_user_married(db, interaction.guild.id, interaction.user.id)
        if not r:
            await interaction.response.send_message(self.config['messages']['not_married'], ephemeral=True)
            return
        a, b = r['user_id_a'], r['user_id_b']
        await db.execute('DELETE FROM marriages WHERE guild_id=? AND user_id_a=? AND user_id_b=?', (interaction.guild.id, a, b))
        await db.commit()
        user_a = interaction.guild.get_member(a)
        user_b = interaction.guild.get_member(b)
        await interaction.response.send_message(self.config['messages']['divorced'].format(a=user_a.mention if user_a else a, b=user_b.mention if user_b else b))

    @app_commands.command(name='relationship', description='Mostra lo stato della tua relazione o di un utente')
    @app_commands.describe(user='Utente (opzionale)')
    async def slash_relationship(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        member = user or interaction.user
        db = await get_db()
        r = await is_user_married(db, interaction.guild.id, member.id)
        if not r:
            await interaction.response.send_message('Nessuna relazione.', ephemeral=True)
            return
        a, b, started = r['user_id_a'], r['user_id_b'], r['started_at']
        partner_id = b if a == member.id else a
        partner = interaction.guild.get_member(partner_id)
        date = f"<t:{started}:D>"
        await interaction.response.send_message(self.config['messages']['status'].format(a=member.mention, b=partner.mention if partner else partner_id, date=date))


async def setup(bot: commands.Bot):
    await bot.add_cog(MarriageCog(bot))
