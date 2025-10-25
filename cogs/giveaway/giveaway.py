import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import json
import random
from typing import Optional, List, Tuple
from datetime import datetime, timedelta, timezone
from bot_utils import OWNER_ID, owner_or_has_permissions, is_owner
from console_logger import logger

DATA_DIR = os.path.join('cogs', 'giveaway', 'data')
BLACKLIST_PATH = os.path.join('cogs', 'giveaway', 'blacklist.json')
CONFIG_PATH = os.path.join('cogs', 'giveaway', 'giveaway.json')


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _file_path(message_id: int) -> str:
    _ensure_data_dir()
    return os.path.join(DATA_DIR, f'{message_id}.json')


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utcnow_epoch() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _parse_duration(s: Optional[str]) -> Optional[int]:
    # Returns seconds from string like 1d2h30m15s
    if not s:
        return None
    total = 0
    num = ''
    units = {'d': 86400, 'h': 3600, 'm': 60, 's': 1}
    for ch in s.strip():
        if ch.isdigit():
            num += ch
        elif ch.lower() in units and num:
            total += int(num) * units[ch.lower()]
            num = ''
        else:
            # invalid char resets
            return None
    if num:
        # default seconds if trailing number
        total += int(num)
    return total if total > 0 else None


def _format_discord_time(epoch: int) -> str:
    return f"<t:{epoch}:R>"


def _render_template(template: str, prize: str, duration_text: Optional[str], expire_epoch: Optional[int], host_mention: str, winners_text: Optional[str] = None) -> str:
    if not template:
        return ''
    result = template
    result = result.replace('{prize}', prize or '')
    result = result.replace('{duration}', duration_text or '')
    result = result.replace('{expire}', _format_discord_time(expire_epoch) if expire_epoch else '')
    result = result.replace('{host}', host_mention)
    if winners_text is not None:
        result = result.replace('{winner}', winners_text)
    return result


