import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import asyncio
import os
import re
from dotenv import load_dotenv

from console_logger import logger
from embed_creator import EmbedCreatorView
from cogs.ticket.ticket import TicketCog, TicketView, CloseTicketView

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


@tasks.loop(minutes=5)
async def status_loop():
    status = config.get('bot_status', 'dnd')
    activity_type = config.get('bot_activity_type', 'watching')
    activity_name = config.get('bot_activity_name', '{membri} membri')

    if status == 'online':
        status_enum = discord.Status.online
    elif status == 'idle':
        status_enum = discord.Status.idle
    elif status == 'dnd':
        status_enum = discord.Status.dnd
    elif status == 'invisible':
        status_enum = discord.Status.invisible
    else:
        status_enum = discord.Status.dnd

    bot_activity_guild_id = config.get('bot_activity_guild_id')
    if bot_activity_guild_id:
        try:
            specific_guild = bot.get_guild(int(bot_activity_guild_id))
            if specific_guild:
                membri = specific_guild.member_count
            else:
                membri = sum(g.member_count for g in bot.guilds)
        except ValueError:
            membri = sum(g.member_count for g in bot.guilds)
    else:
        membri = sum(g.member_count for g in bot.guilds)
    activity_name = activity_name.replace('{membri}', str(membri))

    if activity_type == 'playing':
        activity = discord.Game(name=activity_name)
    elif activity_type == 'streaming':
        activity = discord.Streaming(name=activity_name, url=config.get('bot_activity_url', ''))
    elif activity_type == 'listening':
        activity = discord.Activity(type=discord.ActivityType.listening, name=activity_name)
    elif activity_type == 'watching':
        activity = discord.Activity(type=discord.ActivityType.watching, name=activity_name)
    elif activity_type == 'competing':
        activity = discord.Activity(type=discord.ActivityType.competing, name=activity_name)
    else:
        activity = discord.Activity(type=discord.ActivityType.watching, name=activity_name)

    await bot.change_presence(status=status_enum, activity=activity)


@bot.event
async def on_ready():
    bot.start_time = discord.utils.utcnow()

    logger.info(f'Bot connesso come {bot.user}')
    try:
        synced = await bot.tree.sync()
        logger.info(f'Sincronizzati {len(synced)} comandi slash')
    except Exception as e:
        logger.error(f'Errore nella sincronizzazione: {e}')

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
                logger.info(f'Counter {channel_type} caricato per guild {guild.name}')
            else:
                logger.warning(f'Canale counter {channel_type} non trovato per guild {guild.name}, rimuovo dal config')
                del config['active_counters'][guild_id_str][channel_type]
                if not config['active_counters'][guild_id_str]:
                    del config['active_counters'][guild_id_str]
                with open('config.json', 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)
    status_loop.start()

    global counter_task
    if counter_channels and (counter_task is None or counter_task.done()):
        counter_task = bot.loop.create_task(counter_update_loop())
        logger.info('Loop di aggiornamento counter avviato')

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
        logger.error(f'Errore nel controllo di pulizia voice: {e}')


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
            ping_message = ping_message.replace('{mention}', member.mention).replace('{username}', member.name).replace(
                '{user}', member.name)
            await welcome_channel.send(content=ping_message, embed=embed)
        else:
            await welcome_channel.send(embed=embed)

        logger.info(f'Messaggio di benvenuto inviato per {member.name}')

    except Exception as e:
        logger.error(f'Errore nell\'invio del messaggio di benvenuto: {e}')


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

            logger.info(f'Messaggio di boost inviato per {after.name}')

        except Exception as e:
            logger.error(f'Errore nell\'invio del messaggio di boost: {e}')


