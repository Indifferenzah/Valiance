import discord
from discord.ext import commands
from discord import app_commands
import json
import asyncio

# Carica configurazione
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

# Configurazione bot
intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True
intents.members = True
intents.message_content = True
intents.reactions = True

bot = commands.Bot(command_prefix='v!', intents=intents)

# Load ticket cog
from ticket import TicketCog, TicketView

# Dizionario per tracciare le sessioni attive
active_sessions = {}

# Variabile per tracciare se stiamo aspettando il ruleset o welcome message
waiting_for_ruleset = False
waiting_for_welcome = False
waiting_for_boost = False

# Dizionario per tracciare i canali counter attivi
counter_channels = {}
counter_task = None
last_counter_update = {}  # Per evitare aggiornamenti troppo frequenti

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
        await ctx.send('❌ Comando inesistente! Fai `v!help` per vedere una lista di comandi disponibili.')
    else:
        # Handle other errors if needed
        pass

@bot.event
async def on_ready():
    print(f'Bot connesso come {bot.user}')
    try:
        synced = await bot.tree.sync()
        print(f'Sincronizzati {len(synced)} comandi slash')
    except Exception as e:
        print(f'Errore nella sincronizzazione: {e}')
    
    # Carica i counter attivi dal config
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

    # Avvia il loop di aggiornamento se ci sono counter attivi
    global counter_task
    if counter_channels and (counter_task is None or counter_task.done()):
        counter_task = bot.loop.create_task(counter_update_loop())
        print('Loop di aggiornamento counter avviato')

    # Add ticket cog
    await bot.add_cog(TicketCog(bot))
    print('Ticket cog aggiunto')

    # Re-attach ticket panel view if exists
    ticket_cog = bot.get_cog('TicketCog')
    if 'ticket_panel_message_id' in config and 'ticket_panel_channel_id' in config:
        channel = bot.get_channel(int(config['ticket_panel_channel_id']))
        if channel:
            try:
                message = await channel.fetch_message(int(config['ticket_panel_message_id']))
                # Get panel config
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

                # Use all buttons for re-attachment
                all_buttons = config.get('ticket_buttons', [])
                view = TicketView(all_buttons, config, ticket_cog)
                await message.edit(embed=embed, view=view)
                print('Ticket panel view re-attached')
            except Exception as e:
                print(f'Errore nel ricaricare il pannello ticket: {e}')

@bot.event
async def on_member_remove(member):
    """Aggiorna i counter quando un membro esce"""
    # Rimuovi l'aggiornamento immediato per evitare rate limits
    if member.guild.id in counter_channels:
        await update_counters(member.guild) 

@bot.event
async def on_voice_state_update(member, before, after):
    # Ignora i bot
    if member.bot:
        return

    lobby_id = int(config['lobby_voice_channel_id'])

    # Controlla se qualcuno è entrato nella lobby
    if after.channel and after.channel.id == lobby_id:
        await check_and_create_game(after.channel)

