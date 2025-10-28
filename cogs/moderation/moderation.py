import discord
from discord.ext import commands
import json
import os
import datetime
import re
import time
import asyncio
import requests
from discord import app_commands
from bot_utils import OWNER_ID, owner_or_has_permissions, is_owner
from console_logger import logger

BASE_DIR = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(BASE_DIR)), 'config.json')
MOD_JSON = os.path.join(BASE_DIR, 'moderation.json')
WARNS_JSON = os.path.join(BASE_DIR, 'warns.json')
USER_WORDS_JSON = os.path.join(BASE_DIR, 'user_words.json')
AI_MOD_JSON = os.path.join(BASE_DIR, 'ai_moderation.json')

class ModerationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        # Load moderation.json (fall back to root if migrating)
        if os.path.exists(MOD_JSON):
            with open(MOD_JSON, 'r', encoding='utf-8') as f:
                self.moderation_words = json.load(f)
        elif os.path.exists('moderation.json'):
            with open('moderation.json', 'r', encoding='utf-8') as f:
                self.moderation_words = json.load(f)
            try:
                with open(MOD_JSON, 'w', encoding='utf-8') as f:
                    json.dump(self.moderation_words, f, indent=2, ensure_ascii=False)
            except Exception:
                pass
        else:
            self.moderation_words = {}

        # Load warns
        self.warns_data = {"next_id": 1, "warns": {}}
        if os.path.exists(WARNS_JSON):
            with open(WARNS_JSON, 'r', encoding='utf-8') as f:
                self.warns_data = json.load(f)
        elif os.path.exists('warns.json'):
            with open('warns.json', 'r', encoding='utf-8') as f:
                self.warns_data = json.load(f)
            try:
                with open(WARNS_JSON, 'w', encoding='utf-8') as f:
                    json.dump(self.warns_data, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

        # Load user words
        self.user_words = {}
        if os.path.exists(USER_WORDS_JSON):
            with open(USER_WORDS_JSON, 'r', encoding='utf-8') as f:
                self.user_words = json.load(f)
        elif os.path.exists('user_words.json'):
            with open('user_words.json', 'r', encoding='utf-8') as f:
                self.user_words = json.load(f)
            try:
                with open(USER_WORDS_JSON, 'w', encoding='utf-8') as f:
                    json.dump(self.user_words, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

        # AI moderation state
        self.ai_state = {"ai_strikes": {}}
        if os.path.exists(AI_MOD_JSON):
            try:
                with open(AI_MOD_JSON, 'r', encoding='utf-8') as f:
                    self.ai_state = json.load(f)
            except Exception:
                self.ai_state = {"ai_strikes": {}}

        # AI configuration defaults (can be overridden by config.json > moderation > ai)
        ai_cfg = (self.config.get('moderation', {}) or {}).get('ai', {}) or {}
        self.ai_enabled = ai_cfg.get('enabled', True)
        self.ai_provider = ai_cfg.get('provider', 'openai')
        self.ai_model = ai_cfg.get('model', 'omni-moderation-latest')
        self.ai_timeout = int(ai_cfg.get('timeout_ms', 5000)) / 1000.0
        self.ai_max_chars = int(ai_cfg.get('max_message_chars', 1200))
        self.ai_timeout_minutes = int(ai_cfg.get('timeout_minutes', 30))
        self.ai_escalate_after = int(ai_cfg.get('escalate_after', 2))  # strikes before timeout
        self.ai_window_sec = int(ai_cfg.get('strike_window_sec', 1800))  # rolling window
        # Perspective API specific (defaults suitable for italiano)
        self.perspective_requested_attributes = ai_cfg.get('requested_attributes', [
            'TOXICITY', 'INSULT', 'THREAT', 'PROFANITY', 'SEXUALLY_EXPLICIT', 'IDENTITY_ATTACK'
        ])
        self.perspective_language = ai_cfg.get('language', 'it')
        default_thresholds = {
            'TOXICITY': 0.80,
            'INSULT': 0.80,
            'THREAT': 0.70,
            'PROFANITY': 0.85,
            'SEXUALLY_EXPLICIT': 0.85,
            'IDENTITY_ATTACK': 0.70
        }
        th = ai_cfg.get('thresholds', default_thresholds)
        # ensure floats
        self.perspective_thresholds = {k: float(th.get(k, default_thresholds.get(k, 0.8))) for k in set(list(default_thresholds.keys()) + list(th.keys()))}

    def save_warns(self):
        with open(WARNS_JSON, 'w', encoding='utf-8') as f:
            json.dump(self.warns_data, f, indent=2, ensure_ascii=False)

    def save_user_words(self):
        with open(USER_WORDS_JSON, 'w', encoding='utf-8') as f:
            json.dump(self.user_words, f, indent=2, ensure_ascii=False)

    def save_ai_state(self):
        try:
            with open(AI_MOD_JSON, 'w', encoding='utf-8') as f:
                json.dump(self.ai_state, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _record_ai_strike(self, user_id: int):
        now = int(time.time())
        sid = str(user_id)
        bucket = self.ai_state.setdefault('ai_strikes', {}).setdefault(sid, [])
        bucket.append(now)
        # prune old
        cutoff = now - self.ai_window_sec
        self.ai_state['ai_strikes'][sid] = [t for t in bucket if t >= cutoff]
        self.save_ai_state()

    def _recent_ai_strikes(self, user_id: int) -> int:
        now = int(time.time())
        sid = str(user_id)
        bucket = self.ai_state.get('ai_strikes', {}).get(sid, [])
        cutoff = now - self.ai_window_sec
        return len([t for t in bucket if t >= cutoff])

    async def ai_moderate_message(self, message) -> dict:
        if not self.ai_enabled:
            return {"ok": False, "flagged": False}
        text = (message.content or '').strip()
        if not text:
            return {"ok": True, "flagged": False}
        if len(text) > self.ai_max_chars:
            text = text[: self.ai_max_chars]

        loop = asyncio.get_event_loop()

        # Provider: Google Perspective API
        if str(self.ai_provider).lower() in ("perspective", "google", "google_perspective"):
            api_key = os.getenv('PERSPECTIVE_API_KEY')
            if not api_key:
                logger.warning("AI moderation (Perspective) attiva ma PERSPECTIVE_API_KEY non configurata nell'ambiente")
                return {"ok": False, "flagged": False}
            url = f'https://commentanalyzer.googleapis.com/v1alpha1/comments:analyze?key={api_key}'
            headers = {
                'Content-Type': 'application/json'
            }
            requested = {attr: {} for attr in self.perspective_requested_attributes}
            payload = {
                'comment': {'text': text},
                'languages': [self.perspective_language],
                'requestedAttributes': requested,
                'doNotStore': True
            }
            try:
                def do_request():
                    return requests.post(url, headers=headers, json=payload, timeout=self.ai_timeout)
                resp = await loop.run_in_executor(None, do_request)
                if resp.status_code != 200:
                    logger.error(f'Perspective API error: {resp.status_code} {resp.text[:200]}')
                    return {"ok": False, "flagged": False}
                data = resp.json()
                attr_scores = data.get('attributeScores', {}) or {}
                categories_bool = {}
                any_flagged = False
                for attr, conf in attr_scores.items():
                    score = None
                    try:
                        score = float(((conf or {}).get('summaryScore') or {}).get('value'))
                    except Exception:
                        score = None
                    thr = float(self.perspective_thresholds.get(attr, 0.8))
                    is_flagged = (score is not None) and (score >= thr)
                    categories_bool[attr] = is_flagged
                    if is_flagged:
                        any_flagged = True
                return {"ok": True, "flagged": any_flagged, "categories": categories_bool}
            except Exception as e:
                logger.error(f'Perspective moderation exception: {e}')
                return {"ok": False, "flagged": False}

        # Fallback provider: OpenAI Moderations (legacy)
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            logger.warning('AI moderation attiva ma OPENAI_API_KEY non configurata nell\'ambiente')
            return {"ok": False, "flagged": False}
        url = 'https://api.openai.com/v1/moderations'
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        payload = {
            'model': self.ai_model,
            'input': text,
        }
        try:
            def do_request():
                return requests.post(url, headers=headers, json=payload, timeout=self.ai_timeout)
            resp = await loop.run_in_executor(None, do_request)
            if resp.status_code != 200:
                logger.error(f'AI moderation API error: {resp.status_code} {resp.text[:200]}')
                return {"ok": False, "flagged": False}
            data = resp.json()
            result = (data.get('results') or [{}])[0]
            flagged = bool(result.get('flagged'))
            categories = result.get('categories') or {}
            return {"ok": True, "flagged": flagged, "categories": categories}
        except Exception as e:
            logger.error(f'AI moderation exception: {e}')
            return {"ok": False, "flagged": False}

    def reload_mod(self):
        with open(MOD_JSON, 'r', encoding='utf-8') as f:
            self.moderation_words = json.load(f)
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            self.config = json.load(f)

    def reload_config(self):
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        # refresh AI config from file
        ai_cfg = (self.config.get('moderation', {}) or {}).get('ai', {}) or {}
        self.ai_enabled = ai_cfg.get('enabled', self.ai_enabled)
        self.ai_provider = ai_cfg.get('provider', self.ai_provider)
        self.ai_model = ai_cfg.get('model', self.ai_model)
        self.ai_timeout = int(ai_cfg.get('timeout_ms', int(self.ai_timeout * 1000))) / 1000.0
        self.ai_max_chars = int(ai_cfg.get('max_message_chars', self.ai_max_chars))
        self.ai_timeout_minutes = int(ai_cfg.get('timeout_minutes', self.ai_timeout_minutes))
        self.ai_escalate_after = int(ai_cfg.get('escalate_after', self.ai_escalate_after))
        self.ai_window_sec = int(ai_cfg.get('strike_window_sec', self.ai_window_sec))
        # Perspective fields
        self.perspective_requested_attributes = ai_cfg.get('requested_attributes', self.perspective_requested_attributes)
        self.perspective_language = ai_cfg.get('language', self.perspective_language)
        th = ai_cfg.get('thresholds', self.perspective_thresholds)
        if isinstance(th, dict):
            # merge with existing thresholds; cast to float
            merged = dict(self.perspective_thresholds)
            for k, v in th.items():
                try:
                    merged[k] = float(v)
                except Exception:
                    pass
            self.perspective_thresholds = merged

    def get_user_warns(self, user_id):
        return [w for w in self.warns_data["warns"].values() if w["user_id"] == str(user_id)]

    async def send_dm(self, member, sanction_type, **kwargs):
        try:
            dm_messages = self.moderation_words.get('dm_messages', {})
            config = dm_messages.get(sanction_type, {})
            if config:
                embed = discord.Embed(
                    title=config.get("title", "Sanzione"),
                    description=config.get("description", ""),
                    color=config.get("color", 0xff0000)
                )
                embed.set_thumbnail(url=config.get("thumbnail"))
                embed.set_footer(text=config.get("footer"))
                description = embed.description
                description = description.replace("{reason}", kwargs.get("reason", "N/A"))
                description = description.replace("{staffer}", kwargs.get("staffer", "N/A"))
                description = description.replace("{time}", kwargs.get("time", "N/A"))
                description = description.replace("{duration}", kwargs.get("duration", "N/A"))
                description = description.replace("{total_warns}", str(kwargs.get("total_warns", 0)))
                description = description.replace("{mention}", member.mention)
                description = description.replace("{word}", kwargs.get("word", "N/A"))
                embed.description = description
                await member.send(embed=embed)
        except discord.Forbidden:
            pass

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        staff_role_id = self.config.get('moderation', {}).get('staff_role_id')
        if staff_role_id and any(role.id == int(staff_role_id) for role in message.author.roles):
            return

        no_automod = self.config.get('moderation', {}).get('no_automod')
        if no_automod:
            exempt_ids = []
            if isinstance(no_automod, list):
                for v in no_automod:
                    try:
                        exempt_ids.append(int(v))
                    except Exception:
                        continue
            else:
                for part in str(no_automod).split(','):
                    s = part.strip()
                    if s.isdigit():
                        exempt_ids.append(int(s))

            if exempt_ids and any(role.id in exempt_ids for role in message.author.roles):
                return

        # AI AutoModerazione (Italiano)
        if self.ai_enabled and message.content and not message.author.is_timed_out():
            ai_res = await self.ai_moderate_message(message)
            if ai_res.get('ok') and ai_res.get('flagged'):
                try:
                    await message.delete()
                except Exception:
                    pass
                # registra strike ed escalazione
                self._record_ai_strike(message.author.id)
                strikes = self._recent_ai_strikes(message.author.id)
                categories = ai_res.get('categories') or {}
                cat_list = [k for k, v in categories.items() if v]
                motivo = f"Contenuto inappropriato rilevato dall'AI ({', '.join(cat_list) or 'violazione'})."
                try:
                    if strikes > self.ai_escalate_after:
                        delta = datetime.timedelta(minutes=self.ai_timeout_minutes)
                        try:
                            await message.author.timeout(delta, reason=motivo)
                        except Exception:
                            pass
                        await self.send_dm(message.author, "mute", reason=motivo, staffer="Sistema", time=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), duration=f"{self.ai_timeout_minutes}m")
                        await message.channel.send(f"{message.author.mention} è stato mutato automaticamente per {self.ai_timeout_minutes} minuti.")
                        logger.warning(f"AI auto-mute: {message.author} per {self.ai_timeout_minutes}m - {motivo}")
                        log_cog = self.bot.get_cog('LogCog')
                        if log_cog:
                            await log_cog.log_automod_mute(message.author, f"{self.ai_timeout_minutes}m", motivo)
                    else:
                        # solo avviso
                        await self.send_dm(message.author, "word_warning", word="contenuto inappropriato")
                        await message.channel.send(f"{message.author.mention} ha ricevuto un avviso: {motivo}")
                        logger.info(f"AI avviso: {message.author} - {motivo}")
                        log_cog = self.bot.get_cog('LogCog')
                        if log_cog:
                            await log_cog.log_automod_warn(message.author, motivo)
                except Exception as e:
                    logger.error(f"Errore gestione AI moderazione: {e}")
                return

        content = (message.content or '').lower()
        user_id_str = str(message.author.id)
        user_words_list = self.user_words.get(user_id_str, [])

        for duration, words in self.moderation_words.items():
            if isinstance(words, list):
                for word in words:
                    if word.lower() in content:
                        if message.author.is_timed_out():
                            return

                        if duration.endswith('h'):
                            hours = int(duration[:-1])
                            delta = datetime.timedelta(hours=hours)
                        elif duration.endswith('d'):
                            days = int(duration[:-1])
                            delta = datetime.timedelta(days=days)
                        elif duration.endswith('m'):
                            minutes = int(duration[:-1])
                            delta = datetime.timedelta(minutes=minutes)
                        elif duration.endswith('s'):
                            seconds = int(duration[:-1])
                            delta = datetime.timedelta(seconds=seconds)
                        else:
                            delta = datetime.timedelta(days=20)

                        try:
                            await message.delete()
                            if word.lower() in [w.lower() for w in user_words_list]:
                                await message.author.timeout(delta, reason=f'Auto-mute per parola vietata ripetuta: {word}')
                                await message.channel.send(f'{message.author.mention} è stato mutato automaticamente per {duration} a causa di una parola vietata ripetuta.')
                                await self.send_dm(message.author, "mute", reason=f'Auto-mute per parola vietata ripetuta: {word}', staffer="Sistema", time=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), duration=duration)
                                logger.warning(f'Auto-mute ripetuto: {message.author.name}#{message.author.discriminator} ({message.author.id}) mutato per {duration} - parola: {word}')
                                log_cog = self.bot.get_cog('LogCog')
                                if log_cog:
                                    await log_cog.log_automod_mute(message.author, duration, f'Auto-mute per parola vietata ripetuta: {word}')
                            else:
                                await self.send_dm(message.author, "word_warning", word=word)
                                if user_id_str not in self.user_words:
                                    self.user_words[user_id_str] = []
                                self.user_words[user_id_str].append(word.lower())
                                await message.channel.send(f'{message.author.mention} ha ricevuto un avviso per una parola vietata. Non ripeterla!')
                                logger.info(f'Avviso parola vietata: {message.author.name}#{message.author.discriminator} ({message.author.id}) - parola: {word}')
                                log_cog = self.bot.get_cog('LogCog')
                                if log_cog:
                                    await log_cog.log_automod_warn(message.author, word)
                        except Exception as e:
                            logger.error(f"Errore nell'automod parola vietata: {e}")
                        self.save_user_words()
                        return

        if 'discord.gg' in content:
            if message.author.is_timed_out():
                return

            try:
                await message.delete()
                await message.author.timeout(datetime.timedelta(days=1), reason="Spam Link")
                await message.channel.send(f'{message.author.mention} è stato mutato automaticamente per 1 giorno a causa di un link invito Discord.')
                await self.send_dm(message.author, "mute", reason="Spam Link", staffer="Sistema", time=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), duration="1d")
                logger.warning(f'Auto-mute link Discord: {message.author.name}#{message.author.discriminator} ({message.author.id}) mutato per 1 giorno')
                log_cog = self.bot.get_cog('LogCog')
                if log_cog:
                    await log_cog.log_automod_mute(message.author, "1d", "Spam Link")
            except Exception as e:
                logger.error(f"Errore nell'automod link Discord: {e}")
            return

    # Commands below are unchanged; keeping definitions identical
    @commands.command(name='ban')
    @owner_or_has_permissions(kick_members=True, ban_members=True)
    async def ban(self, ctx, member: discord.Member, *, reason="Nessuna ragione specificata"):
        try:
            await member.ban(reason=reason)
            await ctx.send(f'✅ {member.mention} è stato bannato. Motivo: {reason}')
            await self.send_dm(member, "ban", reason=reason, staffer=str(ctx.author), time=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), duration="permanente")
        except Exception as e:
            await ctx.send(f"❌ Errore nel ban: {e}")

    @app_commands.command(name='ban', description='Banna un utente dal server')
    @owner_or_has_permissions(kick_members=True, ban_members=True)
    async def slash_ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Nessuna ragione specificata"):
        try:
            await member.ban(reason=reason)
            await interaction.response.send_message(f'✅ {member.mention} è stato bannato. Motivo: {reason}')
            await self.send_dm(member, "ban", reason=reason, staffer=str(interaction.user), time=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), duration="permanente")
        except Exception as e:
            await interaction.response.send_message(f"❌ Errore nel ban: {e}", ephemeral=True)

    @commands.command(name='kick')
    @owner_or_has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason="Nessuna ragione specificata"):
        try:
            await member.kick(reason=reason)
            await ctx.send(f'✅ {member.mention} è stato kickato. Motivo: {reason}')
            await self.send_dm(member, "kick", reason=reason, staffer=str(ctx.author), time=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), duration="N/A")
        except Exception as e:
            await ctx.send(f"❌ Errore nel kick: {e}")

    @app_commands.command(name='kick', description='Kicka un utente dal server')
    @owner_or_has_permissions(kick_members=True)
    async def slash_kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Nessuna ragione specificata"):
        try:
            await member.kick(reason=reason)
            await interaction.response.send_message(f'✅ {member.mention} è stato kickato. Motivo: {reason}')
            await self.send_dm(member, "kick", reason=reason, staffer=str(interaction.user), time=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), duration="N/A")
        except Exception as e:
            await interaction.response.send_message(f"❌ Errore nel kick: {e}", ephemeral=True)

    # ... The rest of commands are same as original file ...

    @app_commands.command(name='mute', description='Muta (timeout) un utente per una durata')
    @owner_or_has_permissions(moderate_members=True)
    @app_commands.describe(member='Utente da mutare', duration='Durata (es: 10m, 2h, 1d)', reason='Motivo (opzionale)')
    async def slash_mute(self, interaction: discord.Interaction, member: discord.Member, duration: str, reason: str = "Auto-moderazione"):
        try:
            if member.id == interaction.user.id:
                await interaction.response.send_message('❌ Non puoi mutare te stesso.', ephemeral=True)
                return
            dur = duration.strip().lower()
            delta = None
            try:
                if dur.endswith('h'):
                    delta = datetime.timedelta(hours=int(dur[:-1]))
                elif dur.endswith('d'):
                    delta = datetime.timedelta(days=int(dur[:-1]))
                elif dur.endswith('m'):
                    delta = datetime.timedelta(minutes=int(dur[:-1]))
                elif dur.endswith('s'):
                    delta = datetime.timedelta(seconds=int(dur[:-1]))
                else:
                    delta = datetime.timedelta(minutes=int(dur))
            except Exception:
                await interaction.response.send_message('❌ Durata non valida. Usa s/m/h/d o minuti interi.', ephemeral=True)
                return
            await member.timeout(delta, reason=reason)
            await interaction.response.send_message(f'✅ {member.mention} mutato per {duration}.', ephemeral=True)
            await self.send_dm(member, "mute", reason=reason, staffer=str(interaction.user), time=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), duration=duration)
        except Exception as e:
            await interaction.response.send_message(f'❌ Errore nel mute: {e}', ephemeral=True)

    @app_commands.command(name='unmute', description='Rimuove il mute (timeout) da un utente')
    @owner_or_has_permissions(moderate_members=True)
    @app_commands.describe(member='Utente da smutare', reason='Motivo (opzionale)')
    async def slash_unmute(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Fine mute"):
        try:
            await member.timeout(None, reason=reason)
            await interaction.response.send_message(f'✅ {member.mention} è stato smutato.', ephemeral=True)
            await self.send_dm(member, "unmute", reason=reason, staffer=str(interaction.user), time=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), duration="0")
        except Exception as e:
            await interaction.response.send_message(f'❌ Errore nell\'unmute: {e}', ephemeral=True)

    @app_commands.command(name='warn', description='Aggiunge un warn a un utente')
    @owner_or_has_permissions(kick_members=True)
    @app_commands.describe(member='Utente da warnare', reason='Motivo del warn')
    async def slash_warn(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        try:
            warn_id = self.warns_data.get("next_id", 1)
            self.warns_data["next_id"] = warn_id + 1
            self.warns_data["warns"][str(warn_id)] = {
                "user_id": str(member.id),
                "moderator_id": str(interaction.user.id),
                "reason": reason,
                "time": datetime.datetime.utcnow().isoformat()
            }
            self.save_warns()
            await interaction.response.send_message(f'⚠️ Warn {warn_id} assegnato a {member.mention}: {reason}', ephemeral=False)
            await self.send_dm(member, "warn", reason=reason, staffer=str(interaction.user), time=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), total_warns=len(self.get_user_warns(member.id)))
        except Exception as e:
            await interaction.response.send_message(f'❌ Errore nel warn: {e}', ephemeral=True)

    @app_commands.command(name='unwarn', description='Rimuove un warn tramite ID')
    @owner_or_has_permissions(kick_members=True)
    @app_commands.describe(warn_id='ID del warn da rimuovere')
    async def slash_unwarn(self, interaction: discord.Interaction, warn_id: int):
        try:
            if str(warn_id) in self.warns_data["warns"]:
                del self.warns_data["warns"][str(warn_id)]
                self.save_warns()
                await interaction.response.send_message(f'✅ Warn {warn_id} rimosso.', ephemeral=True)
            else:
                await interaction.response.send_message('❌ Warn non trovato.', ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f'❌ Errore nell\'unwarn: {e}', ephemeral=True)

    @app_commands.command(name='listwarns', description='Mostra i warn di un utente')
    @owner_or_has_permissions(kick_members=True)
    @app_commands.describe(member='Utente di cui visualizzare i warn')
    async def slash_listwarns(self, interaction: discord.Interaction, member: discord.Member):
        try:
            warns = [(wid, w) for wid, w in self.warns_data.get("warns", {}).items() if w.get("user_id") == str(member.id)]
            if not warns:
                await interaction.response.send_message(f'ℹ️ Nessun warn per {member.mention}.', ephemeral=True)
                return
            lines = [f"`#{wid}` • {w.get('reason','N/A')} • <@{w.get('moderator_id')}> • {w.get('time','')}" for wid, w in warns]
            embed = discord.Embed(title=f'Warns di {member}', description='\n'.join(lines), color=0xFFA500)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f'❌ Errore nel listwarns: {e}', ephemeral=True)

    @app_commands.command(name='clearwarns', description='Rimuove tutti i warn di un utente')
    @owner_or_has_permissions(administrator=True)
    @app_commands.describe(member='Utente per cui cancellare i warn')
    async def slash_clearwarns(self, interaction: discord.Interaction, member: discord.Member):
        try:
            to_delete = [wid for wid, w in self.warns_data.get("warns", {}).items() if w.get("user_id") == str(member.id)]
            for wid in to_delete:
                del self.warns_data["warns"][wid]
            self.save_warns()
            await interaction.response.send_message(f'✅ Rimossi {len(to_delete)} warn per {member.mention}.', ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f'❌ Errore nel clearwarns: {e}', ephemeral=True)

    @app_commands.command(name='listban', description='Mostra la lista dei ban del server')
    @owner_or_has_permissions(ban_members=True)
    async def slash_listban(self, interaction: discord.Interaction):
        try:
            bans = await interaction.guild.bans()
            if not bans:
                await interaction.response.send_message('ℹ️ Nessun utente bannato.', ephemeral=True)
                return
            lines = [f"{entry.user} (ID: {entry.user.id})" for entry in bans][:25]
            embed = discord.Embed(title='Utenti bannati', description='\n'.join(lines), color=0xFF0000)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f'❌ Errore nel listban: {e}', ephemeral=True)

    @app_commands.command(name='checkban', description='Controlla se un utente è bannato')
    @owner_or_has_permissions(ban_members=True)
    @app_commands.describe(user_id='ID utente da controllare')
    async def slash_checkban(self, interaction: discord.Interaction, user_id: str):
        try:
            uid = int(user_id)
            bans = await interaction.guild.bans()
            banned = any(entry.user.id == uid for entry in bans)
            await interaction.response.send_message('✅ L\'utente è bannato.' if banned else '❌ L\'utente non è bannato.', ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f'❌ Errore nel checkban: {e}', ephemeral=True)

    @app_commands.command(name='unban', description='Sbanna un utente tramite ID')
    @owner_or_has_permissions(ban_members=True)
    @app_commands.describe(user_id='ID utente da sbannare', reason='Motivo (opzionale)')
    async def slash_unban(self, interaction: discord.Interaction, user_id: str, reason: str = "Unban"):
        try:
            uid = int(user_id)
            user = await self.bot.fetch_user(uid)
            await interaction.guild.unban(user, reason=reason)
            await interaction.response.send_message(f'✅ Utente {user} sbannato.', ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f'❌ Errore nell\'unban: {e}', ephemeral=True)

    @app_commands.command(name='checkmute', description='Controlla se un utente è mutato (timeout attivo)')
    @owner_or_has_permissions(moderate_members=True)
    @app_commands.describe(member='Utente da controllare')
    async def slash_checkmute(self, interaction: discord.Interaction, member: discord.Member):
        try:
            if member.is_timed_out():
                await interaction.response.send_message('✅ L\'utente è attualmente mutato.', ephemeral=True)
            else:
                await interaction.response.send_message('❌ L\'utente non è mutato.', ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f'❌ Errore nel checkmute: {e}', ephemeral=True)

    @app_commands.command(name='nick', description='Imposta il nickname di un utente')
    @owner_or_has_permissions(manage_nicknames=True)
    @app_commands.describe(member='Utente', nickname='Nuovo nickname')
    async def slash_nick(self, interaction: discord.Interaction, member: discord.Member, nickname: str):
        try:
            await member.edit(nick=nickname)
            await interaction.response.send_message(f'✅ Nickname di {member.mention} impostato a "{nickname}".', ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f'❌ Errore nella modifica nickname: {e}', ephemeral=True)

    @app_commands.command(name='reloadmod', description='Ricarica la configurazione di moderazione')
    @owner_or_has_permissions(administrator=True)
    async def slash_reloadmod(self, interaction: discord.Interaction):
        try:
            self.reload_mod()
            await interaction.response.send_message('✅ Configurazione di moderazione ricaricata.', ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f'❌ Errore nel reloadmod: {e}', ephemeral=True)

async def setup(bot):
    await bot.add_cog(ModerationCog(bot))