@bot.event
async def on_message(message):
    global waiting_for_ruleset, waiting_for_welcome, waiting_for_boost

    if message.author.bot:
        return

    mention_pattern = f'<@!?{bot.user.id}>'
    if re.match(f'^{mention_pattern}$', message.content.strip()):
        await message.channel.send(
            "❌ Sistema trasferito su comandi /. Usa `/help` per vedere una lista di comandi disponibili.")
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
        await message.channel.send(
            '✅ Messaggio di benvenuto salvato!\n\n**Variabili disponibili:**\n`{mention}` - Tag dell\'utente\n`{username}` - Nome utente\n`{avatar}` - Avatar utente (per thumbnail)')
        return

    content = message.content.strip()
    prefixes = config.get('prefixes', ['v!'])
    for prefix in prefixes:
        if content.startswith(prefix):
            if content.startswith(prefix + "!") or content.startswith(prefix + "?"):
                return
            await message.channel.send(
                '❌ Sistema trasferito su comandi /. Usa `/help` per vedere una lista di comandi disponibili.')
            return

    await bot.process_commands(message)

    if message.content.lower() in ['wlc', 'welcome', 'benvenuto']:
        emojis = config.get('welcome_emojis', [])
        for emoji in emojis:
            try:
                await message.add_reaction(emoji)
            except Exception as e:
                logger.error(f'Errore nell\'aggiungere reazione {emoji}: {e}')

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
            is_red = position < 4

            if mention.voice and mention.voice.channel:
                try:
                    target_channel = session.red_voice if is_red else session.green_voice
                    await mention.move_to(target_channel)
                    team_name = "ROSSO" if is_red else "VERDE"
                    logger.info(f'Spostato {mention.name} nel team {team_name}')

                    await session.text_channel.send(f'{mention.mention} → {"Team Rosso" if is_red else "Team Verde"}')
                except Exception as e:
                    logger.error(f'Errore nello spostamento di {mention.name}: {e}')


async def check_and_create_game(lobby_channel):
    guild = lobby_channel.guild

    if guild.id in active_sessions and active_sessions[guild.id].is_active:
        return

    members = [m for m in lobby_channel.members if not m.bot]

    if len(members) >= 1:
        logger.info(f'Giocatore rilevato! Creazione partita...')
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
            description='**CW Interne Valiance**\n\nTagga fino a 8 giocatori per assegnare i team automaticamente:\n> I primi 4 taggati verranno inseriti nel team ROSSO\n> Gli altri 4 nel team VERDE',
            color=discord.Color.blue()
        )

        embed.set_footer(text='Usa `!cwend` per terminare la partita ed eliminare tutti i canali.')

        await session.text_channel.send(embed=embed)

        active_sessions[guild.id] = session

        logger.info(f'Partita creata con successo nel server {guild.name}')

    except Exception as e:
        logger.error(f'Errore nella creazione della partita: {e}')
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
                    logger.info(f'Spostato {member.name} nel team ROSSO')
            except Exception as e:
                logger.error(f'Errore nello spostamento di {member.name} nel ROSSO: {e}')

        await asyncio.sleep(0.5)

        for member in green_team:
            try:
                if member.voice and member.voice.channel:
                    await member.move_to(session.green_voice)
                    logger.info(f'Spostato {member.name} nel team VERDE')
            except Exception as e:
                logger.error(f'Errore nello spostamento di {member.name} nel VERDE: {e}')

        logger.info(f'Team assegnati con successo nel server {session.guild.name}')

    except Exception as e:
        logger.error(f'Errore nell\'assegnazione dei team: {e}')


async def cleanup_session(guild_id):
    if guild_id not in active_sessions:
        return

    session = active_sessions[guild_id]

    try:
        if session.text_channel:
            try:
                await session.text_channel.delete()
                logger.info(f'Canale di testo eliminato')
            except Exception as e:
                logger.error(f'Errore nell\'eliminazione del canale di testo: {e}')

        if session.red_voice:
            try:
                await session.red_voice.delete()
                logger.info(f'Canale vocale ROSSO eliminato')
            except Exception as e:
                logger.error(f'Errore nell\'eliminazione del canale ROSSO: {e}')

        if session.green_voice:
            try:
                await session.green_voice.delete()
                logger.info(f'Canale vocale VERDE eliminato')
            except Exception as e:
                logger.error(f'Errore nell\'eliminazione del canale VERDE: {e}')

        del active_sessions[guild_id]
        logger.info(f'Sessione pulita con successo')

    except Exception as e:
        logger.error(f'Errore durante la pulizia: {e}')


