import discord
from discord.ext import commands
from discord import app_commands
from bot_utils import is_owner
import json
import os
from console_logger import logger

class AutoRoleCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.autorole_config = {}
        if os.path.exists('autorole.json'):
            with open('autorole.json', 'r', encoding='utf-8') as f:
                try:
                    self.autorole_config = json.load(f)
                except Exception:
                    self.autorole_config = {}

    def save_config(self):
        with open('autorole.json', 'w', encoding='utf-8') as f:
            json.dump(self.autorole_config, f, indent=2, ensure_ascii=False)

    @app_commands.command(name='createreact', description='Crea un messaggio di reazione per assegnare ruoli')
    @app_commands.describe(message_id='ID del messaggio esistente', emoji='Emoji da usare per la reazione', role='Ruolo da assegnare')
    async def slash_createreact(self, interaction: discord.Interaction, message_id: str, emoji: str, role: discord.Role):
        if not interaction.user.guild_permissions.administrator and not is_owner(interaction.user):
            await interaction.response.send_message('❌ Non hai i permessi per usare questo comando!', ephemeral=True)
            return

        try:
            message_id = int(message_id)
        except ValueError:
            await interaction.response.send_message('❌ ID messaggio non valido!', ephemeral=True)
            return

        try:
            message = await interaction.channel.fetch_message(message_id)
        except discord.NotFound:
            await interaction.response.send_message('❌ Messaggio non trovato in questo canale!', ephemeral=True)
            return

        try:
            await message.add_reaction(emoji)
        except Exception:
            await interaction.response.send_message('❌ Emoji non valida!', ephemeral=True)
            return

        key = f"{interaction.guild.id}_{interaction.channel.id}_{message_id}"
        if key not in self.autorole_config:
            self.autorole_config[key] = {}
        self.autorole_config[key][emoji] = role.id
        self.save_config()

        await interaction.response.send_message(f'✅ Configurazione completata! Reagisci con {emoji} al messaggio per ottenere il ruolo {role.mention}.', ephemeral=True)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.user_id == self.bot.user.id:
            return

        key = f"{payload.guild_id}_{payload.channel_id}_{payload.message_id}"
        if key in self.autorole_config and str(payload.emoji) in self.autorole_config[key]:
            guild = self.bot.get_guild(payload.guild_id)
            if not guild:
                return

            member = guild.get_member(payload.user_id)
            if not member:
                return

            role_id = self.autorole_config[key][str(payload.emoji)]
            role = guild.get_role(role_id)
            if not role:
                return

            try:
                await member.add_roles(role)
                logger.info(f'Ruolo {role.name} assegnato a {member.name}#{member.discriminator} ({member.id})')
                log_cog = self.bot.get_cog('LogCog')
                if log_cog:
                    await log_cog.log_autorole_add(member, role)
            except Exception as e:
                logger.error(f'Errore nell\'assegnazione del ruolo {role.name} a {member.name}#{member.discriminator} ({member.id}): {e}')

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        if payload.user_id == self.bot.user.id:
            return

        key = f"{payload.guild_id}_{payload.channel_id}_{payload.message_id}"
        if key in self.autorole_config and str(payload.emoji) in self.autorole_config[key]:
            guild = self.bot.get_guild(payload.guild_id)
            if not guild:
                return

            member = guild.get_member(payload.user_id)
            if not member:
                return

            role_id = self.autorole_config[key][str(payload.emoji)]
            role = guild.get_role(role_id)
            if not role:
                return

            try:
                await member.remove_roles(role)
                logger.info(f'Ruolo {role.name} rimosso da {member.name}#{member.discriminator} ({member.id})')
                log_cog = self.bot.get_cog('LogCog')
                if log_cog:
                    await log_cog.log_autorole_remove(member, role)
            except Exception as e:
                logger.error(f'Errore nella rimozione del ruolo {role.name} da {member.name}#{member.discriminator} ({member.id}): {e}')

async def setup(bot):
    await bot.add_cog(AutoRoleCog(bot))
