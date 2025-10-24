import discord
from discord.ext import commands
from discord import app_commands
import random

class FunCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="userinfo", description="Mostra informazioni su un utente")
    async def userinfo(self, interaction: discord.Interaction, user: discord.Member = None):
        user = user or interaction.user
        roles = [r.mention for r in user.roles[1:]] or ["Nessun ruolo"]
        embed = discord.Embed(
            title=f"👤 Informazioni su {user.name}",
            color=user.color if user.color.value != 0 else discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_thumbnail(url=user.avatar.url if user.avatar else user.default_avatar.url)
        embed.add_field(name="🆔 ID", value=user.id, inline=True)
        embed.add_field(name="📅 Account creato il", value=user.created_at.strftime("%d/%m/%Y %H:%M"), inline=True)
        embed.add_field(name="📥 Entrato nel server il", value=user.joined_at.strftime("%d/%m/%Y %H:%M") if user.joined_at else "N/A", inline=True)
        embed.add_field(name="🔰 Ruoli", value=", ".join(roles), inline=False)
        embed.add_field(name="🧱 È bot?", value="✅ Sì" if user.bot else "❌ No", inline=True)
        embed.add_field(name="🎨 Colore ruolo", value=str(user.color), inline=True)
        embed.set_footer(text=f"Richiesto da {interaction.user.name}", icon_url=interaction.user.avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="serverinfo", description="Mostra informazioni sul server")
    async def serverinfo(self, interaction: discord.Interaction):
        g = interaction.guild
        online = sum(1 for m in g.members if m.status != discord.Status.offline)
        embed = discord.Embed(
            title=f"🏰 {g.name}",
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_thumbnail(url=g.icon.url if g.icon else None)
        embed.add_field(name="🆔 ID Server", value=g.id, inline=True)
        embed.add_field(name="👑 Proprietario", value=f"{g.owner.mention} ({g.owner})", inline=True)
        embed.add_field(name="📅 Creato il", value=g.created_at.strftime("%d/%m/%Y %H:%M"), inline=True)
        embed.add_field(name="👥 Membri", value=f"{g.member_count} totali\n🟢 {online} online", inline=True)
        embed.add_field(name="💬 Canali", value=f"{len(g.text_channels)} testo / {len(g.voice_channels)} vocali", inline=True)
        embed.add_field(name="🎭 Ruoli", value=len(g.roles), inline=True)
        embed.add_field(name="🪪 Boost Level", value=f"{g.premium_tier} ({g.premium_subscription_count} boost)", inline=True)
        embed.add_field(name="🌍 Regione", value=str(g.preferred_locale).upper(), inline=True)
        embed.set_footer(text=f"Richiesto da {interaction.user.name}", icon_url=interaction.user.avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="avatar", description="Mostra l'avatar di un utente")
    async def avatar(self, interaction: discord.Interaction, user: discord.Member = None):
        user = user or interaction.user
        embed = discord.Embed(title=f"Avatar di {user.name}", color=discord.Color.random())
        embed.set_image(url=user.avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="coinflip", description="Lancia una moneta")
    async def coinflip(self, interaction: discord.Interaction):
        await interaction.response.send_message(random.choice(["🪙 Testa", "🪙 Croce"]))

    @app_commands.command(name="roll", description="Tira un dado")
    @app_commands.describe(max="Numero massimo (default 6)")
    async def roll(self, interaction: discord.Interaction, max: int = 6):
        n = random.randint(1, max)
        await interaction.response.send_message(f"🎲 Hai tirato un {n}")

async def setup(bot):
    await bot.add_cog(FunCog(bot))