@bot.tree.command(name='cwend', description='Termina la partita custom e elimina i canali (solo admin)')
@owner_or_has_permissions(administrator=True)
async def slash_cwend(interaction: discord.Interaction):
    guild_id = interaction.guild.id

    if guild_id not in active_sessions:
        await interaction.response.send_message('❌ Non ci sono partite attive!', ephemeral=True)
        logger.warning(
            f'Comando /cwend usato senza partite attive da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) in {interaction.guild.name}')
        return

    await interaction.response.send_message('🧹 Terminazione partita in corso...', ephemeral=True)
    await cleanup_session(guild_id)
    await interaction.followup.send('✅ Partita terminata e canali eliminati!', ephemeral=True)
    logger.info(
        f'Partita terminata da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) in {interaction.guild.name}')


@bot.tree.command(name='setruleset', description='Imposta il ruleset (solo per admin)')
@owner_or_has_permissions(administrator=True)
async def slash_setruleset(interaction: discord.Interaction):
    global waiting_for_ruleset
    waiting_for_ruleset = True
    await interaction.response.send_message('📝 Invia il prossimo messaggio che vuoi salvare come ruleset.',
                                            ephemeral=False)
    logger.info(
        f'Comando /setruleset usato da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) in {interaction.guild.name}')


@bot.tree.command(name='ruleset', description='Mostra il ruleset salvato')
async def slash_ruleset(interaction: discord.Interaction):
    if 'ruleset_message' not in config or not config['ruleset_message']:
        await interaction.response.send_message('❌ Nessun ruleset configurato! Usa `!setruleset` per impostarne uno.',
                                                ephemeral=False)
        logger.warning(
            f'Comando /ruleset usato senza ruleset configurato da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) in {interaction.guild.name}')
        return

    await interaction.response.send_message(config['ruleset_message'], ephemeral=False)
    logger.info(
        f'Ruleset mostrato a {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) in {interaction.guild.name}')


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
                if str(guild.id) in config.get('active_counters', {}) and channel_type in config['active_counters'][
                    str(guild.id)]:
                    del config['active_counters'][str(guild.id)][channel_type]
                    if not config['active_counters'][str(guild.id)]:
                        del config['active_counters'][str(guild.id)]
                    with open('config.json', 'w', encoding='utf-8') as f:
                        json.dump(config, f, indent=2, ensure_ascii=False)
                logger.info(f'Counter {channel_type} rimosso per guild {guild.name} (canale eliminato)')

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
                logger.info(f'Aggiornato counter membri totali: {new_name}')

        if 'role_members' in counter_channels[guild.id]:
            channel = counter_channels[guild.id]['role_members']
            name_template = counters_config.get('role_members_name', '⭐ Membri Clan: {count}')
            new_name = name_template.replace('{count}', str(role_members))
            if channel.name != new_name:
                await channel.edit(name=new_name)
                logger.info(f'Aggiornato counter membri ruolo: {new_name}')

    except Exception as e:
        logger.error(f'Errore nell\'aggiornamento dei counter: {e}')


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
            logger.error(f'Errore nel loop di aggiornamento counter: {e}')
            await asyncio.sleep(15)