@bot.event
async def on_member_join(member):
    """Invia il messaggio di benvenuto quando un nuovo membro entra e aggiorna i counter"""
    # Aggiorna i counter se attivi
    if member.guild.id in counter_channels:
        await update_counters(member.guild)
    
    # Invia messaggio di benvenuto
    if 'welcome_channel_id' not in config or not config['welcome_channel_id']:
        return
    
    try:
        welcome_channel = member.guild.get_channel(int(config['welcome_channel_id']))
        if not welcome_channel:
            return
        
        # Ottieni il messaggio di benvenuto dalla config
        welcome_data = config.get('welcome_message', {})
        
        # Sostituisci le variabili
        description = welcome_data.get('description', '{mention}, benvenuto/a!')
        description = description.replace('{mention}', member.mention)
        description = description.replace('{username}', member.name)
        description = description.replace('{user}', member.name)

        # Crea l'embed
        embed = discord.Embed(
            title=welcome_data.get('title', 'Nuovo membro!'),
            description=description,
            color=welcome_data.get('color', 3447003)
        )

        # Aggiungi thumbnail (avatar dell'utente)
        thumbnail = welcome_data.get('thumbnail', '{avatar}')
        if '{avatar}' in thumbnail:
            embed.set_thumbnail(url=member.display_avatar.url)
        elif thumbnail:
            embed.set_thumbnail(url=thumbnail)

        # Aggiungi footer
        footer = welcome_data.get('footer', '')
        if footer:
            embed.set_footer(text=footer)

        # Aggiungi author (header con icona profilo)
        embed.set_author(name=member.name, icon_url=member.display_avatar.url)

        # Invia messaggio con ping e embed
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
    """Invia il messaggio di boost quando un membro boosta il server"""
    # Controlla se il membro ha iniziato a boostare
    if before.premium_since is None and after.premium_since is not None:
        # Invia messaggio di boost
        if 'boost_channel_id' not in config or not config['boost_channel_id']:
            return

        try:
            boost_channel = after.guild.get_channel(int(config['boost_channel_id']))
            if not boost_channel:
                return

            # Ottieni il messaggio di boost dalla config
            boost_data = config.get('boost_message', {})

            # Sostituisci le variabili
            description = boost_data.get('description', '{mention} ha boostato il server!')
            description = description.replace('{mention}', after.mention)
            description = description.replace('{username}', after.name)
            description = description.replace('{user}', after.name)

            # Crea l'embed
            embed = discord.Embed(
                title=boost_data.get('title', 'Nuovo Boost!'),
                description=description,
                color=boost_data.get('color', 16776960)
            )

            # Aggiungi thumbnail (avatar dell'utente)
            thumbnail = boost_data.get('thumbnail', '{avatar}')
            if '{avatar}' in thumbnail:
                embed.set_thumbnail(url=after.display_avatar.url)
            elif thumbnail:
                embed.set_thumbnail(url=thumbnail)

            # Aggiungi footer
            footer = boost_data.get('footer', '')
            if footer:
                embed.set_footer(text=footer)

            # Aggiungi author (header con icona profilo)
            embed.set_author(name=after.name, icon_url=after.display_avatar.url)

            await boost_channel.send(embed=embed)

            print(f'Messaggio di boost inviato per {after.name}')

        except Exception as e:
            print(f'Errore nell\'invio del messaggio di boost: {e}')

@bot.event
async def on_message(message):
    global waiting_for_ruleset, waiting_for_welcome, waiting_for_boost

    # Ignora i messaggi del bot stesso
    if message.author.bot:
        return

    # Se stiamo aspettando il ruleset e il messaggio è dall'utente autorizzato
    if waiting_for_ruleset and message.author.id == 1123622103917285418:
        # Salva il contenuto del messaggio in config.json
        config['ruleset_message'] = message.content
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        waiting_for_ruleset = False
        await message.add_reaction('✅')
        await message.channel.send('✅ Ruleset salvato! Usa `v!ruleset` per visualizzarlo.')
        return

    # Se stiamo aspettando il welcome message e il messaggio è dall'utente autorizzato
    if waiting_for_welcome and message.author.id == 1123622103917285418:
        # Salva il contenuto del messaggio come descrizione del welcome
        config['welcome_message']['description'] = message.content
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        waiting_for_welcome = False
        await message.add_reaction('✅')
        await message.channel.send('✅ Messaggio di benvenuto salvato!\n\n**Variabili disponibili:**\n`{mention}` - Tag dell\'utente\n`{username}` - Nome utente\n`{avatar}` - Avatar utente (per thumbnail)')
        return
    
    # Processa i comandi del bot
    await bot.process_commands(message)

    # Check for welcome messages
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

    # Raccogli i tag unici dal messaggio e spostali immediatamente
    for mention in message.mentions:
        if mention not in session.tagged_users:
            session.tagged_users.append(mention)
            
            # Determina il team in base alla posizione (alternato)
            position = len(session.tagged_users) - 1
            is_red = position % 2 == 0  # 0, 2, 4, 6... = ROSSO
            
            # Sposta immediatamente se è in vc
            if mention.voice and mention.voice.channel:
                try:
                    target_channel = session.red_voice if is_red else session.green_voice
                    await mention.move_to(target_channel)
                    team_name = "ROSSO" if is_red else "VERDE"
                    print(f'Spostato {mention.name} nel team {team_name}')
                    
                    # Invia conferma nel canale di testo
                    await session.text_channel.send(f'{mention.mention} → {"Team Rosso" if is_red else "Team Verde"}')
                except Exception as e:
                    print(f'Errore nello spostamento di {mention.name}: {e}')

