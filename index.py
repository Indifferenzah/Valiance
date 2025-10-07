import discord
from discord.ext import commands
from discord import app_commands
import json
import asyncio

# Carica configurazione
with open('config.json', 'r') as f:
    config = json.load(f)

# Configurazione bot
intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix='v!', intents=intents)

# Dizionario per tracciare le sessioni attive
active_sessions = {}

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
async def on_ready():
    print(f'Bot connesso come {bot.user}')
    try:
        synced = await bot.tree.sync()
        print(f'Sincronizzati {len(synced)} comandi slash')
    except Exception as e:
        print(f'Errore nella sincronizzazione: {e}')

@bot.event
async def on_voice_state_update(member, before, after):
    # Ignora i bot
    if member.bot:
        return

    lobby_id = int(config['lobby_voice_channel_id'])

    # Controlla se qualcuno è entrato nella lobby
    if after.channel and after.channel.id == lobby_id:
        await check_and_create_game(after.channel)

    # Controlla se qualcuno è uscito dai canali di gioco
    if before.channel:
        await check_cleanup(before.channel)

@bot.event
async def on_message(message):
    # Ignora i messaggi del bot stesso
    if message.author.bot:
        return
    
    # Processa i comandi del bot
    await bot.process_commands(message)

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

        # Crea canale di testo
        session.text_channel = await guild.create_text_channel(
            name='cw-interna',
            category=category,
            topic='CW - Team Rosso vs Verde'
        )

        # Crea canali vocali
        session.red_voice = await guild.create_voice_channel(
            name='Team Rosso',
            category=category,
            user_limit=4
        )

        session.green_voice = await guild.create_voice_channel(
            name='Team Verde',
            category=category,
            user_limit=4
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

async def check_cleanup(channel):
    """Controlla se i canali di gioco sono vuoti e li pulisce"""
    guild = channel.guild
    
    if guild.id not in active_sessions:
        return
    
    session = active_sessions[guild.id]
    
    # Controlla se i canali vocali sono vuoti
    red_empty = session.red_voice and len([m for m in session.red_voice.members if not m.bot]) == 0
    green_empty = session.green_voice and len([m for m in session.green_voice.members if not m.bot]) == 0
    
    if red_empty and green_empty:
        print(f'Canali vuoti rilevati, pulizia in corso...')
        await cleanup_session(guild.id)

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

@bot.command(name='cwend', help='Termina la partita custom e elimina i canali')
async def cwend(ctx):
    guild_id = ctx.guild.id
    
    if guild_id not in active_sessions:
        await ctx.send('❌ Non ci sono partite attive!')
        return
    
    await ctx.send('🧹 Terminazione partita in corso...')
    await cleanup_session(guild_id)
    await ctx.send('✅ Partita terminata e canali eliminati!')

# Avvia il bot
if __name__ == '__main__':
    try:
        bot.run(config['token'])
    except Exception as e:
        print(f'Errore nell\'avvio del bot: {e}')
