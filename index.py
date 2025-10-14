import discord
from discord.ext import commands
from discord import app_commands
import json
import asyncio
import os
import re
from dotenv import load_dotenv

load_dotenv()

with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True
intents.members = True
intents.message_content = True
intents.reactions = True

def get_prefix(bot, message):
    prefixes = config.get('prefixes', ['v!'])
    return commands.when_mentioned_or(*prefixes)(bot, message)

bot = commands.Bot(command_prefix=get_prefix, intents=intents)

from bot_utils import OWNER_ID, owner_or_has_permissions, is_owner

from ticket import TicketCog, TicketView, CloseTicketView
from moderation import ModerationCog
from log import LogCog
from autorole import AutoRoleCog

active_sessions = {}

waiting_for_ruleset = False
waiting_for_welcome = False
waiting_for_boost = False

counter_channels = {}
counter_task = None
last_counter_update = {}

class GameSession:
    def __init__(self, guild, lobby_channel):
        self.guild = guild
        self.lobby_channel = lobby_channel
        self.text_channel = None
        self.red_voice = None
        self.green_voice = None
        self.tagged_users = []
        self.is_active = False

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send('❌ Sistema trasferito su comandi /. Usa `/help` per vedere una lista di comandi disponibili.')
    else:
        pass

@bot.event
async def on_ready():
    print(f'Bot connesso come {bot.user}')
    try:
        synced = await bot.tree.sync()
        print(f'Sincronizzati {len(synced)} comandi slash')
    except Exception as e:
        print(f'Errore nella sincronizzazione: {e}')
    
    active_counters = config.get('active_counters', {})
    for guild_id_str, channels in active_counters.items():
        guild_id = int(guild_id_str)
        guild = bot.get_guild(guild_id)
        if not guild:
            continue
        counter_channels[guild_id] = {}
        for channel_type, channel_id in channels.items():
            channel = guild.get_channel(int(channel_id))
            if channel:
                counter_channels[guild_id][channel_type] = channel
                print(f'Counter {channel_type} caricato per guild {guild.name}')
            else:
                print(f'Canale counter {channel_type} non trovato per guild {guild.name}, rimuovo dal config')
                del config['active_counters'][guild_id_str][channel_type]
                if not config['active_counters'][guild_id_str]:
                    del config['active_counters'][guild_id_str]
                with open('config.json', 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)

    global counter_task
    if counter_channels and (counter_task is None or counter_task.done()):
        counter_task = bot.loop.create_task(counter_update_loop())
        print('Loop di aggiornamento counter avviato')

    ticket_cog = bot.get_cog('TicketCog')
    if ticket_cog is None:
        ticket_cog = TicketCog(bot)
        try:
            await bot.add_cog(ticket_cog)
            print('Ticket cog aggiunto')
        except Exception as e:
            print(f'Ticket cog non aggiunto: {e}')
    else:
        print('Ticket cog già caricato')

    for channel_id, ticket_info in list(ticket_cog.ticket_owners.items()):
        if isinstance(ticket_info, dict) and 'close_message_id' in ticket_info:
            channel = bot.get_channel(channel_id)
            if channel:
                try:
                    message = await channel.fetch_message(ticket_info['close_message_id'])
                    view = CloseTicketView(channel_id, ticket_cog)
                    await message.edit(view=view)
                    print(f'View re-attached for ticket {channel.name}')
                except Exception as e:
                    print(f'Errore nel re-attach della view per ticket {channel_id}: {e}')
            else:
                del ticket_cog.ticket_owners[channel_id]
                ticket_cog.save_tickets()
                print(f'Ticket {channel_id} rimosso (canale eliminato)')

    moderation_cog = bot.get_cog('ModerationCog')
    if moderation_cog is None:
        try:
            await bot.add_cog(ModerationCog(bot))
            print('Moderation cog aggiunto')
        except Exception as e:
            print(f'Moderation cog non aggiunto: {e}')
    else:
        print('Moderation cog già caricato')

    log_cog = bot.get_cog('LogCog')
    if log_cog is None:
        try:
            await bot.add_cog(LogCog(bot))
            print('Log cog aggiunto')
        except Exception as e:
            print(f'Log cog non aggiunto: {e}')
    else:
        print('Log cog già caricato')

    autorole_cog = bot.get_cog('AutoRoleCog')
    if autorole_cog is None:
        try:
            await bot.add_cog(AutoRoleCog(bot))
            print('AutoRole cog aggiunto')
        except Exception as e:
            print(f'AutoRole cog non aggiunto: {e}')
    else:
        print('AutoRole cog già caricato')

    ticket_cog = bot.get_cog('TicketCog')
    if 'ticket_panel_message_id' in config and 'ticket_panel_channel_id' in config:
        channel = bot.get_channel(int(config['ticket_panel_channel_id']))
        if channel:
            try:
                message = await channel.fetch_message(int(config['ticket_panel_message_id']))
                panel = config.get('ticket_panel', {})
                embed = discord.Embed(
                    title=panel.get('title', 'Support Tickets'),
                    description=panel.get('description', 'Click a button to open a ticket'),
                    color=panel.get('color', 0x00ff00)
                )
                if panel.get('thumbnail'):
                    embed.set_thumbnail(url=panel['thumbnail'])
                if panel.get('footer'):
                    embed.set_footer(text=panel['footer'])

                all_buttons = config.get('ticket_buttons', [])
                view = TicketView(all_buttons, config, ticket_cog)
                await message.edit(embed=embed, view=view)
                print('Ticket panel view re-attached')
            except Exception as e:
                print(f'Errore nel ricaricare il pannello ticket: {e}')