async def check_and_create_game(lobby_channel):
    guild = lobby_channel.guild
    
    # Se c'è già una sessione attiva per questo server, non fare nulla
    if guild.id in active_sessions and active_sessions[guild.id].is_active:
        return
    
    # Conta i membri nella lobby (esclusi i bot)
    members = [m for m in lobby_channel.members if not m.bot]
    
    if len(members) >= 1:
        print(f'Giocatore rilevato! Creazione partita...')
        await create_game_session(guild, lobby_channel)

async def create_game_session(guild, lobby_channel):
    try:
        # Crea una nuova sessione
        session = GameSession(guild, lobby_channel)
        session.is_active = True

        # Ottieni la categoria (se specificata)
        category = None
        if 'category_id' in config and config['category_id']:
            category = guild.get_channel(int(config['category_id']))

        # ID utente con permessi speciali
        admin_user_id = 1123622103917285418
        admin_user = guild.get_member(admin_user_id)
        
        # Configura i permessi per l'utente admin e blocca gli altri
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=False,
                connect=False
            ),
        }
        
        if admin_user:
            overwrites[admin_user] = discord.PermissionOverwrite(
                # Permessi generali
                view_channel=True,
                manage_channels=True,
                manage_permissions=True,
                manage_webhooks=True,
                # Permessi testuali
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
                # Permessi vocali
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

        # Crea canale di testo con permessi
        session.text_channel = await guild.create_text_channel(
            name='cw-interna',
            category=category,
            topic='CW - Team Rosso vs Verde',
            overwrites=overwrites
        )

        # Crea canali vocali con permessi
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

        # Invia messaggio di istruzioni
        embed = discord.Embed(
            title='**CW Interna** - Istruzioni',
            description='**CW Interne Valiance**\n\nTagga fino a 8 giocatori per assegnare i team automaticamente:\n> Il primo taggato verrà inserito nel team ROSSO\n> Il secondo nel team VERDE\n> E cosi via...',
            color=discord.Color.blue()
        )

        embed.set_footer(text='Usa `v!cwend` per terminare la partita ed eliminare tutti i canali.')

        await session.text_channel.send(embed=embed)

        # Salva la sessione
        active_sessions[guild.id] = session

        print(f'Partita creata con successo nel server {guild.name}')

    except Exception as e:
        print(f'Errore nella creazione della partita: {e}')
        # Cleanup in caso di errore
        await cleanup_session(guild.id)

async def assign_teams(session):
    """Assegna i giocatori taggati ai team e li sposta nei canali vocali"""
    try:
        # Primi 4 = ROSSO, successivi 4 = VERDE
        red_team = session.tagged_users[:4]
        green_team = session.tagged_users[4:8]

        # Invia messaggio con i team
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

        embed.set_footer(text='Buon divertimento! Usa `v!cwend` per terminare')

        await session.text_channel.send(embed=embed)

        # Sposta i giocatori nei canali vocali (solo quelli attualmente in vc)
        await asyncio.sleep(1)  # Piccolo delay

        for member in red_team:
            try:
                # Sposta solo se è in vc
                if member.voice and member.voice.channel:
                    await member.move_to(session.red_voice)
                    print(f'Spostato {member.name} nel team ROSSO')
            except Exception as e:
                print(f'Errore nello spostamento di {member.name} nel ROSSO: {e}')

        await asyncio.sleep(0.5)

        for member in green_team:
            try:
                # Sposta solo se è in vc
                if member.voice and member.voice.channel:
                    await member.move_to(session.green_voice)
                    print(f'Spostato {member.name} nel team VERDE')
            except Exception as e:
                print(f'Errore nello spostamento di {member.name} nel VERDE: {e}')

        print(f'Team assegnati con successo nel server {session.guild.name}')

    except Exception as e:
        print(f'Errore nell\'assegnazione dei team: {e}')

async def cleanup_session(guild_id):
    """Elimina tutti i canali creati per la sessione"""
    if guild_id not in active_sessions:
        return
    
    session = active_sessions[guild_id]
    
    try:
        # Elimina canale di testo
        if session.text_channel:
            try:
                await session.text_channel.delete()
                print(f'Canale di testo eliminato')
            except Exception as e:
                print(f'Errore nell\'eliminazione del canale di testo: {e}')
        
        # Elimina canale vocale rosso
        if session.red_voice:
            try:
                await session.red_voice.delete()
                print(f'Canale vocale ROSSO eliminato')
            except Exception as e:
                print(f'Errore nell\'eliminazione del canale ROSSO: {e}')
        
        # Elimina canale vocale verde
        if session.green_voice:
            try:
                await session.green_voice.delete()
                print(f'Canale vocale VERDE eliminato')
            except Exception as e:
                print(f'Errore nell\'eliminazione del canale VERDE: {e}')
        
        # Rimuovi la sessione
        del active_sessions[guild_id]
        print(f'Sessione pulita con successo')
        
    except Exception as e:
        print(f'Errore durante la pulizia: {e}')

@bot.command(name='cwend', help='Termina la partita custom e elimina i canali (solo admin)')
async def cwend(ctx):
    # Controlla se l'utente è autorizzato
    if ctx.author.id != 1123622103917285418:
        await ctx.send('❌ Non hai i permessi per usare questo comando!')
        return
    
    guild_id = ctx.guild.id
    
    if guild_id not in active_sessions:
        await ctx.send('❌ Non ci sono partite attive!')
        return
    
    await ctx.send('🧹 Terminazione partita in corso...')
    await cleanup_session(guild_id)
    await ctx.send('✅ Partita terminata e canali eliminati!')

@bot.command(name='setruleset', help='Imposta il ruleset (solo per admin)')
async def setruleset(ctx):
    global waiting_for_ruleset
    
    # Controlla se l'utente è autorizzato
    if ctx.author.id != 1123622103917285418:
        await ctx.send('❌ Non hai i permessi per usare questo comando!')
        return
    
    waiting_for_ruleset = True
    await ctx.send('📝 Invia il prossimo messaggio che vuoi salvare come ruleset.')

@bot.command(name='ruleset', help='Mostra il ruleset salvato')
async def ruleset(ctx):
    if 'ruleset_message' not in config or not config['ruleset_message']:
        await ctx.send('❌ Nessun ruleset configurato! Usa `v!setruleset` per impostarne uno.')
        return
    
    await ctx.send(config['ruleset_message'])

@bot.command(name='testwelcome', help='Testa il messaggio di benvenuto (solo per admin)')
async def testwelcome(ctx):
    # Controlla se l'utente è autorizzato
    if ctx.author.id != 1123622103917285418:
        await ctx.send('❌ Non hai i permessi per usare questo comando!')
        return
    
    if 'welcome_channel_id' not in config or not config['welcome_channel_id']:
        await ctx.send('❌ Canale di benvenuto non configurato in config.json!')
        return
    
    try:
        welcome_channel = ctx.guild.get_channel(int(config['welcome_channel_id']))
        if not welcome_channel:
            await ctx.send('❌ Canale di benvenuto non trovato!')
            return
        
        # Ottieni il messaggio di benvenuto dalla config
        welcome_data = config.get('welcome_message', {})
        
        # Sostituisci le variabili con i dati dell'utente che ha eseguito il comando
        description = welcome_data.get('description', '{mention}, benvenuto/a!')
        description = description.replace('{mention}', ctx.author.mention)
        description = description.replace('{username}', ctx.author.name)
        description = description.replace('{user}', ctx.author.name)
        
        # Crea l'embed
        embed = discord.Embed(
            title=welcome_data.get('title', 'Nuovo membro!'),
            description=description,
            color=welcome_data.get('color', 3447003)
        )
        
        # Aggiungi thumbnail (avatar dell'utente)
        thumbnail = welcome_data.get('thumbnail', '{avatar}')
        if '{avatar}' in thumbnail:
            embed.set_thumbnail(url=ctx.author.display_avatar.url)
        elif thumbnail:
            embed.set_thumbnail(url=thumbnail)
        
        # Aggiungi footer
        footer = welcome_data.get('footer', '')
        if footer:
            embed.set_footer(text=footer)
        
        # Aggiungi author (header con icona profilo)
        embed.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar.url)
        
        await welcome_channel.send(embed=embed)
        await ctx.send('✅ Messaggio di benvenuto di test inviato!')

    except Exception as e:
        await ctx.send(f'❌ Errore nell\'invio del messaggio di test: {e}')

