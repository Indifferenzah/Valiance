import discord
from discord.ext import commands
from discord import ui
import json
import os
from datetime import datetime
from discord import InteractionType
import asyncio

class TicketCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        with open('config.json', 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        self.ticket_messages = {}
        if os.path.exists('ticketmsg.json'):
            with open('ticketmsg.json', 'r', encoding='utf-8') as f:
                try:
                    self.ticket_messages = json.load(f)
                except Exception:
                    self.ticket_messages = {}
        self.ticket_owners = {}
        if os.path.exists('ticket.json'):
            with open('ticket.json', 'r') as f:
                loaded = json.load(f)
                self.ticket_owners = {int(k): v for k, v in loaded.items()}
        self.blacklist = []
        if os.path.exists('blacklist.json'):
            with open('blacklist.json', 'r') as f:
                self.blacklist = json.load(f)

    def save_tickets(self):
        with open('ticket.json', 'w') as f:
            json.dump(self.ticket_owners, f)

    async def _delete_message_later(self, message: discord.Message, delay: int = 3):
        try:
            await asyncio.sleep(delay)
            await message.delete()
        except Exception:
            pass

    def _format_message_for_transcript(self, message: discord.Message, staff_role_id=None):
        prefix = ''
        try:
            if message.author.id == self.bot.user.id:
                prefix = '[BOT] '
            else:
                cw_role_id = 1350073967716732971
                try:
                    author_roles = getattr(message.author, 'roles', []) or []
                    if staff_role_id and any(role.id == int(staff_role_id) for role in author_roles):
                        prefix = '[STAFF] '
                    elif any(getattr(r, 'id', None) == cw_role_id for r in author_roles):
                        prefix = '[STAFF CW] '
                except Exception:
                    if staff_role_id and any(role.id == int(staff_role_id) for role in message.author.roles):
                        prefix = '[STAFF] '
        except Exception:
            pass

        parts = []
        if message.content and message.content.strip():
            parts.append(message.content)

        for emb in getattr(message, 'embeds', []) or []:
            emb_parts = []
            if getattr(emb, 'title', None):
                emb_parts.append(str(emb.title))
            if getattr(emb, 'description', None):
                emb_parts.append(str(emb.description))
            for f in getattr(emb, 'fields', []) or []:
                try:
                    emb_parts.append(f"{f.name}: {f.value}")
                except Exception:
                    pass
            if emb_parts:
                parts.append('[EMBED] ' + ' | '.join(emb_parts))

        if getattr(message, 'attachments', None):
            atts = [a.filename for a in message.attachments]
            if atts:
                parts.append('[ATTACHMENTS] ' + ', '.join(atts))

        content = ' '.join(parts) if parts else ''
        time_str = message.created_at.strftime("[%Y-%m-%d %H:%M:%S]") if getattr(message, 'created_at', None) else ''
        author = getattr(message.author, 'name', str(getattr(message.author, 'id', 'Unknown')))
        return f"{time_str} {prefix}{author}: {content}"

    @commands.command(name='ticketpanel')
    async def ticketpanel(self, ctx):
        if ctx.author.id != 1123622103917285418:
            await ctx.send('❌ Non hai i permessi per usare questo comando!')
            return

        panel = self.config.get('ticket_panel', {})
        embed = discord.Embed(
            title=panel.get('title', 'Support Tickets'),
            description=panel.get('description', 'Click a button to open a ticket'),
            color=panel.get('color', 0x00ff00)
        )
        if panel.get('thumbnail'):
            embed.set_thumbnail(url=panel['thumbnail'])
        if panel.get('footer'):
            embed.set_footer(text=panel['footer'])

        all_buttons = self.config.get('ticket_buttons', [])
        user_role_ids = [str(role.id) for role in ctx.author.roles]
        filtered_buttons = []
        for btn in all_buttons:
            roles = btn.get('roles', [])
            if not roles or any(role_id in user_role_ids for role_id in roles):
                filtered_buttons.append(btn)

        view = TicketView(filtered_buttons, self.config, self)
        message = await ctx.send(embed=embed, view=view)

        self.config['ticket_panel_channel_id'] = ctx.channel.id
        self.config['ticket_panel_message_id'] = message.id
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)

    @commands.command(name='close')
    async def close(self, ctx):
        if ctx.channel.id not in self.ticket_owners:
            await ctx.send('❌ Questo comando può essere usato solo nei canali ticket!')
            return

        staff_role_id = self.config.get('ticket_staff_role_id')
        if staff_role_id and not any(role.id == int(staff_role_id) for role in ctx.author.roles):
            await ctx.send('❌ Non hai i permessi per chiudere i ticket!')
            return

        try:
            asyncio.create_task(self._delete_message_later(ctx.message, 3))
        except Exception:
            pass

        embed = discord.Embed(
            title='Conferma Chiusura',
            description='Sei sicuro di voler chiudere questo ticket? Verrà generato e inviato il transcript.',
            color=0xff0000
        )
        view = ConfirmCloseView(ctx.channel.id, self)
        await ctx.send(embed=embed, view=view)

    @commands.command(name='transcript')
    async def transcript(self, ctx):
        if ctx.channel.id not in self.ticket_owners:
            await ctx.send('❌ Questo comando può essere usato solo nei canali ticket!')
            return

        staff_role_id = self.config.get('ticket_staff_role_id')
        if staff_role_id and not any(role.id == int(staff_role_id) for role in ctx.author.roles):
            await ctx.send('❌ Non hai i permessi per creare transcript!')
            return

        messages = []
        staff_role_id = self.config.get('ticket_staff_role_id')
        async for message in ctx.channel.history(limit=None, oldest_first=True):
            messages.append(self._format_message_for_transcript(message, staff_role_id))

        filename = f'transcript-{ctx.channel.name}-{datetime.now().strftime("%Y%m%d%H%M%S")}.txt'
        with open(filename, 'w', encoding='utf-8') as f:
            f.write('\n'.join(messages))

        embed_data = self.config.get('ticket_transcript_embed', {})
        embed = discord.Embed(
            title=embed_data.get('title', 'Transcript del Ticket'),
            description=embed_data.get('description', 'Ecco il transcript del ticket.'),
            color=embed_data.get('color', 0x00ff00)
        )
        if embed_data.get('thumbnail'):
            embed.set_thumbnail(url=embed_data['thumbnail'])
        if embed_data.get('footer'):
            embed.set_footer(text=embed_data['footer'])

        ticket_info = self.ticket_owners.get(ctx.channel.id, {})
        if isinstance(ticket_info, int):
            owner_id = ticket_info
            button_id = ''
        else:
            owner_id = ticket_info.get('owner')
            button_id = ticket_info.get('button', '')
        opener = self.bot.get_user(owner_id).mention if owner_id and self.bot.get_user(owner_id) else 'Unknown'
        staffer = ctx.author.mention
        name = ctx.channel.name

        embed.title = embed.title.replace('{opener}', opener).replace('{staffer}', staffer).replace('{name}', name).replace('{id}', button_id)
        embed.description = embed.description.replace('{opener}', opener).replace('{staffer}', staffer).replace('{name}', name).replace('{id}', button_id)
        if embed.footer:
            embed.set_footer(text=embed.footer.text.replace('{opener}', opener).replace('{staffer}', staffer).replace('{name}', name).replace('{id}', button_id))

        transcript_channel_id = self.config.get('ticket_transcript_channel_id')
        if transcript_channel_id:
            channel = self.bot.get_channel(int(transcript_channel_id))
            if channel:
                await channel.send(embed=embed, file=discord.File(filename))
                tpl = self.ticket_messages.get('transcript')
                if tpl:
                    e = discord.Embed(title=tpl.get('title'), description=tpl.get('description', '').replace('{name}', name).replace('{author}', ctx.author.mention), color=tpl.get('color', 0x00ff00))
                    if tpl.get('footer'):
                        e.set_footer(text=tpl.get('footer'))
                    await ctx.send(embed=e)
                else:
                    await ctx.send('✅ Transcript inviato!')
            else:
                await ctx.send('❌ Canale transcript non trovato!')
        else:
            await ctx.send('❌ Canale transcript non configurato!')

        if owner_id:
            owner = channel.guild.get_member(owner_id)
            if owner:
                try:
                    await owner.send(embed=embed, file=discord.File(filename))
                except discord.Forbidden:
                    pass

        os.remove(filename)

    @commands.command(name='add')
    async def add_user(self, ctx, member: discord.Member):
        try:
            asyncio.create_task(self._delete_message_later(ctx.message, 3))
        except Exception:
            pass
        if ctx.channel.id not in self.ticket_owners:
            await ctx.send('❌ Questo comando può essere usato solo nei canali ticket!')
            return

        staff_role_id = self.config.get('ticket_staff_role_id')
        if not staff_role_id or not any(role.id == int(staff_role_id) for role in ctx.author.roles):
            await ctx.send('❌ Non hai i permessi per usare questo comando!')
            return

        if ctx.channel.permissions_for(member).read_messages:
            await ctx.send('❌ L\'utente è già nel ticket!')
            return
        overwrites = ctx.channel.overwrites
        overwrites[member] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        await ctx.channel.edit(overwrites=overwrites)
        tpl = self.ticket_messages.get('add')
        if tpl:
            e = discord.Embed(title=tpl.get('title'), description=tpl.get('description', '').replace('{member}', member.mention).replace('{author}', ctx.author.mention), color=tpl.get('color', 0x00ff00))
            # thumbnail from template
            if tpl.get('thumbnail'):
                e.set_thumbnail(url=tpl.get('thumbnail'))
            # author header (who performed the action)
            try:
                e.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar.url)
            except Exception:
                pass
            if tpl.get('footer'):
                e.set_footer(text=tpl.get('footer'))
            await ctx.send(embed=e)

    @commands.command(name='remove')
    async def remove_user(self, ctx, member: discord.Member):
        try:
            asyncio.create_task(self._delete_message_later(ctx.message, 3))
        except Exception:
            pass
        if ctx.channel.id not in self.ticket_owners:
            await ctx.send('❌ Questo comando può essere usato solo nei canali ticket!')
            return

        staff_role_id = self.config.get('ticket_staff_role_id')
        if not staff_role_id or not any(role.id == int(staff_role_id) for role in ctx.author.roles):
            await ctx.send('❌ Non hai i permessi per usare questo comando!')
            return

        if not ctx.channel.permissions_for(member).read_messages:
            await ctx.send('❌ L\'utente non è nel ticket!')
            return

        ticket_info = self.ticket_owners.get(ctx.channel.id, {})
        if isinstance(ticket_info, int):
            ticket_owner = ticket_info
        else:
            ticket_owner = ticket_info.get('owner')
        if member.id == ticket_owner:
            await ctx.send('❌ Non puoi rimuovere il proprietario del ticket!')
            return

        if staff_role_id and any(role.id == int(staff_role_id) for role in member.roles):
            await ctx.send('❌ Non puoi rimuovere uno staffer!')
            return

        overwrites = ctx.channel.overwrites
        if member in overwrites:
            del overwrites[member]
        await ctx.channel.edit(overwrites=overwrites)
        tpl = self.ticket_messages.get('remove')
        if tpl:
            e = discord.Embed(title=tpl.get('title'), description=tpl.get('description', '').replace('{member}', member.mention).replace('{author}', ctx.author.mention), color=tpl.get('color', 0xff0000))
            if tpl.get('thumbnail'):
                e.set_thumbnail(url=tpl.get('thumbnail'))
            try:
                e.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar.url)
            except Exception:
                pass
            if tpl.get('footer'):
                e.set_footer(text=tpl.get('footer'))
            await ctx.send(embed=e)

    @commands.command(name='rename')
    async def rename_ticket(self, ctx, *, new_name: str):
        try:
            asyncio.create_task(self._delete_message_later(ctx.message, 3))
        except Exception:
            pass
        if ctx.channel.id not in self.ticket_owners:
            msg = await ctx.send('❌ Questo comando può essere usato solo nei canali ticket!')
            try:
                asyncio.create_task(self._delete_message_later(msg, 3))
            except Exception:
                pass
            return

        staff_role_id = self.config.get('ticket_staff_role_id')
        if not staff_role_id or not any(role.id == int(staff_role_id) for role in ctx.author.roles):
            msg = await ctx.send('❌ Non hai i permessi per usare questo comando!')
            try:
                asyncio.create_task(self._delete_message_later(msg, 3))
            except Exception:
                pass
            return

        if len(new_name) > 100:
            msg = await ctx.send('❌ Il nome è troppo lungo! (max 100 caratteri)')
            try:
                asyncio.create_task(self._delete_message_later(msg, 3))
            except Exception:
                pass
            return

        try:
            await ctx.channel.edit(name=new_name)
            tpl = self.ticket_messages.get('rename')
            sent = None
            if tpl:
                e = discord.Embed(title=tpl.get('title'), description=tpl.get('description', '').replace('{name}', new_name).replace('{author}', ctx.author.mention), color=tpl.get('color', 0x00ff00))
                if tpl.get('thumbnail'):
                    e.set_thumbnail(url=tpl.get('thumbnail'))
                try:
                    e.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar.url)
                except Exception:
                    pass
                if tpl.get('footer'):
                    e.set_footer(text=tpl.get('footer'))
                sent = await ctx.send(embed=e)
        except discord.Forbidden:
            sent = await ctx.send('❌ Non ho i permessi per rinominare il canale!')
            try:
                asyncio.create_task(self._delete_message_later(sent, 3))
            except Exception:
                pass
        except Exception as e:
            sent = await ctx.send(f'❌ Errore nel rinominare: {e}')
            try:
                asyncio.create_task(self._delete_message_later(sent, 3))
            except Exception:
                pass

    @commands.command(name='blacklist')
    async def blacklist_user(self, ctx, member: discord.Member = None):
        staff_role_id = self.config.get('ticket_staff_role_id')
        if not staff_role_id or not any(role.id == int(staff_role_id) for role in ctx.author.roles):
            await ctx.send('❌ Non hai i permessi per usare questo comando!')
            return

        if member is None:
            await ctx.send('Devi specificare un utente!')
            return

        if member.id in self.blacklist:
            self.blacklist.remove(member.id)
            await ctx.send(f'✅ {member.mention} è stato rimosso dalla blacklist!')
        else:
            self.blacklist.append(member.id)
            await ctx.send(f'✅ {member.mention} è stato aggiunto alla blacklist!')

        with open('blacklist.json', 'w') as f:
            json.dump(self.blacklist, f)