@bot.event
async def on_member_remove(member):
    if member.guild.id in counter_channels:
        await update_counters(member.guild) 

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    lobby_id = int(config['lobby_voice_channel_id'])

    if after.channel and after.channel.id == lobby_id:
        await check_and_create_game(after.channel)
        return

    try:
        left_channel = None
        if before.channel and (not after.channel or (after.channel and before.channel.id != after.channel.id)):
            left_channel = before.channel

        if left_channel:
            for gid, session in list(active_sessions.items()):
                if session.red_voice and session.red_voice.id == left_channel.id or session.green_voice and session.green_voice.id == left_channel.id:
                    red_empty = True
                    green_empty = True
                    try:
                        if session.red_voice:
                            red_empty = len([m for m in session.red_voice.members if not m.bot]) == 0
                    except Exception:
                        red_empty = True
                    try:
                        if session.green_voice:
                            green_empty = len([m for m in session.green_voice.members if not m.bot]) == 0
                    except Exception:
                        green_empty = True

                    if red_empty and green_empty:
                        await cleanup_session(gid)
                    break
    except Exception as e:
        print(f'Errore nel controllo di pulizia voice: {e}')

@bot.event
async def on_member_join(member):
    if member.guild.id in counter_channels:
        await update_counters(member.guild)
    
    if 'welcome_channel_id' not in config or not config['welcome_channel_id']:
        return
    
    try:
        welcome_channel = member.guild.get_channel(int(config['welcome_channel_id']))
        if not welcome_channel:
            return
        
        welcome_data = config.get('welcome_message', {})
        
        description = welcome_data.get('description', '{mention}, benvenuto/a!')
        description = description.replace('{mention}', member.mention)
        description = description.replace('{username}', member.name)
        description = description.replace('{user}', member.name)

        embed = discord.Embed(
            title=welcome_data.get('title', 'Nuovo membro!'),
            description=description,
            color=welcome_data.get('color', 3447003)
        )

        thumbnail = welcome_data.get('thumbnail', '{avatar}')
        if '{avatar}' in thumbnail:
            embed.set_thumbnail(url=member.display_avatar.url)
        elif thumbnail:
            embed.set_thumbnail(url=thumbnail)

        footer = welcome_data.get('footer', '')
        if footer:
            embed.set_footer(text=footer)

        embed.set_author(name=member.name, icon_url=member.display_avatar.url)

        ping_message = welcome_data.get('ping_message', '')
        if ping_message:
            ping_message = ping_message.replace('{mention}', member.mention).replace('{username}', member.name).replace('{user}', member.name)
            await welcome_channel.send(content=ping_message, embed=embed)
        else:
            await welcome_channel.send(embed=embed)

        print(f'Messaggio di benvenuto inviato per {member.name}')
        
    except Exception as e:
        print(f'Errore nell\'invio del messaggio di benvenuto: {e}')

