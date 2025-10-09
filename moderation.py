import discord
from discord.ext import commands
import json
import os
import datetime
import re

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

    def save_warns(self):
        with open('warns.json', 'w') as f:
            json.dump(self.warns_data, f, indent=2)

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
                embed.description = description
                await member.send(embed=embed)
        except discord.Forbidden:
            pass  # DM blocked

    @commands.command(name='ban')
    async def ban(self, ctx, member: discord.Member, *, reason="Nessuna ragione specificata"):
        staff_role_id = self.config.get('moderation', {}).get('staff_role_id', '1123622103917285418')
        if ctx.author.id != 1123622103917285418 and not any(role.id == int(staff_role_id) for role in ctx.author.roles):
            await ctx.send('❌ Non hai i permessi per usare questo comando!')
            return

        try:
            await member.ban(reason=reason)
            await ctx.send(f'✅ {member.mention} è stato bannato. Ragione: {reason}')
            await self.send_dm(member, "ban", reason=reason, staffer=str(ctx.author), time=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
        except Exception as e:
            await ctx.send(f'❌ Errore nel bannare: {e}')

    @commands.command(name='kick')
    async def kick(self, ctx, member: discord.Member, *, reason="Nessuna ragione specificata"):
        mod_role_id = self.config.get('moderation', {}).get('mod_role_id', '1350073957168058408')
        if ctx.author.id != 1123622103917285418 and not any(role.id == int(mod_role_id) for role in ctx.author.roles):
            await ctx.send('❌ Non hai i permessi per usare questo comando!')
            return

        try:
            await member.kick(reason=reason)
            await ctx.send(f'✅ {member.mention} è stato kickato. Ragione: {reason}')
            await self.send_dm(member, "kick", reason=reason, staffer=str(ctx.author), time=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
        except Exception as e:
            await ctx.send(f'❌ Errore nel kickare: {e}')

    @commands.command(name='mute')
    async def mute(self, ctx, member: discord.Member, duration: str = None, *, reason="Nessuna ragione specificata"):
        staff_role_id = self.config.get('moderation', {}).get('staff_role_id', '1123622103917285418')
        if ctx.author.id != 1123622103917285418 and not any(role.id == int(staff_role_id) for role in ctx.author.roles):
            await ctx.send('❌ Non hai i permessi per usare questo comando!')
            return

        if member.is_timed_out():
            await ctx.send('❌ L\'utente è già mutato!')
            return

        if not duration:
            await ctx.send('❌ Devi specificare una durata (es. 1h, 30m, 1d)!')
            return

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
            await ctx.send(f'✅ {member.mention} è stato mutato per {duration}. Ragione: {reason}')
            await self.send_dm(member, "mute", reason=reason, staffer=str(ctx.author), time=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), duration=duration)
        except Exception as e:
            await ctx.send(f'❌ Errore nel mutare: {e}')

    @commands.command(name='unmute')
    async def unmute(self, ctx, member: discord.Member, *, reason="Nessuna ragione specificata"):
        staff_role_id = self.config.get('moderation', {}).get('staff_role_id', '1123622103917285418')
        if ctx.author.id != 1123622103917285418 and not any(role.id == int(staff_role_id) for role in ctx.author.roles):
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

    @commands.command(name='warn')
    async def warn(self, ctx, member: discord.Member, *, reason="Nessuna ragione specificata"):
        staff_role_id = self.config.get('moderation', {}).get('staff_role_id', '1123622103917285418')
        if ctx.author.id != 1123622103917285418 and not any(role.id == int(staff_role_id) for role in ctx.author.roles):
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

        # Send to warn channel
        warn_channel_id = self.config.get('moderation', {}).get('warn_channel_id')
        if warn_channel_id:
            channel = self.bot.get_channel(int(warn_channel_id))
            if channel:
                await channel.send(f'⚠️ Warn aggiunto a {member.mention} per **{reason}** (ID: {warn_id}) - Totale: {total_warns}/3')

        # DM to user
        await self.send_dm(member, "warn", reason=reason, staffer=str(ctx.author), time=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), total_warns=total_warns)

        # Check for 3 warns
        if total_warns >= 3:
            try:
                await member.timeout(datetime.timedelta(days=7), reason="3 warn")
                await ctx.send(f'⚠️ {member.mention} ha raggiunto 3 warn e è stato mutato per 7 giorni!')
                await self.send_dm(member, "mute", reason="3 warn", staffer="Sistema", time=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), duration="7d")
            except Exception as e:
                await ctx.send(f'❌ Errore nel mutare per 3 warn: {e}')

    @commands.command(name='unwarn')
    async def unwarn(self, ctx, warn_id: int):
        staff_role_id = self.config.get('moderation', {}).get('staff_role_id', '1123622103917285418')
        if ctx.author.id != 1123622103917285418 and not any(role.id == int(staff_role_id) for role in ctx.author.roles):
            await ctx.send('❌ Non hai i permessi per usare questo comando!')
            return

        if str(warn_id) not in self.warns_data["warns"]:
            await ctx.send('❌ Warn ID non trovato!')
            return

        del self.warns_data["warns"][str(warn_id)]
        self.save_warns()
        await ctx.send(f'✅ Warn ID {warn_id} rimosso!')

    @commands.command(name='listwarns')
    async def listwarns(self, ctx, member: discord.Member = None):
        staff_role_id = self.config.get('moderation', {}).get('staff_role_id', '1123622103917285418')
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

    @commands.command(name='clearwarns')
    async def clearwarns(self, ctx, member: discord.Member):
        staff_role_id = self.config.get('moderation', {}).get('staff_role_id', '1350073958933729371')
        if ctx.author.id != 1123622103917285418 and not any(role.id == int(staff_role_id) for role in ctx.author.roles):
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

    @commands.command(name='purge')
    async def purge(self, ctx, limit: int):
        staff_role_id = self.config.get('moderation', {}).get('staff_role_id', '1123622103917285418')
        if ctx.author.id != 1123622103917285418 and not any(role.id == int(staff_role_id) for role in ctx.author.roles):
            await ctx.send('❌ Non hai i permessi per usare questo comando!')
            return

        if limit < 1 or limit > 100:
            await ctx.send('❌ Limite tra 1 e 100!')
            return

        try:
            deleted = await ctx.channel.purge(limit=limit)
            await ctx.send(f'✅ Eliminati {len(deleted)} messaggi.', delete_after=5)
        except Exception as e:
            await ctx.send(f'❌ Errore: {e}')

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        staff_role_id = self.config.get('moderation', {}).get('staff_role_id')
        if staff_role_id and any(role.id == int(staff_role_id) for role in message.author.roles):
            return

        content = message.content.lower()

        for duration, words in self.moderation_words.items():
            if isinstance(words, list):
                for word in words:
                    if word.lower() in content:
                        if message.author.is_timed_out():
                            return

                        if duration.endswith('h'):
                            hours = int(duration[:-1])
                            delta = datetime.timedelta(hours=hours)
                        elif duration.endswith('d'):
                            days = int(duration[:-1])
                            delta = datetime.timedelta(days=days)
                        else:
                            delta = datetime.timedelta(hours=1)

                        try:
                            await message.delete()
                            await message.author.timeout(delta, reason=f'Auto-mute per parola vietata: {word}')
                            await message.channel.send(f'{message.author.mention} è stato mutato automaticamente per {duration} a causa di una parola vietata.')
                            await self.send_dm(message.author, "mute", reason=f'Auto-mute per parola vietata: {word}', staffer="Sistema", time=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), duration=duration)
                        except Exception as e:
                            print(f'Errore auto-mute: {e}')
                        return

async def setup(bot):
    await bot.add_cog(ModerationCog(bot))