@bot.tree.command(name='startct', description='Avvia i canali counter (solo admin)')
@owner_or_has_permissions(administrator=True)
async def slash_startct(interaction: discord.Interaction):
    global counter_task

    guild = interaction.guild

    if guild.id in counter_channels:
        await interaction.response.send_message('❌ I counter sono già attivi! Usa `/stopct` per fermarli prima.',
                                                ephemeral=True)
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

        total_name = counters_config.get('total_members_name', '👥 Membri: {count}').replace('{count}',
                                                                                            str(total_members))
        role_name = counters_config.get('role_members_name', '⭐ Membri Clan: {count}').replace('{count}',
                                                                                               str(role_members))

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

        await interaction.followup.send(
            f'✅ Canali counter creati con successo!\n📊 Membri totali: {total_members}\n⭐ Membri clan: {role_members}',
            ephemeral=False)
        logger.info(f'Counter attivati nel server {guild.name}')

    except Exception as e:
        await interaction.followup.send(f'❌ Errore nella creazione dei counter: {e}', ephemeral=True)
        logger.error(f'Errore nella creazione dei counter: {e}')


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

        for channel_type, channel in counter_channels[guild.id].items():
            try:
                await channel.delete()
                logger.info(f'Canale counter {channel_type} eliminato per guild {guild.name}')
            except Exception as e:
                logger.error(f'Errore nell\'eliminazione del canale {channel_type}: {e}')

        del counter_channels[guild.id]

        if 'active_counters' in config and str(guild.id) in config['active_counters']:
            del config['active_counters'][str(guild.id)]
            with open('config.json', 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)

        if not counter_channels and counter_task and not counter_task.done():
            counter_task.cancel()
            counter_task = None
            logger.info('Loop di aggiornamento counter fermato')

        await interaction.followup.send('✅ Counter fermati e canali eliminati con successo!', ephemeral=False)
        logger.info(f'Counter fermati nel server {guild.name}')

    except Exception as e:
        await interaction.followup.send(f'❌ Errore nel fermare i counter: {e}', ephemeral=True)
        logger.error(f'Errore nel fermare i counter: {e}')


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
            logger.info(f'{self.ctx.author.name} ha eliminato il canale {self.ctx.channel.name}')
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
        logger.warning(
            f'Comando /delete usato senza permessi da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) in {interaction.guild.name}')
        return
    embed = discord.Embed(
        title='🗑️ Conferma Eliminazione',
        description=f'Sei sicuro di voler eliminare il canale **{interaction.channel.name}**?\n\nQuesta azione è irreversibile.',
        color=0xff0000
    )
    embed.set_footer(text='Scade in 30 secondi')
    view = SlashDeleteConfirmView(interaction.user.id, interaction.channel)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    logger.info(
        f'Conferma eliminazione canale richiesta da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) per canale {interaction.channel.name} in {interaction.guild.name}')


@bot.tree.command(name='purge', description='Elimina un numero di messaggi (1-250)')
@app_commands.describe(limit='Numero di messaggi da eliminare (1-250)')
async def slash_purge(interaction: discord.Interaction, limit: int):
    try:
        if not interaction.user.guild_permissions.manage_messages and interaction.user.id != OWNER_ID:
            await interaction.response.send_message('❌ Non hai abbastanza permessi!', ephemeral=True)
            logger.warning(
                f'Comando /purge usato senza permessi da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) in {interaction.guild.name}')
            return

        if limit < 1 or limit > 250:
            await interaction.response.send_message('❌ puoi scegliere numeri tra 1 e 250.', ephemeral=True)
            logger.warning(
                f'Comando /purge con limite invalido ({limit}) da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) in {interaction.guild.name}')
            return

        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=limit, before=interaction.created_at)
        await interaction.followup.send(f'✅ Ho eliminato {len(deleted)} messaggi.', ephemeral=True)
        logger.info(
            f'Purge eseguita: {len(deleted)} messaggi eliminati da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) in canale {interaction.channel.name} ({interaction.guild.name})')
    except discord.Forbidden:
        try:
            await interaction.followup.send('❌ Non ho i permessi per eliminare messaggi in questo canale!',
                                            ephemeral=True)
            logger.error(
                f'Errore permessi purge da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) in {interaction.guild.name}')
        except Exception:
            pass
    except Exception as e:
        try:
            await interaction.followup.send(f'❌ Errore durante la purge: {e}', ephemeral=True)
            logger.error(
                f'Errore purge da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) in {interaction.guild.name}: {e}')
        except Exception:
            pass


@bot.tree.command(name='ping', description='Mostra la latenza del bot')
async def slash_ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"🏓 Pong! Latenza: {round(bot.latency * 1000)}ms", ephemeral=True)
    logger.info(
        f'Comando /ping usato da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) in {interaction.guild.name} - Latenza: {round(bot.latency * 1000)}ms')