@bot.event
async def on_member_update(before, after):
    if before.premium_since is None and after.premium_since is not None:
        if 'boost_channel_id' not in config or not config['boost_channel_id']:
            return

        try:
            boost_channel = after.guild.get_channel(int(config['boost_channel_id']))
            if not boost_channel:
                return

            boost_data = config.get('boost_message', {})

            description = boost_data.get('description', '{mention} ha boostato il server!')
            description = description.replace('{mention}', after.mention)
            description = description.replace('{username}', after.name)
            description = description.replace('{user}', after.name)

            embed = discord.Embed(
                title=boost_data.get('title', 'Nuovo Boost!'),
                description=description,
                color=boost_data.get('color', 16776960)
            )

            thumbnail = boost_data.get('thumbnail', '{avatar}')
            if '{avatar}' in thumbnail:
                embed.set_thumbnail(url=after.display_avatar.url)
            elif thumbnail:
                embed.set_thumbnail(url=thumbnail)

            footer = boost_data.get('footer', '')
            if footer:
                embed.set_footer(text=footer)

            embed.set_author(name=after.name, icon_url=after.display_avatar.url)

            await boost_channel.send(embed=embed)

            print(f'Messaggio di boost inviato per {after.name}')

        except Exception as e:
            print(f'Errore nell\'invio del messaggio di boost: {e}')

@bot.event
async def on_message(message):
    global waiting_for_ruleset, waiting_for_welcome, waiting_for_boost

    if message.author.bot:
        return

    mention_pattern = f'<@!?{bot.user.id}>'
    if re.match(f'^{mention_pattern}$', message.content.strip()):
        await message.channel.send("❌ Sistema trasferito su comandi /. Usa `/help` per vedere una lista di comandi disponibili.")
        return

    if waiting_for_ruleset and message.author.id == 1123622103917285418:
        config['ruleset_message'] = message.content
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        waiting_for_ruleset = False
        await message.add_reaction('✅')
        await message.channel.send('✅ Ruleset salvato! Usa `/ruleset` per visualizzarlo.')
        return

    if waiting_for_welcome and message.author.id == 1123622103917285418:
        config['welcome_message']['description'] = message.content
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        waiting_for_welcome = False
        await message.add_reaction('✅')
        await message.channel.send('✅ Messaggio di benvenuto salvato!\n\n**Variabili disponibili:**\n`{mention}` - Tag dell\'utente\n`{username}` - Nome utente\n`{avatar}` - Avatar utente (per thumbnail)')
        return

    content = message.content.strip()
    prefixes = config.get('prefixes', ['v!'])
    for prefix in prefixes:
        if content.startswith(prefix):
            await message.channel.send('❌ Sistema trasferito su comandi /. Usa `/help` per vedere una lista di comandi disponibili.')
            return

    await bot.process_commands(message)

    if message.content.lower() in ['wlc', 'welcome', 'benvenuto']:
        emojis = config.get('welcome_emojis', [])
        for emoji in emojis:
            try:
                await message.add_reaction(emoji)
            except Exception as e:
                print(f'Errore nell\'aggiungere reazione {emoji}: {e}')

    guild = message.guild
    if not guild or guild.id not in active_sessions:
        return

    session = active_sessions[guild.id]
    if not session.is_active or message.channel != session.text_channel:
        return

    for mention in message.mentions:
        if mention not in session.tagged_users:
            session.tagged_users.append(mention)
            
            position = len(session.tagged_users) - 1
            is_red = position % 2 == 0
            
            if mention.voice and mention.voice.channel:
                try:
                    target_channel = session.red_voice if is_red else session.green_voice
                    await mention.move_to(target_channel)
                    team_name = "ROSSO" if is_red else "VERDE"
                    print(f'Spostato {mention.name} nel team {team_name}')
                    
                    await session.text_channel.send(f'{mention.mention} → {"Team Rosso" if is_red else "Team Verde"}')
                except Exception as e:
                    print(f'Errore nello spostamento di {mention.name}: {e}')

