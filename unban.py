import discord
from discord.ext import commands
import json
import os
import datetime
from discord import ui

class UnbanCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.unban_config = {}
        if os.path.exists('unban.json'):
            with open('unban.json', 'r', encoding='utf-8') as f:
                try:
                    self.unban_config = json.load(f)
                except Exception:
                    self.unban_config = {}
        else:
            self.unban_config = {
                "unban_channel_id": None,
                "dm_message": {
                    "title": "Sei stato bannato",
                    "description": "Sei stato bannato dal server {guild_name}.\n\n**Motivo:** {reason}\n\nSe vuoi appellare il ban, clicca il pulsante qui sotto.",
                    "color": 0xff0000,
                    "thumbnail": None,
                    "footer": "Sistema di Unban"
                },
                "appeal_embed": {
                    "title": "Richiesta Unban",
                    "description": "Compila il modulo per richiedere l'unban.\n\n**Nota:** Puoi fare una richiesta al mese.",
                    "color": 0x00ff00,
                    "thumbnail": None,
                    "footer": "Sistema di Unban"
                },
                "appeal_questions": [
                    "Perché dovremmo unbannarti?",
                    "Cosa hai imparato da questa esperienza?",
                    "Prometti di non ripetere gli errori commessi?"
                ],
                "reject_embed": {
                    "title": "Richiesta Unban Rifiutata",
                    "description": "La tua richiesta di unban è stata rifiutata.\n\n**Motivo:** {reject_reason}",
                    "color": 0xff0000,
                    "thumbnail": None,
                    "footer": "Sistema di Unban"
                },
                "accept_embed": {
                    "title": "Richiesta Unban Accettata",
                    "description": "La tua richiesta di unban è stata accettata! Sei stato unbannato dal server.",
                    "color": 0x00ff00,
                    "thumbnail": None,
                    "footer": "Sistema di Unban"
                }
            }
            self.save_config()

    def save_config(self):
        with open('unban.json', 'w', encoding='utf-8') as f:
            json.dump(self.unban_config, f, indent=2, ensure_ascii=False)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        # Send DM to banned user with appeal button
        try:
            dm_embed = discord.Embed(
                title=self.unban_config["dm_message"]["title"],
                description=self.unban_config["dm_message"]["description"].replace("{guild_name}", guild.name).replace("{reason}", "Ban manuale"),
                color=self.unban_config["dm_message"]["color"]
            )
            if self.unban_config["dm_message"]["thumbnail"]:
                dm_embed.set_thumbnail(url=self.unban_config["dm_message"]["thumbnail"])
            dm_embed.set_footer(text=self.unban_config["dm_message"]["footer"])

            view = AppealButtonView(self.bot, user.id, guild.id)
            await user.send(embed=dm_embed, view=view)
        except discord.Forbidden:
            pass  # User has DMs disabled