@bot.tree.command(name='uptime', description='Mostra da quanto tempo il bot è online')
async def slash_uptime(interaction: discord.Interaction):
    from datetime import datetime, timezone
    uptime = datetime.now(timezone.utc) - bot.start_time if hasattr(bot, 'start_time') else None
    if uptime:
        days = uptime.days
        hours, remainder = divmod(uptime.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{days}d {hours}h {minutes}m {seconds}s"
    else:
        uptime_str = "N/A"
    await interaction.response.send_message(f"**⏱️ Uptime**: {uptime_str}", ephemeral=True)
    logger.info(
        f'Comando /uptime usato da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) in {interaction.guild.name} - Uptime: {uptime_str}')


@bot.tree.command(name='embed', description='Crea e modifica un embed in tempo reale (solo admin)')
@owner_or_has_permissions(administrator=True)
async def slash_embed(interaction: discord.Interaction):
    embed = discord.Embed(title='Embed Creator', description='Usa il menu sottostante per modificare l\'embed.',
                          color=0x00ff00)
    embed.set_footer(text='Valiance Bot - Embed Creator')

    view = EmbedCreatorView(embed, interaction.user.id)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    logger.info(
        f'Comando /embed usato da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) in {interaction.guild.name}')


class LogSelectView(discord.ui.View):
    def __init__(self, log_files, action='view'):
        super().__init__(timeout=60)
        self.log_files = log_files
        self.action = action

        options = []
        for file in log_files:
            options.append(discord.SelectOption(label=file, value=file))
        if not options:
            options.append(discord.SelectOption(label='Nessun file trovato', value='none'))

        self.select = discord.ui.Select(placeholder='Seleziona un file di log', options=options)
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: discord.Interaction):
        selected_file = self.select.values[0]
        if selected_file == 'none':
            await interaction.response.send_message('❌ Nessun file di log disponibile.', ephemeral=True)
            return

        if self.action == 'view':
            file_path = os.path.join('logs', selected_file)
            if os.path.exists(file_path):
                try:
                    await interaction.user.send(file=discord.File(file_path))
                    await interaction.response.send_message(f'✅ File `{selected_file}` inviato in DM!', ephemeral=True)
                    logger.info(
                        f'File log {selected_file} inviato in DM a {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id})')
                except Exception as e:
                    await interaction.response.send_message(f'❌ Errore nell\'invio del file: {e}', ephemeral=True)
                    logger.error(
                        f'Errore invio file log {selected_file} a {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}): {e}')
            else:
                await interaction.response.send_message('❌ File non trovato.', ephemeral=True)
        elif self.action == 'delete':
            embed = discord.Embed(
                title='🗑️ Conferma Eliminazione',
                description=f'Sei sicuro di voler eliminare il file di log **{selected_file}**?\n\nQuesta azione è irreversibile.',
                color=0xff0000
            )
            embed.set_footer(text='Scade in 30 secondi')
            view = DeleteLogConfirmView(selected_file, interaction.user.id)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class DeleteLogConfirmView(discord.ui.View):
    def __init__(self, filename, author_id):
        super().__init__(timeout=30)
        self.filename = filename
        self.author_id = author_id

    @discord.ui.button(label='Conferma', style=discord.ButtonStyle.danger, emoji='🗑️')
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message('❌ Solo chi ha eseguito il comando può confermare!', ephemeral=True)
            return
        file_path = os.path.join('logs', self.filename)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                await interaction.response.edit_message(
                    content=f'✅ File di log `{self.filename}` eliminato con successo!', view=None)
                logger.info(
                    f'File log {self.filename} eliminato da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id})')
            except Exception as e:
                await interaction.response.edit_message(content=f'❌ Errore nell\'eliminazione del file: {e}', view=None)
                logger.error(
                    f'Errore eliminazione file log {self.filename} da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}): {e}')
        else:
            await interaction.response.edit_message(content='❌ File non trovato.', view=None)

    @discord.ui.button(label='Annulla', style=discord.ButtonStyle.secondary, emoji='❌')
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message('❌ Solo chi ha eseguito il comando può annullare!', ephemeral=True)
            return
        await interaction.response.edit_message(content='❌ Eliminazione annullata.', view=None)