async def check_and_create_game(lobby_channel):
    guild = lobby_channel.guild
    
    if guild.id in active_sessions and active_sessions[guild.id].is_active:
        return
    
    members = [m for m in lobby_channel.members if not m.bot]
    
    if len(members) >= 1:
        print(f'Giocatore rilevato! Creazione partita...')
        await create_game_session(guild, lobby_channel)

async def create_game_session(guild, lobby_channel):
    try:
        session = GameSession(guild, lobby_channel)
        session.is_active = True

        category = None
        if 'category_id' in config and config['category_id']:
            category = guild.get_channel(int(config['category_id']))

        admin_user_id = 1123622103917285418
        admin_user = guild.get_member(admin_user_id)
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=False,
                connect=False
            ),
        }
        
        if admin_user:
            overwrites[admin_user] = discord.PermissionOverwrite(
                view_channel=True,
                manage_channels=True,
                manage_permissions=True,
                manage_webhooks=True,
                create_instant_invite=True,
                send_messages=True,
                send_messages_in_threads=True,
                create_public_threads=True,
                create_private_threads=True,
                embed_links=True,
                attach_files=True,
                add_reactions=True,
                use_external_emojis=True,
                use_external_stickers=True,
                mention_everyone=True,
                manage_messages=True,
                manage_threads=True,
                read_message_history=True,
                send_tts_messages=True,
                use_application_commands=True,
                send_polls=True,
                connect=True,
                speak=True,
                stream=True,
                use_embedded_activities=True,
                use_soundboard=True,
                use_external_sounds=True,
                use_voice_activation=True,
                priority_speaker=True,
                mute_members=True,
                deafen_members=True,
                move_members=True,
                request_to_speak=True
            )

        session.text_channel = await guild.create_text_channel(
            name='cw-interna',
            category=category,
            topic='CW - Team Rosso vs Verde',
            overwrites=overwrites
        )

        session.red_voice = await guild.create_voice_channel(
            name='Team Rosso',
            category=category,
            user_limit=4,
            overwrites=overwrites
        )

        session.green_voice = await guild.create_voice_channel(
            name='Team Verde',
            category=category,
            user_limit=4,
            overwrites=overwrites
        )

        embed = discord.Embed(
            title='**CW Interna** - Istruzioni',
            description='**CW Interne Valiance**\n\nTagga fino a 8 giocatori per assegnare i team automaticamente:\n> Il primo taggato verrà inserito nel team ROSSO\n> Il secondo nel team VERDE\n> E cosi via...',
            color=discord.Color.blue()
        )

        embed.set_footer(text='Usa `!cwend` per terminare la partita ed eliminare tutti i canali.')

        await session.text_channel.send(embed=embed)

        active_sessions[guild.id] = session

        print(f'Partita creata con successo nel server {guild.name}')

    except Exception as e:
        print(f'Errore nella creazione della partita: {e}')
        await cleanup_session(guild.id)

async def assign_teams(session):
    try:
        red_team = session.tagged_users[:4]
        green_team = session.tagged_users[4:8]

        embed = discord.Embed(
            title='🎮 TEAM ASSEGNATI',
            description='I giocatori sono stati divisi nei team!',
            color=discord.Color.green()
        )

        red_mentions = ' '.join([m.mention for m in red_team])
        green_mentions = ' '.join([m.mention for m in green_team])

        embed.add_field(
            name='Team Rosso',
            value=red_mentions,
            inline=False
        )

        embed.add_field(
            name='Team Verde',
            value=green_mentions,
            inline=False
        )

        embed.set_footer(text='Buon divertimento! Usa `!cwend` per terminare')

        await session.text_channel.send(embed=embed)

        await asyncio.sleep(1)

        for member in red_team:
            try:
                if member.voice and member.voice.channel:
                    await member.move_to(session.red_voice)
                    print(f'Spostato {member.name} nel team ROSSO')
            except Exception as e:
                print(f'Errore nello spostamento di {member.name} nel ROSSO: {e}')

        await asyncio.sleep(0.5)

        for member in green_team:
            try:
                if member.voice and member.voice.channel:
                    await member.move_to(session.green_voice)
                    print(f'Spostato {member.name} nel team VERDE')
            except Exception as e:
                print(f'Errore nello spostamento di {member.name} nel VERDE: {e}')

        print(f'Team assegnati con successo nel server {session.guild.name}')

    except Exception as e:
        print(f'Errore nell\'assegnazione dei team: {e}')