class TicketView(discord.ui.View):
    def __init__(self, buttons, config, cog):
        super().__init__(timeout=None)
        self.config = config
        self.cog = cog
        for btn in buttons:
            self.add_item(TicketButton(btn, self.config))

class TicketButton(discord.ui.Button):
    def __init__(self, btn_config, config):
        style_str = btn_config.get('style', 'primary')
        style = getattr(discord.ButtonStyle, style_str, discord.ButtonStyle.primary)
        super().__init__(
            label=btn_config['label'],
            emoji=btn_config.get('emoji'),
            style=style,
            custom_id=btn_config['id']
        )
        self.btn_config = btn_config
        self.config = config

    async def callback(self, interaction):
        if interaction.user.id in self.view.cog.blacklist:
            await interaction.response.send_message('❌ Sei nella blacklist e non puoi aprire ticket!', ephemeral=True)
            return
        guild = interaction.guild
        category_id = self.config.get('ticket_category_id')
        category = guild.get_channel(int(category_id)) if category_id else None

        staff_role_id = self.config.get('ticket_staff_role_id')
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        if staff_role_id:
            role = guild.get_role(int(staff_role_id))
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        additional_roles = self.btn_config.get('roles', [])
        for role_id in additional_roles:
            role = guild.get_role(int(role_id))
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        channel = await guild.create_text_channel(
            name=f'ticket-{interaction.user.name}',
            category=category,
            overwrites=overwrites
        )

        self.view.cog.ticket_owners[channel.id] = {'owner': interaction.user.id, 'button': self.custom_id}

        outside_message = self.btn_config.get('outside_message', 'Ticket aperto!')
        outside_message = outside_message.replace('{mention}', interaction.user.mention)
        await channel.send(outside_message)

        embed_message = self.btn_config.get('embed_message', 'A breve riceverai il supporto richiesto.\nClicca il bottone sotto per chiudere il ticket.')
        embed = discord.Embed(description=embed_message, color=0x00ff00)
        view = CloseTicketView(channel.id, self.view.cog)
        message = await channel.send(embed=embed, view=view)
        self.view.cog.ticket_owners[channel.id]['close_message_id'] = message.id
        self.view.cog.save_tickets()

        await interaction.response.send_message(f'🎫 Ticket creato: {channel.mention}', ephemeral=True)

