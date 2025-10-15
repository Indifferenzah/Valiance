import discord
from discord.ext import commands
from discord import ui
import json
import os
from datetime import datetime
from discord import InteractionType
import asyncio
from discord import app_commands
from bot_utils import is_owner
from console_logger import logger

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
        self.closed_tickets = {}
        if os.path.exists('closed_tickets.json'):
            with open('closed_tickets.json', 'r') as f:
                try:
                    self.closed_tickets = json.load(f)
                except Exception:
                    self.closed_tickets = {}
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

    @app_commands.command(name='ticketpanel', description='Crea un pannello per i ticket di supporto')
    async def slash_ticketpanel(self, interaction: discord.Interaction):
        if not is_owner(interaction.user):
            await interaction.response.send_message('❌ Non hai i permessi per usare questo comando!', ephemeral=True)
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
        user_role_ids = [str(role.id) for role in interaction.user.roles]
        filtered_buttons = []
        for btn in all_buttons:
            roles = btn.get('roles', [])
            if not roles or any(role_id in user_role_ids for role_id in roles):
                filtered_buttons.append(btn)

        view = TicketView(filtered_buttons, self.config, self)
        message = await interaction.channel.send(embed=embed, view=view)

        self.config['ticket_panel_channel_id'] = interaction.channel.id
        self.config['ticket_panel_message_id'] = message.id
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)

        await interaction.response.send_message('✅ Pannello ticket creato!', ephemeral=True)

    @app_commands.command(name='close', description='Avvia la procedura di chiusura del ticket (mostra il pannello di conferma)')
    async def slash_close(self, interaction: discord.Interaction):
        ctx = await self.bot.get_context(interaction.message) if interaction.message else None
        channel = interaction.channel
        if channel.id not in self.ticket_owners:
            await interaction.response.send_message('❌ Questo comando può essere usato solo nei canali ticket!', ephemeral=True)
            return

        staff_role_id = self.config.get('ticket_staff_role_id')
        if staff_role_id and not any(role.id == int(staff_role_id) for role in interaction.user.roles):
            await interaction.response.send_message('❌ Non hai i permessi per chiudere i ticket!', ephemeral=True)
            return

        try:
            asyncio.create_task(self._delete_message_later(interaction.message, 3))
        except Exception:
            pass

        embed = discord.Embed(
            title='Conferma Chiusura',
            description='Sei sicuro di voler chiudere questo ticket? Verrà generato e inviato il transcript.',
            color=0xff0000
        )
        view = ConfirmCloseView(channel.id, self)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)



    @app_commands.command(name='rename', description='Rinomina il canale ticket')
    @app_commands.describe(new_name='Il nuovo nome del canale (max 100 caratteri)')
    async def slash_rename_ticket(self, interaction: discord.Interaction, new_name: str):
        channel = interaction.channel
        try:
            if channel.id not in self.ticket_owners:
                await interaction.response.send_message('❌ Questo comando può essere usato solo nei canali ticket!', ephemeral=True)
                return

            staff_role_id = self.config.get('ticket_staff_role_id')
            if not staff_role_id or not any(role.id == int(staff_role_id) for role in interaction.user.roles):
                await interaction.response.send_message('❌ Non hai i permessi per usare questo comando!', ephemeral=True)
                return

            if len(new_name) > 100:
                await interaction.response.send_message('❌ Il nome è troppo lungo! (max 100 caratteri)', ephemeral=True)
                return

            if channel.id in self.ticket_owners and 'number' not in self.ticket_owners[channel.id]:
                try:
                    old_number = int(channel.name.split('-')[1])
                    self.ticket_owners[channel.id]['number'] = old_number
                    self.save_tickets()
                except (IndexError, ValueError):
                    pass
            await channel.edit(name=new_name)
            tpl = self.ticket_messages.get('rename')
            if tpl:
                e = discord.Embed(title=tpl.get('title'), description=tpl.get('description', '').replace('{name}', new_name).replace('{author}', interaction.user.mention), color=tpl.get('color', 0x00ff00))
                if tpl.get('thumbnail'):
                    e.set_thumbnail(url=tpl.get('thumbnail'))
                try:
                    e.set_author(name=interaction.user.name, icon_url=interaction.user.display_avatar.url)
                except Exception:
                    pass
                if tpl.get('footer'):
                    e.set_footer(text=tpl.get('footer'))
                await interaction.response.send_message(embed=e, ephemeral=False)
            else:
                await interaction.response.send_message('✅ Canale rinominato!', ephemeral=False)
        except discord.Forbidden:
            await interaction.response.send_message('❌ Non ho i permessi per rinominare il canale!', ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f'❌ Errore nel rinominare: {e}', ephemeral=True)

    @app_commands.command(name='blacklist', description='Aggiungi/rimuovi un utente dalla blacklist dei ticket')
    @app_commands.describe(member='Utente da blacklistare / de-blacklistare')
    async def slash_blacklist_user(self, interaction: discord.Interaction, member: discord.Member):
        staff_role_id = self.config.get('ticket_staff_role_id')
        if not staff_role_id or not any(role.id == int(staff_role_id) for role in interaction.user.roles):
            await interaction.response.send_message('❌ Non hai i permessi per usare questo comando!', ephemeral=True)
            return

        if member.id in self.blacklist:
            self.blacklist.remove(member.id)
            await interaction.response.send_message(f'✅ {member.mention} è stato rimosso dalla blacklist!', ephemeral=True)
        else:
            self.blacklist.append(member.id)
            await interaction.response.send_message(f'✅ {member.mention} è stato aggiunto alla blacklist!', ephemeral=True)

        with open('blacklist.json', 'w') as f:
            json.dump(self.blacklist, f)

    @app_commands.command(name='add', description='Aggiungi un utente al ticket')
    @app_commands.describe(member='Utente da aggiungere')
    async def slash_add_user(self, interaction: discord.Interaction, member: discord.Member):
        try:
            tpl = self.ticket_messages.get('add')
            if interaction.channel.id not in self.ticket_owners:
                await interaction.response.send_message('❌ Questo comando può essere usato solo nei canali ticket!', ephemeral=True)
                return

            staff_role_id = self.config.get('ticket_staff_role_id')
            if not staff_role_id or not any(role.id == int(staff_role_id) for role in interaction.user.roles):
                await interaction.response.send_message('❌ Non hai i permessi per usare questo comando!', ephemeral=True)
                return

            overwrites = interaction.channel.overwrites
            overwrites[member] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            await interaction.channel.edit(overwrites=overwrites)

            if tpl:
                e = discord.Embed(title=tpl.get('title'), description=tpl.get('description', '').replace('{member}', member.mention).replace('{author}', interaction.user.mention), color=tpl.get('color', 0x00ff00))
                if tpl.get('thumbnail'):
                    e.set_thumbnail(url=tpl.get('thumbnail'))
                try:
                    e.set_author(name=interaction.user.name, icon_url=interaction.user.display_avatar.url)
                except Exception:
                    pass
                if tpl.get('footer'):
                    e.set_footer(text=tpl.get('footer'))
                await interaction.response.send_message(embed=e, ephemeral=False)
            else:
                await interaction.response.send_message(f'✅ {member.mention} aggiunto!', ephemeral=False)
        except Exception as e:
            await interaction.response.send_message(f'❌ Errore: {e}', ephemeral=True)

    @app_commands.command(name='remove', description='Rimuovi un utente dal ticket')
    @app_commands.describe(member='Utente da rimuovere')
    async def slash_remove_user(self, interaction: discord.Interaction, member: discord.Member):
        try:
            tpl = self.ticket_messages.get('remove')
            if interaction.channel.id not in self.ticket_owners:
                await interaction.response.send_message('❌ Questo comando può essere usato solo nei canali ticket!', ephemeral=True)
                return

            staff_role_id = self.config.get('ticket_staff_role_id')
            if not staff_role_id or not any(role.id == int(staff_role_id) for role in interaction.user.roles):
                await interaction.response.send_message('❌ Non hai i permessi per usare questo comando!', ephemeral=True)
                return

            if not interaction.channel.permissions_for(member).read_messages:
                await interaction.response.send_message('❌ L\'utente non è nel ticket!', ephemeral=True)
                return

            ticket_info = self.ticket_owners.get(interaction.channel.id, {})
            if isinstance(ticket_info, int):
                ticket_owner = ticket_info
            else:
                ticket_owner = ticket_info.get('owner')
            if member.id == ticket_owner:
                await interaction.response.send_message('❌ Non puoi rimuovere il proprietario del ticket!', ephemeral=True)
                return

            if staff_role_id and any(role.id == int(staff_role_id) for role in member.roles):
                await interaction.response.send_message('❌ Non puoi rimuovere uno staffer!', ephemeral=True)
                return

            overwrites = interaction.channel.overwrites
            if member in overwrites:
                del overwrites[member]
            await interaction.channel.edit(overwrites=overwrites)

            if tpl:
                e = discord.Embed(title=tpl.get('title'), description=tpl.get('description', '').replace('{member}', member.mention).replace('{author}', interaction.user.mention), color=tpl.get('color', 0xff0000))
                if tpl.get('thumbnail'):
                    e.set_thumbnail(url=tpl.get('thumbnail'))
                try:
                    e.set_author(name=interaction.user.name, icon_url=interaction.user.display_avatar.url)
                except Exception:
                    pass
                if tpl.get('footer'):
                    e.set_footer(text=tpl.get('footer'))
                await interaction.response.send_message(embed=e, ephemeral=False)
            else:
                await interaction.response.send_message(f'✅ {member.mention} rimosso!', ephemeral=False)
        except Exception as e:
            await interaction.response.send_message(f'❌ Errore: {e}', ephemeral=True)

    @app_commands.command(name='list', description='Mostra i ticket aperti e chiusi di un utente')
    @app_commands.describe(user='Utente di cui mostrare i ticket')
    async def slash_list_tickets(self, interaction: discord.Interaction, user: discord.Member):
        staff_role_id = self.config.get('ticket_staff_role_id')
        if not staff_role_id or not any(role.id == int(staff_role_id) for role in interaction.user.roles):
            await interaction.response.send_message('❌ Non hai i permessi per usare questo comando!', ephemeral=True)
            return

        open_tickets = []
        closed_tickets = []

        for channel_id, info in self.ticket_owners.items():
            owner_id = info.get('owner') if isinstance(info, dict) else info
            if owner_id == user.id:
                channel = self.bot.get_channel(channel_id)
                if channel:
                    open_tickets.append(channel.mention)

        for ticket_num, info in self.closed_tickets.items():
            if info.get('owner') == user.id:
                closed_tickets.append(f"***`#{ticket_num}`*** - {info.get('channel_name', 'Unknown')}")

        embed = discord.Embed(
            title=f'Ticket di {user.name}',
            color=0x00ff00
        )
        embed.set_author(name=user.name, icon_url=user.display_avatar.url)
        embed.set_footer(text='Valiance | Ticket System')

        if open_tickets:
            embed.add_field(name='**Ticket Aperti**', value='\n'.join(open_tickets), inline=False)
        else:
            embed.add_field(name='**Ticket Aperti**', value='Nessuno', inline=False)

        if closed_tickets:
            embed.add_field(name='**Ticket Chiusi**', value='\n'.join(closed_tickets), inline=False)
        else:
            embed.add_field(name='**Ticket Chiusi**', value='Nessuno', inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)
        await asyncio.sleep(60)
        try:
            await interaction.delete_original_response()
        except Exception:
            pass

    @app_commands.command(name='transcript', description='Invia il transcript di un ticket chiuso')
    @app_commands.describe(number='Numero del ticket')
    async def slash_transcript(self, interaction: discord.Interaction, number: int):
        ticket_str = str(number)
        if ticket_str not in self.closed_tickets:
            await interaction.response.send_message('❌ Ticket non trovato!', ephemeral=True)
            return

        ticket_info = self.closed_tickets[ticket_str]
        owner_id = ticket_info.get('owner')
        if owner_id != interaction.user.id:
            staff_role_id = self.config.get('ticket_staff_role_id')
            if not staff_role_id or not any(role.id == int(staff_role_id) for role in interaction.user.roles):
                await interaction.response.send_message('❌ Non hai i permessi per vedere questo transcript!', ephemeral=True)
                return

        filename = ticket_info.get('transcript_file')
        if not os.path.exists(filename):
            await interaction.response.send_message('❌ Transcript non trovato!', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(file=discord.File(filename), ephemeral=True)



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

        ticket_number = self.view.cog.config.get('ticket_counter', 0) + 1
        self.view.cog.config['ticket_counter'] = ticket_number
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(self.view.cog.config, f, indent=2, ensure_ascii=False)

        channel = await guild.create_text_channel(
            name=f'ticket-{ticket_number}',
            category=category,
            overwrites=overwrites
        )

        self.view.cog.ticket_owners[channel.id] = {'owner': interaction.user.id, 'button': self.custom_id, 'number': ticket_number}

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

        ticket_info = self.cog.ticket_owners.get(self.channel_id, {})
        if isinstance(ticket_info, int):
            owner_id = ticket_info
            button_id = ''
            try:
                ticket_number = int(channel.name.split('-')[1])
            except (IndexError, ValueError):
                ticket_number = self.cog.config.get('ticket_counter', 0) + 1
                self.cog.config['ticket_counter'] = ticket_number
                with open('config.json', 'w', encoding='utf-8') as f:
                    json.dump(self.cog.config, f, indent=2, ensure_ascii=False)
        else:
            owner_id = ticket_info.get('owner')
            button_id = ticket_info.get('button', '')
            ticket_number = ticket_info.get('number')

        filename = f'transcripts/transcript-{ticket_number}.txt'
        os.makedirs('transcripts', exist_ok=True)
        with open(filename, 'w', encoding='utf-8') as f:
            f.write('\n'.join(messages))

        self.cog.closed_tickets[str(ticket_number)] = {
            'owner': owner_id,
            'transcript_file': filename,
            'closed_at': datetime.now().isoformat(),
            'button': button_id,
            'channel_name': channel.name
        }
        with open('closed_tickets.json', 'w') as f:
            json.dump(self.cog.closed_tickets, f)

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
                logger.error('Canale transcript non trovato!')

        if owner_id:
            owner = channel.guild.get_member(owner_id)
            if owner:
                try:
                    await owner.send(embed=embed, file=discord.File(filename))
                except discord.Forbidden:
                    pass

        await channel.delete()

        if self.channel_id in self.cog.ticket_owners:
            del self.cog.ticket_owners[self.channel_id]
            self.cog.save_tickets()

    @discord.ui.button(label='Annulla', style=discord.ButtonStyle.secondary, emoji='❌')
    async def cancel_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message('Chiusura annullata.', ephemeral=True)

async def setup(bot):
    await bot.add_cog(TicketCog(bot))