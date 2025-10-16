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

    async def _send_log_embed(self, channel_id, embed_config, **kwargs):
        try:
            if not channel_id:
                return
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                return

            cfg = embed_config
            title = self._render_template(cfg.get('title', ''), **kwargs)
            description = self._render_template(cfg.get('description', ''), **kwargs)

            embed = discord.Embed(title=title or None, description=description or None, color=cfg.get('color', 0x00ff00))
            if cfg.get('thumbnail'):
                thumb = self._render_template(cfg.get('thumbnail'), **kwargs)
                embed.set_thumbnail(url=thumb)
            if cfg.get('author_header'):
                try:
                    embed.set_author(name=kwargs.get('author_name', ''), icon_url=kwargs.get('author_icon', ''))
                except Exception:
                    pass
            if cfg.get('footer'):
                footer = self._render_template(cfg.get('footer'), **kwargs)
                embed.set_footer(text=footer)

            await channel.send(embed=embed)
        except Exception as e:
            logger.error(f'Errore in _send_log_embed: {e}')

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
                    embed.set_author(name=member.name, icon_url=member.display_avatar.url)
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
                    embed.set_author(name=member.name, icon_url=member.display_avatar.url)
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

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        try:
            async for entry in guild.audit_logs(action=discord.AuditLogAction.ban, limit=1):
                if entry.target.id == user.id:
                    staffer = entry.user.mention if entry.user else 'Sistema'
                    reason = entry.reason or 'Nessuna ragione'
                    break
            else:
                staffer = 'Sistema'
                reason = 'Nessuna ragione'

            await self._send_log_embed(
                self.log_config.get('moderation_log_channel_id'),
                self.log_config.get('ban_message', {}),
                mention=user.mention,
                id=user.id,
                avatar=user.display_avatar.url,
                author_name=user.name,
                author_icon=user.display_avatar.url,
                total_members=guild.member_count,
                staffer=staffer,
                reason=reason
            )
        except Exception as e:
            logger.error(f'Errore in on_member_ban: {e}')

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        try:
            async for entry in guild.audit_logs(action=discord.AuditLogAction.unban, limit=1):
                if entry.target.id == user.id:
                    staffer = entry.user.mention if entry.user else 'Sistema'
                    break
            else:
                staffer = 'Sistema'

            await self._send_log_embed(
                self.log_config.get('moderation_log_channel_id'),
                self.log_config.get('unban_message', {}),
                mention=user.mention,
                id=user.id,
                avatar=user.display_avatar.url,
                author_name=user.name,
                author_icon=user.display_avatar.url,
                total_members=guild.member_count,
                staffer=staffer
            )
        except Exception as e:
            logger.error(f'Errore in on_member_unban: {e}')

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        try:
            if before.overwrites != after.overwrites:
                async for entry in after.guild.audit_logs(action=discord.AuditLogAction.channel_update, limit=5):
                    if entry.target.id == after.id:
                        staffer = entry.user.mention if entry.user else 'Sistema'
                        break
                else:
                    staffer = 'Sistema'

                added_perms = []
                removed_perms = []
                for target, after_overwrite in after.overwrites.items():
                    before_overwrite = before.overwrites.get(target)
                    if before_overwrite:
                        for perm, value in after_overwrite:
                            if perm not in before_overwrite or before_overwrite[perm] != value:
                                if value is True:
                                    added_perms.append(f"{perm} per {target}")
                                elif value is False:
                                    removed_perms.append(f"{perm} per {target}")
                    else:
                        for perm, value in after_overwrite:
                            if value is True:
                                added_perms.append(f"{perm} per {target}")
                            elif value is False:
                                removed_perms.append(f"{perm} per {target}")

                added_str = ', '.join(added_perms) if added_perms else 'Nessuno'
                removed_str = ', '.join(removed_perms) if removed_perms else 'Nessuno'

                await self._send_log_embed(
                    self.log_config.get('moderation_log_channel_id'),
                    self.log_config.get('channel_permission_update_message', {}),
                    channel=after.mention,
                    id=after.id,
                    staffer=staffer,
                    total_members=after.guild.member_count,
                    added_perms=added_str,
                    removed_perms=removed_str
                )
        except Exception as e:
            logger.error(f'Errore in on_guild_channel_update: {e}')

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        try:
            if before.permissions != after.permissions:
                async for entry in after.guild.audit_logs(action=discord.AuditLogAction.role_update, limit=5):
                    if entry.target.id == after.id:
                        staffer = entry.user.mention if entry.user else 'Sistema'
                        break
                else:
                    staffer = 'Sistema'

                added_perms = []
                removed_perms = []
                for perm in discord.Permissions.VALID_FLAGS:
                    before_value = getattr(before.permissions, perm, False)
                    after_value = getattr(after.permissions, perm, False)
                    if before_value != after_value:
                        if after_value:
                            added_perms.append(perm.replace('_', ' '))
                        else:
                            removed_perms.append(perm.replace('_', ' '))

                added_str = ', '.join(added_perms) if added_perms else 'Nessuno'
                removed_str = ', '.join(removed_perms) if removed_perms else 'Nessuno'

                await self._send_log_embed(
                    self.log_config.get('moderation_log_channel_id'),
                    self.log_config.get('role_permission_update_message', {}),
                    role=after.mention,
                    id=after.id,
                    staffer=staffer,
                    total_members=after.guild.member_count,
                    added_perms=added_str,
                    removed_perms=removed_str
                )
        except Exception as e:
            logger.error(f'Errore in on_guild_role_update: {e}')

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        try:
            if before.is_timed_out() != after.is_timed_out():
                if after.is_timed_out():
                    async for entry in after.guild.audit_logs(action=discord.AuditLogAction.member_update, limit=5):
                        if entry.target.id == after.id and entry.after.timed_out_until is not None:
                            staffer = entry.user.mention if entry.user else 'Sistema'
                            reason = entry.reason or 'Nessuna ragione'
                            duration = 'Unknown'
                            if entry.after.timed_out_until:
                                delta = entry.after.timed_out_until - datetime.now(timezone.utc)
                                duration = self._format_timedelta(delta)
                            break
                    else:
                        staffer = 'Sistema'
                        reason = 'Nessuna ragione'
                        duration = 'Unknown'

                    await self._send_log_embed(
                        self.log_config.get('moderation_log_channel_id'),
                        self.log_config.get('mute_message', {}),
                        mention=after.mention,
                        id=after.id,
                        avatar=after.display_avatar.url,
                        author_name=after.name,
                        author_icon=after.display_avatar.url,
                        total_members=after.guild.member_count,
                        staffer=staffer,
                        reason=reason,
                        duration=duration
                    )
                else:
                    async for entry in after.guild.audit_logs(action=discord.AuditLogAction.member_update, limit=5):
                        if entry.target.id == after.id and entry.before.timed_out_until is not None and entry.after.timed_out_until is None:
                            staffer = entry.user.mention if entry.user else 'Sistema'
                            break
                    else:
                        staffer = 'Sistema'

                    await self._send_log_embed(
                        self.log_config.get('moderation_log_channel_id'),
                        self.log_config.get('unmute_message', {}),
                        mention=after.mention,
                        id=after.id,
                        avatar=after.display_avatar.url,
                        author_name=after.name,
                        author_icon=after.display_avatar.url,
                        total_members=after.guild.member_count,
                        staffer=staffer
                    )
            elif before.nick != after.nick:
                async for entry in after.guild.audit_logs(action=discord.AuditLogAction.member_update, limit=5):
                    if entry.target.id == after.id and (entry.before.nick != entry.after.nick):
                        staffer = entry.user.mention if entry.user else 'Sistema'
                        new_nick = entry.after.nick or 'Resettato'
                        break
                else:
                    staffer = 'Sistema'
                    new_nick = after.nick or 'Resettato'

                await self._send_log_embed(
                    self.log_config.get('moderation_log_channel_id'),
                    self.log_config.get('nick_message', {}),
                    mention=after.mention,
                    id=after.id,
                    avatar=after.display_avatar.url,
                    author_name=after.name,
                    author_icon=after.display_avatar.url,
                    total_members=after.guild.member_count,
                    staffer=staffer,
                    new_nick=new_nick
                )
            elif before.roles != after.roles:
                added_roles = [role for role in after.roles if role not in before.roles]
                removed_roles = [role for role in before.roles if role not in after.roles]

                if added_roles or removed_roles:
                    async for entry in after.guild.audit_logs(action=discord.AuditLogAction.member_role_update, limit=5):
                        if entry.target.id == after.id:
                            staffer = entry.user.mention if entry.user else 'Sistema'
                            break
                    else:
                        staffer = 'Sistema'

                    added_str = ', '.join([r.name for r in added_roles]) if added_roles else 'Nessuno'
                    removed_str = ', '.join([r.name for r in removed_roles]) if removed_roles else 'Nessuno'

                    await self._send_log_embed(
                        self.log_config.get('moderation_log_channel_id'),
                        self.log_config.get('role_change_message', {}),
                        mention=after.mention,
                        id=after.id,
                        avatar=after.display_avatar.url,
                        author_name=after.name,
                        author_icon=after.display_avatar.url,
                        total_members=after.guild.member_count,
                        added_roles=added_str,
                        removed_roles=removed_str,
                        staffer=staffer
                    )
            elif before.premium_since != after.premium_since and after.premium_since is not None:
                await self._send_log_embed(
                    self.log_config.get('boost_log_channel_id'),
                    self.log_config.get('boost_message', {}),
                    mention=after.mention,
                    id=after.id,
                    avatar=after.display_avatar.url,
                    author_name=after.name,
                    author_icon=after.display_avatar.url,
                    total_members=after.guild.member_count
                )
            elif before.nick != after.nick:
                async for entry in after.guild.audit_logs(action=discord.AuditLogAction.member_update, limit=5):
                    if entry.target.id == after.id and (entry.before.nick != entry.after.nick):
                        staffer = entry.user.mention if entry.user else 'Sistema'
                        new_nick = entry.after.nick or 'Resettato'
                        break
                else:
                    staffer = 'Sistema'
                    new_nick = after.nick or 'Resettato'

                await self._send_log_embed(
                    self.log_config.get('moderation_log_channel_id'),
                    self.log_config.get('nick_message', {}),
                    mention=after.mention,
                    id=after.id,
                    avatar=after.display_avatar.url,
                    author_name=after.name,
                    author_icon=after.display_avatar.url,
                    total_members=after.guild.member_count,
                    staffer=staffer,
                    new_nick=new_nick
                )
            elif before.premium_since != after.premium_since and after.premium_since is not None:
                await self._send_log_embed(
                    self.log_config.get('boost_log_channel_id'),
                    self.log_config.get('boost_message', {}),
                    mention=after.mention,
                    id=after.id,
                    avatar=after.display_avatar.url,
                    author_name=after.name,
                    author_icon=after.display_avatar.url,
                    total_members=after.guild.member_count
                )
        except Exception as e:
            logger.error(f'Errore in on_member_update: {e}')

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        try:
            if message.author.bot:
                return
            content = message.content or 'Nessun contenuto'
            await self._send_log_embed(
                self.log_config.get('message_log_channel_id'),
                self.log_config.get('message_delete_message', {}),
                mention=message.author.mention,
                id=message.author.id,
                avatar=message.author.display_avatar.url,
                author_name=message.author.name,
                author_icon=message.author.display_avatar.url,
                total_members=message.guild.member_count,
                channel=message.channel.mention,
                content=content[:1000] + ('...' if len(content) > 1000 else '')
            )
        except Exception as e:
            logger.error(f'Errore in on_message_delete: {e}')

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        try:
            if before.author.bot or before.content == after.content:
                return
            old_content = before.content or 'Nessun contenuto'
            new_content = after.content or 'Nessun contenuto'
            await self._send_log_embed(
                self.log_config.get('message_log_channel_id'),
                self.log_config.get('message_edit_message', {}),
                mention=before.author.mention,
                id=before.author.id,
                avatar=before.author.display_avatar.url,
                author_name=before.author.name,
                author_icon=before.author.display_avatar.url,
                total_members=before.guild.member_count,
                channel=before.channel.mention,
                old_content=old_content[:500] + ('...' if len(old_content) > 500 else ''),
                new_content=new_content[:500] + ('...' if len(new_content) > 500 else '')
            )
        except Exception as e:
            logger.error(f'Errore in on_message_edit: {e}')

    async def log_warn(self, member: discord.Member, reason: str, staffer: str, total_warns: int):
        await self._send_log_embed(
            self.log_config.get('moderation_log_channel_id'),
            self.log_config.get('warn_message', {}),
            mention=member.mention,
            id=member.id,
            avatar=member.display_avatar.url,
            author_name=member.name,
            author_icon=member.display_avatar.url,
            total_members=member.guild.member_count,
            staffer=staffer,
            reason=reason,
            total_warns=total_warns
        )

    async def log_unwarn(self, member: discord.Member, warn_id: int, staffer: str):
        await self._send_log_embed(
            self.log_config.get('moderation_log_channel_id'),
            self.log_config.get('unwarn_message', {}),
            mention=member.mention,
            id=member.id,
            avatar=member.display_avatar.url,
            author_name=member.name,
            author_icon=member.display_avatar.url,
            total_members=member.guild.member_count,
            staffer=staffer,
            warn_id=warn_id
        )

    async def log_clearwarns(self, member: discord.Member, count: int, staffer: str):
        await self._send_log_embed(
            self.log_config.get('moderation_log_channel_id'),
            self.log_config.get('clearwarns_message', {}),
            mention=member.mention,
            id=member.id,
            avatar=member.display_avatar.url,
            author_name=member.name,
            author_icon=member.display_avatar.url,
            total_members=member.guild.member_count,
            staffer=staffer,
            count=count
        )

    async def log_ticket_open(self, member: discord.Member, name: str, category: str):
        await self._send_log_embed(
            self.log_config.get('ticket_log_channel_id'),
            self.log_config.get('ticket_open_message', {}),
            mention=member.mention,
            id=member.id,
            avatar=member.display_avatar.url,
            author_name=member.name,
            author_icon=member.display_avatar.url,
            total_members=member.guild.member_count,
            name=name,
            category=category
        )

    async def log_ticket_close(self, channel_name: str, opener: str, staffer: str):
        await self._send_log_embed(
            self.log_config.get('ticket_log_channel_id'),
            self.log_config.get('ticket_close_message', {}),
            name=channel_name,
            opener=opener,
            staffer=staffer,
            id='N/A'
        )

    async def log_ticket_rename(self, new_name: str, staffer: str):
        await self._send_log_embed(
            self.log_config.get('ticket_log_channel_id'),
            self.log_config.get('ticket_rename_message', {}),
            new_name=new_name,
            staffer=staffer,
            id='N/A'
        )

    async def log_ticket_add(self, member: discord.Member, name: str, staffer: str):
        await self._send_log_embed(
            self.log_config.get('ticket_log_channel_id'),
            self.log_config.get('ticket_add_message', {}),
            member=member.mention,
            name=name,
            staffer=staffer,
            id=member.id,
            avatar=member.display_avatar.url,
            author_name=member.name,
            author_icon=member.display_avatar.url,
            total_members=member.guild.member_count
        )

    async def log_ticket_remove(self, member: discord.Member, name: str, staffer: str):
        await self._send_log_embed(
            self.log_config.get('ticket_log_channel_id'),
            self.log_config.get('ticket_remove_message', {}),
            member=member.mention,
            name=name,
            staffer=staffer,
            id=member.id,
            avatar=member.display_avatar.url,
            author_name=member.name,
            author_icon=member.display_avatar.url,
            total_members=member.guild.member_count
        )

    async def log_autorole_add(self, member: discord.Member, role: discord.Role):
        await self._send_log_embed(
            self.log_config.get('autorole_log_channel_id'),
            self.log_config.get('autorole_add_message', {}),
            mention=member.mention,
            id=member.id,
            avatar=member.display_avatar.url,
            author_name=member.name,
            author_icon=member.display_avatar.url,
            total_members=member.guild.member_count,
            role=role.mention
        )

    async def log_autorole_remove(self, member: discord.Member, role: discord.Role):
        await self._send_log_embed(
            self.log_config.get('autorole_log_channel_id'),
            self.log_config.get('autorole_remove_message', {}),
            mention=member.mention,
            id=member.id,
            avatar=member.display_avatar.url,
            author_name=member.name,
            author_icon=member.display_avatar.url,
            total_members=member.guild.member_count,
            role=role.mention
        )

    async def log_automod_mute(self, member: discord.Member, duration: str, reason: str):
        await self._send_log_embed(
            self.log_config.get('automod_log_channel_id'),
            self.log_config.get('automod_mute_message', {}),
            mention=member.mention,
            id=member.id,
            avatar=member.display_avatar.url,
            author_name=member.name,
            author_icon=member.display_avatar.url,
            total_members=member.guild.member_count,
            duration=duration,
            reason=reason
        )

    async def log_automod_warn(self, member: discord.Member, word: str):
        await self._send_log_embed(
            self.log_config.get('automod_log_channel_id'),
            self.log_config.get('automod_warn_message', {}),
            mention=member.mention,
            id=member.id,
            avatar=member.display_avatar.url,
            author_name=member.name,
            author_icon=member.display_avatar.url,
            total_members=member.guild.member_count,
            word=word
        )

async def setup(bot):
    await bot.add_cog(LogCog(bot))