class CloseTicketView(discord.ui.View):
    def __init__(self, channel_id, cog):
        super().__init__(timeout=None)
        self.channel_id = channel_id
        self.cog = cog

    @discord.ui.button(label='Chiudi Ticket', style=discord.ButtonStyle.danger, emoji='🔒')
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = self.cog.bot.get_channel(self.channel_id)
        if not channel:
            await interaction.response.send_message('❌ Canale non trovato!', ephemeral=True)
            return

        ticket_info = self.cog.ticket_owners.get(self.channel_id, {})
        if isinstance(ticket_info, int):
            ticket_owner = ticket_info
        else:
            ticket_owner = ticket_info.get('owner')
        staff_role_id = self.cog.config.get('ticket_staff_role_id')
        is_staff = staff_role_id and any(role.id == int(staff_role_id) for role in interaction.user.roles)

        if not is_staff:
            await interaction.response.send_message('❌ Solo uno staffer può chiudere il ticket!', ephemeral=True)
            return

        embed = discord.Embed(
            title='Conferma Chiusura',
            description='Sei sicuro di voler chiudere questo ticket? Verrà generato e inviato il transcript.',
            color=0xff0000
        )
        view = ConfirmCloseView(self.channel_id, self.cog)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class ConfirmCloseView(discord.ui.View):
    def __init__(self, channel_id, cog):
        super().__init__(timeout=300)
        self.channel_id = channel_id
        self.cog = cog

    @discord.ui.button(label='Conferma', style=discord.ButtonStyle.danger, emoji='✅')
    async def confirm_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = self.cog.bot.get_channel(self.channel_id)
        if not channel:
            await interaction.response.send_message('❌ Canale non trovato!', ephemeral=True)
            return

        messages = []
        staff_role_id = self.cog.config.get('ticket_staff_role_id')
        async for message in channel.history(limit=None, oldest_first=True):
            messages.append(self.cog._format_message_for_transcript(message, staff_role_id))

        filename = f'transcript-{channel.name}-{datetime.now().strftime("%Y%m%d%H%M%S")}.txt'
        with open(filename, 'w', encoding='utf-8') as f:
            f.write('\n'.join(messages))

        embed_data = self.cog.config.get('ticket_transcript_embed', {})
        embed = discord.Embed(
            title=embed_data.get('title', 'Transcript del Ticket'),
            description=embed_data.get('description', 'Ecco il transcript del ticket.'),
            color=embed_data.get('color', 0x00ff00)
        )
        if embed_data.get('thumbnail'):
            embed.set_thumbnail(url=embed_data['thumbnail'])
        if embed_data.get('footer'):
            embed.set_footer(text=embed_data['footer'])

        ticket_info = self.cog.ticket_owners.get(self.channel_id, {})
        if isinstance(ticket_info, int):
            owner_id = ticket_info
            button_id = ''
        else:
            owner_id = ticket_info.get('owner')
            button_id = ticket_info.get('button', '')
        opener = self.cog.bot.get_user(owner_id).mention if owner_id and self.cog.bot.get_user(owner_id) else 'Unknown'
        staffer = interaction.user.mention
        name = channel.name

        embed.title = embed.title.replace('{opener}', opener).replace('{staffer}', staffer).replace('{name}', name).replace('{id}', button_id)
        embed.description = embed.description.replace('{opener}', opener).replace('{staffer}', staffer).replace('{name}', name).replace('{id}', button_id)
        if embed.footer:
            embed.set_footer(text=embed.footer.text.replace('{opener}', opener).replace('{staffer}', staffer).replace('{name}', name).replace('{id}', button_id))

        transcript_channel_id = self.cog.config.get('ticket_transcript_channel_id')
        if transcript_channel_id:
            transcript_channel = self.cog.bot.get_channel(int(transcript_channel_id))
            if transcript_channel:
                await transcript_channel.send(embed=embed, file=discord.File(filename))
            else:
                print('Canale transcript non trovato!')

        if owner_id:
            owner = channel.guild.get_member(owner_id)
            if owner:
                try:
                    await owner.send(embed=embed, file=discord.File(filename))
                except discord.Forbidden:
                    pass

        os.remove(filename)

        await channel.delete()

        if self.channel_id in self.cog.ticket_owners:
            del self.cog.ticket_owners[self.channel_id]
            self.cog.save_tickets()

    @discord.ui.button(label='Annulla', style=discord.ButtonStyle.secondary, emoji='❌')
    async def cancel_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message('Chiusura annullata.', ephemeral=True)

async def setup(bot):
    await bot.add_cog(TicketCog(bot))