async def cleanup_session(guild_id):
    if guild_id not in active_sessions:
        return
    
    session = active_sessions[guild_id]
    
    try:
        if session.text_channel:
            try:
                await session.text_channel.delete()
                print(f'Canale di testo eliminato')
            except Exception as e:
                print(f'Errore nell\'eliminazione del canale di testo: {e}')
        
        if session.red_voice:
            try:
                await session.red_voice.delete()
                print(f'Canale vocale ROSSO eliminato')
            except Exception as e:
                print(f'Errore nell\'eliminazione del canale ROSSO: {e}')
        
        if session.green_voice:
            try:
                await session.green_voice.delete()
                print(f'Canale vocale VERDE eliminato')
            except Exception as e:
                print(f'Errore nell\'eliminazione del canale VERDE: {e}')
        
        del active_sessions[guild_id]
        print(f'Sessione pulita con successo')
        
    except Exception as e:
        print(f'Errore durante la pulizia: {e}')



@bot.tree.command(name='cwend', description='Termina la partita custom e elimina i canali (solo admin)')
@owner_or_has_permissions(administrator=True)
async def slash_cwend(interaction: discord.Interaction):
    guild_id = interaction.guild.id

    if guild_id not in active_sessions:
        await interaction.response.send_message('❌ Non ci sono partite attive!', ephemeral=True)
        return

    await interaction.response.send_message('🧹 Terminazione partita in corso...', ephemeral=True)
    await cleanup_session(guild_id)
    await interaction.followup.send('✅ Partita terminata e canali eliminati!', ephemeral=True)

@bot.tree.command(name='setruleset', description='Imposta il ruleset (solo per admin)')
@owner_or_has_permissions(administrator=True)
async def slash_setruleset(interaction: discord.Interaction):
    global waiting_for_ruleset
    waiting_for_ruleset = True
    await interaction.response.send_message('📝 Invia il prossimo messaggio che vuoi salvare come ruleset.', ephemeral=False)

@bot.tree.command(name='ruleset', description='Mostra il ruleset salvato')
async def slash_ruleset(interaction: discord.Interaction):
    if 'ruleset_message' not in config or not config['ruleset_message']:
        await interaction.response.send_message('❌ Nessun ruleset configurato! Usa `!setruleset` per impostarne uno.', ephemeral=False)
        return

    await interaction.response.send_message(config['ruleset_message'], ephemeral=False)

async def update_counters(guild):
    if guild.id not in counter_channels:
        return

    now = asyncio.get_event_loop().time()
    if guild.id in last_counter_update and now - last_counter_update[guild.id] < 30:
        return
    last_counter_update[guild.id] = now

    try:
        for channel_type in list(counter_channels[guild.id].keys()):
            channel = counter_channels[guild.id][channel_type]
            if channel is None or not hasattr(channel, 'id') or channel.id is None:
                del counter_channels[guild.id][channel_type]
                if str(guild.id) in config.get('active_counters', {}) and channel_type in config['active_counters'][str(guild.id)]:
                    del config['active_counters'][str(guild.id)][channel_type]
                    if not config['active_counters'][str(guild.id)]:
                        del config['active_counters'][str(guild.id)]
                    with open('config.json', 'w', encoding='utf-8') as f:
                        json.dump(config, f, indent=2, ensure_ascii=False)
                print(f'Counter {channel_type} rimosso per guild {guild.name} (canale eliminato)')

        counters_config = config.get('counters', {})

        total_members = len([m for m in guild.members if not m.bot])

        role_id = int(counters_config.get('member_role_id', '0'))
        role = guild.get_role(role_id)
        role_members = 0
        if role:
            role_members = len([m for m in role.members if not m.bot])

        if 'total_members' in counter_channels[guild.id]:
            channel = counter_channels[guild.id]['total_members']
            name_template = counters_config.get('total_members_name', '👥 Membri: {count}')
            new_name = name_template.replace('{count}', str(total_members))
            if channel.name != new_name:
                await channel.edit(name=new_name)
                print(f'Aggiornato counter membri totali: {new_name}')

        if 'role_members' in counter_channels[guild.id]:
            channel = counter_channels[guild.id]['role_members']
            name_template = counters_config.get('role_members_name', '⭐ Membri Clan: {count}')
            new_name = name_template.replace('{count}', str(role_members))
            if channel.name != new_name:
                await channel.edit(name=new_name)
                print(f'Aggiornato counter membri ruolo: {new_name}')

    except Exception as e:
        print(f'Errore nell\'aggiornamento dei counter: {e}')

