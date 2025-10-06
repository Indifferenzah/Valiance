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

bot = commands.Bot(command_prefix='!', intents=intents)

# Dizionario per tracciare le sessioni attive
active_sessions = {}

class GameSession:
    def __init__(self, guild, lobby_channel):
        self.guild = guild
        self.lobby_channel = lobby_channel
        self.text_channel = None
        self.red_voice = None
        self.green_voice = None
        self.red_team = []
        self.green_team = []
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

async def check_and_create_game(lobby_channel):
    guild = lobby_channel.guild
    
    # Se c'è già una sessione attiva per questo server, non fare nulla
    if guild.id in active_sessions and active_sessions[guild.id].is_active:
        return
    
    # Conta i membri nella lobby (esclusi i bot)
    members = [m for m in lobby_channel.members if not m.bot]
    
    if len(members) >= 8:
        print(f'8 giocatori rilevati! Creazione partita...')
        await create_game_session(guild, lobby_channel, members[:8])

async def create_game_session(guild, lobby_channel, members):
    try:
        # Crea una nuova sessione
        session = GameSession(guild, lobby_channel)
        session.is_active = True
        
        # Dividi i team
        session.red_team = members[:4]
        session.green_team = members[4:8]
        
        # Ottieni la categoria (se specificata)
        category = None
        if 'category_id' in config and config['category_id']:
            category = guild.get_channel(int(config['category_id']))
        
        # Crea canale di testo
        session.text_channel = await guild.create_text_channel(
            name='🎮-partita-custom',
            category=category,
            topic='Partita Custom - Team ROSSO vs Team VERDE'
        )
        
        # Crea canali vocali
        session.red_voice = await guild.create_voice_channel(
            name='🔴 ROSSO',
            category=category,
            user_limit=4
        )
        
        session.green_voice = await guild.create_voice_channel(
            name='🟢 VERDE',
            category=category,
            user_limit=4
        )
        
        # Invia messaggio con i team
        embed = discord.Embed(
            title='🎮 PARTITA CUSTOM INIZIATA',
            description='I team sono stati creati!',
            color=discord.Color.blue()
        )
        
        red_mentions = ' '.join([m.mention for m in session.red_team])
        green_mentions = ' '.join([m.mention for m in session.green_team])
        
        embed.add_field(
            name='🔴 TEAM ROSSO',
            value=red_mentions,
            inline=False
        )
        
        embed.add_field(
            name='🟢 TEAM VERDE',
            value=green_mentions,
            inline=False
        )
        
        embed.set_footer(text='Usa /cwend per terminare la partita')
        
        await session.text_channel.send(embed=embed)
        
        # Sposta i giocatori nei canali vocali
        await asyncio.sleep(1)  # Piccolo delay per evitare rate limit
        
        for member in session.red_team:
            try:
                await member.move_to(session.red_voice)
            except Exception as e:
                print(f'Errore nello spostamento di {member.name}: {e}')
        
        await asyncio.sleep(0.5)
        
        for member in session.green_team:
            try:
                await member.move_to(session.green_voice)
            except Exception as e:
                print(f'Errore nello spostamento di {member.name}: {e}')
        
        # Salva la sessione
        active_sessions[guild.id] = session
        
        print(f'Partita creata con successo nel server {guild.name}')
        
    except Exception as e:
        print(f'Errore nella creazione della partita: {e}')
        # Cleanup in caso di errore
        await cleanup_session(guild.id)

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

@bot.tree.command(name='cwend', description='Termina la partita custom e elimina i canali')
async def cwend(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    
    if guild_id not in active_sessions:
        await interaction.response.send_message('❌ Non ci sono partite attive!', ephemeral=True)
        return
    
    await interaction.response.send_message('🧹 Terminazione partita in corso...', ephemeral=True)
    await cleanup_session(guild_id)
    
    try:
        await interaction.followup.send('✅ Partita terminata e canali eliminati!', ephemeral=True)
    except:
        pass

@bot.tree.command(name='cwstatus', description='Mostra lo stato delle partite attive')
async def cwstatus(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    
    if guild_id not in active_sessions:
        await interaction.response.send_message('❌ Nessuna partita attiva', ephemeral=True)
        return
    
    session = active_sessions[guild_id]
    
    embed = discord.Embed(
        title='📊 Stato Partita',
        color=discord.Color.green()
    )
    
    red_count = len([m for m in session.red_voice.members if not m.bot]) if session.red_voice else 0
    green_count = len([m for m in session.green_voice.members if not m.bot]) if session.green_voice else 0
    
    embed.add_field(name='🔴 Team ROSSO', value=f'{red_count}/4 giocatori', inline=True)
    embed.add_field(name='🟢 Team VERDE', value=f'{green_count}/4 giocatori', inline=True)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# Avvia il bot
if __name__ == '__main__':
    try:
        bot.run(config['token'])
    except Exception as e:
        print(f'Errore nell\'avvio del bot: {e}')