@bot.command(name='testboost', help='Testa il messaggio di boost (solo per admin)')
async def testboost(ctx):
    # Controlla se l'utente è autorizzato
    if ctx.author.id != 1123622103917285418:
        await ctx.send('❌ Non hai i permessi per usare questo comando!')
        return

    if 'boost_channel_id' not in config or not config['boost_channel_id']:
        await ctx.send('❌ Canale di boost non configurato in config.json!')
        return

    try:
        boost_channel = ctx.guild.get_channel(int(config['boost_channel_id']))
        if not boost_channel:
            await ctx.send('❌ Canale di boost non trovato!')
            return

        # Ottieni il messaggio di boost dalla config
        boost_data = config.get('boost_message', {})

        # Sostituisci le variabili con i dati dell'utente che ha eseguito il comando
        description = boost_data.get('description', '{mention} ha boostato il server!')
        description = description.replace('{mention}', ctx.author.mention)
        description = description.replace('{username}', ctx.author.name)
        description = description.replace('{user}', ctx.author.name)

        # Crea l'embed
        embed = discord.Embed(
            title=boost_data.get('title', 'Nuovo Boost!'),
            description=description,
            color=boost_data.get('color', 16776960)
        )

        # Aggiungi thumbnail (avatar dell'utente)
        thumbnail = boost_data.get('thumbnail', '{avatar}')
        if '{avatar}' in thumbnail:
            embed.set_thumbnail(url=ctx.author.display_avatar.url)
        elif thumbnail:
            embed.set_thumbnail(url=thumbnail)

        # Aggiungi footer
        footer = boost_data.get('footer', '')
        if footer:
            embed.set_footer(text=footer)

        # Aggiungi author (header con icona profilo)
        embed.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar.url)

        await boost_channel.send(embed=embed)
        await ctx.send('✅ Messaggio di boost di test inviato!')

    except Exception as e:
        await ctx.send(f'❌ Errore nell\'invio del messaggio di test: {e}')

