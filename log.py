import discord
from discord.ext import commands
import json
import os
import asyncio
from datetime import datetime, timezone, timedelta
from console_logger import logger


class LogCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = {}
        self.log_config = {}
        with open('config.json', 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        if os.path.exists('log.json'):
            with open('log.json', 'r', encoding='utf-8') as f:
                try:
                    self.log_config = json.load(f)
                except Exception:
                    self.log_config = {}

    def _format_datetime(self, dt: datetime):
        if not dt:
            return 'Unknown'
        return dt.strftime('%Y-%m-%d %H:%M:%S')

    def _format_timedelta(self, delta: timedelta):
        if not delta:
            return 'Unknown'
        days = delta.days
        secs = delta.seconds
        hours = secs // 3600
        mins = (secs % 3600) // 60
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if mins:
            parts.append(f"{mins}m")
        if not parts:
            parts.append(f"{secs}s")
        return ' '.join(parts)

    def _get_roles_str(self, member: discord.Member):
        try:
            roles = [f'<@&{r.id}>' for r in member.roles if r.name != '@everyone']
            return ' '.join(roles) if roles else 'Nessun ruolo'
        except Exception:
            return 'N/A'

    def _render_template(self, template: str, **kwargs):
        s = template
        for k, v in kwargs.items():
            s = s.replace('{' + k + '}', str(v))
        return s

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        try:
            cfg = self.log_config.get('join_message', {})
            channel_id = self.log_config.get('join_log_channel_id') or self.config.get('join_log_channel_id')
            if not channel_id:
                return
            channel = member.guild.get_channel(int(channel_id))
            if not channel:
                return

            joined_at = self._format_datetime(member.joined_at)
            created_at = self._format_datetime(member.created_at)
            mention = member.mention

            title = cfg.get('title', '').replace('{mention}', mention).replace('{username}', member.name)
            description = self._render_template(cfg.get('description', ''), mention=mention, joined_at=joined_at, created_at=created_at, username=member.name, total_members=str(member.guild.member_count))

            embed = discord.Embed(title=title or None, description=description or None, color=cfg.get('color', 0x00ff00))
            if cfg.get('thumbnail'):
                thumb = cfg.get('thumbnail')
                thumb = thumb.replace('{avatar}', member.display_avatar.url)
                embed.set_thumbnail(url=thumb)
            if cfg.get('author_header'):
                try:
                    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
                except Exception:
                    pass
            if cfg.get('footer'):
                footer = cfg.get('footer')
                footer = footer.replace('{id}', str(member.id)).replace('{total_members}', str(member.guild.member_count))
                embed.set_footer(text=footer)

            await asyncio.sleep(5)
            await channel.send(embed=embed)
        except Exception as e:
            logger.error(f'Errore in on_member_join log cog: {e}')

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        try:
            cfg = self.log_config.get('leave_message', {})
            channel_id = self.log_config.get('leave_log_channel_id') or self.config.get('leave_log_channel_id')
            if not channel_id:
                return
            channel = member.guild.get_channel(int(channel_id))
            if not channel:
                return

            left_dt = datetime.now(timezone.utc)
            left_at = self._format_datetime(left_dt)
            created_at = self._format_datetime(member.created_at)
            mention = member.mention
            roles = self._get_roles_str(member)

            time_in_server = 'Unknown'
            try:
                if member.joined_at:
                    joined = member.joined_at
                    if joined.tzinfo is None:
                        joined = joined.replace(tzinfo=timezone.utc)
                    delta = left_dt - joined
                    time_in_server = self._format_timedelta(delta)
            except Exception:
                time_in_server = 'Unknown'

            title = cfg.get('title', '').replace('{mention}', mention).replace('{username}', member.name)
            description = self._render_template(cfg.get('description', ''), mention=mention, left_at=left_at, created_at=created_at, roles=roles, username=member.name, id=member.id, time_in_server=time_in_server)

            embed = discord.Embed(title=title or None, description=description or None, color=cfg.get('color', 0xff0000))
            if cfg.get('thumbnail'):
                thumb = cfg.get('thumbnail')
                thumb = thumb.replace('{avatar}', member.display_avatar.url)
                embed.set_thumbnail(url=thumb)
            if cfg.get('author_header'):
                try:
                    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
                except Exception:
                    pass
            if cfg.get('footer'):
                footer = cfg.get('footer')
                footer = footer.replace('{id}', str(member.id)).replace('{total_members}', str(member.guild.member_count))
                embed.set_footer(text=footer)

            embed.add_field(name='Ruoli', value=roles, inline=False)
            embed.add_field(name='ID Utente', value=str(member.id), inline=True)
            embed.add_field(name='Data uscita', value=left_at, inline=True)
            embed.add_field(name='Tempo nel server', value=time_in_server, inline=True)

            await asyncio.sleep(5)
            await channel.send(embed=embed)
        except Exception as e:
            logger.error(f'Errore in on_member_remove log cog: {e}')

async def setup(bot):
    await bot.add_cog(LogCog(bot))