def _load_blacklist() -> dict:
    if not os.path.exists(BLACKLIST_PATH):
        return {}
    try:
        with open(BLACKLIST_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_blacklist(data: dict):
    os.makedirs(os.path.dirname(BLACKLIST_PATH), exist_ok=True)
    with open(BLACKLIST_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _eligible_entrants(guild_id: int, entrants: List[int]) -> List[int]:
    bl = _load_blacklist()
    blocked = set(bl.get(str(guild_id), []))
    return [uid for uid in entrants if uid not in blocked]


def _default_config() -> dict:
    return {
        "embed_template": {
            "title": "🎉 {prize}",
            "description": "Host: {host}\nPremio: {prize}\nTermina {expire}",
            "thumbnail": None,
            "footer_text": "Partecipa cliccando il bottone!",
            "footer_use_server_icon": True,
            "color": "gold"
        },
        "end_message": "🎉 Giveaway terminato! Vincitore: {winner} — Premio: {prize} — Finito {expire} (Host: {host})"
    }


def _load_config() -> dict:
    try:
        if not os.path.exists(CONFIG_PATH):
            return _default_config()
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        # Merge shallow with defaults to ensure keys exist
        defaults = _default_config()
        merged = {**defaults, **cfg}
        # merge nested embed_template
        et = {**defaults.get('embed_template', {}), **(merged.get('embed_template') or {})}
        merged['embed_template'] = et
        return merged
    except Exception:
        return _default_config()


def _parse_color(value) -> Optional[discord.Color]:
    try:
        if value is None:
            return None
        if isinstance(value, int):
            return discord.Color(value)
        if isinstance(value, str):
            v = value.strip().lower()
            named = {
                'red': discord.Color.red(),
                'green': discord.Color.green(),
                'blue': discord.Color.blue(),
                'blurple': discord.Color.blurple(),
                'gold': discord.Color.gold(),
                'orange': discord.Color.orange(),
                'purple': discord.Color.purple(),
                'teal': discord.Color.teal(),
                'dark_theme': discord.Color.dark_theme()
            }
            if v in named:
                return named[v]
            if v.startswith('#'):
                v = v[1:]
            return discord.Color(int(v, 16))
    except Exception:
        return None
    return None


def owner_or_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        # Bot owner
        app = interaction.client
        try:
            app_owner_id = (await app.application_info()).owner.id if hasattr(app, 'application_id') else None
        except Exception:
            app_owner_id = None
        is_owner = (interaction.user.id == app_owner_id)
        is_admin = interaction.user.guild_permissions.administrator if interaction.guild else False
        return bool(is_owner or is_admin)
    return app_commands.check(predicate)


class GiveawayView(discord.ui.View):
    def __init__(self, cog: 'GiveawayCog', message_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.message_id = message_id

    @discord.ui.button(label='🎉 Partecipa', style=discord.ButtonStyle.green, custom_id='gw_join')
    async def join_leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            data = self.cog.load_giveaway(self.message_id)
            if data is None:
                await interaction.response.send_message('❌ Giveaway non trovato o non inizializzato.', ephemeral=True)
                return

            if data.get('status', 'active') != 'active':
                await interaction.response.send_message('⛔ Questo giveaway è terminato.', ephemeral=True)
                return

            # Blacklist check
            bl = _load_blacklist()
            guild_key = str(interaction.guild_id)
            if str(interaction.user.id) in set(map(str, bl.get(guild_key, []))):
                await interaction.response.send_message('🚫 Sei in blacklist e non puoi partecipare ai giveaway.', ephemeral=True)
                return

            user_id = interaction.user.id
            entrants = data.get('entrants', [])

            if user_id in entrants:
                entrants.remove(user_id)
                action = 'uscito dal'
                color = discord.Color.red()
            else:
                entrants.append(user_id)
                action = 'entrato nel'
                color = discord.Color.green()

            data['entrants'] = entrants
            data['updated_at'] = _utcnow_iso()
            self.cog.save_giveaway(self.message_id, data)

            # Update main message embed counter if possible
            try:
                channel = interaction.guild.get_channel(data['channel_id']) if interaction.guild else None
                if channel is None:
                    channel = await interaction.client.fetch_channel(data['channel_id'])
                msg = await channel.fetch_message(self.message_id)
                if msg and msg.embeds:
                    emb = msg.embeds[0]
                    # Rebuild embed to safely update a field
                    new_emb = discord.Embed(title=emb.title, description=emb.description, color=emb.color)
                    if emb.footer:
                        new_emb.set_footer(text=emb.footer.text, icon_url=emb.footer.icon_url)
                    if emb.image:
                        new_emb.set_image(url=emb.image.url)
                    if emb.thumbnail:
                        new_emb.set_thumbnail(url=emb.thumbnail.url)
                    for f in emb.fields:
                        if f.name.startswith('Partecipanti'):
                            continue
                        new_emb.add_field(name=f.name, value=f.value, inline=f.inline)
                    new_emb.add_field(name=f'Partecipanti ({len(entrants)})', value='Premi "Mostra iscritti" per vedere la lista', inline=False)
                    await msg.edit(embed=new_emb, view=self)
            except Exception:
                pass

            # Reply to user
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"Sei {action} giveaway. Attuali partecipanti: {len(entrants)}",
                    color=color
                ),
                ephemeral=True
            )
        except Exception as e:
            try:
                await interaction.response.send_message(f'❌ Errore: {e}', ephemeral=True)
            except Exception:
                pass

    @discord.ui.button(label='👥 Mostra iscritti', style=discord.ButtonStyle.blurple, custom_id='gw_show')
    async def show_list(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = self.cog.load_giveaway(self.message_id)
        if data is None:
            await interaction.response.send_message('❌ Giveaway non trovato o non inizializzato.', ephemeral=True)
            return
        entrants = data.get('entrants', [])
        if not entrants:
            await interaction.response.send_message('Nessun iscritto al momento.', ephemeral=True)
            return
        # Build a paginated-like plain list (up to 50 per chunk) but send once ephemeral
        mentions = []
        for uid in entrants:
            user = interaction.guild.get_member(uid) if interaction.guild else None
            mentions.append(user.mention if user else f'<@{uid}>')
        text = '\n'.join(mentions)
        if len(text) > 1900:
            # If too long, send as file
            try:
                await interaction.response.send_message(
                    content=f'Iscritti totali: {len(entrants)}',
                    file=discord.File(fp=self.cog.make_temp_file('\n'.join(mentions)), filename='iscritti.txt'),
                    ephemeral=True
                )
            finally:
                self.cog.cleanup_temp_files()
        else:
            await interaction.response.send_message(
                embed=discord.Embed(title=f'Iscritti ({len(entrants)})', description=text, color=discord.Color.blurple()),
                ephemeral=True
            )


class GiveawayCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        _ensure_data_dir()
        self._temp_files = []
        self._end_loop_started = False
        # Do NOT start the loop here: at cog setup time the client is not logged in yet.
        # The loop will be started safely in on_ready.
        logger.info('[Giveaway] Cog initialised; end checker will start on_ready')

    # Utility for ephemeral file sending
    def make_temp_file(self, content: str):
        path = os.path.join(DATA_DIR, f'_tmp_{len(self._temp_files)}.txt')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        self._temp_files.append(path)
        return path

    def cleanup_temp_files(self):
        for p in self._temp_files:
            try:
                os.remove(p)
            except Exception:
                pass
        self._temp_files.clear()

    def load_giveaway(self, message_id: int):
        path = _file_path(message_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None

    def save_giveaway(self, message_id: int, data: dict):
        path = _file_path(message_id)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _build_embed(self, guild: Optional[discord.Guild], data: dict) -> discord.Embed:
        # Build embed from global config merged with per-giveaway overrides
        cfg = _load_config()
        cfg_et = cfg.get('embed_template', {})
        data_et = data.get('embed_template', {}) or {}
        et = {**cfg_et, **data_et}  # data overrides config

        color = _parse_color(et.get('color')) or discord.Color.gold()
        emb = discord.Embed(
            title=_render_template(
                et.get('title', f"🎉 {data.get('title', 'Giveaway')}") or '',
                data.get('prize', ''), data.get('duration_text'), data.get('expire_epoch'),
                host_mention=f"<@{data.get('host')}>"
            ),
            description=_render_template(
                et.get('description', data.get('description', '')) or '',
                data.get('prize', ''), data.get('duration_text'), data.get('expire_epoch'),
                host_mention=f"<@{data.get('host')}>"
            ),
            color=color
        )
        thumb = et.get('thumbnail')
        if thumb:
            emb.set_thumbnail(url=thumb)
        footer_text = et.get('footer_text')
        footer_server_icon = et.get('footer_use_server_icon', False)
        icon_url = guild.icon.url if (footer_server_icon and guild and guild.icon) else None
        if footer_text or icon_url:
            if footer_text:
                emb.set_footer(text=footer_text, icon_url=icon_url)
            else:
                emb.set_footer(icon_url=icon_url)
        # participants field appended by caller
        return emb

    @app_commands.command(name='gwcreate', description='Crea un giveaway con pulsanti di partecipazione')
    @app_commands.describe(
        titolo='Titolo del giveaway',
        descrizione='Descrizione (può contenere variabili)',
        prize='Premio',
        duration='Durata es. 1d2h30m (alternativa a expire)',
        expire='Timestamp UNIX di scadenza (alternativa a duration)',
        number_winners='Numero vincitori',
        thumbnail='URL thumbnail (opzionale)',
        footer_text='Testo footer (opzionale)',
        footer_use_server_icon='Usa icona del server nel footer',
        end_message_template='Messaggio finale con variabili ({winner}, {prize}, {expire}, {host})'
    )
    @owner_or_has_permissions(Administrator=True)
    async def slash_gwcreate(self, interaction: discord.Interaction,
                             prize: str,
                             duration: Optional[str] = None,
                             expire: Optional[int] = None,
                             number_winners: int = 1,
                             titolo: Optional[str] = None,
                             descrizione: Optional[str] = None,
                             thumbnail: Optional[str] = None,
                             footer_text: Optional[str] = None,
                             footer_use_server_icon: bool = False,
                             end_message_template: Optional[str] = None):
        await interaction.response.defer(thinking=True, ephemeral=True)

        # Compute expire
        duration_text = duration
        expire_epoch = None
        if expire:
            expire_epoch = int(expire)
        else:
            seconds = _parse_duration(duration)
            if not seconds:
                await interaction.followup.send('❌ Specifica una durata valida (es. 1d2h30m) o un expire timestamp valido.', ephemeral=True)
                return
            expire_epoch = _utcnow_epoch() + seconds

        # Build per-giveaway embed overrides only for provided values, so global config can supply defaults
        embed_template = {}
        if titolo:
            embed_template['title'] = titolo
        if descrizione:
            embed_template['description'] = descrizione
        if thumbnail is not None:
            embed_template['thumbnail'] = thumbnail
        if footer_text is not None:
            embed_template['footer_text'] = footer_text
        if footer_use_server_icon is not None:
            embed_template['footer_use_server_icon'] = footer_use_server_icon

        base = {
            'guild_id': interaction.guild_id,
            'channel_id': interaction.channel.id,
            'message_id': 0,  # fill after send
            'title': titolo,
            'description': descrizione,
            'prize': prize,
            'duration_text': duration_text,
            'expire_epoch': expire_epoch,
            'number_winners': max(1, number_winners),
            'host': interaction.user.id,
            'created_by': interaction.user.id,
            'created_at': _utcnow_iso(),
            'updated_at': _utcnow_iso(),
            'status': 'active',
            'entrants': [],
            'winners': [],
            'embed_template': embed_template,
            'end_message_template': end_message_template or _load_config().get('end_message')
        }

        # Remove empty overrides to rely purely on config templates
        if not titolo:
            base.pop('title', None)
        if not descrizione:
            base.pop('description', None)

        # Build embed and send
        emb = self._build_embed(interaction.guild, base)
        if prize:
            emb.add_field(name='Premio', value=prize, inline=False)
        emb.add_field(name='Scade', value=_format_discord_time(expire_epoch), inline=True)
        emb.add_field(name='Host', value=interaction.user.mention, inline=True)
        emb.add_field(name='Partecipanti (0)', value='Premi "Partecipa" per unirti', inline=False)

        view = GiveawayView(self, message_id=0)
        msg = await interaction.channel.send(embed=emb, view=view)
        base['message_id'] = msg.id
        self.save_giveaway(msg.id, base)

        # Swap view to bind message id
        await msg.edit(view=GiveawayView(self, message_id=msg.id))

        await interaction.followup.send(f'✅ Giveaway creato in {interaction.channel.mention} (ID: `{msg.id}`) — termina {_format_discord_time(expire_epoch)}', ephemeral=True)

    async def _end_giveaway(self, message_id: int) -> Tuple[List[int], Optional[discord.Message]]:
        data = self.load_giveaway(message_id)
        if not data or data.get('status') != 'active':
            return [], None
        guild = self.bot.get_guild(data['guild_id'])
        channel = None
        try:
            channel = guild.get_channel(data['channel_id']) if guild else None
            if channel is None:
                channel = await self.bot.fetch_channel(data['channel_id'])
            msg = await channel.fetch_message(message_id)
        except Exception:
            msg = None
        # Determine winners
        entrants = data.get('entrants', [])
        pool = _eligible_entrants(data['guild_id'], entrants)
        winners_count = min(len(pool), int(data.get('number_winners', 1)))
        winners = random.sample(pool, winners_count) if winners_count > 0 else []
        data['winners'] = list(dict.fromkeys(data.get('winners', []) + winners))  # append unique
        data['status'] = 'ended'
        data['updated_at'] = _utcnow_iso()
        self.save_giveaway(message_id, data)

        # Edit original message: mark as ended and remove buttons
        if msg:
            try:
                ended_embed = self._build_embed(guild, data)
                ended_embed.color = discord.Color.red()
                winners_mentions = ', '.join(f'<@{w}>' for w in data['winners']) if data['winners'] else 'Nessuno'
                ended_embed.add_field(name='Stato', value='Terminato', inline=True)
                ended_embed.add_field(name='Vincitori', value=winners_mentions, inline=False)
                ended_embed.add_field(name='Partecipanti', value=str(len(entrants)), inline=True)
                await msg.edit(embed=ended_embed, view=None)
            except Exception:
                pass

        # Post end announcement
        if channel:
            winners_mentions = ', '.join(f'<@{w}>' for w in winners) if winners else 'Nessuno'
            template = data.get('end_message_template') or _load_config().get('end_message', '')
            text = _render_template(
                template,
                prize=data.get('prize', ''),
                duration_text=data.get('duration_text'),
                expire_epoch=data.get('expire_epoch'),
                host_mention=f"<@{data.get('host')}>",
                winners_text=winners_mentions
            )
            if text:
                try:
                    await channel.send(text)
                except Exception:
                    pass
        return winners, msg

    @tasks.loop(seconds=30)
    async def _end_checker(self):
        try:
            now = _utcnow_epoch()
            logger.debug(f'[Giveaway] End checker tick at {now}')
            if not os.path.exists(DATA_DIR):
                return
            for fname in os.listdir(DATA_DIR):
                if not fname.endswith('.json'):
                    continue
                try:
                    mid = int(os.path.splitext(fname)[0])
                except ValueError:
                    continue
                data = self.load_giveaway(mid)
                if not data:
                    continue
                if data.get('status', 'active') != 'active':
                    continue
                expire = int(data.get('expire_epoch', 0) or 0)
                if expire and expire <= now:
                    logger.info(f'[Giveaway] Auto-ending giveaway {mid} (expired at {expire})')
                    await self._end_giveaway(mid)
        except Exception as e:
            logger.error(f'[Giveaway] Error in end checker: {e}')

    @_end_checker.before_loop
    async def _before_checker(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name='gwend', description='Termina un giveaway immediatamente (solo owner o admin)')
    @owner_or_has_permissions(Administrator=True)
    async def slash_gwend(self, interaction: discord.Interaction, message_id: str):
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message('❌ message_id non valido.', ephemeral=True)
            return
        data = self.load_giveaway(mid)
        if not data:
            await interaction.response.send_message('❌ Giveaway non trovato.', ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        winners, _ = await self._end_giveaway(mid)
        await interaction.followup.send(f'✅ Giveaway `{mid}` terminato. Nuovi vincitori: {", ".join(f"<@{w}>" for w in winners) if winners else "Nessuno"}', ephemeral=True)

    @app_commands.command(name='gwremove', description='Rimuovi forzatamente un membro dal giveaway (solo owner o admin)')
    @app_commands.describe(message_id='ID del messaggio giveaway', user='Utente da rimuovere')
    @owner_or_has_permissions(Administrator=True)
    async def slash_gwremove(self, interaction: discord.Interaction, message_id: str, user: discord.Member):
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message('❌ message_id non valido.', ephemeral=True)
            return
        data = self.load_giveaway(mid)
        if not data:
            await interaction.response.send_message('❌ Giveaway non trovato.', ephemeral=True)
            return
        uid = user.id
        changed = False
        if uid in data.get('entrants', []):
            data['entrants'] = [x for x in data['entrants'] if x != uid]
            changed = True
        if uid in data.get('winners', []):
            data['winners'] = [x for x in data['winners'] if x != uid]
            changed = True
        if changed:
            data['updated_at'] = _utcnow_iso()
            self.save_giveaway(mid, data)
            await interaction.response.send_message(f'✅ Rimosso {user.mention} dal giveaway `{mid}`.', ephemeral=True)
        else:
            await interaction.response.send_message('ℹ️ Utente non presente tra gli iscritti/vincitori.', ephemeral=True)

    # Blacklist group
    gwblacklist = app_commands.Group(name='gwblacklist', description='Gestisci la blacklist giveaway (solo owner/admin)')

    @gwblacklist.command(name='add', description='Aggiungi un utente in blacklist')
    @owner_or_has_permissions(Administrator=True)
    async def gwblacklist_add(self, interaction: discord.Interaction, user: discord.Member):
        bl = _load_blacklist()
        key = str(interaction.guild_id)
        users = set(map(int, bl.get(key, [])))
        users.add(int(user.id))
        bl[key] = list(users)
        _save_blacklist(bl)
        await interaction.response.send_message(f'✅ {user.mention} aggiunto in blacklist per i giveaway.', ephemeral=True)

    @gwblacklist.command(name='remove', description='Rimuovi un utente dalla blacklist')
    @owner_or_has_permissions(Administrator=True)
    async def gwblacklist_remove(self, interaction: discord.Interaction, user: discord.Member):
        bl = _load_blacklist()
        key = str(interaction.guild_id)
        users = set(map(int, bl.get(key, [])))
        if int(user.id) in users:
            users.remove(int(user.id))
            bl[key] = list(users)
            _save_blacklist(bl)
            await interaction.response.send_message(f'✅ {user.mention} rimosso dalla blacklist.', ephemeral=True)
        else:
            await interaction.response.send_message('ℹ️ Utente non in blacklist.', ephemeral=True)

    @gwblacklist.command(name='list', description='Mostra la blacklist corrente')
    @owner_or_has_permissions(Administrator=True)
    async def gwblacklist_list(self, interaction: discord.Interaction):
        bl = _load_blacklist()
        key = str(interaction.guild_id)
        ids = list(map(int, bl.get(key, [])))
        if not ids:
            await interaction.response.send_message('La blacklist è vuota.', ephemeral=True)
            return
        mentions = []
        for uid in ids:
            member = interaction.guild.get_member(uid) if interaction.guild else None
            mentions.append(member.mention if member else f'<@{uid}>')
        text = ', '.join(mentions)
        await interaction.response.send_message(f'Lista blacklist: {text}', ephemeral=True)

    @app_commands.command(name='gwreroll', description='Estrai nuovi vincitori aggiuntivi (non sostituisce i precedenti)')
    @app_commands.describe(message_id='ID del messaggio giveaway', count='Quanti nuovi vincitori aggiungere (default 1)')
    @owner_or_has_permissions(Administrator=True)
    async def slash_gwreroll(self, interaction: discord.Interaction, message_id: str, count: int = 1):
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message('❌ message_id non valido.', ephemeral=True)
            return
        data = self.load_giveaway(mid)
        if not data:
            await interaction.response.send_message('❌ Giveaway non trovato.', ephemeral=True)
            return
        entrants = data.get('entrants', [])
        existing = set(data.get('winners', []))
        pool = [uid for uid in _eligible_entrants(data['guild_id'], entrants) if uid not in existing]
        if not pool:
            await interaction.response.send_message('ℹ️ Nessun altro partecipante idoneo da estrarre.', ephemeral=True)
            return
        k = max(1, min(len(pool), count))
        new_winners = random.sample(pool, k)
        data['winners'] = list(existing.union(new_winners))
        data['updated_at'] = _utcnow_iso()
        self.save_giveaway(mid, data)

        # Announce
        guild = interaction.guild
        channel = guild.get_channel(data['channel_id']) if guild else None
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(data['channel_id'])
            except Exception:
                channel = None
        mentions = ', '.join(f'<@{w}>' for w in new_winners)
        if channel:
            try:
                await channel.send(f'🔁 Nuovo reroll per giveaway `{mid}`! Vincitore/i: {mentions}')
            except Exception:
                pass
        await interaction.response.send_message(f'✅ Reroll eseguito. Nuovi vincitori: {mentions}', ephemeral=True)

    @commands.Cog.listener()
    async def on_ready(self):
        # Start end checker loop safely only once when the bot is ready
        try:
            if not self._end_loop_started and not self._end_checker.is_running():
                self._end_checker.start()
                self._end_loop_started = True
                logger.info('[Giveaway] End checker loop started on_ready')
        except Exception as e:
            logger.error(f'[Giveaway] Failed to start end checker loop on_ready: {e}')
        # Register persistent views for existing giveaways and catch up ended ones
        try:
            now = _utcnow_epoch()
            if not os.path.exists(DATA_DIR):
                return
            for fname in os.listdir(DATA_DIR):
                if not fname.endswith('.json'):
                    continue
                try:
                    mid = int(os.path.splitext(fname)[0])
                except ValueError:
                    continue
                data = self.load_giveaway(mid) or {}
                status = data.get('status', 'active')
                if status == 'active':
                    # Attach persistent view
                    self.bot.add_view(GiveawayView(self, message_id=mid))
                    # Catch-up: end if expired already
                    expire = int(data.get('expire_epoch', 0) or 0)
                    if expire and expire <= now:
                        logger.info(f'[Giveaway] Catch-up ending giveaway {mid} on ready (expired at {expire})')
                        try:
                            await self._end_giveaway(mid)
                        except Exception as e:
                            logger.error(f'[Giveaway] Error during catch-up end for {mid}: {e}')
        except FileNotFoundError:
            pass

    def cog_unload(self):
        # Ensure the loop is stopped when the cog is unloaded/reloaded
        try:
            if self._end_checker.is_running():
                self._end_checker.cancel()
                logger.info('[Giveaway] End checker loop cancelled on cog unload')
        except Exception:
            pass


aSYNC_SETUP_ERR = 'Errore durante il setup del cog Giveaway: {}'


async def setup(bot):
    try:
        await bot.add_cog(GiveawayCog(bot))
    except Exception as e:
        print(aSYNC_SETUP_ERR.format(e))