async def update_counters(guild):
    """Aggiorna i nomi dei canali counter con i conteggi attuali"""
    if guild.id not in counter_channels:
        return

    # Controlla se è passato abbastanza tempo dall'ultimo aggiornamento
    now = asyncio.get_event_loop().time()
    if guild.id in last_counter_update and now - last_counter_update[guild.id] < 30:
        return  # Aggiorna al massimo ogni minuto
    last_counter_update[guild.id] = now

    try:
        # Rimuovi counter se canali eliminati
        for channel_type in list(counter_channels[guild.id].keys()):
            channel = counter_channels[guild.id][channel_type]
            if channel is None or not hasattr(channel, 'id') or channel.id is None:
                # Channel deleted, remove
                del counter_channels[guild.id][channel_type]
                if str(guild.id) in config.get('active_counters', {}) and channel_type in config['active_counters'][str(guild.id)]:
                    del config['active_counters'][str(guild.id)][channel_type]
                    if not config['active_counters'][str(guild.id)]:
                        del config['active_counters'][str(guild.id)]
                    with open('config.json', 'w', encoding='utf-8') as f:
                        json.dump(config, f, indent=2, ensure_ascii=False)
                print(f'Counter {channel_type} rimosso per guild {guild.name} (canale eliminato)')

        counters_config = config.get('counters', {})

        # Conta tutti i membri (esclusi i bot)
        total_members = len([m for m in guild.members if not m.bot])

        # Conta i membri con il ruolo specifico
        role_id = int(counters_config.get('member_role_id', '0'))
        role = guild.get_role(role_id)
        role_members = 0
        if role:
            role_members = len([m for m in role.members if not m.bot])

        # Aggiorna canale membri totali
        if 'total_members' in counter_channels[guild.id]:
            channel = counter_channels[guild.id]['total_members']
            name_template = counters_config.get('total_members_name', '👥 Membri: {count}')
            new_name = name_template.replace('{count}', str(total_members))
            if channel.name != new_name:
                await channel.edit(name=new_name)
                print(f'Aggiornato counter membri totali: {new_name}')

        # Aggiorna canale membri con ruolo
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
    """Loop per aggiornare i counter periodicamente"""
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            for guild_id in list(counter_channels.keys()):
                guild = bot.get_guild(guild_id)
                if guild:
                    await update_counters(guild)
            await asyncio.sleep(30)  # Aggiorna ogni 5 minuti
        except Exception as e:
            print(f'Errore nel loop di aggiornamento counter: {e}')
            await asyncio.sleep(15)

