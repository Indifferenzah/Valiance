import asyncio
import io
import os
from collections import deque
from typing import List
import random
import requests
import discord
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv
import json
import ffmpeg

from console_logger import logger

load_dotenv()

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

BASE_DIR = os.path.dirname(__file__)
TTS_JSON = os.path.join(BASE_DIR, 'tts.json')

class VoiceManager:
    """Manages voice-related operations."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.voice_cache = []
        self.user_voices = {}
        self.session = requests.Session()

    def fetch_voices(self):
        url = "https://api.elevenlabs.io/v1/voices"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json"
        }
        response = self.session.get(url, headers=headers)
        response.raise_for_status()
        self.voice_cache = response.json().get('voices', [])

    def find_voice_by_name(self, name: str):
        return next((voice for voice in self.voice_cache if voice["name"] == name), None)

    def fetch_audio_stream(self, text: str, voice_id: str):
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
        params = {
            "optimize_streaming_latency": 1
        }
        payload = {
            "model_id": "eleven_multilingual_v2",
            "text": text,
            "voice_settings": {
                "stability": 1,
                "similarity_boost": 0.8,
                "style": 0.5,
                "use_speaker_boost": True
            }
        }
        headers = {
            "xi-api-key": ELEVENLABS_API_KEY,
            "Content-Type": "application/json"
        }

        try:
            response = self.session.post(url, params=params, headers=headers, json=payload, stream=True)
            response.raise_for_status()
            return io.BytesIO(response.content)
        except requests.RequestException as e:
            logger.error(f"Error fetching audio stream: {e}")
            return None


class TTSCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.voice_manager = VoiceManager(api_key=ELEVENLABS_API_KEY)
        self.audio_queue = deque()
        self.tts_config = {}
        self.load_config()
        # Fetch voices immediately on startup
        try:
            self.voice_manager.fetch_voices()
            logger.tts(f"Voice cache initialized with {len(self.voice_manager.voice_cache)} voices")
        except Exception as e:
            logger.error(f"Failed to fetch voices on startup: {e}")
        self.update_voice_cache.start()

    def load_config(self):
        try:
            if os.path.exists(TTS_JSON):
                with open(TTS_JSON, 'r', encoding='utf-8') as f:
                    self.tts_config = json.load(f)
            elif os.path.exists('tts.json'):
                with open('tts.json', 'r', encoding='utf-8') as f:
                    self.tts_config = json.load(f)
                try:
                    with open(TTS_JSON, 'w', encoding='utf-8') as f:
                        json.dump(self.tts_config, f, indent=2, ensure_ascii=False)
                except Exception:
                    pass
            else:
                self.tts_config = {"channel_id": None, "lang": "ita", "voice": "maschio", "xsaid": False}
                with open(TTS_JSON, 'w', encoding='utf-8') as f:
                    json.dump(self.tts_config, f, indent=2, ensure_ascii=False)
        except FileNotFoundError:
            self.tts_config = {"channel_id": None, "lang": "ita", "voice": "maschio", "xsaid": False}
            with open(TTS_JSON, 'w', encoding='utf-8') as f:
                json.dump(self.tts_config, f, indent=2, ensure_ascii=False)

    @tasks.loop(minutes=2)
    async def update_voice_cache(self):
        try:
            self.voice_manager.fetch_voices()
        except requests.RequestException as e:
            logger.error(f"Error updating voice cache: {e}")

    def play_next_audio(self, interaction: discord.Interaction, error=None):
        if error:
            logger.error(f'Player error: {error}')
        if self.audio_queue:
            audio_stream = self.audio_queue.popleft()
            audio_stream.seek(0)  # Ensure the stream is at the start
            source = discord.FFmpegPCMAudio(audio_stream, pipe=True)
            interaction.guild.voice_client.play(source, after=lambda e: self.play_next_audio(interaction, e))
        else:
            try:
                if interaction.guild.voice_client:
                    asyncio.create_task(interaction.guild.voice_client.disconnect())
            except Exception:
                pass

    @app_commands.command(name='say', description='Text-to-Speech nel canale vocale')
    async def say(self, interaction: discord.Interaction, text: str):
        try:
            await self.ensure_voice_connection(interaction)
            default_voice_name = self.tts_config.get('voice_name')
            selected_voice = self.voice_manager.find_voice_by_name(default_voice_name) if default_voice_name else None
            if not selected_voice:
                if not self.voice_manager.voice_cache:
                    try:
                        self.voice_manager.fetch_voices()
                    except Exception:
                        pass
                selected_voice = random.choice(self.voice_manager.voice_cache) if self.voice_manager.voice_cache else None
            if not selected_voice:
                await interaction.response.send_message('❌ Nessuna voce disponibile al momento.', ephemeral=True)
                return

            voice_id = selected_voice.get('voice_id') or selected_voice.get('id')
            audio_stream = self.voice_manager.fetch_audio_stream(text, voice_id)
            if not audio_stream:
                await interaction.response.send_message('❌ Errore nella generazione dell\'audio.', ephemeral=True)
                return

            await interaction.response.send_message('🔊 Sto parlando...', ephemeral=True)

            self.audio_queue.append(audio_stream)
            if not interaction.guild.voice_client.is_playing():
                self.play_next_audio(interaction)
        except Exception as e:
            await interaction.response.send_message(f'❌ Errore TTS: {e}', ephemeral=True)

    async def ensure_voice_connection(self, interaction: discord.Interaction):
        if interaction.user.voice is None or interaction.user.voice.channel is None:
            await interaction.response.send_message('❌ Devi essere in un canale vocale.', ephemeral=True)
            raise commands.CommandError("User not in voice channel")
        channel = interaction.user.voice.channel
        vc = interaction.guild.voice_client
        if vc is None or not vc.is_connected():
            await channel.connect()
        elif vc.channel != channel:
            await vc.move_to(channel)

    @app_commands.command(name='voice', description='Seleziona la voce TTS per te')
    @app_commands.describe(voice='Nome della voce')
    async def voice(self, interaction: discord.Interaction, voice: str):
        try:
            user_id = str(interaction.user.id)
            if 'user_voices' not in self.tts_config:
                self.tts_config['user_voices'] = {}
            self.tts_config['user_voices'][user_id] = voice
            with open(TTS_JSON, 'w', encoding='utf-8') as f:
                json.dump(self.tts_config, f, indent=2, ensure_ascii=False)
            await interaction.response.send_message(f'✅ Voce impostata su {voice}', ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f'❌ Errore: {e}', ephemeral=True)

    @voice.autocomplete('voice')
    async def voices_autocomplete(self, interaction: discord.Interaction, current: str):
        try:
            if not self.voice_manager.voice_cache:
                self.voice_manager.fetch_voices()
            choices = [v['name'] for v in self.voice_manager.voice_cache if current.lower() in v['name'].lower()][:25]
            return [app_commands.Choice(name=name, value=name) for name in choices]
        except Exception:
            return []

    @app_commands.command(name='volume', description='Imposta il volume del TTS (non implementato, placeholder)')
    async def volume(self, interaction: discord.Interaction, volume: int):
        await interaction.response.send_message('🔧 Il controllo volume non è implementato in questa versione.', ephemeral=True)

    @app_commands.command(name='stop', description='Ferma il TTS e svuota la coda')
    async def stop(self, interaction: discord.Interaction):
        try:
            vc = interaction.guild.voice_client
            if vc and vc.is_playing():
                vc.stop()
            self.audio_queue.clear()
            await interaction.response.send_message('⏹️ TTS fermato.', ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f'❌ Errore: {e}', ephemeral=True)

async def setup(bot):
    await bot.add_cog(TTSCog(bot))