async def counter_update_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            for guild_id in list(counter_channels.keys()):
                guild = bot.get_guild(guild_id)
                if guild:
                    await update_counters(guild)
            await asyncio.sleep(30)
        except Exception as e:
            print(f'Errore nel loop di aggiornamento counter: {e}')
            await asyncio.sleep(15)

@bot.tree.command(name='startct', description='Avvia i canali counter (solo admin)')
@owner_or_has_permissions(administrator=True)
async def slash_startct(interaction: discord.Interaction):
    global counter_task

    guild = interaction.guild

    if guild.id in counter_channels:
        await interaction.response.send_message('❌ I counter sono già attivi! Usa `/stopct` per fermarli prima.', ephemeral=True)
        return

    try:
        await interaction.response.send_message('🔄 Creazione canali counter in corso...', ephemeral=False)

        counters_config = config.get('counters', {})

        total_members = len([m for m in guild.members if not m.bot])
        role_id = int(counters_config.get('member_role_id', '0'))
        role = guild.get_role(role_id)
        role_members = 0
        if role:
            role_members = len([m for m in role.members if not m.bot])

        total_name = counters_config.get('total_members_name', '👥 Membri: {count}').replace('{count}', str(total_members))
        role_name = counters_config.get('role_members_name', '⭐ Membri Clan: {count}').replace('{count}', str(role_members))

        total_channel = await guild.create_voice_channel(
            name=total_name,
            position=0,
            user_limit=0,
            overwrites={
                guild.default_role: discord.PermissionOverwrite(connect=False)
            }
        )

        role_channel = await guild.create_voice_channel(
            name=role_name,
            position=1,
            user_limit=0,
            overwrites={
                guild.default_role: discord.PermissionOverwrite(connect=False)
            }
        )

        counter_channels[guild.id] = {
            'total_members': total_channel,
            'role_members': role_channel
        }

        if 'active_counters' not in config:
            config['active_counters'] = {}
        config['active_counters'][str(guild.id)] = {
            'total_members': total_channel.id,
            'role_members': role_channel.id
        }
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        if counter_task is None or counter_task.done():
            counter_task = bot.loop.create_task(counter_update_loop())

        await interaction.followup.send(f'✅ Canali counter creati con successo!\n📊 Membri totali: {total_members}\n⭐ Membri clan: {role_members}', ephemeral=False)
        print(f'Counter attivati nel server {guild.name}')

    except Exception as e:
        await interaction.followup.send(f'❌ Errore nella creazione dei counter: {e}', ephemeral=True)
        print(f'Errore nella creazione dei counter: {e}')