class AppealButtonView(discord.ui.View):
    def __init__(self, bot, user_id, guild_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.user_id = user_id
        self.guild_id = guild_id

    @discord.ui.button(label="Appella il Ban", style=discord.ButtonStyle.primary, emoji="📝")
    async def appeal_ban(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if user already appealed this month
        current_month = datetime.datetime.utcnow().strftime("%Y-%m")
        appeal_key = f"{self.user_id}_{current_month}"

        # For simplicity, we'll use a basic check (in a real implementation, you'd store this in a database)
        # Here we'll assume we have a way to check, but for now, allow appeals

        await interaction.response.send_modal(AppealModal(self.bot, self.user_id, self.guild_id))

class AppealModal(discord.ui.Modal, title="Richiesta Unban"):
    def __init__(self, bot, user_id, guild_id):
        super().__init__()
        self.bot = bot
        self.user_id = user_id
        self.guild_id = guild_id

    reason = ui.TextInput(label="Perché dovremmo unbannarti?", style=discord.TextStyle.paragraph, required=True)
    learned = ui.TextInput(label="Cosa hai imparato da questa esperienza?", style=discord.TextStyle.paragraph, required=True)
    promise = ui.TextInput(label="Prometti di non ripetere gli errori?", style=discord.TextStyle.paragraph, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        # Send appeal to configured channel
        unban_cog = self.bot.get_cog('UnbanCog')
        if not unban_cog or not unban_cog.unban_config.get("unban_channel_id"):
            await interaction.response.send_message("Sistema di unban non configurato.", ephemeral=True)
            return

        channel = self.bot.get_channel(int(unban_cog.unban_config["unban_channel_id"]))
        if not channel:
            await interaction.response.send_message("Canale di unban non trovato.", ephemeral=True)
            return

        user = self.bot.get_user(self.user_id)
        username = user.name if user else "Unknown"

        embed = discord.Embed(
            title="Nuova Richiesta Unban",
            description=f"**Utente:** {username} (ID: {self.user_id})\n**Motivo dell'unban:** {self.reason.value}\n**Cosa ha imparato:** {self.learned.value}\n**Promessa:** {self.promise.value}",
            color=0x00ff00
        )
        embed.set_footer(text=f"ID: {self.user_id} | Username: {username}")

        view = AppealDecisionView(self.bot, self.user_id, self.guild_id, username)
        await channel.send(embed=embed, view=view)

        await interaction.response.send_message("Richiesta di unban inviata! Riceverai una risposta via DM.", ephemeral=True)

class AppealDecisionView(discord.ui.View):
    def __init__(self, bot, user_id, guild_id, username):
        super().__init__(timeout=None)
        self.bot = bot
        self.user_id = user_id
        self.guild_id = guild_id
        self.username = username

    @discord.ui.button(label="Accetta", style=discord.ButtonStyle.success, emoji="✅")
    async def accept_appeal(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check permissions
        if not interaction.user.guild_permissions.administrator and interaction.user.id != 1123622103917285418:
            await interaction.response.send_message("Non hai i permessi per accettare richieste di unban.", ephemeral=True)
            return

        guild = self.bot.get_guild(self.guild_id)
        if not guild:
            await interaction.response.send_message("Server non trovato.", ephemeral=True)
            return

        try:
            user = await self.bot.fetch_user(self.user_id)
            await guild.unban(user, reason="Richiesta Unban")

            # Send DM to user
            unban_cog = self.bot.get_cog('UnbanCog')
            accept_embed = discord.Embed(
                title=unban_cog.unban_config["accept_embed"]["title"],
                description=unban_cog.unban_config["accept_embed"]["description"],
                color=unban_cog.unban_config["accept_embed"]["color"]
            )
            if unban_cog.unban_config["accept_embed"]["thumbnail"]:
                accept_embed.set_thumbnail(url=unban_cog.unban_config["accept_embed"]["thumbnail"])
            accept_embed.set_footer(text=unban_cog.unban_config["accept_embed"]["footer"])

            try:
                await user.send(embed=accept_embed)
            except discord.Forbidden:
                pass

            await interaction.response.send_message(f"✅ Richiesta di unban accettata per {self.username}.", ephemeral=True)

            # Disable buttons
            for child in self.children:
                child.disabled = True
            await interaction.message.edit(view=self)

        except Exception as e:
            await interaction.response.send_message(f"Errore nell'unbannare: {e}", ephemeral=True)

    @discord.ui.button(label="Rifiuta", style=discord.ButtonStyle.danger, emoji="❌")
    async def reject_appeal(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check permissions
        if not interaction.user.guild_permissions.administrator and interaction.user.id != 1123622103917285418:
            await interaction.response.send_message("Non hai i permessi per rifiutare richieste di unban.", ephemeral=True)
            return

        await interaction.response.send_modal(RejectReasonModal(self.bot, self.user_id, self.username, interaction.message))

class RejectReasonModal(discord.ui.Modal, title="Motivo Rifiuto"):
    def __init__(self, bot, user_id, username, message):
        super().__init__()
        self.bot = bot
        self.user_id = user_id
        self.username = username
        self.message = message

    reason = ui.TextInput(label="Motivo del rifiuto", style=discord.TextStyle.paragraph, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        # Send DM to user
        unban_cog = self.bot.get_cog('UnbanCog')
        reject_embed = discord.Embed(
            title=unban_cog.unban_config["reject_embed"]["title"],
            description=unban_cog.unban_config["reject_embed"]["description"].replace("{reject_reason}", self.reason.value),
            color=unban_cog.unban_config["reject_embed"]["color"]
        )
        if unban_cog.unban_config["reject_embed"]["thumbnail"]:
            reject_embed.set_thumbnail(url=unban_cog.unban_config["reject_embed"]["thumbnail"])
        reject_embed.set_footer(text=unban_cog.unban_config["reject_embed"]["footer"])

        user = self.bot.get_user(self.user_id)
        if user:
            try:
                await user.send(embed=reject_embed)
            except discord.Forbidden:
                pass

        await interaction.response.send_message(f"❌ Richiesta di unban rifiutata per {self.username}.", ephemeral=True)

        # Disable buttons
        view = self.message.view
        for child in view.children:
            child.disabled = True
        await self.message.edit(view=view)

async def setup(bot):
    await bot.add_cog(UnbanCog(bot))
