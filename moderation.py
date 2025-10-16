import discord
from discord.ext import commands
import json
import os
import datetime
import re
from discord import app_commands
from bot_utils import is_owner
from console_logger import logger

class ModerationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        with open('config.json', 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        with open('moderation.json', 'r', encoding='utf-8') as f:
            self.moderation_words = json.load(f)
        self.warns_data = {}
        if os.path.exists('warns.json'):
            with open('warns.json', 'r') as f:
                self.warns_data = json.load(f)
        else:
            self.warns_data = {"next_id": 1, "warns": {}}

        self.user_words = {}
        if os.path.exists('user_words.json'):
            with open('user_words.json', 'r') as f:
                self.user_words = json.load(f)

    def save_warns(self):
        with open('warns.json', 'w') as f:
            json.dump(self.warns_data, f, indent=2)

    def save_user_words(self):
        with open('user_words.json', 'w') as f:
            json.dump(self.user_words, f, indent=2)

    def get_user_warns(self, user_id):
        return [w for w in self.warns_data["warns"].values() if w["user_id"] == str(user_id)]

    async def send_dm(self, member, sanction_type, **kwargs):
        try:
            dm_messages = self.moderation_words.get('dm_messages', {})
            config = dm_messages.get(sanction_type, {})
            if config:
                embed = discord.Embed(
                    title=config.get("title", "Sanzione"),
                    description=config.get("description", ""),
                    color=config.get("color", 0xff0000)
                )
                embed.set_thumbnail(url=config.get("thumbnail"))
                embed.set_footer(text=config.get("footer"))
                description = embed.description
                description = description.replace("{reason}", kwargs.get("reason", "N/A"))
                description = description.replace("{staffer}", kwargs.get("staffer", "N/A"))
                description = description.replace("{time}", kwargs.get("time", "N/A"))
                description = description.replace("{duration}", kwargs.get("duration", "N/A"))
                description = description.replace("{total_warns}", str(kwargs.get("total_warns", 0)))
                description = description.replace("{mention}", member.mention)
                description = description.replace("{word}", kwargs.get("word", "N/A"))
                embed.description = description
                await member.send(embed=embed)
        except discord.Forbidden:
            pass

    @commands.command(name='ban')
    async def ban(self, ctx, member: discord.Member, *, reason="Nessuna ragione specificata"):
        staff_role_id = self.config.get('moderation', {}).get('staff_role_id', '1350073958933729371')
        if not is_owner(ctx.author) and not any(role.id == int(staff_role_id) for role in ctx.author.roles):
            await ctx.send('❌ Non hai i permessi per usare questo comando!')
            return

        try:
            await self.send_dm(member, "ban", reason=reason, staffer=str(ctx.author), time=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
            await member.ban(reason=reason)
            await ctx.send(f'✅ {member.mention} è stato bannato. Ragione: {reason}')
            logger.info(f'Ban eseguito: {member.name}#{member.discriminator} ({member.id}) bannato da {ctx.author.name}#{ctx.author.discriminator} per: {reason}')
        except Exception as e:
            await ctx.send(f'❌ Errore nel bannare: {e}')
            logger.error(f'Errore ban: {member.name}#{member.discriminator} ({member.id}) - {e}')

    @app_commands.command(name='ban', description='Banna un membro dal server')
    @app_commands.describe(member='Il membro da bannare', reason='La ragione del ban')
    async def slash_ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Nessuna ragione specificata"):
        staff_role_id = self.config.get('moderation', {}).get('staff_role_id', '1350073958933729371')
        if not is_owner(interaction.user) and not any(role.id == int(staff_role_id) for role in interaction.user.roles):
            await interaction.response.send_message('❌ Non hai i permessi per usare questo comando!', ephemeral=True)
            return

        try:
            await self.send_dm(member, "ban", reason=reason, staffer=str(interaction.user), time=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
            await member.ban(reason=reason)
            await interaction.response.send_message(f'✅ {member.mention} è stato bannato. Ragione: {reason}', ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f'❌ Errore nel bannare: {e}', ephemeral=True)

    @commands.command(name='kick')
    async def kick(self, ctx, member: discord.Member, *, reason="Nessuna ragione specificata"):
        mod_role_id = self.config.get('moderation', {}).get('mod_role_id', '1350073957168058408')
        if not is_owner(ctx.author) and not any(role.id == int(mod_role_id) for role in ctx.author.roles):
            await ctx.send('❌ Non hai i permessi per usare questo comando!')
            return

        try:
            await self.send_dm(member, "kick", reason=reason, staffer=str(ctx.author), time=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
            await member.kick(reason=reason)
            await ctx.send(f'✅ {member.mention} è stato kickato. Ragione: {reason}')
            logger.info(f'Kick eseguito: {member.name}#{member.discriminator} ({member.id}) kickato da {ctx.author.name}#{ctx.author.discriminator} per: {reason}')
        except Exception as e:
            await ctx.send(f'❌ Errore nel kickare: {e}')
            logger.error(f'Errore kick: {member.name}#{member.discriminator} ({member.id}) - {e}')

    @app_commands.command(name='kick', description='Kicka un membro dal server')
    @app_commands.describe(member='Il membro da kickare', reason='La ragione del kick')
    async def slash_kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Nessuna ragione specificata"):
        mod_role_id = self.config.get('moderation', {}).get('mod_role_id', '1350073957168058408')
        if not is_owner(interaction.user) and not any(role.id == int(mod_role_id) for role in interaction.user.roles):
            await interaction.response.send_message('❌ Non hai i permessi per usare questo comando!', ephemeral=True)
            return

        try:
            await self.send_dm(member, "kick", reason=reason, staffer=str(interaction.user), time=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
            await member.kick(reason=reason)
            await interaction.response.send_message(f'✅ {member.mention} è stato kickato. Ragione: {reason}', ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f'❌ Errore nel kickare: {e}', ephemeral=True)

    @commands.command(name='mute')
    async def mute(self, ctx, *, args):
        staff_role_id = self.config.get('moderation', {}).get('staff_role_id', '1123622103917285418')
        if not is_owner(ctx.author) and not any(role.id == int(staff_role_id) for role in ctx.author.roles):
            await ctx.send('❌ Non hai i permessi per usare questo comando!')
            return

        args_list = args.split()
        if not args_list:
            await ctx.send('❌ Uso: v!mute <membro> [durata] [ragione]')
            return

        member_str = args_list[0]
        try:
            member = await commands.MemberConverter().convert(ctx, member_str)
        except commands.MemberNotFound:
            await ctx.send('❌ Membro non trovato!')
            return

        if member.is_timed_out():
            await ctx.send('❌ L\'utente è già mutato!')
            return

        rest = args_list[1:]
        duration = None
        reason_parts = []
        for part in rest:
            if re.match(r'\d+[smhd]', part.lower()):
                if duration is None:
                    duration = part
                else:
                    reason_parts.append(part)
            else:
                reason_parts.append(part)
        reason = ' '.join(reason_parts) if reason_parts else "Nessuna ragione specificata"

        if not duration:
            duration = "25d"

        match = re.match(r'(\d+)([smhd])', duration.lower())
        if not match:
            await ctx.send('❌ Formato durata non valido (es. 1h, 30m, 1d)!')
            return

        num, unit = match.groups()
        num = int(num)
        if unit == 's':
            delta = datetime.timedelta(seconds=num)
        elif unit == 'm':
            delta = datetime.timedelta(minutes=num)
        elif unit == 'h':
            delta = datetime.timedelta(hours=num)
        elif unit == 'd':
            delta = datetime.timedelta(days=num)
        else:
            await ctx.send('❌ Unità non valida!')
            return

        try:
            await member.timeout(delta, reason=reason)
            await ctx.send(f'✅ {member.mention} è stato mutato per {duration}. Ragione: {reason}', ephemeral=True)
            await self.send_dm(member, "mute", reason=reason, staffer=str(ctx.author), time=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), duration=duration)
        except Exception as e:
            await ctx.send(f'❌ Errore nel mutare: {e}')

    @app_commands.command(name='mute', description='Muta un membro per una durata specificata (es. 1h, 30m, 1d)')
    @app_commands.describe(member='Il membro da mutare', duration='Durata (es. 1h, 30m, 1d)', reason='Ragione del mute')
    async def slash_mute(self, interaction: discord.Interaction, member: discord.Member, duration: str = None, *, reason: str = "Nessuna ragione specificata"):
        staff_role_id = self.config.get('moderation', {}).get('staff_role_id', '1123622103917285418')
        if not is_owner(interaction.user) and not any(role.id == int(staff_role_id) for role in interaction.user.roles):
            await interaction.response.send_message('❌ Non hai i permessi per usare questo comando!', ephemeral=True)
            return

        if member.is_timed_out():
            await interaction.response.send_message('❌ L\'utente è già mutato!', ephemeral=True)
            return

        if not duration:
            duration = '25d'

        match = re.match(r'(\d+)([smhd])', duration.lower())
        if not match:
            await interaction.response.send_message('❌ Formato durata non valido (es. 1h, 30m, 1d)!', ephemeral=True)
            return

        num, unit = match.groups()
        num = int(num)
        if unit == 's':
            delta = datetime.timedelta(seconds=num)
        elif unit == 'm':
            delta = datetime.timedelta(minutes=num)
        elif unit == 'h':
            delta = datetime.timedelta(hours=num)
        elif unit == 'd':
            delta = datetime.timedelta(days=num)
        else:
            await interaction.response.send_message('❌ Unità non valida!', ephemeral=True)
            return

        try:
            await member.timeout(delta, reason=reason)
            await interaction.response.send_message(f'✅ {member.mention} è stato mutato per {duration}. Ragione: {reason}', ephemeral=True)
            await self.send_dm(member, "mute", reason=reason, staffer=str(interaction.user), time=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), duration=duration)
        except Exception as e:
            await interaction.response.send_message(f'❌ Errore nel mutare: {e}', ephemeral=True)

    @commands.command(name='unmute')
    async def unmute(self, ctx, member: discord.Member, *, reason="Nessuna ragione specificata"):
        staff_role_id = self.config.get('moderation', {}).get('staff_role_id', '1350073958933729371')
        if not is_owner(ctx.author) and not any(role.id == int(staff_role_id) for role in ctx.author.roles):
            await ctx.send('❌ Non hai i permessi per usare questo comando!')
            return

        if not member.is_timed_out():
            await ctx.send('❌ L\'utente non è mutato!')
            return

        try:
            await member.timeout(None, reason=reason)
            await ctx.send(f'✅ {member.mention} è stato smutato. Ragione: {reason}')
        except Exception as e:
            await ctx.send(f'❌ Errore nello smutare: {e}')

    @app_commands.command(name='unmute', description='Smetti il timeout di un membro')
    @app_commands.describe(member='Il membro da smutare', reason='La ragione dello smut')
    async def slash_unmute(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Nessuna ragione specificata"):
        staff_role_id = self.config.get('moderation', {}).get('staff_role_id', '1350073958933729371')
        if not is_owner(interaction.user) and not any(role.id == int(staff_role_id) for role in interaction.user.roles):
            await interaction.response.send_message('❌ Non hai i permessi per usare questo comando!', ephemeral=True)
            return

        if not member.is_timed_out():
            await interaction.response.send_message('❌ L\'utente non è mutato!', ephemeral=True)
            return

        try:
            await member.timeout(None, reason=reason)
            await interaction.response.send_message(f'✅ {member.mention} è stato smutato. Ragione: {reason}', ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f'❌ Errore nello smutare: {e}', ephemeral=True)

    @commands.command(name='warn')
    async def warn(self, ctx, member: discord.Member, *, reason="Nessuna ragione specificata"):
        staff_role_id = self.config.get('moderation', {}).get('staff_role_id', '1350073958933729371')
        if not is_owner(ctx.author) and not any(role.id == int(staff_role_id) for role in ctx.author.roles):
            await ctx.send('❌ Non hai i permessi per usare questo comando!')
            return

        warn_id = self.warns_data["next_id"]
        self.warns_data["next_id"] += 1
        self.warns_data["warns"][str(warn_id)] = {
            "id": warn_id,
            "user_id": str(member.id),
            "reason": reason,
            "moderator": ctx.author.id,
            "timestamp": datetime.datetime.utcnow().isoformat()
        }
        self.save_warns()

        user_warns = self.get_user_warns(member.id)
        total_warns = len(user_warns)

        await ctx.send(f'✅ Warn aggiunto a {member.mention}. Ragione: {reason} (ID: {warn_id})')

        warn_channel_id = self.config.get('moderation', {}).get('warn_channel_id')
        if warn_channel_id:
            channel = self.bot.get_channel(int(warn_channel_id))
            if channel:
                await channel.send(f'⚠️ Warn aggiunto a {member.mention} per **{reason}** (ID: {warn_id}) - Totale: {total_warns}/3')

        await self.send_dm(member, "warn", reason=reason, staffer=str(ctx.author), time=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), total_warns=total_warns)

        log_cog = self.bot.get_cog('LogCog')
        if log_cog:
            await log_cog.log_warn(member, reason, str(ctx.author), total_warns)

        if total_warns >= 3:
            try:
                await member.timeout(datetime.timedelta(days=7), reason="3 warn")
                await ctx.send(f'⚠️ {member.mention} ha raggiunto 3 warn e è stato mutato per 7 giorni!')
                await self.send_dm(member, "mute", reason="3 warn", staffer="Sistema", time=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), duration="7d")
            except Exception as e:
                await ctx.send(f'❌ Errore nel mutare per 3 warn: {e}')

    @app_commands.command(name='warn', description='Aggiungi un warn a un membro')
    @app_commands.describe(member='Il membro da warning', reason='La ragione del warn')
    async def slash_warn(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Nessuna ragione specificata"):
        staff_role_id = self.config.get('moderation', {}).get('staff_role_id', '1350073958933729371')
        if not is_owner(interaction.user) and not any(role.id == int(staff_role_id) for role in interaction.user.roles):
            await interaction.response.send_message('❌ Non hai i permessi per usare questo comando!', ephemeral=True)
            return

        warn_id = self.warns_data["next_id"]
        self.warns_data["next_id"] += 1
        self.warns_data["warns"][str(warn_id)] = {
            "id": warn_id,
            "user_id": str(member.id),
            "reason": reason,
            "moderator": interaction.user.id,
            "timestamp": datetime.datetime.utcnow().isoformat()
        }
        self.save_warns()

        user_warns = self.get_user_warns(member.id)
        total_warns = len(user_warns)

        try:
            await interaction.response.send_message(f'✅ Warn aggiunto a {member.mention}. Ragione: {reason} (ID: {warn_id})', ephemeral=True)
        except Exception:
            await interaction.followup.send(f'✅ Warn aggiunto a {member.mention}. Ragione: {reason} (ID: {warn_id})', ephemeral=True)

        warn_channel_id = self.config.get('moderation', {}).get('warn_channel_id')
        if warn_channel_id:
            channel = self.bot.get_channel(int(warn_channel_id))
            if channel:
                await channel.send(f'⚠️ Warn aggiunto a {member.mention} per **{reason}** (ID: {warn_id}) - Totale: {total_warns}/3')

        await self.send_dm(member, "warn", reason=reason, staffer=str(interaction.user), time=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), total_warns=total_warns)

        if total_warns >= 3:
            try:
                await member.timeout(datetime.timedelta(days=7), reason="3 warn")
                await interaction.followup.send(f'⚠️ {member.mention} ha raggiunto 3 warn e è stato mutato per 7 giorni!', ephemeral=True)
                await self.send_dm(member, "mute", reason="3 warn", staffer="Sistema", time=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), duration="7d")
            except Exception as e:
                await interaction.followup.send(f'❌ Errore nel mutare per 3 warn: {e}', ephemeral=True)

    @commands.command(name='unwarn')
    async def unwarn(self, ctx, warn_id: int):
        staff_role_id = self.config.get('moderation', {}).get('staff_role_id', '1350073958933729371')
        if ctx.author.id != 1123622103917285418 and not any(role.id == int(staff_role_id) for role in ctx.author.roles):
            await ctx.send('❌ Non hai i permessi per usare questo comando!')
            return

        if str(warn_id) not in self.warns_data["warns"]:
            await ctx.send('❌ Warn ID non trovato!')
            return

        del self.warns_data["warns"][str(warn_id)]
        self.save_warns()
        await ctx.send(f'✅ Warn ID {warn_id} rimosso!')

    @app_commands.command(name='unwarn', description='Rimuovi un warn tramite ID')
    @app_commands.describe(warn_id='L\'ID del warn da rimuovere')
    async def slash_unwarn(self, interaction: discord.Interaction, warn_id: int):
        staff_role_id = self.config.get('moderation', {}).get('staff_role_id', '1350073958933729371')
        if interaction.user.id != 1123622103917285418 and not any(role.id == int(staff_role_id) for role in interaction.user.roles):
            await interaction.response.send_message('❌ Non hai i permessi per usare questo comando!', ephemeral=True)
            return

        if str(warn_id) not in self.warns_data["warns"]:
            await interaction.response.send_message('❌ Warn ID non trovato!', ephemeral=True)
            return

        del self.warns_data["warns"][str(warn_id)]
        self.save_warns()
        await interaction.response.send_message(f'✅ Warn ID {warn_id} rimosso!', ephemeral=True)

    @commands.command(name='listwarns')
    async def listwarns(self, ctx, member: discord.Member = None):
        staff_role_id = self.config.get('moderation', {}).get('staff_role_id', '1350073958933729371')
        if ctx.author.id != 1123622103917285418 and not any(role.id == int(staff_role_id) for role in ctx.author.roles):
            await ctx.send('❌ Non hai i permessi per usare questo comando!')
            return

        if not member:
            member = ctx.author

        user_warns = self.get_user_warns(member.id)
        if not user_warns:
            await ctx.send(f'{member.mention} non ha warn.')
            return

        embed = discord.Embed(title=f'Warn di {member}', color=0xffa500)
        for w in user_warns:
            embed.add_field(name=f'ID {w["id"]}', value=f'**Ragione:** {w["reason"]}\n**Moderatore:** <@{w["moderator"]}>\n**Data:** {w["timestamp"][:10]}', inline=False)
        await ctx.send(embed=embed)

    @app_commands.command(name='listwarns', description='Mostra i warn di un membro')
    @app_commands.describe(member='Il membro di cui mostrare i warn (opzionale)')
    async def slash_listwarns(self, interaction: discord.Interaction, member: discord.Member = None):
        staff_role_id = self.config.get('moderation', {}).get('staff_role_id', '1350073958933729371')
        if interaction.user.id != 1123622103917285418 and not any(role.id == int(staff_role_id) for role in interaction.user.roles):
            await interaction.response.send_message('❌ Non hai i permessi per usare questo comando!', ephemeral=True)
            return

        if not member:
            member = interaction.user

        user_warns = self.get_user_warns(member.id)
        if not user_warns:
            await interaction.response.send_message(f'{member.mention} non ha warn.', ephemeral=True)
            return

        embed = discord.Embed(title=f'Warn di {member}', color=0xffa500)
        for w in user_warns:
            embed.add_field(name=f'ID {w["id"]}', value=f'**Ragione:** {w["reason"]}\n**Moderatore:** <@{w["moderator"]}>\n**Data:** {w["timestamp"][:10]}', inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.command(name='clearwarns')
    async def clearwarns(self, ctx, member: discord.Member):
        staff_role_id = self.config.get('moderation', {}).get('staff_role_id', '1350073958933729371')
        if not is_owner(ctx.author) and not any(role.id == int(staff_role_id) for role in ctx.author.roles):
            await ctx.send('❌ Non hai i permessi per usare questo comando!')
            return

        user_warns = self.get_user_warns(member.id)
        if not user_warns:
            await ctx.send(f'{member.mention} non ha warn da rimuovere.')
            return

        for w in user_warns:
            del self.warns_data["warns"][str(w["id"])]
        self.save_warns()
        await ctx.send(f'✅ Tutti i warn di {member.mention} sono stati rimossi! ({len(user_warns)} warn)')

    @app_commands.command(name='clearwarns', description='Rimuove tutti i warn di un membro')
    @app_commands.describe(member='Il membro di cui rimuovere i warn')
    async def slash_clearwarns(self, interaction: discord.Interaction, member: discord.Member):
        staff_role_id = self.config.get('moderation', {}).get('staff_role_id', '1350073958933729371')
        if not is_owner(interaction.user) and not any(role.id == int(staff_role_id) for role in interaction.user.roles):
            await interaction.response.send_message('❌ Non hai i permessi per usare questo comando!', ephemeral=True)
            return

        user_warns = self.get_user_warns(member.id)
        if not user_warns:
            await interaction.response.send_message(f'{member.mention} non ha warn da rimuovere.', ephemeral=True)
            return

        for w in user_warns:
            del self.warns_data["warns"][str(w["id"])]
        self.save_warns()
        await interaction.response.send_message(f'✅ Tutti i warn di {member.mention} sono stati rimossi! ({len(user_warns)} warn)', ephemeral=True)

    @commands.command(name='unban')
    async def unban(self, ctx, user_id: str, *, reason="Nessuna ragione specificata"):
        mod_role_id = self.config.get('moderation', {}).get('mod_role_id', '1350073957168058408')
        if ctx.author.id != 1123622103917285418 and not any(role.id == int(mod_role_id) for role in ctx.author.roles):
            await ctx.send('❌ Non hai i permessi per usare questo comando!')
            return

        if not user_id.isdigit():
            await ctx.send('❌ Inserisci l\'ID utente, non la menzione.')
            return

        user_id = int(user_id)

        try:
            user = await self.bot.fetch_user(user_id)
            await ctx.guild.unban(user, reason=reason)
            await ctx.send(f'✅ {user} è stato unbannato. Ragione: {reason}')
        except Exception as e:
            await ctx.send(f'❌ Errore nell\'unbannare: {e}')

    @app_commands.command(name='unban', description='Sbanna un utente dal server')
    @app_commands.describe(user_id='L\'ID dell\'utente da sbannare', reason='La ragione dello sban')
    async def slash_unban(self, interaction: discord.Interaction, user_id: str, reason: str = "Nessuna ragione specificata"):
        mod_role_id = self.config.get('moderation', {}).get('mod_role_id', '1350073957168058408')
        if interaction.user.id != 1123622103917285418 and not any(role.id == int(mod_role_id) for role in interaction.user.roles):
            await interaction.response.send_message('❌ Non hai i permessi per usare questo comando!', ephemeral=True)
            return

        if not user_id.isdigit():
            await interaction.response.send_message('❌ Inserisci l\'ID utente, non la menzione.', ephemeral=True)
            return

        user_id = int(user_id)

        try:
            user = await self.bot.fetch_user(user_id)
            await interaction.guild.unban(user, reason=reason)
            await interaction.response.send_message(f'✅ {user} è stato unbannato. Ragione: {reason}', ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f'❌ Errore nell\'unbannare: {e}', ephemeral=True)

    @app_commands.command(name='checkban', description='Controlla se un utente è bannato e i dettagli')
    @app_commands.describe(user_id='ID dell\'utente da controllare')
    async def slash_checkban(self, interaction: discord.Interaction, user_id: str):
        staff_role_id = self.config.get('moderation', {}).get('staff_role_id', '1350073958933729371')
        if interaction.user.id != 1123622103917285418 and not any(role.id == int(staff_role_id) for role in interaction.user.roles):
            await interaction.response.send_message('❌ Non hai i permessi per usare questo comando!', ephemeral=True)
            return

        if not user_id.isdigit():
            await interaction.response.send_message('❌ Inserisci un ID utente valido.', ephemeral=True)
            return

        user_id = int(user_id)

        try:
            bans = [ban async for ban in interaction.guild.bans()]
            for ban in bans:
                if ban.user.id == user_id:
                    async for entry in interaction.guild.audit_logs(action=discord.AuditLogAction.ban, limit=20):
                        if entry.target.id == user_id:
                            moderator = entry.user
                            staffer = interaction.user
                            reason = entry.reason or "Nessuna ragione"
                            await interaction.response.send_message(f'{ban.user} è bannato da {moderator} ({staffer}). Ragione: {reason}', ephemeral=True)
                            return
                    await interaction.response.send_message(f'{ban.user} è bannato.', ephemeral=True)
                    return
            await interaction.response.send_message('Utente non bannato.', ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f'❌ Errore nel controllare il ban: {e}', ephemeral=True)

    @app_commands.command(name='checkmute', description='Controlla se un membro è mutato e i dettagli')
    @app_commands.describe(member='Il membro da controllare')
    async def slash_checkmute(self, interaction: discord.Interaction, member: discord.Member):
        staff_role_id = self.config.get('moderation', {}).get('staff_role_id', '1350073958933729371')
        if interaction.user.id != 1123622103917285418 and not any(role.id == int(staff_role_id) for role in interaction.user.roles):
            await interaction.response.send_message('❌ Non hai i permessi per usare questo comando!', ephemeral=True)
            return

        if not member.is_timed_out():
            await interaction.response.send_message(f'{member.mention} non è mutato.', ephemeral=True)
            return

        try:
            async for entry in interaction.guild.audit_logs(action=discord.AuditLogAction.member_update, limit=20):
                if entry.target.id == member.id and entry.after.timed_out_until is not None:
                    moderator = entry.user
                    staffer = interaction.user
                    reason = entry.reason or "Nessuna ragione"
                    muted_until = entry.after.timed_out_until.strftime("%Y-%m-%d %H:%M:%S") if entry.after.timed_out_until else "Sconosciuto"
                    await interaction.response.send_message(f'{member.mention} è mutato da {moderator} ({staffer}) fino al {muted_until}. Ragione: {reason}', ephemeral=True)
                    return
            await interaction.response.send_message(f'{member.mention} è mutato.', ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f'❌ Errore nel controllare il mute: {e}', ephemeral=True)

    @app_commands.command(name='listban', description='Lista tutti gli utenti bannati')
    async def slash_listban(self, interaction: discord.Interaction):
        staff_role_id = self.config.get('moderation', {}).get('staff_role_id', '1350073958933729371')
        if interaction.user.id != 1123622103917285418 and not any(role.id == int(staff_role_id) for role in interaction.user.roles):
            await interaction.response.send_message('❌ Non hai i permessi per usare questo comando!', ephemeral=True)
            return

        try:
            bans = [ban async for ban in interaction.guild.bans()]
            if not bans:
                await interaction.response.send_message('Nessun utente bannato.', ephemeral=True)
                return

            view = ListBanView(bans)
            embed = view.create_embed()
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f'❌ Errore nel recuperare la lista ban: {e}', ephemeral=True)

    @app_commands.command(name='nick', description='Cambia il nickname di un membro')
    @app_commands.describe(member='Il membro a cui cambiare il nickname', nickname='Il nuovo nickname (lascia vuoto per resettare)')
    async def slash_nick(self, interaction: discord.Interaction, member: discord.Member, nickname: str = None):
        staff_role_id = self.config.get('moderation', {}).get('staff_role_id', '1350073958933729371')
        if not is_owner(interaction.user) and not any(role.id == int(staff_role_id) for role in interaction.user.roles):
            await interaction.response.send_message('❌ Non hai i permessi per usare questo comando!', ephemeral=True)
            return

        try:
            if nickname is None:
                await member.edit(nick=None)
                await interaction.response.send_message(f'✅ Nickname di {member.mention} resettato.', ephemeral=True)
            else:
                await member.edit(nick=nickname)
                await interaction.response.send_message(f'✅ Nickname di {member.mention} cambiato in "{nickname}".', ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f'❌ Errore nel cambiare nickname: {e}', ephemeral=True)

class ListBanView(discord.ui.View):
    def __init__(self, bans, current_page=0):
        super().__init__(timeout=300)
        self.bans = bans
        self.current_page = current_page
        self.total_pages = (len(bans) - 1) // 25 + 1
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        if self.current_page > 0:
            self.add_item(discord.ui.Button(label="Previous", style=discord.ButtonStyle.primary, custom_id="prev"))
        if self.current_page < self.total_pages - 1:
            self.add_item(discord.ui.Button(label="Next", style=discord.ButtonStyle.primary, custom_id="next"))

    def create_embed(self):
        embed = discord.Embed(title=f'Lista Ban (Page {self.current_page + 1}/{self.total_pages})', color=0xff0000)
        start = self.current_page * 25
        end = start + 25
        for ban in self.bans[start:end]:
            embed.add_field(name=f'{ban.user} ({ban.user.id})', value=f'**Ragione:** {ban.reason or "//"}', inline=False)
        return embed

    async def interaction_check(self, interaction):
        if interaction.data['custom_id'] == 'prev':
            self.current_page -= 1
        elif interaction.data['custom_id'] == 'next':
            self.current_page += 1
        self.update_buttons()
        embed = self.create_embed()
        await interaction.response.edit_message(embed=embed, view=self)



async def setup(bot):
    await bot.add_cog(ModerationCog(bot))