@bot.tree.command(name='stopct', description='Ferma e elimina i canali counter (solo admin)')
@owner_or_has_permissions(administrator=True)
async def slash_stopct(interaction: discord.Interaction):
    global counter_task

    guild = interaction.guild

    if guild.id not in counter_channels:
        await interaction.response.send_message('❌ I counter non sono attivi!', ephemeral=True)
        return

    try:
        await interaction.response.send_message('🔄 Fermando e eliminando canali counter...', ephemeral=False)

        # Delete channels
        for channel_type, channel in counter_channels[guild.id].items():
            try:
                await channel.delete()
                print(f'Canale counter {channel_type} eliminato per guild {guild.name}')
            except Exception as e:
                print(f'Errore nell\'eliminazione del canale {channel_type}: {e}')

        # Remove from memory
        del counter_channels[guild.id]

        # Remove from config
        if 'active_counters' in config and str(guild.id) in config['active_counters']:
            del config['active_counters'][str(guild.id)]
            with open('config.json', 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)

        # Stop the task if no more counters
        if not counter_channels and counter_task and not counter_task.done():
            counter_task.cancel()
            counter_task = None
            print('Loop di aggiornamento counter fermato')

        await interaction.followup.send('✅ Counter fermati e canali eliminati con successo!', ephemeral=False)
        print(f'Counter fermati nel server {guild.name}')

    except Exception as e:
        await interaction.followup.send(f'❌ Errore nel fermare i counter: {e}', ephemeral=True)
        print(f'Errore nel fermare i counter: {e}')

class DeleteConfirmView(discord.ui.View):
    def __init__(self, ctx):
        super().__init__(timeout=30)
        self.ctx = ctx

    @discord.ui.button(label='Conferma', style=discord.ButtonStyle.danger, emoji='🗑️')
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message('❌ Solo chi ha eseguito il comando può confermare!', ephemeral=True)
            return

        try:
            print(f'{self.ctx.author.name} ha eliminato il canale {self.ctx.channel.name}')
            await self.ctx.channel.delete()
        except Exception as e:
            await interaction.response.send_message(f'❌ Errore nell\'eliminazione del canale: {e}', ephemeral=True)

    @discord.ui.button(label='Annulla', style=discord.ButtonStyle.secondary, emoji='❌')
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message('❌ Solo chi ha eseguito il comando può annullare!', ephemeral=True)
            return

        await interaction.response.edit_message(content='❌ Eliminazione annullata.', view=None)


class SlashDeleteConfirmView(discord.ui.View):
    def __init__(self, author_id, channel):
        super().__init__(timeout=30)
        self.author_id = author_id
        self.channel = channel

    @discord.ui.button(label='Conferma', style=discord.ButtonStyle.danger, emoji='🗑️')
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message('❌ Solo chi ha eseguito il comando può confermare!', ephemeral=True)
            return
        try:
            await self.channel.delete()
        except Exception as e:
            await interaction.response.send_message(f'❌ Errore nell\'eliminazione del canale: {e}', ephemeral=True)

    @discord.ui.button(label='Annulla', style=discord.ButtonStyle.secondary, emoji='❌')
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message('❌ Solo chi ha eseguito il comando può annullare!', ephemeral=True)
            return
        await interaction.response.edit_message(content='❌ Eliminazione annullata.', view=None)

@bot.tree.command(name='delete', description='Elimina il canale corrente (con conferma)')
async def slash_delete(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator and interaction.user.id != 1123622103917285418:
        await interaction.response.send_message('❌ Non hai i permessi per usare questo comando!', ephemeral=True)
        return
    embed = discord.Embed(
        title='🗑️ Conferma Eliminazione',
        description=f'Sei sicuro di voler eliminare il canale **{interaction.channel.name}**?\n\nQuesta azione è irreversibile.',
        color=0xff0000
    )
    embed.set_footer(text='Scade in 30 secondi')
    view = SlashDeleteConfirmView(interaction.user.id, interaction.channel)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@bot.tree.command(name='purge', description='Elimina un numero di messaggi (1-250)')
@app_commands.describe(limit='Numero di messaggi da eliminare (1-250)')
async def slash_purge(interaction: discord.Interaction, limit: int):
    try:
        if not interaction.user.guild_permissions.manage_messages and interaction.user.id != OWNER_ID:
            await interaction.response.send_message('❌ Non hai abbastanza permessi!', ephemeral=True)
            return

        if limit < 1 or limit > 250:
            await interaction.response.send_message('❌ puoi scegliere numeri tra 1 e 250.', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=limit, before=interaction.created_at)
        await interaction.followup.send(f'✅ Ho eliminato {len(deleted)} messaggi.', ephemeral=True)
    except discord.Forbidden:
        try:
            await interaction.followup.send('❌ Non ho i permessi per eliminare messaggi in questo canale!', ephemeral=True)
        except Exception:
            pass
    except Exception as e:
        try:
            await interaction.followup.send(f'❌ Errore durante la purge: {e}', ephemeral=True)
        except Exception:
            pass

@bot.tree.command(name='ping', description='Mostra la latenza del bot')
async def slash_ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"🏓 Pong! Latenza: {round(bot.latency * 1000)}ms", ephemeral=True)

