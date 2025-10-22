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

    async def reload_config(self):
        try:
            if os.path.exists('log.json'):
                with open('log.json', 'r', encoding='utf-8') as f:
                    self.log_config = json.load(f)
        except Exception as e:
            logger.error(f'Errore nel caricamento di log.json: {e}')
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

    async def _get_audit_user(self, action, target_id, guild):
        try:
            async for entry in guild.audit_logs(action=action, limit=5):
                if entry.target.id == target_id:
                    return entry.user.mention if entry.user else 'Sistema'
            return 'Sistema'
        except Exception:
            return 'Sistema'

    def _format_permissions_diff(self, before_overwrites, after_overwrites):
        changes = []
        all_targets = set(before_overwrites.keys()) | set(after_overwrites.keys())
        for target in all_targets:
            b_over = before_overwrites.get(target)
            a_over = after_overwrites.get(target)
            if b_over is None:
                if a_over:
                    allow_perms = [p.replace('_', ' ') for p in discord.Permissions.VALID_FLAGS if getattr(a_over, 'allow', 0) & getattr(discord.Permissions, p, 0)]
                    deny_perms = [p.replace('_', ' ') for p in discord.Permissions.VALID_FLAGS if getattr(a_over, 'deny', 0) & getattr(discord.Permissions, p, 0)]
                    if allow_perms or deny_perms:
                        changes.append(f"Aggiunto overwrite per {target.mention}: Allow {', '.join(allow_perms) or 'Nessuno'}, Deny {', '.join(deny_perms) or 'Nessuno'}")
            elif a_over is None:
                changes.append(f"Rimosso overwrite per {target.mention}")
            else:
                b_allow = getattr(b_over, 'allow', 0)
                b_deny = getattr(b_over, 'deny', 0)
                a_allow = getattr(a_over, 'allow', 0)
                a_deny = getattr(a_over, 'deny', 0)
                added_allow = [p.replace('_', ' ') for p in discord.Permissions.VALID_FLAGS if (a_allow & getattr(discord.Permissions, p, 0)) and not (b_allow & getattr(discord.Permissions, p, 0))]
                removed_allow = [p.replace('_', ' ') for p in discord.Permissions.VALID_FLAGS if (b_allow & getattr(discord.Permissions, p, 0)) and not (a_allow & getattr(discord.Permissions, p, 0))]
                added_deny = [p.replace('_', ' ') for p in discord.Permissions.VALID_FLAGS if (a_deny & getattr(discord.Permissions, p, 0)) and not (b_deny & getattr(discord.Permissions, p, 0))]
                removed_deny = [p.replace('_', ' ') for p in discord.Permissions.VALID_FLAGS if (b_deny & getattr(discord.Permissions, p, 0)) and not (a_deny & getattr(discord.Permissions, p, 0))]
                if added_allow or removed_allow or added_deny or removed_deny:
                    change_parts = []
                    if added_allow:
                        change_parts.append(f"Allow aggiunti: {', '.join(added_allow)}")
                    if removed_allow:
                        change_parts.append(f"Allow rimossi: {', '.join(removed_allow)}")
                    if added_deny:
                        change_parts.append(f"Deny aggiunti: {', '.join(added_deny)}")
                    if removed_deny:
                        change_parts.append(f"Deny rimossi: {', '.join(removed_deny)}")
                    changes.append(f"Modificato overwrite per {target.mention}: {'; '.join(change_parts)}")
        return '\n'.join(changes) if changes else 'Nessuno'

    def _get_channel_type_name(self, channel):
        if isinstance(channel, discord.TextChannel):
            return 'Testo'
        elif isinstance(channel, discord.VoiceChannel):
            return 'Voce'
        elif isinstance(channel, discord.CategoryChannel):
            return 'Categoria'
        elif isinstance(channel, discord.Thread):
            return 'Thread'
        else:
            return 'Sconosciuto'

    async def _send_log_embed(self, channel_id, embed_config, guild=None, **kwargs):
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
            embed.timestamp = datetime.now(timezone.utc)
            if cfg.get('thumbnail'):
                thumb = self._render_template(cfg.get('thumbnail'), **kwargs)
                embed.set_thumbnail(url=thumb)
            if cfg.get('author_header'):
                try:
                    icon_url = kwargs.get('author_icon', '')
                    if guild and guild.icon and not icon_url:
                        icon_url = guild.icon.url
                    embed.set_author(name=kwargs.get('author_name', ''), icon_url=icon_url)
                except Exception:
                    pass
            elif guild and guild.icon:
                embed.set_author(name=guild.name, icon_url=guild.icon.url)
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
            staffer = await self._get_audit_user(discord.AuditLogAction.ban, user.id, guild)
            async for entry in guild.audit_logs(action=discord.AuditLogAction.ban, limit=1):
                if entry.target.id == user.id:
                    reason = entry.reason or 'Nessuna ragione'
                    break
            else:
                reason = 'Nessuna ragione'

            logger.info(f'Member banned: {user.name} ({user.id}) by {staffer} - Reason: {reason}')
            await self._send_log_embed(
                self.log_config.get('moderation_log_channel_id'),
                self.log_config.get('ban_message', {}),
                guild=guild,
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
            staffer = await self._get_audit_user(discord.AuditLogAction.unban, user.id, guild)

            logger.info(f'Member unbanned: {user.name} ({user.id}) by {staffer}')
            await self._send_log_embed(
                self.log_config.get('moderation_log_channel_id'),
                self.log_config.get('unban_message', {}),
                guild=guild,
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
            changes = []

            if before.name != after.name:
                changes.append(f"Nome: `{before.name}` → `{after.name}`")

            if getattr(before, 'topic', None) != getattr(after, 'topic', None):
                before_topic = before.topic or 'Nessuno'
                after_topic = after.topic or 'Nessuno'
                changes.append(f"Topic: `{before_topic}` → `{after_topic}`")

            if getattr(before, 'nsfw', None) != getattr(after, 'nsfw', None):
                changes.append(f"NSFW: `{before.nsfw}` → `{after.nsfw}`")

            if getattr(before, 'slowmode_delay', None) != getattr(after, 'slowmode_delay', None):
                changes.append(f"Slowmode: `{before.slowmode_delay}s` → `{after.slowmode_delay}s`")

            if before.position != after.position:
                changes.append(f"Posizione: `{before.position}` → `{after.position}`")

            perm_changes = ""
            if before.overwrites != after.overwrites:
                perm_changes = self._format_permissions_diff(before.overwrites, after.overwrites)
                if perm_changes:
                    changes.append(f"Permessi aggiornati:\n{perm_changes}")

            if changes:
                staffer = await self._get_audit_user(
                    discord.AuditLogAction.channel_update, after.id, after.guild
                )

                formatted_changes = "\n".join(changes)
                logger.info(f"Channel updated: {after.name} ({after.id}) by {staffer} - Changes:\n{formatted_changes}")

                await self._send_log_embed(
                    self.log_config.get("moderation_log_channel_id"),
                    self.log_config.get("channel_update_message", {}),
                    guild=after.guild,
                    channel=after.mention,
                    id=after.id,
                    staffer=staffer,
                    total_members=after.guild.member_count,
                    changes=formatted_changes
                )

        except Exception as e:
            logger.error(f"Errore in on_guild_channel_update: {e}")

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        try:
            if before.permissions != after.permissions:
                staffer = await self._get_audit_user(discord.AuditLogAction.role_update, after.id, after.guild)
                added_perms, removed_perms = self._format_permissions_diff(before.permissions, after.permissions)
                logger.info(f'Role permissions updated: {after.name} ({after.id}) by {staffer} - Added: {added_perms}, Removed: {removed_perms}')
                await self._send_log_embed(
                    self.log_config.get('moderation_log_channel_id'),
                    self.log_config.get('role_permission_update_message', {}),
                    guild=after.guild,
                    role=after.mention,
                    id=after.id,
                    staffer=staffer,
                    total_members=after.guild.member_count,
                    added_perms=added_perms,
                    removed_perms=removed_perms
                )
        except Exception as e:
            logger.error(f'Errore in on_guild_role_update: {e}')

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        try:
            if before.is_timed_out() != after.is_timed_out():
                if after.is_timed_out():
                    staffer = await self._get_audit_user(discord.AuditLogAction.member_update, after.id, after.guild)
                    async for entry in after.guild.audit_logs(action=discord.AuditLogAction.member_update, limit=5):
                        if entry.target.id == after.id and entry.after.timed_out_until is not None:
                            reason = entry.reason or 'Nessuna ragione'
                            duration = 'Unknown'
                            if entry.after.timed_out_until:
                                delta = entry.after.timed_out_until - datetime.now(timezone.utc)
                                duration = self._format_timedelta(delta)
                            break
                    else:
                        reason = 'Nessuna ragione'
                        duration = 'Unknown'

                    logger.info(f'Member muted: {after.name} ({after.id}) by {staffer} - Reason: {reason}, Duration: {duration}')
                    await self._send_log_embed(
                        self.log_config.get('moderation_log_channel_id'),
                        self.log_config.get('mute_message', {}),
                        guild=after.guild,
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
                    staffer = await self._get_audit_user(discord.AuditLogAction.member_update, after.id, after.guild)
                    logger.info(f'Member unmuted: {after.name} ({after.id}) by {staffer}')
                    await self._send_log_embed(
                        self.log_config.get('moderation_log_channel_id'),
                        self.log_config.get('unmute_message', {}),
                        guild=after.guild,
                        mention=after.mention,
                        id=after.id,
                        avatar=after.display_avatar.url,
                        author_name=after.name,
                        author_icon=after.display_avatar.url,
                        total_members=after.guild.member_count,
                        staffer=staffer
                    )
            elif before.nick != after.nick:
                staffer = await self._get_audit_user(discord.AuditLogAction.member_update, after.id, after.guild)
                new_nick = after.nick or 'Resettato'
                logger.info(f'Member nickname changed: {after.name} ({after.id}) by {staffer} - New nick: {new_nick}')
                await self._send_log_embed(
                    self.log_config.get('moderation_log_channel_id'),
                    self.log_config.get('nick_message', {}),
                    guild=after.guild,
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
                    staffer = await self._get_audit_user(discord.AuditLogAction.member_role_update, after.id, after.guild)
                    added_str = ', '.join([r.mention for r in added_roles]) if added_roles else 'Nessuno'
                    removed_str = ', '.join([r.mention for r in removed_roles]) if removed_roles else 'Nessuno'
                    logger.info(f'Member roles changed: {after.name} ({after.id}) by {staffer} - Added: {added_str}, Removed: {removed_str}')
                    await self._send_log_embed(
                        self.log_config.get('moderation_log_channel_id'),
                        self.log_config.get('role_change_message', {}),
                        guild=after.guild,
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
                logger.info(f'Member boosted: {after.name} ({after.id})')
                await self._send_log_embed(
                    self.log_config.get('boost_log_channel_id'),
                    self.log_config.get('boost_message', {}),
                    guild=after.guild,
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
            logger.info(f'Message deleted: {message.author.name} ({message.author.id}) in {message.channel.name} - Content: {content[:100]}...')
            await self._send_log_embed(
                self.log_config.get('message_log_channel_id'),
                self.log_config.get('message_delete_message', {}),
                guild=message.guild,
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
            logger.info(f'Message edited: {before.author.name} ({before.author.id}) in {before.channel.name} - Old: {old_content[:50]}..., New: {new_content[:50]}...')
            await self._send_log_embed(
                self.log_config.get('message_log_channel_id'),
                self.log_config.get('message_edit_message', {}),
                guild=before.guild,
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

    async def log_ticket_open(self, member: discord.Member, channel: str, number: str, category: str):
        await self._send_log_embed(
            self.log_config.get('ticket_log_channel_id'),
            self.log_config.get('ticket_open_message', {}),
            mention=member.mention,
            id=member.id,
            avatar=member.display_avatar.url,
            author_name=member.name,
            author_icon=member.display_avatar.url,
            total_members=member.guild.member_count,
            channel=channel,
            number=number,
            category=category
        )

    async def log_ticket_close(self, channel_name: str, opener: str, staffer: str, number: str):
        await self._send_log_embed(
            self.log_config.get('ticket_log_channel_id'),
            self.log_config.get('ticket_close_message', {}),
            name=channel_name,
            opener=opener,
            staffer=staffer,
            number=number,
            id='N/A'
        )

    async def log_ticket_rename(self, channel_mention: str, new_name: str, number: str, staffer: str):
        await self._send_log_embed(
            self.log_config.get('ticket_log_channel_id'),
            self.log_config.get('ticket_rename_message', {}),
            channel=channel_mention,
            new_name=new_name,
            number=number,
            staffer=staffer,
            id='N/A'
        )

    async def log_ticket_add(self, member: discord.Member, channel: str, number: str, staffer: str):
        await self._send_log_embed(
            self.log_config.get('ticket_log_channel_id'),
            self.log_config.get('ticket_add_message', {}),
            member=member.mention,
            channel=channel,
            number=number,
            staffer=staffer,
            id=member.id,
            avatar=member.display_avatar.url,
            author_name=member.name,
            author_icon=member.display_avatar.url,
            total_members=member.guild.member_count
        )

    async def log_ticket_remove(self, member: discord.Member, channel: str, number: str, staffer: str):
        await self._send_log_embed(
            self.log_config.get('ticket_log_channel_id'),
            self.log_config.get('ticket_remove_message', {}),
            member=member.mention,
            channel=channel,
            number=number,
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

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        try:
            staffer = await self._get_audit_user(discord.AuditLogAction.channel_create, channel.id, channel.guild)
            logger.info(f'Channel created: {channel.name} ({channel.id}) by {staffer} - Type: {self._get_channel_type_name(channel)}')
            await self._send_log_embed(
                self.log_config.get('moderation_log_channel_id'),
                self.log_config.get('channel_create_message', {}),
                guild=channel.guild,
                channel=channel.mention,
                id=channel.id,
                staffer=staffer,
                total_members=channel.guild.member_count,
                type=self._get_channel_type_name(channel)
            )
        except Exception as e:
            logger.error(f'Errore in on_guild_channel_create: {e}')

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        try:
            staffer = await self._get_audit_user(discord.AuditLogAction.channel_delete, channel.id, channel.guild)
            logger.info(f'Channel deleted: {channel.name} ({channel.id}) by {staffer} - Type: {self._get_channel_type_name(channel)}')
            await self._send_log_embed(
                self.log_config.get('moderation_log_channel_id'),
                self.log_config.get('channel_delete_message', {}),
                guild=channel.guild,
                name=channel.name,
                id=channel.id,
                staffer=staffer,
                total_members=channel.guild.member_count,
                type=self._get_channel_type_name(channel)
            )
        except Exception as e:
            logger.error(f'Errore in on_guild_channel_delete: {e}')

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        try:
            staffer = await self._get_audit_user(discord.AuditLogAction.thread_create, thread.id, thread.guild)
            logger.info(f'Thread created: {thread.name} ({thread.id}) by {staffer}')
            await self._send_log_embed(
                self.log_config.get('moderation_log_channel_id'),
                self.log_config.get('thread_create_message', {}),
                guild=thread.guild,
                thread=thread.mention,
                id=thread.id,
                staffer=staffer,
                total_members=thread.guild.member_count
            )
        except Exception as e:
            logger.error(f'Errore in on_thread_create: {e}')

    @commands.Cog.listener()
    async def on_thread_delete(self, thread: discord.Thread):
        try:
            staffer = await self._get_audit_user(discord.AuditLogAction.thread_delete, thread.id, thread.guild)
            logger.info(f'Thread deleted: {thread.name} ({thread.id}) by {staffer}')
            await self._send_log_embed(
                self.log_config.get('moderation_log_channel_id'),
                self.log_config.get('thread_delete_message', {}),
                guild=thread.guild,
                name=thread.name,
                id=thread.id,
                staffer=staffer,
                total_members=thread.guild.member_count
            )
        except Exception as e:
            logger.error(f'Errore in on_thread_delete: {e}')

    @commands.Cog.listener()
    async def on_thread_update(self, before: discord.Thread, after: discord.Thread):
        try:
            changes = []
            if before.name != after.name:
                changes.append(f"Nome: {before.name} → {after.name}")
            if before.archived != after.archived:
                changes.append(f"Archiviato: {before.archived} → {after.archived}")
            if before.locked != after.locked:
                changes.append(f"Bloccato: {before.locked} → {after.locked}")

            if changes:
                staffer = await self._get_audit_user(discord.AuditLogAction.thread_update, after.id, after.guild)
                logger.info(f'Thread updated: {after.name} ({after.id}) by {staffer} - Changes: {", ".join(changes)}')
                await self._send_log_embed(
                    self.log_config.get('moderation_log_channel_id'),
                    self.log_config.get('thread_update_message', {}),
                    guild=after.guild,
                    thread=after.mention,
                    id=after.id,
                    staffer=staffer,
                    total_members=after.guild.member_count,
                    changes=', '.join(changes)
                )
        except Exception as e:
            logger.error(f'Errore in on_thread_update: {e}')

    @commands.Cog.listener()
    async def on_webhook_create(self, webhook: discord.Webhook):
        try:
            staffer = await self._get_audit_user(discord.AuditLogAction.webhook_create, webhook.id, webhook.guild)
            logger.info(f'Webhook created: {webhook.name} ({webhook.id}) by {staffer}')
            await self._send_log_embed(
                self.log_config.get('moderation_log_channel_id'),
                self.log_config.get('webhook_create_message', {}),
                guild=webhook.guild,
                name=webhook.name,
                id=webhook.id,
                staffer=staffer,
                total_members=webhook.guild.member_count
            )
        except Exception as e:
            logger.error(f'Errore in on_webhook_create: {e}')

    @commands.Cog.listener()
    async def on_webhook_delete(self, webhook: discord.Webhook):
        try:
            staffer = await self._get_audit_user(discord.AuditLogAction.webhook_delete, webhook.id, webhook.guild)
            logger.info(f'Webhook deleted: {webhook.name} ({webhook.id}) by {staffer}')
            await self._send_log_embed(
                self.log_config.get('moderation_log_channel_id'),
                self.log_config.get('webhook_delete_message', {}),
                guild=webhook.guild,
                name=webhook.name,
                id=webhook.id,
                staffer=staffer,
                total_members=webhook.guild.member_count
            )
        except Exception as e:
            logger.error(f'Errore in on_webhook_delete: {e}')

    @commands.Cog.listener()
    async def on_webhook_update(self, before: discord.Webhook, after: discord.Webhook):
        try:
            changes = []
            if before.name != after.name:
                changes.append(f"Nome: {before.name} → {after.name}")
            if before.channel != after.channel:
                changes.append(f"Canale: {before.channel.mention} → {after.channel.mention}")

            if changes:
                staffer = await self._get_audit_user(discord.AuditLogAction.webhook_update, after.id, after.guild)
                logger.info(f'Webhook updated: {after.name} ({after.id}) by {staffer} - Changes: {", ".join(changes)}')
                await self._send_log_embed(
                    self.log_config.get('moderation_log_channel_id'),
                    self.log_config.get('webhook_update_message', {}),
                    guild=after.guild,
                    name=after.name,
                    id=after.id,
                    staffer=staffer,
                    total_members=after.guild.member_count,
                    changes=', '.join(changes)
                )
        except Exception as e:
            logger.error(f'Errore in on_webhook_update: {e}')

    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild: discord.Guild, before, after):
        try:
            added = [e for e in after if e not in before]
            removed = [e for e in before if e not in after]
            updated = [e for e in after if e in before and any(getattr(e, attr) != getattr(next((b for b in before if b.id == e.id), None), attr) for attr in ['name'])]

            if added:
                staffer = await self._get_audit_user(discord.AuditLogAction.emoji_create, added[0].id, guild)
                logger.info(f'Emoji added: {", ".join([e.name for e in added])} by {staffer}')
                await self._send_log_embed(
                    self.log_config.get('moderation_log_channel_id'),
                    self.log_config.get('emoji_create_message', {}),
                    guild=guild,
                    emojis=', '.join([str(e) for e in added]),
                    staffer=staffer,
                    total_members=guild.member_count
                )
            if removed:
                staffer = await self._get_audit_user(discord.AuditLogAction.emoji_delete, removed[0].id, guild)
                logger.info(f'Emoji removed: {", ".join([e.name for e in removed])} by {staffer}')
                await self._send_log_embed(
                    self.log_config.get('moderation_log_channel_id'),
                    self.log_config.get('emoji_delete_message', {}),
                    guild=guild,
                    emojis=', '.join([e.name for e in removed]),
                    staffer=staffer,
                    total_members=guild.member_count
                )
            if updated:
                staffer = await self._get_audit_user(discord.AuditLogAction.emoji_update, updated[0].id, guild)
                logger.info(f'Emoji updated: {", ".join([e.name for e in updated])} by {staffer}')
                await self._send_log_embed(
                    self.log_config.get('moderation_log_channel_id'),
                    self.log_config.get('emoji_update_message', {}),
                    guild=guild,
                    emojis=', '.join([str(e) for e in updated]),
                    staffer=staffer,
                    total_members=guild.member_count
                )
        except Exception as e:
            logger.error(f'Errore in on_guild_emojis_update: {e}')

    @commands.Cog.listener()
    async def on_guild_stickers_update(self, guild: discord.Guild, before, after):
        try:
            added = [s for s in after if s not in before]
            removed = [s for s in before if s not in after]
            updated = [s for s in after if s in before and any(getattr(s, attr) != getattr(next((b for b in before if b.id == s.id), None), attr) for attr in ['name'])]

            if added:
                staffer = await self._get_audit_user(discord.AuditLogAction.sticker_create, added[0].id, guild)
                logger.info(f'Sticker added: {", ".join([s.name for s in added])} by {staffer}')
                await self._send_log_embed(
                    self.log_config.get('moderation_log_channel_id'),
                    self.log_config.get('sticker_create_message', {}),
                    guild=guild,
                    stickers=', '.join([s.name for s in added]),
                    staffer=staffer,
                    total_members=guild.member_count
                )
            if removed:
                staffer = await self._get_audit_user(discord.AuditLogAction.sticker_delete, removed[0].id, guild)
                logger.info(f'Sticker removed: {", ".join([s.name for s in removed])} by {staffer}')
                await self._send_log_embed(
                    self.log_config.get('moderation_log_channel_id'),
                    self.log_config.get('sticker_delete_message', {}),
                    guild=guild,
                    stickers=', '.join([s.name for s in removed]),
                    staffer=staffer,
                    total_members=guild.member_count
                )
            if updated:
                staffer = await self._get_audit_user(discord.AuditLogAction.sticker_update, updated[0].id, guild)
                logger.info(f'Sticker updated: {", ".join([s.name for s in updated])} by {staffer}')
                await self._send_log_embed(
                    self.log_config.get('moderation_log_channel_id'),
                    self.log_config.get('sticker_update_message', {}),
                    guild=guild,
                    stickers=', '.join([s.name for s in updated]),
                    staffer=staffer,
                    total_members=guild.member_count
                )
        except Exception as e:
            logger.error(f'Errore in on_guild_stickers_update: {e}')

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        try:
            staffer = await self._get_audit_user(discord.AuditLogAction.role_create, role.id, role.guild)
            logger.info(f'Role created: {role.name} ({role.id}) by {staffer}')
            await self._send_log_embed(
                self.log_config.get('moderation_log_channel_id'),
                self.log_config.get('role_create_message', {}),
                guild=role.guild,
                role=role.mention,
                id=role.id,
                staffer=staffer,
                total_members=role.guild.member_count
            )
        except Exception as e:
            logger.error(f'Errore in on_guild_role_create: {e}')

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        try:
            staffer = await self._get_audit_user(discord.AuditLogAction.role_delete, role.id, role.guild)
            logger.info(f'Role deleted: {role.name} ({role.id}) by {staffer}')
            await self._send_log_embed(
                self.log_config.get('moderation_log_channel_id'),
                self.log_config.get('role_delete_message', {}),
                guild=role.guild,
                name=role.name,
                id=role.id,
                staffer=staffer,
                total_members=role.guild.member_count
            )
        except Exception as e:
            logger.error(f'Errore in on_guild_role_delete: {e}')

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        try:
            changes = []
            if before.name != after.name:
                changes.append(f"Nome: {before.name} → {after.name}")
            if before.description != after.description:
                changes.append(f"Descrizione: {before.description or 'Nessuna'} → {after.description or 'Nessuna'}")
            if before.icon != after.icon:
                changes.append("Icona cambiata")
            if before.banner != after.banner:
                changes.append("Banner cambiato")
            if before.splash != after.splash:
                changes.append("Splash cambiato")
            if before.afk_channel != after.afk_channel:
                changes.append(f"Canale AFK: {before.afk_channel.mention if before.afk_channel else 'Nessuno'} → {after.afk_channel.mention if after.afk_channel else 'Nessuno'}")
            if before.system_channel != after.system_channel:
                changes.append(f"Canale di sistema: {before.system_channel.mention if before.system_channel else 'Nessuno'} → {after.system_channel.mention if after.system_channel else 'Nessuno'}")

            if changes:
                staffer = await self._get_audit_user(discord.AuditLogAction.guild_update, after.id, after)
                logger.info(f'Guild updated: {after.name} ({after.id}) by {staffer} - Changes: {", ".join(changes)}')
                await self._send_log_embed(
                    self.log_config.get('moderation_log_channel_id'),
                    self.log_config.get('guild_update_message', {}),
                    guild=after,
                    name=after.name,
                    id=after.id,
                    staffer=staffer,
                    total_members=after.member_count,
                    changes=', '.join(changes)
                )
        except Exception as e:
            logger.error(f'Errore in on_guild_update: {e}')

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        try:
            if before.channel != after.channel:
                if before.channel is None and after.channel is not None:
                    logger.info(f'Voice join: {member.name} ({member.id}) joined {after.channel.name}')
                    await self._send_log_embed(
                        self.log_config.get('voice_log_channel_id'),
                        self.log_config.get('vc_join_message', {}),
                        guild=member.guild,
                        mention=member.mention,
                        id=member.id,
                        avatar=member.display_avatar.url,
                        author_name=member.name,
                        author_icon=member.display_avatar.url,
                        total_members=member.guild.member_count,
                        channel=after.channel.mention
                    )
                elif before.channel is not None and after.channel is None:
                    logger.info(f'Voice leave: {member.name} ({member.id}) left {before.channel.name}')
                    await self._send_log_embed(
                        self.log_config.get('voice_log_channel_id'),
                        self.log_config.get('vc_leave_message', {}),
                        guild=member.guild,
                        mention=member.mention,
                        id=member.id,
                        avatar=member.display_avatar.url,
                        author_name=member.name,
                        author_icon=member.display_avatar.url,
                        total_members=member.guild.member_count,
                        channel=before.channel.mention
                    )
                elif before.channel is not None and after.channel is not None:
                    logger.info(f'Voice move: {member.name} ({member.id}) moved from {before.channel.name} to {after.channel.name}')
                    await self._send_log_embed(
                        self.log_config.get('voice_log_channel_id'),
                        self.log_config.get('vc_move_message', {}),
                        guild=member.guild,
                        mention=member.mention,
                        id=member.id,
                        avatar=member.display_avatar.url,
                        author_name=member.name,
                        author_icon=member.display_avatar.url,
                        total_members=member.guild.member_count,
                        old_channel=before.channel.mention,
                        new_channel=after.channel.mention
                    )
        except Exception as e:
            logger.error(f'Errore in on_voice_state_update: {e}')

async def setup(bot):
    await bot.add_cog(LogCog(bot))
