import discord
from discord.ext import commands
from discord import app_commands
from bot_utils import is_owner
import json
import os

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

    @commands.command(name='createreact')
    async def createreact(self, ctx):
        """Crea un messaggio di reazione per assegnare ruoli automaticamente"""
        if not ctx.author.guild_permissions.administrator and not is_owner(ctx.author):
            await ctx.send('❌ Non hai i permessi per usare questo comando!')
            return

        await ctx.send('📝 Invia il link del messaggio esistente su cui vuoi aggiungere la reazione per il ruolo.')

        def check_link(m):
            return m.author == ctx.author and m.channel == ctx.channel and 'discord.com/channels/' in m.content

        try:
            link_msg = await self.bot.wait_for('message', check=check_link, timeout=60.0)
            link = link_msg.content.strip()

            parts = link.split('/')
            if len(parts) < 7:
                await ctx.send('❌ Link non valido! Assicurati che sia un link completo a un messaggio.')
                return

            guild_id = int(parts[4])
            channel_id = int(parts[5])
            message_id = int(parts[6])

            if guild_id != ctx.guild.id:
                await ctx.send('❌ Il messaggio deve essere in questo server!')
                return

            channel = ctx.guild.get_channel(channel_id)
            if not channel:
                await ctx.send('❌ Canale non trovato!')
                return

            try:
                message = await channel.fetch_message(message_id)
            except discord.NotFound:
                await ctx.send('❌ Messaggio non trovato!')
                return

            await ctx.send('✅ Messaggio trovato! Ora invia l\'emoji da usare per la reazione.')

            def check_emoji(m):
                return m.author == ctx.author and m.channel == ctx.channel

            emoji_msg = await self.bot.wait_for('message', check=check_emoji, timeout=60.0)
            emoji = emoji_msg.content.strip()

            try:
                await ctx.message.add_reaction(emoji)
                await ctx.message.remove_reaction(emoji, ctx.me)
            except:
                await ctx.send('❌ Emoji non valida!')
                return

            await ctx.send('✅ Emoji valida! Ora pinga il ruolo da assegnare quando si reagisce con questa emoji.')

            def check_role(m):
                return m.author == ctx.author and m.channel == ctx.channel and len(m.role_mentions) > 0

            role_msg = await self.bot.wait_for('message', check=check_role, timeout=60.0)
            role = role_msg.role_mentions[0]

            key = f"{guild_id}_{channel_id}_{message_id}"
            if key not in self.autorole_config:
                self.autorole_config[key] = {}
            self.autorole_config[key][emoji] = role.id
            self.save_config()

            try:
                await message.add_reaction(emoji)
                await ctx.send(f'✅ Configurazione completata! Reagisci con {emoji} al messaggio per ottenere il ruolo {role.mention}.')
            except Exception as e:
                await ctx.send(f'❌ Errore nell\'aggiungere la reazione: {e}')

        except TimeoutError:
            await ctx.send('❌ Timeout! Riprova il comando.')

    @app_commands.command(name='createreact', description='Crea un messaggio di reazione per assegnare ruoli')
    async def slash_createreact(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator and not is_owner(interaction.user):
            await interaction.response.send_message('❌ Non hai i permessi per usare questo comando!', ephemeral=True)
            return

        await interaction.response.send_message('📝 Invia il link del messaggio esistente su cui vuoi aggiungere la reazione per il ruolo.', ephemeral=True)

        def check_link(m):
            return m.author == interaction.user and m.channel == interaction.channel and 'discord.com/channels/' in m.content

        try:
            link_msg = await self.bot.wait_for('message', check=check_link, timeout=60.0)
            link = link_msg.content.strip()

            parts = link.split('/')
            if len(parts) < 7:
                await interaction.followup.send('❌ Link non valido! Assicurati che sia un link completo a un messaggio.', ephemeral=True)
                return

            guild_id = int(parts[4])
            channel_id = int(parts[5])
            message_id = int(parts[6])

            if guild_id != interaction.guild.id:
                await interaction.followup.send('❌ Il messaggio deve essere in questo server!', ephemeral=True)
                return

            channel = interaction.guild.get_channel(channel_id)
            if not channel:
                await interaction.followup.send('❌ Canale non trovato!', ephemeral=True)
                return

            try:
                message = await channel.fetch_message(message_id)
            except discord.NotFound:
                await interaction.followup.send('❌ Messaggio non trovato!', ephemeral=True)
                return

            await interaction.followup.send('✅ Messaggio trovato! Ora invia l\'emoji da usare per la reazione.', ephemeral=True)

            def check_emoji(m):
                return m.author == interaction.user and m.channel == interaction.channel

            emoji_msg = await self.bot.wait_for('message', check=check_emoji, timeout=60.0)
            emoji = emoji_msg.content.strip()

            try:
                await interaction.message.add_reaction(emoji)
                await interaction.message.remove_reaction(emoji, self.bot.user)
            except Exception:
                await interaction.followup.send('❌ Emoji non valida!', ephemeral=True)
                return

            await interaction.followup.send('✅ Emoji valida! Ora pinga il ruolo da assegnare quando si reagisce con questa emoji.', ephemeral=True)

            def check_role(m):
                return m.author == interaction.user and m.channel == interaction.channel and len(m.role_mentions) > 0

            role_msg = await self.bot.wait_for('message', check=check_role, timeout=60.0)
            role = role_msg.role_mentions[0]

            key = f"{guild_id}_{channel_id}_{message_id}"
            if key not in self.autorole_config:
                self.autorole_config[key] = {}
            self.autorole_config[key][emoji] = role.id
            self.save_config()

            try:
                await message.add_reaction(emoji)
                await interaction.followup.send(f'✅ Configurazione completata! Reagisci con {emoji} al messaggio per ottenere il ruolo {role.mention}.', ephemeral=False)
            except Exception as e:
                await interaction.followup.send(f'❌ Errore nell\'aggiungere la reazione: {e}', ephemeral=True)

        except TimeoutError:
            await interaction.followup.send('❌ Timeout! Riprova il comando.', ephemeral=True)

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
                print(f'Ruolo {role.name} assegnato a {member.name}')
            except Exception as e:
                print(f'Errore nell\'assegnazione del ruolo: {e}')

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
                print(f'Ruolo {role.name} rimosso da {member.name}')
            except Exception as e:
                print(f'Errore nella rimozione del ruolo: {e}')

async def setup(bot):
    await bot.add_cog(AutoRoleCog(bot))