@bot.tree.command(name='help', description='Mostra una lista di tutti i comandi slash disponibili')
async def slash_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title='📋 Comandi Disponibili',
        description='Ecco una lista di tutti i comandi slash disponibili su questo bot:',
        color=0x00ff00
    )

    embed.add_field(
        name='🛡️ Moderazione',
        value='`/ban` - Banna un membro\n`/kick` - Kicka un membro\n`/mute` - Muta un membro\n`/unmute` - Smuta un membro\n`/warn` - Aggiungi un warn\n`/unwarn` - Rimuovi un warn\n`/listwarns` - Mostra i warn\n`/clearwarns` - Rimuovi tutti i warn\n`/listban` - Mostra i ban\n`/checkban` - Controlla se un utente è bannato\n`/checkmute` - Controlla se un utente è mutato',
        inline=False
    )

    embed.add_field(
        name='🎫 Ticket',
        value='`/ticketpanel` - Crea pannello ticket\n`/close` - Chiudi ticket\n`/transcript` - Genera transcript\n`/add` - Aggiungi utente al ticket\n`/remove` - Rimuovi utente dal ticket\n`/rename` - Rinomina ticket\n`/blacklist` - Blacklist utente',
        inline=False
    )

    embed.add_field(
        name='🔧 Utilità',
        value='`/ping` - Mostra latenza bot\n`/purge` - Elimina messaggi\n`/delete` - Elimina canale\n`/cwend` - Termina partita CW\n`/ruleset` - Mostra ruleset\n`/setruleset` - Imposta ruleset\n`/startct` - Avvia counter\n`/stopct` - Ferma counter',
        inline=False
    )

    embed.add_field(
        name='🎭 AutoRole',
        value='`/createreact` - Crea messaggio reazione ruoli',
        inline=False
    )
    

    embed.set_footer(text='Valiance Bot | Usa / per accedere ai comandi')

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    try:
        if isinstance(error, app_commands.errors.CheckFailure):
            try:
                if interaction.response.is_done():
                    await interaction.followup.send('❌ Non hai abbastanza permessi!', ephemeral=True)
                else:
                    await interaction.response.send_message('❌ Non hai abbastanza permessi!', ephemeral=True)
            except Exception:
                pass
            return

        if isinstance(error, discord.errors.NotFound):
            print(f'Ignored NotFound in app command: {error}')
            return

        try:
            if interaction.response.is_done():
                await interaction.followup.send(f'❌ Errore nel comando: {error}', ephemeral=True)
            else:
                await interaction.response.send_message(f'❌ Errore nel comando: {error}', ephemeral=True)
        except Exception:
            pass
    except Exception:
        pass

if __name__ == '__main__':
    try:
        import importlib
        import asyncio

        async def setup_modules():
            modules_to_setup = ['ticket', 'moderation', 'autorole', 'log']
            for modname in modules_to_setup:
                try:
                    mod = importlib.import_module(modname)
                    setup = getattr(mod, 'setup', None)
                    if setup:
                        if asyncio.iscoroutinefunction(setup):
                            await setup(bot)
                        else:
                            setup(bot)
                    print(f'Extension {modname} setup executed')
                except Exception as e:
                    print(f'Non sono riuscito a caricare {modname}: {e}')

        asyncio.run(setup_modules())
        bot.run(os.getenv('TOKEN'))
    except Exception as e:
        print(f'Errore nell\'avvio del bot: {e}')