@bot.tree.command(name='logs', description='Visualizza e scarica i file di log del bot')
@owner_or_has_permissions(administrator=True)
async def slash_logs(interaction: discord.Interaction):
    logs_dir = 'logs'
    if not os.path.exists(logs_dir):
        await interaction.response.send_message('❌ Cartella logs non trovata.', ephemeral=True)
        return

    log_files = [f for f in os.listdir(logs_dir) if f.endswith('.log')]
    if not log_files:
        await interaction.response.send_message('❌ Nessun file di log trovato.', ephemeral=True)
        return

    view = LogSelectView(log_files, action='view')
    await interaction.response.send_message('📄 Seleziona un file di log da visualizzare:', view=view, ephemeral=True)
    logger.info(
        f'Comando /logs usato da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) in {interaction.guild.name}')


@bot.tree.command(name='dellogs', description='Elimina un file di log del bot')
@owner_or_has_permissions(administrator=True)
async def slash_dellogs(interaction: discord.Interaction):
    logs_dir = 'logs'
    if not os.path.exists(logs_dir):
        await interaction.response.send_message('❌ Cartella logs non trovata.', ephemeral=True)
        return

    log_files = [f for f in os.listdir(logs_dir) if f.endswith('.log')]
    if not log_files:
        await interaction.response.send_message('❌ Nessun file di log trovato.', ephemeral=True)
        return

    view = LogSelectView(log_files, action='delete')
    await interaction.response.send_message('🗑️ Seleziona un file di log da eliminare:', view=view, ephemeral=True)
    logger.info(
        f'Comando /dellogs usato da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) in {interaction.guild.name}')


@bot.tree.command(name='reloadlog',
                  description='Ricarica la configurazione log.json senza riavviare il bot (solo admin)')
@owner_or_has_permissions(administrator=True)
async def slash_reloadlog(interaction: discord.Interaction):
    try:
        log_cog = bot.get_cog('LogCog')
        if log_cog:
            log_cog.reload_config()
            await interaction.response.send_message('✅ Configurazione log ricaricata con successo!', ephemeral=True)
            logger.info(
                f'Configurazione log ricaricata da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) in {interaction.guild.name}')
        else:
            await interaction.response.send_message('❌ Cog Log non trovato.', ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f'❌ Errore nel ricaricare la configurazione log: {e}', ephemeral=True)
        logger.error(
            f'Errore reloadlog da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) in {interaction.guild.name}: {e}')


