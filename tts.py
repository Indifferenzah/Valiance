import discord
from discord.ext import commands
import json
import asyncio
import pyttsx3
from discord import app_commands
from bot_utils import OWNER_ID, owner_or_has_permissions, is_owner
from console_logger import logger

class TTSCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.tts_config = {}
        self.load_config()
        self.engine = pyttsx3.init()
        self.is_speaking = False

    def load_config(self):
        try:
            with open('tts.json', 'r', encoding='utf-8') as f:
                self.tts_config = json.load(f)
        except FileNotFoundError:
            self.tts_config = {"channel_id": None, "lang": "ita", "voice": "maschio"}
            self.save_config()

    def save_config(self):
        with open('tts.json', 'w', encoding='utf-8') as f:
            json.dump(self.tts_config, f, indent=2, ensure_ascii=False)

    async def speak(self, text, voice_channel):
        if self.is_speaking:
            return

        self.is_speaking = True
        try:
            voices = self.engine.getProperty('voices')
            if self.tts_config.get('voice') == 'maschio':
                for voice in voices:
                    if 'male' in voice.name.lower() or 'italian' in voice.name.lower():
                        self.engine.setProperty('voice', voice.id)
                        break
            else:
                for voice in voices:
                    if 'female' in voice.name.lower() or 'italian' in voice.name.lower():
                        self.engine.setProperty('voice', voice.id)
                        break

            self.engine.setProperty('rate', 150)
            self.engine.save_to_file(text, 'tts_output.wav')
            self.engine.runAndWait()

            vc = await voice_channel.connect()
            vc.play(discord.FFmpegPCMAudio('tts_output.wav'), after=lambda e: asyncio.run_coroutine_threadsafe(self.cleanup_vc(vc), self.bot.loop))
        except Exception as e:
            logger.error(f'Errore TTS: {e}')
        finally:
            self.is_speaking = False

    async def cleanup_vc(self, vc):
        await vc.disconnect()

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        channel_id = self.tts_config.get('channel_id')
        if channel_id and str(message.channel.id) == channel_id:
            if message.author.voice and message.author.voice.channel:
                await self.speak(message.content, message.author.voice.channel)

    @app_commands.command(name='tts', description='Gestisci le impostazioni TTS')
    async def slash_tts(self, interaction: discord.Interaction):
        await interaction.response.send_message('❌ Usa i sottocomandi: /tts join, /tts leave, /tts channel, /tts lang, /tts voice.', ephemeral=True)

    @slash_tts.subcommand(name='join', description='Unisci il canale vocale corrente come canale TTS')
    async def tts_join(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message('❌ Devi essere in un canale vocale!', ephemeral=True)
            return
        self.tts_config['channel_id'] = str(interaction.user.voice.channel.id)
        self.save_config()
        await interaction.response.send_message(f'✅ TTS unito al canale {interaction.user.voice.channel.name}!', ephemeral=True)

    @slash_tts.subcommand(name='leave', description='Rimuovi il canale TTS')
    async def tts_leave(self, interaction: discord.Interaction):
        self.tts_config['channel_id'] = None
        self.save_config()
        await interaction.response.send_message('✅ TTS lasciato il canale!', ephemeral=True)

    @slash_tts.subcommand(name='channel', description='Imposta o mostra il canale TTS')
    @app_commands.describe(channel_id='ID del canale testo (opzionale, mostra attuale se non specificato)')
    async def tts_channel(self, interaction: discord.Interaction, channel_id: str = None):
        if not channel_id:
            current_channel = self.tts_config.get('channel_id')
            if current_channel:
                channel = self.bot.get_channel(int(current_channel))
                channel_name = channel.name if channel else 'Sconosciuto'
                await interaction.response.send_message(f'📢 Canale TTS attuale: {channel_name}', ephemeral=True)
            else:
                await interaction.response.send_message('❌ Nessun canale TTS impostato!', ephemeral=True)
        else:
            try:
                channel_id_int = int(channel_id)
                channel = self.bot.get_channel(channel_id_int)
                if not channel or not isinstance(channel, discord.TextChannel):
                    await interaction.response.send_message('❌ Canale testo non valido!', ephemeral=True)
                    return
                self.tts_config['channel_id'] = str(channel_id_int)
                self.save_config()
                await interaction.response.send_message(f'✅ Canale TTS impostato a {channel.name}!', ephemeral=True)
            except ValueError:
                await interaction.response.send_message('❌ ID canale non valido!', ephemeral=True)

    @slash_tts.subcommand(name='lang', description='Imposta la lingua TTS')
    @app_commands.describe(lang='Lingua: ita o ing')
    async def tts_lang(self, interaction: discord.Interaction, lang: str):
        if lang not in ['ita', 'ing']:
            await interaction.response.send_message('❌ Lingua non valida! Usa "ita" o "ing".', ephemeral=True)
            return
        self.tts_config['lang'] = lang
        self.save_config()
        await interaction.response.send_message(f'✅ Lingua TTS impostata a {lang}!', ephemeral=True)

    @slash_tts.subcommand(name='voice', description='Imposta il genere della voce TTS')
    @app_commands.describe(voice='Genere: maschio o femmina')
    async def tts_voice(self, interaction: discord.Interaction, voice: str):
        if voice not in ['maschio', 'femmina']:
            await interaction.response.send_message('❌ Voce non valida! Usa "maschio" o "femmina".', ephemeral=True)
            return
        self.tts_config['voice'] = voice
        self.save_config()
        await interaction.response.send_message(f'✅ Voce TTS impostata a {voice}!', ephemeral=True)

async def setup(bot):
    await bot.add_cog(TTSCog(bot))