@bot.command(name='startct', help='Avvia i canali counter (solo admin)')
async def startct(ctx):
    global counter_task
    
    # Controlla se l'utente è autorizzato
    if ctx.author.id != 1123622103917285418:
        await ctx.send('❌ Non hai i permessi per usare questo comando!')
        return
    
    guild = ctx.guild
    
    # Controlla se i counter sono già attivi
    if guild.id in counter_channels:
        await ctx.send('❌ I counter sono già attivi! Usa `v!stopct` per fermarli prima.')
        return
    
    try:
        await ctx.send('🔄 Creazione canali counter in corso...')
        
        counters_config = config.get('counters', {})
        
        # Conta i membri
        total_members = len([m for m in guild.members if not m.bot])
        role_id = int(counters_config.get('member_role_id', '0'))
        role = guild.get_role(role_id)
        role_members = 0
        if role:
            role_members = len([m for m in role.members if not m.bot])
        
        # Crea i nomi dei canali con i conteggi
        total_name = counters_config.get('total_members_name', '👥 Membri: {count}').replace('{count}', str(total_members))
        role_name = counters_config.get('role_members_name', '⭐ Membri Clan: {count}').replace('{count}', str(role_members))
        
        # Crea i canali vocali in cima (position=0) senza categoria
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
        
        # Salva i canali
        counter_channels[guild.id] = {
            'total_members': total_channel,
            'role_members': role_channel
        }

        # Salva gli ID nel config
        if 'active_counters' not in config:
            config['active_counters'] = {}
        config['active_counters'][str(guild.id)] = {
            'total_members': total_channel.id,
            'role_members': role_channel.id
        }
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        # Avvia il task di aggiornamento se non è già attivo
        if counter_task is None or counter_task.done():
            counter_task = bot.loop.create_task(counter_update_loop())

        await ctx.send(f'✅ Canali counter creati con successo!\n📊 Membri totali: {total_members}\n⭐ Membri clan: {role_members}')
        print(f'Counter attivati nel server {guild.name}')
        
    except Exception as e:
        await ctx.send(f'❌ Errore nella creazione dei counter: {e}')
        print(f'Errore nella creazione dei counter: {e}')

@bot.command(name='stopct', help='Ferma e elimina i canali counter (solo admin)')
async def stopct(ctx):
    # Controlla se l'utente è autorizzato
    if ctx.author.id != 1123622103917285418:
        await ctx.send('❌ Non hai i permessi per usare questo comando!')
        return
    
    guild = ctx.guild
    
    # Controlla se i counter sono attivi
    if guild.id not in counter_channels:
        await ctx.send('❌ Non ci sono counter attivi!')
        return
    
    try:
        await ctx.send('🧹 Eliminazione canali counter in corso...')
        
        channels = counter_channels[guild.id]
        
        # Elimina i canali
        if 'total_members' in channels:
            try:
                await channels['total_members'].delete()
                print('Canale counter membri totali eliminato')
            except Exception as e:
                print(f'Errore nell\'eliminazione del canale membri totali: {e}')
        
        if 'role_members' in channels:
            try:
                await channels['role_members'].delete()
                print('Canale counter membri ruolo eliminato')
            except Exception as e:
                print(f'Errore nell\'eliminazione del canale membri ruolo: {e}')
        
        # Rimuovi dalla lista
        del counter_channels[guild.id]

        # Rimuovi dal config
        if str(guild.id) in config.get('active_counters', {}):
            del config['active_counters'][str(guild.id)]
            with open('config.json', 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)

        await ctx.send('✅ Canali counter eliminati con successo!')
        print(f'Counter disattivati nel server {guild.name}')
        
    except Exception as e:
        await ctx.send(f'❌ Errore nell\'eliminazione dei counter: {e}')
        print(f'Errore nell\'eliminazione dei counter: {e}')

@bot.command(name='purge', help='Elimina un tot di messaggi')
@commands.has_permissions(manage_messages=True)
async def purge_messages(ctx, limit: int):
    if limit < 1 or limit > 250:
        await ctx.send("❌ puoi scegliere numeri tra 1 e 250.")
        return
    deleted = await ctx.channel.purge(limit=limit)
    await ctx.send(f"✅ Ho eliminato {len(deleted)} messaggi.", delete_after=3)

# Avvia il bot
if __name__ == '__main__':
    try:
        bot.run(config['token'])
    except Exception as e:
        print(f'Errore nell\'avvio del bot: {e}')