def reload_global_config():
    global config
    with open('config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)

    moderation_cog = bot.get_cog('ModerationCog')
    if moderation_cog:
        moderation_cog.reload_config()

    log_cog = bot.get_cog('LogCog')
    if log_cog:
        log_cog.reload_config()


@bot.tree.command(name='reloadconfig',
                  description='Ricarica la configurazione config.json senza riavviare il bot (solo admin)')
@owner_or_has_permissions(administrator=True)
async def slash_reloadconfig(interaction: discord.Interaction):
    try:
        reload_global_config()
        await interaction.response.send_message('✅ Configurazione globale ricaricata con successo!', ephemeral=True)
        logger.info(
            f'Configurazione globale ricaricata da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) in {interaction.guild.name}')
    except Exception as e:
        await interaction.response.send_message(f'❌ Errore nel ricaricare la configurazione globale: {e}',
                                                ephemeral=True)
        logger.error(
            f'Errore reloadconfig da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) in {interaction.guild.name}: {e}')


def reload_all():
    global config
    with open('config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)

    moderation_cog = bot.get_cog('ModerationCog')
    if moderation_cog:
        moderation_cog.reload_mod()

    ticket_cog = bot.get_cog('TicketCog')
    if ticket_cog:
        ticket_cog.reload_ticket()

    log_cog = bot.get_cog('LogCog')
    if log_cog:
        log_cog.reload_config()


@bot.tree.command(name='reloadall', description='Ricarica tutte le configurazioni senza riavviare il bot (solo admin)')
@owner_or_has_permissions(administrator=True)
async def slash_reloadall(interaction: discord.Interaction):
    try:
        reload_all()
        await interaction.response.send_message('✅ Tutte le configurazioni ricaricate con successo!', ephemeral=True)
        logger.info(
            f'Tutte le configurazioni ricaricate da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) in {interaction.guild.name}')
    except Exception as e:
        await interaction.response.send_message(f'❌ Errore nel ricaricare tutte le configurazioni: {e}', ephemeral=True)
        logger.error(
            f'Errore reloadall da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) in {interaction.guild.name}: {e}')


@bot.tree.command(name='setlogchannel', description='Imposta i canali di log per ogni tipo di evento (solo admin)')
@app_commands.describe(
    channel_id='ID del canale di log (se non specificato, usa questo canale per tutti)',
    join_leave='Canale per join/leave',
    moderation='Canale per moderazione (ban, kick, mute, etc.)',
    ticket='Canale per ticket',
    autorole='Canale per autorole',
    automod='Canale per automod',
    message='Canale per messaggi (delete/edit)',
    boost='Canale per boost server'
)
@owner_or_has_permissions(administrator=True)
async def slash_setlogchannel(
        interaction: discord.Interaction,
        channel_id: str = None,
        join_leave: str = None,
        moderation: str = None,
        ticket: str = None,
        autorole: str = None,
        automod: str = None,
        message: str = None,
        boost: str = None
):
    try:
        if os.path.exists('cogs/log/log.json'):
            with open('cogs/log/log.json', 'r', encoding='utf-8') as f:
                log_config = json.load(f)
        else:
            log_config = {}

        default_channel = channel_id or str(interaction.channel.id)

        channel_map = {
            'join_leave': ('join_log_channel_id', 'leave_log_channel_id'),
            'moderation': ('moderation_log_channel_id',),
            'ticket': ('ticket_log_channel_id',),
            'autorole': ('autorole_log_channel_id',),
            'automod': ('automod_log_channel_id',),
            'message': ('message_log_channel_id',),
            'boost': ('boost_log_channel_id',)
        }

        params = {
            'join_leave': join_leave,
            'moderation': moderation,
            'ticket': ticket,
            'autorole': autorole,
            'automod': automod,
            'message': message,
            'boost': boost
        }

        updated_channels = []

        if not any(params.values()):
            for param, fields in channel_map.items():
                for field in fields:
                    log_config[field] = default_channel
                updated_channels.append(f"{param}: {default_channel}")
        else:
            for param, value in params.items():
                if value:
                    for field in channel_map[param]:
                        log_config[field] = value
                    updated_channels.append(f"{param}: {value}")

        with open('cogs/log/log.json', 'w', encoding='utf-8') as f:
            json.dump(log_config, f, indent=2, ensure_ascii=False)

        embed = discord.Embed(
            title='✅ Canali Log Aggiornati',
            description='I canali di log sono stati configurati con successo:',
            color=0x00ff00
        )

        for update in updated_channels:
            embed.add_field(name='📝', value=update, inline=False)

        embed.set_footer(text='Valiance Bot | Logging System')

        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info(
            f'Canali log aggiornati da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) in {interaction.guild.name}: {", ".join(updated_channels)}')

    except Exception as e:
        await interaction.response.send_message(f'❌ Errore nell\'impostazione dei canali log: {e}', ephemeral=True)
        logger.error(
            f'Errore setlogchannel da {interaction.user.name}#{interaction.user.discriminator} ({interaction.user.id}) in {interaction.guild.name}: {e}')


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
            logger.error(f'Ignored NotFound in app command: {error}')
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
            modules_to_setup = [
                'cogs.ticket.ticket',
                'cogs.moderation.moderation',
                'cogs.autorole.autorole',
                'cogs.log.log',
                'cogs.fun',
                'cogs.regole.regole',
                'cogs.tts.tts',
                'cogs.cw.cw',
                'cogs.help'
            ]
            for modname in modules_to_setup:
                try:
                    mod = importlib.import_module(modname)
                    setup = getattr(mod, 'setup', None)
                    if setup:
                        if asyncio.iscoroutinefunction(setup):
                            await setup(bot)
                        else:
                            setup(bot)
                    logger.info(f'Extension {modname} setup executed')
                except Exception as e:
                    logger.error(f'Non sono riuscito a caricare {modname}: {e}')


        asyncio.run(setup_modules())
        bot.run(os.getenv('TOKEN'))
    except Exception as e:
        logger.critical(f'Errore fatale nell\'avvio del bot: {e}')
