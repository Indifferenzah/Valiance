import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import time
from typing import Optional

from bot_utils import owner_or_has_permissions
from json_store import load_json, save_json

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')
DATA_PATH = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')), 'data', 'marriages.json')


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


async def is_user_married_json(guild_id: int, user_id: int):
    data = await load_json(DATA_PATH, {})
    gid = str(guild_id)
    pairs = data.get(gid, {}).get('pairs', [])
    for p in pairs:
        a = int(p.get('a'))
        b = int(p.get('b'))
        if a == int(user_id) or b == int(user_id):
            return {'user_id_a': a, 'user_id_b': b, 'started_at': int(p.get('started_at', 0))}
    return None


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
        # No DB init with JSON storage
        pass

    @app_commands.command(name='marry', description='Chiedi di sposare un utente')
    @app_commands.describe(user='Utente da sposare')
    async def slash_marry(self, interaction: discord.Interaction, user: discord.Member):
        if user.id == interaction.user.id or user.bot:
            await interaction.response.send_message('Non puoi sposarti da solo o con un bot.', ephemeral=True)
            return
        # Check already married
        if await is_user_married_json(interaction.guild.id, interaction.user.id) or await is_user_married_json(interaction.guild.id, user.id):
            await interaction.response.send_message(self.config['messages']['already_married'], ephemeral=True)
            return
        msg = self.config['messages']['proposal'].format(proposer=interaction.user.mention, target=user.mention)
        view = ConsentView(interaction.user.id, user)
        await interaction.response.send_message(msg, view=view)
        await view.wait()
        if view.result is True:
            started = int(time.time())
            a, b = sorted((interaction.user.id, user.id))
            data = await load_json(DATA_PATH, {})
            gid = str(interaction.guild.id)
            g = data.get(gid, {"pairs": []})
            pairs = g.get('pairs', [])
            pairs.append({"a": int(a), "b": int(b), "started_at": started})
            g['pairs'] = pairs
            data[gid] = g
            await save_json(DATA_PATH, data)
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
        r = await is_user_married_json(interaction.guild.id, interaction.user.id)
        if not r:
            await interaction.response.send_message(self.config['messages']['not_married'], ephemeral=True)
            return
        a, b = r['user_id_a'], r['user_id_b']
        data = await load_json(DATA_PATH, {})
        gid = str(interaction.guild.id)
        g = data.get(gid, {"pairs": []})
        pairs = g.get('pairs', [])
        pairs = [p for p in pairs if not ((int(p.get('a')) == int(a) and int(p.get('b')) == int(b)) or (int(p.get('a')) == int(b) and int(p.get('b')) == int(a)))]
        g['pairs'] = pairs
        data[gid] = g
        await save_json(DATA_PATH, data)
        user_a = interaction.guild.get_member(a)
        user_b = interaction.guild.get_member(b)
        await interaction.response.send_message(self.config['messages']['divorced'].format(a=user_a.mention if user_a else a, b=user_b.mention if user_b else b))

    @app_commands.command(name='relationship', description='Mostra lo stato della tua relazione o di un utente')
    @app_commands.describe(user='Utente (opzionale)')
    async def slash_relationship(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        member = user or interaction.user
        r = await is_user_married_json(interaction.guild.id, member.id)
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
