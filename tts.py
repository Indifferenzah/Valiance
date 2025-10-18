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
from loguru import logger
from dotenv import load_dotenv
import json
import ffmpeg

load_dotenv()

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

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
            logger.info(f"Voice cache initialized with {len(self.voice_manager.voice_cache)} voices")
        except Exception as e:
            logger.error(f"Failed to fetch voices on startup: {e}")
        self.update_voice_cache.start()

    def load_config(self):
        try:
            with open('tts.json', 'r', encoding='utf-8') as f:
                self.tts_config = json.load(f)
        except FileNotFoundError:
            self.tts_config = {"channel_id": None, "lang": "ita", "voice": "maschio", "xsaid": False}
            with open('tts.json', 'w', encoding='utf-8') as f:
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
            logger.info("No more audio in the queue.")

    @app_commands.command(name='say', description='Plays a text-to-speech response from Eleven Labs')
    @app_commands.describe(text='The text to be spoken')
    async def say(self, interaction: discord.Interaction, text: str):
        if interaction.response.is_done():
            logger.warning(f"Interaction {interaction.id} already acknowledged")
            return

        try:
            await interaction.response.defer(thinking=True)
        except discord.NotFound:
            logger.warning(f"Interaction {interaction.id} expired before defer")
            return
        except discord.HTTPException as e:
            if e.code == 40060:  # Interaction already acknowledged
                logger.warning(f"Interaction {interaction.id} already acknowledged")
                return
            logger.exception(f"Error deferring interaction: {e}")
            return
        except Exception as e:
            logger.exception(f"Error deferring interaction: {e}")
            return

        try:
            if len(text) > 100:
                await interaction.followup.send(f'Max 100 chars. Your text is too long ({len(text)} chars).', ephemeral=True)
                return

            await self.ensure_voice_connection(interaction)
            voice = self.voice_manager.user_voices.get(interaction.user.global_name, None)
            if voice is None:
                if not self.voice_manager.voice_cache:
                    await interaction.followup.send("Voice cache is empty. Please try again in a moment.", ephemeral=True)
                    return
                voice = random.choice(self.voice_manager.voice_cache)
            audio_stream = self.voice_manager.fetch_audio_stream(text, voice['voice_id'])

            if audio_stream:
                self.audio_queue.append(audio_stream)
                if not interaction.guild.voice_client.is_playing():
                    self.play_next_audio(interaction)
                await interaction.followup.send("Message queued", ephemeral=True)
            else:
                await interaction.followup.send("Failed to generate audio stream.", ephemeral=True)
        except Exception as e:
            logger.exception(e)
            try:
                await interaction.followup.send("An error occurred while processing your request.", ephemeral=True)
            except:
                pass

    async def ensure_voice_connection(self, interaction: discord.Interaction):
        if interaction.user.voice:
            channel = interaction.user.voice.channel
            if interaction.guild.voice_client is None or not interaction.guild.voice_client.is_connected():
                await channel.connect()
            elif interaction.guild.voice_client.channel != channel:
                await interaction.guild.voice_client.move_to(channel)
        else:
            await interaction.followup.send('You are not in a voice channel.', ephemeral=True)

    @app_commands.command(name='voice', description="Set user's voice")
    @app_commands.describe(voice='The voice to set')
    async def voice(self, interaction: discord.Interaction, voice: str):
        await interaction.response.defer()
        global_name = str(interaction.user.global_name)
        selected_voice = next((v for v in self.voice_manager.voice_cache if v['name'].lower() == voice.lower()), None)
        if not selected_voice:
            await interaction.followup.send('No voice found.', ephemeral=True)
            return
        self.voice_manager.user_voices[global_name] = selected_voice
        await interaction.followup.send(f"Voice set to {selected_voice['name']}", ephemeral=True)

    @voice.autocomplete('voice')
    async def voices_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        voices_name = [voice["name"] for voice in self.voice_manager.voice_cache if voice["category"] == "cloned"]

        return [
            app_commands.Choice(name=voice_name, value=voice_name)
            for voice_name in voices_name if current.lower() in voice_name.lower()
        ]

    @app_commands.command(name='volume', description='Changes the bot volume')
    @app_commands.describe(volume='The volume level (0-100)')
    async def volume(self, interaction: discord.Interaction, volume: int):
        if interaction.guild.voice_client is None:
            await interaction.response.send_message("Not connected to a voice channel.")
            return

        interaction.guild.voice_client.source.volume = volume / 100
        await interaction.response.send_message(f"Changed volume to {volume}%")

    @app_commands.command(name='stop', description='Stops and disconnects the bot from voice channel')
    async def stop(self, interaction: discord.Interaction):
        if interaction.guild.voice_client and interaction.guild.voice_client.channel:
            await interaction.guild.voice_client.disconnect(force=True)
            await interaction.response.send_message("Disconnected from the voice channel.")
        else:
            await interaction.response.send_message("Not connected to a voice channel.")


async def setup(bot):
    await bot.add_cog(TTSCog(bot))
