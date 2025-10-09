import discord
from discord.ext import commands
from discord import ui
import json
import os
from datetime import datetime

class TicketCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        with open('config.json', 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        self.ticket_owners = {}

    @commands.command(name='ticketpanel')
    async def ticketpanel(self, ctx):
        # Check if specific user
        if ctx.author.id != 1123622103917285418:
            await ctx.send('❌ Non hai i permessi per usare questo comando!')
            return

        # Get panel config
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

        # Filter buttons based on user roles
        all_buttons = self.config.get('ticket_buttons', [])
        user_role_ids = [str(role.id) for role in ctx.author.roles]
        filtered_buttons = []
        for btn in all_buttons:
            roles = btn.get('roles', [])
            if not roles or any(role_id in user_role_ids for role_id in roles):
                filtered_buttons.append(btn)

        # Create view with filtered buttons
        view = TicketView(filtered_buttons, self.config, self)
        await ctx.send(embed=embed, view=view)

    @commands.command(name='close')
    async def close(self, ctx):
        # Check if in ticket channel
        if ctx.channel.id not in self.ticket_owners:
            await ctx.send('❌ Questo comando può essere usato solo nei canali ticket!')
            return

        # Check permission
        staff_role_id = self.config.get('ticket_staff_role_id')
        if staff_role_id and not any(role.id == int(staff_role_id) for role in ctx.author.roles):
            await ctx.send('❌ Non hai i permessi per chiudere i ticket!')
            return

        await ctx.send('🔒 Chiusura ticket...')
        await ctx.channel.delete()

    @commands.command(name='transcript')
    async def transcript(self, ctx):
        # Check if in ticket channel
        if ctx.channel.id not in self.ticket_owners:
            await ctx.send('❌ Questo comando può essere usato solo nei canali ticket!')
            return

        # Check permission
        staff_role_id = self.config.get('ticket_staff_role_id')
        if staff_role_id and not any(role.id == int(staff_role_id) for role in ctx.author.roles):
            await ctx.send('❌ Non hai i permessi per creare transcript!')
            return

        # Get messages
        messages = []
        async for message in ctx.channel.history(limit=None, oldest_first=True):
            messages.append(f'{message.created_at.strftime("%Y-%m-%d %H:%M:%S")} {message.author}: {message.content}')

        # Create txt
        filename = f'transcript-{ctx.channel.name}-{datetime.now().strftime("%Y%m%d%H%M%S")}.txt'
        with open(filename, 'w', encoding='utf-8') as f:
            f.write('\n'.join(messages))

        # Send to transcript channel
        transcript_channel_id = self.config.get('ticket_transcript_channel_id')
        if transcript_channel_id:
            channel = self.bot.get_channel(int(transcript_channel_id))
            if channel:
                await channel.send(file=discord.File(filename))
                await ctx.send('✅ Transcript inviato!')
            else:
                await ctx.send('❌ Canale transcript non trovato!')
        else:
            await ctx.send('❌ Canale transcript non configurato!')

        # Delete file
        os.remove(filename)

    @commands.command(name='add')
    async def add_user(self, ctx, member: discord.Member):
        # Check if in ticket channel
        if ctx.channel.id not in self.ticket_owners:
            await ctx.send('❌ Questo comando può essere usato solo nei canali ticket!')
            return

        # Check permission
        staff_role_id = self.config.get('ticket_staff_role_id')
        if not staff_role_id or not any(role.id == int(staff_role_id) for role in ctx.author.roles):
            await ctx.send('❌ Non hai i permessi per usare questo comando!')
            return

        # Check if user is already in the channel
        if ctx.channel.permissions_for(member).read_messages:
            await ctx.send('❌ L\'utente è già nel ticket!')
            return

        # Add user to overwrites
        overwrites = ctx.channel.overwrites
        overwrites[member] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        await ctx.channel.edit(overwrites=overwrites)

        await ctx.send(f'✅ {member.mention} è stato aggiunto al ticket!')

    @commands.command(name='remove')
    async def remove_user(self, ctx, member: discord.Member):
        # Check if in ticket channel
        if ctx.channel.id not in self.ticket_owners:
            await ctx.send('❌ Questo comando può essere usato solo nei canali ticket!')
            return

        # Check permission
        staff_role_id = self.config.get('ticket_staff_role_id')
        if not staff_role_id or not any(role.id == int(staff_role_id) for role in ctx.author.roles):
            await ctx.send('❌ Non hai i permessi per usare questo comando!')
            return

        # Check if user is in the channel
        if not ctx.channel.permissions_for(member).read_messages:
            await ctx.send('❌ L\'utente non è nel ticket!')
            return

        # Cannot remove owner or staff
        ticket_owner = self.ticket_owners.get(ctx.channel.id)
        if member.id == ticket_owner:
            await ctx.send('❌ Non puoi rimuovere il proprietario del ticket!')
            return

        if staff_role_id and any(role.id == int(staff_role_id) for role in member.roles):
            await ctx.send('❌ Non puoi rimuovere uno staffer!')
            return

        # Remove user from overwrites
        overwrites = ctx.channel.overwrites
        if member in overwrites:
            del overwrites[member]
        await ctx.channel.edit(overwrites=overwrites)

        await ctx.send(f'✅ {member.mention} è stato rimosso dal ticket!')

    @commands.command(name='rename')
    async def rename_ticket(self, ctx, *, new_name: str):
        # Check if in ticket channel
        if ctx.channel.id not in self.ticket_owners:
            await ctx.send('❌ Questo comando può essere usato solo nei canali ticket!')
            return

        # Check permission
        staff_role_id = self.config.get('ticket_staff_role_id')
        if not staff_role_id or not any(role.id == int(staff_role_id) for role in ctx.author.roles):
            await ctx.send('❌ Non hai i permessi per usare questo comando!')
            return

        # Validate new name
        if len(new_name) > 100:
            await ctx.send('❌ Il nome è troppo lungo! (max 100 caratteri)')
            return

        # Rename channel
        try:
            await ctx.channel.edit(name=new_name)
            await ctx.send(f'✅ Ticket rinominato a `{new_name}`!')
        except discord.Forbidden:
            await ctx.send('❌ Non ho i permessi per rinominare il canale!')
        except Exception as e:
            await ctx.send(f'❌ Errore nel rinominare: {e}')

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
        # Create ticket channel
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

        # Check if button has additional roles
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

        # Store ticket owner
        self.view.cog.ticket_owners[channel.id] = interaction.user.id

        # Send outside message
        outside_message = self.btn_config.get('outside_message', 'Ticket aperto!')
        outside_message = outside_message.replace('{mention}', interaction.user.mention)
        await channel.send(outside_message)

        # Send embed message
        embed_message = self.btn_config.get('embed_message', 'A breve riceverai il supporto richiesto.\nClicca il bottone sotto per chiudere il ticket.')
        embed = discord.Embed(description=embed_message, color=0x00ff00)
        view = CloseTicketView(channel.id, self.view.cog)
        await channel.send(embed=embed, view=view)

        await interaction.response.send_message(f'🎫 Ticket creato: {channel.mention}', ephemeral=True)

class CloseTicketView(discord.ui.View):
    def __init__(self, channel_id, cog):
        super().__init__(timeout=None)
        self.channel_id = channel_id
        self.cog = cog

    @discord.ui.button(label='Chiudi Ticket', style=discord.ButtonStyle.danger, emoji='🔒')
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if the user is the ticket owner or staff
        channel = self.cog.bot.get_channel(self.channel_id)
        if not channel:
            await interaction.response.send_message('❌ Canale non trovato!', ephemeral=True)
            return

        ticket_owner = self.cog.ticket_owners.get(self.channel_id)
        staff_role_id = self.cog.config.get('ticket_staff_role_id')
        is_owner = interaction.user.id == ticket_owner
        is_staff = staff_role_id and any(role.id == int(staff_role_id) for role in interaction.user.roles)

        if not is_owner and not is_staff:
            await interaction.response.send_message('❌ Solo il proprietario del ticket o uno staffer può chiudere il ticket!', ephemeral=True)
            return

        # Send confirmation
        embed = discord.Embed(
            title='Conferma Chiusura',
            description='Sei sicuro di voler chiudere questo ticket? Verrà generato e inviato il transcript.',
            color=0xff0000
        )
        view = ConfirmCloseView(self.channel_id, self.cog)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class ConfirmCloseView(discord.ui.View):
    def __init__(self, channel_id, cog):
        super().__init__(timeout=300)  # 5 minutes timeout
        self.channel_id = channel_id
        self.cog = cog

    @discord.ui.button(label='Conferma', style=discord.ButtonStyle.danger, emoji='✅')
    async def confirm_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = self.cog.bot.get_channel(self.channel_id)
        if not channel:
            await interaction.response.send_message('❌ Canale non trovato!', ephemeral=True)
            return

        # Generate transcript
        messages = []
        async for message in channel.history(limit=None, oldest_first=True):
            messages.append(f'{message.created_at.strftime("%Y-%m-%d %H:%M:%S")} {message.author}: {message.content}')

        # Create txt
        filename = f'transcript-{channel.name}-{datetime.now().strftime("%Y%m%d%H%M%S")}.txt'
        with open(filename, 'w', encoding='utf-8') as f:
            f.write('\n'.join(messages))

        # Send to transcript channel
        transcript_channel_id = self.cog.config.get('ticket_transcript_channel_id')
        if transcript_channel_id:
            transcript_channel = self.cog.bot.get_channel(int(transcript_channel_id))
            if transcript_channel:
                await transcript_channel.send(file=discord.File(filename))
            else:
                print('Canale transcript non trovato!')

        # Delete file
        os.remove(filename)

        # Delete channel
        await channel.delete()

        # Remove from ticket owners
        if self.channel_id in self.cog.ticket_owners:
            del self.cog.ticket_owners[self.channel_id]

    @discord.ui.button(label='Annulla', style=discord.ButtonStyle.secondary, emoji='❌')
    async def cancel_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message('Chiusura annullata.', ephemeral=True)

async def setup(bot):
    await bot.add_cog(TicketCog(bot))
